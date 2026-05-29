from __future__ import annotations

import json

from app.services.public_market_evidence_builder import PublicMarketEvidenceBuilder


class FakeLongbridgeToolService:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.batch_calls: list[dict] = []
        self.discovery_calls: list[dict] = []
        self.direct_calls = 0

    def list_public_tools(self, categories=None, limit_per_category=10, **kwargs) -> dict:
        self.discovery_calls.append({"categories": categories, "limit_per_category": limit_per_category, **kwargs})
        all_tools = {
            "quote": ["quote"],
            "valuation": ["valuation"],
            "analyst": ["analyst_estimates", "consensus"],
            "financial": ["financial_report_latest", "financial_report"],
            "news": ["news_search"],
            "candles": ["history_candlesticks", "candlesticks"],
            "company": ["company"],
            "calendar": ["finance_calendar"],
            "market": ["market_status"],
        }
        groups = []
        for category in categories or all_tools.keys():
            items = [{"name": name, "category": category, "description": f"{name} public tool"} for name in all_tools.get(category, [])]
            if items:
                groups.append({"category": category, "label": category, "items": items})
        return {"ok": True, "data": {"groups": groups}, "data_limitations": []}

    def call_public_tools(self, calls, intent=None, max_total_chars=18000) -> dict:
        self.batch_calls.append({"calls": calls, "intent": intent, "max_total_chars": max_total_chars})
        results = []
        for call in calls:
            tool_name = call["tool_name"]
            ok = True
            status = "success"
            data = {"symbol": call.get("arguments", {}).get("symbol"), "value": f"{tool_name} data"}
            limitations = []
            if self.mode == "partial" and tool_name == "news_search":
                ok = False
                status = "mcp_error"
                data = {}
                limitations = ["Longbridge MCP tool call failed."]
            if self.mode == "required_failed" and tool_name in {"quote", "valuation"}:
                ok = False
                status = "empty_result"
                data = {}
                limitations = ["Required public tool returned empty result."]
            if self.mode == "large" and tool_name == "news_search":
                data = {"items": [{"title": f"AMD news {index}", "summary": "x" * 500} for index in range(80)]}
            results.append(
                {
                    "tool_name": tool_name,
                    "ok": ok,
                    "status": status,
                    "priority": call.get("priority", "required"),
                    "purpose": call.get("purpose"),
                    "summary": f"{tool_name} returned compacted public market data." if ok else f"{tool_name} failed",
                    "data": data,
                    "data_limitations": limitations,
                    "latency_ms": 1,
                }
            )
        success_count = len([item for item in results if item["ok"]])
        failed_count = len(results) - success_count
        required_failed = any(item["priority"] == "required" and not item["ok"] for item in results)
        status = "success" if failed_count == 0 else "partial_success"
        return {
            "ok": not required_failed and success_count > 0,
            "tool": "longbridge_call_public_tools",
            "data_source": "LONGBRIDGE_MCP_PUBLIC",
            "data": {
                "intent": intent,
                "status": "failed" if required_failed else status,
                "results": results,
                "requested_count": len(calls),
                "executed_count": len(calls),
                "success_count": success_count,
                "failed_count": failed_count,
                "forbidden_count": 0,
                "budget": {"max_total_chars": max_total_chars, "used_chars": 1000, "truncated": False},
            },
            "data_limitations": [],
            "metadata": {"read_only": True},
        }

    def call_public_tool(self, *args, **kwargs):
        self.direct_calls += 1
        raise AssertionError("PublicMarketEvidenceBuilder must not call single public tool directly")


def test_build_symbol_evidence_success() -> None:
    service = FakeLongbridgeToolService()
    pack = PublicMarketEvidenceBuilder(service).build_symbol_evidence("AMD.US", intent="estimate_amd_three_year_scenario")
    assert pack["ok"] is True
    assert pack["symbol"] == "AMD.US"
    assert pack["data_sources"]["public_market_data"] == "LONGBRIDGE_PUBLIC_ONLY"
    assert pack["data_sources"]["account_data"] == "NOT_INCLUDED"
    assert pack["quote_summary"]
    assert pack["valuation_summary"]
    assert pack["analyst_summary"]
    assert pack["financial_summary"]
    assert pack["news_summary"]
    assert pack["tool_results"]
    payload = json.dumps(pack, ensure_ascii=False).lower()
    assert "account_balance" not in payload
    assert "stock_positions" not in payload
    assert "submit_order" not in payload
    assert "withdrawal" not in payload


def test_build_symbol_evidence_uses_batch_call_only() -> None:
    service = FakeLongbridgeToolService()
    PublicMarketEvidenceBuilder(service).build_symbol_evidence("AMD.US")
    assert len(service.batch_calls) == 1
    assert service.direct_calls == 0


def test_build_symbol_evidence_partial_success() -> None:
    service = FakeLongbridgeToolService(mode="partial")
    pack = PublicMarketEvidenceBuilder(service).build_symbol_evidence("AMD.US")
    assert pack["ok"] is True
    assert "Public market evidence is partial because some tools failed or returned empty results." in pack["data_limitations"]
    assert "Optional public market tool news_search unavailable." in pack["missing_information"]


def test_build_symbol_evidence_required_failed() -> None:
    service = FakeLongbridgeToolService(mode="required_failed")
    pack = PublicMarketEvidenceBuilder(service).build_symbol_evidence("AMD.US")
    assert pack["ok"] is False
    assert any("Required public market tool quote failed" in item for item in pack["missing_information"])
    assert any("Required public market tool valuation failed" in item for item in pack["missing_information"])
    assert "Required public market evidence is insufficient because quote or valuation failed." in pack["data_limitations"]


def test_evidence_pack_budget_compaction() -> None:
    service = FakeLongbridgeToolService(mode="large")
    pack = PublicMarketEvidenceBuilder(service).build_symbol_evidence(
        "AMD.US",
        question="AMD 最近为什么大涨",
        max_total_chars=6000,
    )
    assert pack["budget"]["truncated"] is True
    assert "Evidence pack was compacted to fit context budget." in pack["data_limitations"]
    assert pack["evidence_id"]
    assert pack["symbol"] == "AMD.US"
    assert pack["intent"]
    assert pack["key_facts"]


def test_question_intent_tool_selection_trend_prefers_candles() -> None:
    service = FakeLongbridgeToolService()
    pack = PublicMarketEvidenceBuilder(service).build_market_question_evidence("AMD.US", "推演 AMD 未来三年股价走势")
    tool_names = {call["tool_name"] for call in pack["tool_plan"]["calls"]}
    assert {"history_candlesticks", "candlesticks"} & tool_names
    assert len(pack["tool_plan"]["calls"]) <= 5


def test_question_intent_tool_selection_news_prefers_news() -> None:
    service = FakeLongbridgeToolService()
    pack = PublicMarketEvidenceBuilder(service).build_market_question_evidence("AMD.US", "AMD 最近为什么大涨")
    tool_names = {call["tool_name"] for call in pack["tool_plan"]["calls"]}
    assert "news_search" in tool_names


def test_builder_does_not_include_private_account_data() -> None:
    service = FakeLongbridgeToolService()
    pack = PublicMarketEvidenceBuilder(service).build_symbol_evidence("AMD.US")
    payload = json.dumps(pack, ensure_ascii=False).lower()
    forbidden_terms = ("account_balance", "stock_positions", "orders", "submit_order", "withdrawal", "executions")
    for term in forbidden_terms:
        assert term not in payload
