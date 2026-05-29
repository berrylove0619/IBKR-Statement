from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.tool_registry import build_default_tool_registry
from app.api.deps import get_account_copilot_tool_registry
from app.core.config import get_settings
from app.main import app
from app.services.account_copilot.ibkr_tool_service import AccountCopilotIBKRToolService


@dataclass
class DummySettings:
    es_account_index: str = "account-index"
    es_position_index: str = "position-index"
    es_trade_index: str = "trade-index"
    es_cash_flow_index: str = "cash-flow-index"


class DummyOverview:
    def model_dump(self) -> dict:
        return {
            "account_id": "MASKED",
            "report_date": "2026-05-22",
            "currency": "USD",
            "total_equity": 100000.0,
            "cash": 10000.0,
            "stock_value": 85000.0,
            "options_value": 0.0,
            "funds_value": 5000.0,
            "crypto_value": 0.0,
            "fifo_total_realized_pnl": 1200.0,
            "fifo_total_unrealized_pnl": 3400.0,
            "fifo_total_pnl": 4600.0,
            "ytd_twr": 4.5,
            "interest_accruals": 1.0,
            "dividend_accruals": 2.0,
            "margin_financing_charge_accruals": 0.0,
            "total_equity_delta": {"amount_change": 100.0, "percent_change": 0.1},
        }


class DummyAccountService:
    def get_overview(self):
        return DummyOverview()


class DummyChartService:
    def get_equity_curve(self, start_date, end_date):
        class Response:
            items = []

        return Response()


class DummyDailyReviewService:
    def build_review_context(self, report_date=None, *, include_public_context=False, include_benchmarks=False):
        return {
            "report_date": report_date or "2026-05-22",
            "overview": {},
            "rankings": {},
            "risk": {},
            "attribution_quality": {},
            "positions": [],
        }


class DummyRiskBuilder:
    def build(self):
        class Snapshot:
            def to_dict(self):
                return {
                    "net_liquidation": 100000.0,
                    "cash": 10000.0,
                    "deployable_liquidity": 15000.0,
                    "position_count": 1,
                    "largest_position_pct": 0.2,
                    "top_3_position_pct": 0.2,
                    "top_5_position_pct": 0.2,
                    "cash_pct": 0.1,
                    "margin_usage_pct": 0.0,
                    "unrealized_pnl": 1000.0,
                    "unrealized_pnl_pct": 0.05,
                    "top_positions": [{"symbol": "AMD", "position_pct": 0.2}],
                    "positions": [],
                }

        return Snapshot()


class FakeESClient:
    def __init__(self) -> None:
        self.positions = [
            {
                "report_date": "2026-05-22",
                "symbol": "AMD",
                "description": "Advanced Micro Devices",
                "asset_class": "STK",
                "quantity": 10,
                "mark_price": 100.0,
                "position_value": 1000.0,
                "percent_of_nav": 1.0,
                "average_cost_price": 90.0,
                "cost_basis_money": 900.0,
                "total_realized_pnl": 5.0,
                "total_unrealized_pnl": 100.0,
                "unrealized_pnl_percent": 11.11,
            }
        ]
        self.trades = [
            {
                "symbol": "AMD",
                "trade_id": "t1",
                "trade_date": "2026-05-20",
                "date_time": "2026-05-20T10:00:00",
                "buy_sell": "BUY",
                "quantity": 10,
                "trade_price": 90.0,
                "proceeds": -900.0,
                "ib_commission": -1.0,
                "currency": "USD",
                "fifo_pnl_realized": 0.0,
            }
        ]
        self.cash_flows = []

    def create_index_if_missing(self, index: str, body: dict) -> None:
        return None

    def index_document(self, index: str, id: str, document: dict) -> dict:
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        return None

    def search(self, index: str, body: dict) -> dict:
        if index == "position-index":
            return self._search_positions(body)
        if index == "trade-index":
            return self._hits(self._filter_symbol(self.trades, body))
        if index == "cash-flow-index":
            return self._hits(self.cash_flows)
        return self._hits([])

    def _search_positions(self, body: dict) -> dict:
        if body.get("_source") == ["report_date"] and body.get("size") == 1:
            return self._hits([{"report_date": "2026-05-22"}])
        return self._hits(self._filter_symbol(self.positions, body))

    def _filter_symbol(self, documents: list[dict], body: dict) -> list[dict]:
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        values = list(documents)
        for item in filters:
            if "term" in item:
                for key, expected in item["term"].items():
                    values = [doc for doc in values if doc.get(key) == expected]
            if "terms" in item:
                for key, expected in item["terms"].items():
                    values = [doc for doc in values if doc.get(key) in expected]
        return values[: body.get("size", 20)]

    def _hits(self, documents: list[dict]) -> dict:
        return {
            "hits": {
                "total": {"value": len(documents)},
                "hits": [{"_id": item.get("trade_id"), "_source": dict(item)} for item in documents],
            }
        }


def _make_registry():
    service = AccountCopilotIBKRToolService(
        FakeESClient(),
        DummySettings(),
        DummyAccountService(),
        DummyChartService(),
        DummyDailyReviewService(),
        DummyRiskBuilder(),
    )
    return build_default_tool_registry(service)


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


def _client() -> TestClient:
    app.dependency_overrides[get_account_copilot_tool_registry] = _make_registry
    client = TestClient(app)
    _login(client)
    return client


def test_tools_lists_nine_ibkr_tools() -> None:
    client = _client()
    try:
        response = client.get("/api/agent/account-copilot/tools")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 9
        assert {item["name"] for item in items} >= {
            "ibkr_get_account_overview",
            "ibkr_get_current_positions",
            "ibkr_get_cash_flow_summary",
        }
        assert all(item["read_only"] is True for item in items)
    finally:
        app.dependency_overrides.clear()


def test_tool_schema_returns_schema() -> None:
    client = _client()
    try:
        response = client.get("/api/agent/account-copilot/tools/ibkr_get_symbol_trades/schema")
        assert response.status_code == 200
        schema = response.json()
        assert schema["name"] == "ibkr_get_symbol_trades"
        assert "symbol" in schema["parameters"]["required"]
    finally:
        app.dependency_overrides.clear()


def test_invoke_account_overview_returns_envelope() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/ibkr_get_account_overview/invoke", json={"arguments": {}})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["tool"] == "ibkr_get_account_overview"
        assert payload["data_source"] == "IBKR_ES"
        assert payload["data"]["total_equity"] == 100000.0
    finally:
        app.dependency_overrides.clear()


def test_invoke_current_positions_returns_items() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/ibkr_get_current_positions/invoke", json={"arguments": {"limit": 10}})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["data"]["items"][0]["symbol"] == "AMD"
    finally:
        app.dependency_overrides.clear()


def test_symbol_position_missing_holding_is_ok_false_holding() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/ibkr_get_symbol_position/invoke", json={"arguments": {"symbol": "MSFT"}})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["data"]["is_holding"] is False
        assert payload["data"]["position"] is None
    finally:
        app.dependency_overrides.clear()


def test_symbol_trades_missing_symbol_does_not_500() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/ibkr_get_symbol_trades/invoke", json={"arguments": {}})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["metadata"]["error_code"] == "INVALID_ARGUMENT"
    finally:
        app.dependency_overrides.clear()


def test_unregistered_tool_returns_404() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/not_a_tool/invoke", json={"arguments": {}})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_registry_to_openai_tools() -> None:
    tools = _make_registry().to_openai_tools(["ibkr_get_symbol_position"])
    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "ibkr_get_symbol_position",
                "description": tools[0]["function"]["description"],
                "parameters": tools[0]["function"]["parameters"],
            },
        }
    ]
    assert tools[0]["function"]["parameters"]["properties"]["symbol"]["type"] == "string"


def test_cash_flow_summary_empty_data_does_not_500() -> None:
    client = _client()
    try:
        response = client.post("/api/agent/account-copilot/tools/ibkr_get_cash_flow_summary/invoke", json={"arguments": {}})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["data"]["summary"]["total_deposits"] == 0.0
        assert payload["data"]["items_sample"] == []
    finally:
        app.dependency_overrides.clear()
