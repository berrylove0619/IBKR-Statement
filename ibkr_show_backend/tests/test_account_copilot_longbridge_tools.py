from fastapi.testclient import TestClient

from app.agents.account_copilot.longbridge_tools import AccountCopilotLongbridgeToolService
from app.agents.account_copilot.tool_registry import build_default_tool_registry
from app.api.deps import get_account_copilot_tool_registry
from app.core.config import get_settings
from app.main import app


class FakeIBKRToolService:
    def get_account_overview(self): return {"ok": True}
    def get_current_positions(self, limit=50, include_cash_equivalents=True): return {"ok": True}
    def get_symbol_position(self, symbol): return {"ok": True}
    def get_symbol_trades(self, symbol, start_date=None, end_date=None, limit=100): return {"ok": True}
    def get_position_history(self, symbol, start_date=None, end_date=None, limit=365): return {"ok": True}
    def get_equity_curve(self, start_date=None, end_date=None): return {"ok": True}
    def get_daily_attribution(self, report_date=None): return {"ok": True}
    def get_risk_snapshot(self): return {"ok": True}
    def get_cash_flow_summary(self, start_date=None, end_date=None): return {"ok": True}


class FakeLongbridgeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_tool_catalog(self, *, force_refresh: bool = False) -> dict:
        return {
            "source": "mcp_tools_list",
            "tools": [
                {
                    "name": "quote",
                    "classification": "public_market_readonly",
                    "allowed": True,
                    "description": "Realtime public quote",
                    "input_schema": {
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                },
                {
                    "name": "news_search",
                    "classification": "public_market_readonly",
                    "allowed": True,
                    "description": "Public market news search",
                    "input_schema": {"type": "object", "properties": {"keyword": {"type": "string"}}},
                },
                {
                    "name": "submit_order",
                    "classification": "trading_write",
                    "allowed": False,
                    "description": "Place order",
                    "input_schema": {"type": "object", "properties": {"token": {"type": "string"}}},
                },
                {
                    "name": "account_balance",
                    "classification": "account_private",
                    "allowed": False,
                    "description": "Private account balance",
                    "input_schema": {"type": "object", "properties": {"account_id": {"type": "string"}}},
                },
                {
                    "name": "mystery_unknown",
                    "classification": "unknown",
                    "allowed": True,
                    "description": "Unknown experimental tool",
                    "input_schema": {"type": "object"},
                },
            ],
            "public_market_readonly": ["quote", "news_search"],
            "blocked": ["submit_order", "account_balance", "mystery_unknown"],
        }

    def call(self, tool_name: str, arguments: dict | None = None) -> dict:
        self.calls.append((tool_name, arguments or {}))
        if tool_name == "quote":
            return {
                "ok": True,
                "tool": tool_name,
                "mcp_tool": tool_name,
                "data": {"symbol": arguments.get("symbol"), "price": 123.45, "authorization": "secret"},
                "data_limitations": [],
            }
        return {"ok": False, "error_code": "UNEXPECTED", "message": "unexpected", "data_limitations": []}


class UnavailableLongbridgeAdapter:
    def get_tool_catalog(self, *, force_refresh: bool = False) -> dict:
        raise RuntimeError("mcp down")


def _registry(adapter=None):
    return build_default_tool_registry(FakeIBKRToolService(), AccountCopilotLongbridgeToolService(adapter or FakeLongbridgeAdapter()))


def _client(adapter=None) -> TestClient:
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: _registry(adapter)
    client = TestClient(app)
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200
    return client


def test_tool_registry_exposes_new_categories_meta_tool() -> None:
    client = _client()
    try:
        response = client.get("/api/agent/account-copilot/tools")
        assert response.status_code == 200
        names = {item["name"] for item in response.json()["items"]}
        assert len(names) == 15
        assert "ibkr_get_account_overview" in names
        assert "longbridge_list_public_tool_categories" in names
        assert "longbridge_list_public_tools" in names
        assert "longbridge_get_public_tool_schema" in names
        assert "longbridge_get_public_tool_schemas" in names
        assert "longbridge_call_public_tool" in names
        assert "longbridge_call_public_tools" in names
        assert "quote" not in names
        assert "news_search" not in names
        assert "valuation" not in names
    finally:
        app.dependency_overrides.clear()


def test_list_public_tool_categories_returns_grouped_categories() -> None:
    service = AccountCopilotLongbridgeToolService(RichFakeLongbridgeAdapter())
    payload = service.list_public_tool_categories()
    assert payload["ok"] is True
    categories = payload["data"]["categories"]
    names = {item["category"] for item in categories}
    assert {"quote", "news", "valuation", "analyst"}.issubset(names)
    assert "submit_order" not in str(categories)
    assert "account_balance" not in str(categories)
    assert "mystery_unknown" not in str(categories)
    assert payload["data"]["blocked_count"] == 3


def test_list_public_tools_hides_forbidden_private_write_unknown() -> None:
    client = _client()
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_list_public_tools/invoke",
            json={"arguments": {"limit": 100}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        names = {item["name"] for item in payload["data"]["items"]}
        assert names == {"quote", "news_search"}
        assert "submit_order" not in names
        assert "account_balance" not in names
        assert "mystery_unknown" not in names
        assert payload["data"]["blocked_count"] == 3
    finally:
        app.dependency_overrides.clear()


def test_list_public_tools_returns_grouped_list() -> None:
    client = _client()
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_list_public_tools/invoke",
            json={"arguments": {"limit_per_category": 10}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        groups = payload["data"]["groups"]
        assert groups
        for group in groups:
            assert {"category", "label", "items"}.issubset(group)
            for item in group["items"]:
                assert {"name", "category", "description", "rank_score", "next_step"}.issubset(item)
        assert payload["data"]["items"]
    finally:
        app.dependency_overrides.clear()


def test_get_public_tool_schema_returns_schema() -> None:
    client = _client()
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_get_public_tool_schema/invoke",
            json={"arguments": {"tool_name": "quote"}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["data"]["name"] == "quote"
        assert payload["data"]["input_schema"]["properties"]["symbol"]["type"] == "string"
    finally:
        app.dependency_overrides.clear()


def test_get_public_tool_schema_forbidden_returns_false_without_schema() -> None:
    client = _client()
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_get_public_tool_schema/invoke",
            json={"arguments": {"tool_name": "submit_order"}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["metadata"]["error_code"] == "LONG_BRIDGE_TOOL_NOT_ALLOWED"
        assert "input_schema" not in payload["data"]
    finally:
        app.dependency_overrides.clear()


def test_call_public_tool_quote_succeeds_and_sanitizes_result() -> None:
    adapter = FakeLongbridgeAdapter()
    client = _client(adapter)
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_call_public_tool/invoke",
            json={"arguments": {"tool_name": "quote", "arguments": {"symbol": "AAPL.US"}}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["data"]["called_tool"] == "quote"
        assert payload["data"]["result"] == {"symbol": "AAPL.US", "price": 123.45}
        assert adapter.calls == [("quote", {"symbol": "AAPL.US"})]
    finally:
        app.dependency_overrides.clear()


def test_call_forbidden_tool_does_not_execute_adapter() -> None:
    adapter = FakeLongbridgeAdapter()
    client = _client(adapter)
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_call_public_tool/invoke",
            json={"arguments": {"tool_name": "submit_order", "arguments": {"symbol": "AAPL.US"}}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["metadata"]["error_code"] == "LONG_BRIDGE_TOOL_NOT_ALLOWED"
        assert adapter.calls == []
    finally:
        app.dependency_overrides.clear()


def test_unknown_longbridge_tool_returns_false() -> None:
    client = _client()
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_call_public_tool/invoke",
            json={"arguments": {"tool_name": "mystery_tool", "arguments": {}}},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False
    finally:
        app.dependency_overrides.clear()


def test_to_openai_tools_exposes_only_top_level_copilot_tools() -> None:
    tools = _registry().to_openai_tools()
    names = {item["function"]["name"] for item in tools}
    assert len(names) == 15
    assert "quote" not in names
    assert "longbridge_list_public_tool_categories" in names
    assert "longbridge_get_public_tool_schemas" in names
    assert "longbridge_call_public_tool" in names
    assert "longbridge_call_public_tools" in names


def test_longbridge_catalog_unavailable_does_not_500() -> None:
    client = _client(UnavailableLongbridgeAdapter())
    try:
        response = client.post(
            "/api/agent/account-copilot/tools/longbridge_list_public_tools/invoke",
            json={"arguments": {}},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["metadata"]["error_code"] == "LONGBRIDGE_CATALOG_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()


class RichFakeLongbridgeAdapter:
    """Adapter with more tools for query filtering tests."""

    def __init__(self, fail_tools: set[str] | None = None, large_tools: set[str] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_tools = fail_tools or set()
        self.large_tools = large_tools or set()

    def get_tool_catalog(self, *, force_refresh: bool = False) -> dict:
        tools = [
            {"name": "quote", "classification": "public_market_readonly", "allowed": True, "description": "Realtime quote for a symbol", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "valuation", "classification": "public_market_readonly", "allowed": True, "description": "Valuation metrics PE PB PS for a symbol", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "analyst_estimates", "classification": "public_market_readonly", "allowed": True, "description": "Analyst consensus estimates and target prices", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "news_search", "classification": "public_market_readonly", "allowed": True, "description": "Search public market news", "input_schema": {"type": "object", "properties": {"keyword": {"type": "string"}}}},
            {"name": "financial_report", "classification": "public_market_readonly", "allowed": True, "description": "Financial statements and reports", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "finance_calendar", "classification": "public_market_readonly", "allowed": True, "description": "Earnings and dividend calendar", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "business_segments", "classification": "public_market_readonly", "allowed": True, "description": "Business segments by revenue", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "forecast_eps", "classification": "public_market_readonly", "allowed": True, "description": "Forecast EPS", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "consensus", "classification": "public_market_readonly", "allowed": True, "description": "Analyst consensus", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "industry_valuation", "classification": "public_market_readonly", "allowed": True, "description": "Industry valuation and peers", "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}}},
            {"name": "market_status", "classification": "public_market_readonly", "allowed": True, "description": "Market trading status", "input_schema": {"type": "object"}},
            {"name": "submit_order", "classification": "trading_write", "allowed": False, "description": "Place order", "input_schema": {"type": "object"}},
            {"name": "account_balance", "classification": "account_private", "allowed": False, "description": "Private account balance", "input_schema": {"type": "object"}},
            {"name": "mystery_unknown", "classification": "unknown", "allowed": True, "description": "Unknown tool", "input_schema": {"type": "object"}},
        ]
        return {
            "source": "mcp_tools_list",
            "tools": tools,
            "public_market_readonly": [t["name"] for t in tools if t["classification"] == "public_market_readonly"],
            "blocked": [t["name"] for t in tools if t["classification"] != "public_market_readonly"],
        }

    def call(self, tool_name: str, arguments: dict | None = None) -> dict:
        self.calls.append((tool_name, arguments or {}))
        if tool_name in self.fail_tools:
            return {"ok": False, "error_code": f"MCP_TOOL_ERROR:{tool_name}", "message": f"{tool_name} failed", "data_limitations": ["Longbridge MCP tool call failed."]}
        if tool_name in self.large_tools:
            return {"ok": True, "tool": tool_name, "mcp_tool": tool_name, "data": {"items": [{"title": f"AMD news {index}", "summary": "x" * 300} for index in range(80)]}, "data_limitations": []}
        return {"ok": True, "tool": tool_name, "mcp_tool": tool_name, "data": {"tool": tool_name, "price": 100, "authorization": "secret"}, "data_limitations": []}


def test_list_public_tools_query_does_not_filter_out_unmatched_tools() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.list_public_tools(
        categories=["valuation", "analyst", "financial"],
        query="AMD forecast analyst valuation",
        limit_per_category=10,
    )
    assert result["ok"] is True
    groups = {group["category"]: group for group in result["data"]["groups"]}
    assert "valuation" in groups
    assert "analyst" in groups
    assert "financial" in groups
    financial_names = {item["name"] for item in groups["financial"]["items"]}
    assert "financial_report" in financial_names
    scores = {item["name"]: item["rank_score"] for item in result["data"]["items"]}
    assert scores["valuation"] >= scores["financial_report"]
    assert result["data"]["source"] == "mcp_tools_list"
    assert result["data"]["ranking_strategy"] == "query_ranking_only_no_filtering"


def test_list_public_tools_query_no_match_still_returns_category_tools() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.list_public_tools(query="blahblah-no-match-xyz", category="valuation")
    assert result["ok"] is True
    groups = {group["category"]: group for group in result["data"]["groups"]}
    assert "valuation" in groups
    assert {item["name"] for item in groups["valuation"]["items"]} >= {"valuation"}
    assert result["data_limitations"] == []


def test_list_public_tools_query_none_returns_all() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.list_public_tools(query=None, limit=30)
    assert result["ok"] is True
    assert result["data"]["total"] == 11


def test_list_public_tools_category_filter() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.list_public_tools(category="valuation", limit=30)
    assert result["ok"] is True
    names = {item["name"] for item in result["data"]["items"]}
    assert "valuation" in names
    assert "quote" not in names


def test_list_public_tools_too_many_categories_returns_error() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.list_public_tools(categories=["quote", "news", "valuation", "analyst", "financial"])
    assert result["ok"] is False
    assert result["metadata"]["error_code"] == "LONG_BRIDGE_TOO_MANY_CATEGORIES"
    assert adapter.calls == []


def test_get_public_tool_schemas_success() -> None:
    service = AccountCopilotLongbridgeToolService(RichFakeLongbridgeAdapter())
    result = service.get_public_tool_schemas(["valuation", "analyst_estimates", "financial_report"])
    assert result["ok"] is True
    schemas = result["data"]["schemas"]
    assert len(schemas) == 3
    assert result["data"]["success_count"] == 3
    for schema in schemas:
        assert schema["ok"] is True
        assert schema["status"] == "success"
        assert schema["input_schema"]
        assert schema["category"]
        assert "example_arguments" in schema


def test_get_public_tool_schemas_rejects_too_many() -> None:
    service = AccountCopilotLongbridgeToolService(RichFakeLongbridgeAdapter())
    result = service.get_public_tool_schemas(["quote", "valuation", "analyst_estimates", "financial_report", "news_search", "company", "market_status"])
    assert result["ok"] is False
    assert result["metadata"]["error_code"] == "LONG_BRIDGE_SCHEMA_BATCH_TOO_LARGE"


def test_get_public_tool_schemas_forbidden_item_does_not_leak_schema() -> None:
    service = AccountCopilotLongbridgeToolService(RichFakeLongbridgeAdapter())
    result = service.get_public_tool_schemas(["valuation", "submit_order", "account_balance", "mystery_unknown"])
    assert result["ok"] is True
    schemas = {item["tool_name"]: item for item in result["data"]["schemas"]}
    assert schemas["valuation"]["ok"] is True
    assert schemas["submit_order"]["ok"] is False
    assert schemas["submit_order"]["status"] == "forbidden"
    assert schemas["account_balance"]["ok"] is False
    assert schemas["account_balance"]["status"] == "forbidden"
    assert schemas["mystery_unknown"]["ok"] is False
    assert "input_schema" not in schemas["submit_order"]
    assert "input_schema" not in schemas["account_balance"]
    assert "input_schema" not in schemas["mystery_unknown"]


def test_call_public_tools_success_parallel_batch() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        intent="estimate_amd_three_year_scenario",
        calls=[
            {"tool_name": "valuation", "arguments": {"symbol": "AMD.US"}, "purpose": "判断当前估值水平"},
            {"tool_name": "analyst_estimates", "arguments": {"symbol": "AMD.US"}, "purpose": "获取分析师预期"},
            {"tool_name": "news_search", "arguments": {"keyword": "AMD"}, "purpose": "获取近期新闻催化"},
        ],
    )
    assert result["ok"] is True
    assert result["data"]["status"] == "success"
    assert len(result["data"]["results"]) == 3
    assert result["data"]["success_count"] == 3
    assert {name for name, _ in adapter.calls} == {"valuation", "analyst_estimates", "news_search"}
    for item in result["data"]["results"]:
        assert "latency_ms" in item
        assert item["status"] == "success"
        assert item["summary"]
        assert "data_limitations" in item
        assert "authorization" not in str(item["data"]).lower()


def test_call_public_tools_partial_success() -> None:
    adapter = RichFakeLongbridgeAdapter(fail_tools={"news_search"})
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        calls=[
            {"tool_name": "valuation", "arguments": {"symbol": "AMD.US"}, "priority": "required"},
            {"tool_name": "news_search", "arguments": {"keyword": "AMD"}, "priority": "optional"},
        ],
    )
    assert result["ok"] is True
    assert result["data"]["status"] == "partial_success"
    results = {item["tool_name"]: item for item in result["data"]["results"]}
    assert results["valuation"]["ok"] is True
    assert results["news_search"]["ok"] is False
    assert result["data"]["failed_count"] == 1


def test_call_public_tools_forbidden_tool_not_executed() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        calls=[
            {"tool_name": "valuation", "arguments": {"symbol": "AMD.US"}},
            {"tool_name": "submit_order", "arguments": {"symbol": "AMD.US"}},
            {"tool_name": "account_balance", "arguments": {}},
        ],
    )
    assert result["ok"] is True
    assert result["data"]["forbidden_count"] == 2
    assert {name for name, _ in adapter.calls} == {"valuation"}
    results = {item["tool_name"]: item for item in result["data"]["results"]}
    assert results["submit_order"]["status"] == "forbidden"
    assert results["account_balance"]["status"] == "forbidden"


def test_call_public_tools_rejects_too_many_calls() -> None:
    adapter = RichFakeLongbridgeAdapter()
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        calls=[
            {"tool_name": "quote", "arguments": {}},
            {"tool_name": "valuation", "arguments": {}},
            {"tool_name": "analyst_estimates", "arguments": {}},
            {"tool_name": "financial_report", "arguments": {}},
            {"tool_name": "news_search", "arguments": {}},
            {"tool_name": "market_status", "arguments": {}},
        ]
    )
    assert result["ok"] is False
    assert result["metadata"]["error_code"] == "LONG_BRIDGE_TOOL_BATCH_TOO_LARGE"
    assert adapter.calls == []


def test_call_public_tools_budget_truncates_large_result() -> None:
    adapter = RichFakeLongbridgeAdapter(large_tools={"news_search"})
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        calls=[
            {"tool_name": "news_search", "arguments": {"keyword": "AMD"}, "max_chars": 1000},
        ],
        max_total_chars=6000,
    )
    assert result["ok"] is True
    item = result["data"]["results"][0]
    assert item["status"] == "success_truncated"
    assert "Tool result was truncated to fit per-tool context budget." in item["data_limitations"]
    assert result["data"]["budget"]["truncated"] is True or "truncated_json" in item["data"]


def test_to_openai_tools_exposes_batch_meta_tools_not_raw_tools() -> None:
    tools = _registry().to_openai_tools()
    names = {item["function"]["name"] for item in tools}
    assert "longbridge_get_public_tool_schemas" in names
    assert "longbridge_call_public_tools" in names
    assert "quote" not in names
    assert "valuation" not in names
    assert "news_search" not in names


def test_call_public_tools_all_required_failed_returns_false() -> None:
    adapter = RichFakeLongbridgeAdapter(fail_tools={"valuation", "news_search"})
    service = AccountCopilotLongbridgeToolService(adapter)
    result = service.call_public_tools(
        calls=[
            {"tool_name": "valuation", "arguments": {"symbol": "AMD.US"}, "priority": "required"},
            {"tool_name": "news_search", "arguments": {"keyword": "AMD"}, "priority": "required"},
        ],
    )
    assert result["ok"] is False
    assert result["data"]["status"] == "failed"


def test_category_classification_priority() -> None:
    service = AccountCopilotLongbridgeToolService(None)
    assert service._category_for_tool("analyst_estimates") == "analyst"
    assert service._category_for_tool("forecast_eps") == "analyst"
    assert service._category_for_tool("consensus") == "analyst"
    assert service._category_for_tool("valuation") == "valuation"
    assert service._category_for_tool("industry_peers") == "valuation"
    assert service._category_for_tool("industry_valuation") == "valuation"
    assert service._category_for_tool("financial_report") == "financial"
    assert service._category_for_tool("business_segments") == "company"
    assert service._category_for_tool("market_status") == "market"
    assert service._category_for_tool("finance_calendar") == "calendar"


def test_list_public_tools_none_adapter_returns_static_fallback() -> None:
    service = AccountCopilotLongbridgeToolService(None)
    result = service.list_public_tools()
    assert result["ok"] is True
    assert result["data"]["source"] == "static_fallback"
    assert result["data"]["items"] == []


def test_get_mcp_adapter_uses_longbridge_mcp_client(monkeypatch) -> None:
    """Verify _get_mcp_adapter uses LongbridgeMCPClient with unified token service."""
    from app.api import deps

    constructed_clients = []

    class FakeMCPClient:
        def __init__(self, **kwargs):
            constructed_clients.append(kwargs)

    class FakeAdapter:
        def __init__(self, client):
            self.client = client

    monkeypatch.setattr(deps, "get_longbridge_oauth_token_service", lambda: object())
    monkeypatch.setattr("app.services.mcp.longbridge_mcp_client.LongbridgeMCPClient", FakeMCPClient)
    monkeypatch.setattr("app.services.mcp.longbridge_mcp_tools.LongbridgeMCPToolAdapter", FakeAdapter)

    adapter = deps._get_mcp_adapter()
    assert adapter is not None
    assert len(constructed_clients) == 1
    assert "token_service" in constructed_clients[0]


def test_get_optional_mcp_adapter_logs_warning_on_failure(monkeypatch, caplog) -> None:
    from app.api import deps

    monkeypatch.setattr(deps, "_get_mcp_adapter", lambda: (_ for _ in ()).throw(RuntimeError("test MCP error")))
    import logging
    with caplog.at_level(logging.WARNING):
        result = deps._get_optional_mcp_adapter()
    assert result is None
    assert "Longbridge MCP adapter unavailable" in caplog.text
    assert "test MCP error" in caplog.text
