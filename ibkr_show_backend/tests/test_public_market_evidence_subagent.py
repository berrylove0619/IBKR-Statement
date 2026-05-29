from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.public_market_evidence_subagent import PublicMarketEvidenceSubAgent


@dataclass
class FakeLLMResult:
    content: str


class FakeLLMService:
    def __init__(self, response: str | None = None, *, raises: bool = False) -> None:
        self.response = response or "{}"
        self.raises = raises
        self.calls: list[list[dict]] = []

    def chat_with_metadata(self, messages, **kwargs):
        self.calls.append(messages)
        if self.raises:
            raise RuntimeError("llm down")
        return FakeLLMResult(self.response)


def sample_evidence_pack() -> dict:
    return {
        "ok": True,
        "evidence_id": "pm_ev_test123",
        "evidence_type": "public_market",
        "symbol": "AMD.US",
        "intent": "estimate_amd_three_year_scenario",
        "question": "推演 AMD 未来三年股价走势",
        "data_sources": {
            "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
            "account_data": "NOT_INCLUDED",
            "position_data": "NOT_INCLUDED",
            "trade_data": "NOT_INCLUDED",
        },
        "key_facts": [
            {"fact": "valuation returned public market evidence.", "source_tool": "valuation", "confidence": "medium"},
            {"fact": "analyst_estimates returned public market evidence.", "source_tool": "analyst_estimates", "confidence": "medium"},
        ],
        "quote_summary": {"summary": "quote ok", "data": {"price": 100}},
        "valuation_summary": {"summary": "valuation ok", "data": {"pe_ttm": 40}},
        "financial_summary": {"summary": "financial ok", "data": {"revenue": 1}},
        "analyst_summary": {"summary": "analyst ok", "data": {"target_price": 120}},
        "news_summary": {"summary": "news ok", "data": {"items": [{"title": "AMD news", "summary": "AI demand"}]}},
        "price_trend_summary": {"summary": "trend ok", "data": {"return_pct": 12}},
        "missing_information": [],
        "data_limitations": [],
        "tool_results": [
            {"tool_name": "valuation", "ok": True, "status": "success", "summary": "valuation ok", "data_limitations": []},
            {"tool_name": "analyst_estimates", "ok": True, "status": "success", "summary": "analyst ok", "data_limitations": []},
        ],
        "budget": {"max_total_chars": 18000, "used_chars": 1000, "truncated": False},
    }


def valid_semantic_payload(**overrides) -> str:
    payload = {
        "ok": True,
        "semantic_evidence_id": "pm_sem_test123",
        "source_evidence_id": "pm_ev_test123",
        "evidence_type": "public_market_semantic",
        "symbol": "AMD.US",
        "intent": "estimate_amd_three_year_scenario",
        "question": "推演 AMD 未来三年股价走势",
        "data_sources": {
            "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
            "account_data": "NOT_INCLUDED",
            "position_data": "NOT_INCLUDED",
            "trade_data": "NOT_INCLUDED",
        },
        "executive_summary": "基于公开市场证据，AMD 的中长期情景需要同时观察估值、预期和新闻催化。",
        "key_facts": [{"claim": "估值数据已返回。", "source_tools": ["valuation"], "confidence": "medium"}],
        "bull_case_evidence": [{"point": "分析师预期可能支持增长情景。", "source_tools": ["analyst_estimates"], "confidence": "medium"}],
        "bear_case_evidence": [{"point": "估值偏高可能放大回撤。", "source_tools": ["valuation"], "confidence": "medium"}],
        "valuation_interpretation": {"summary": "估值需要结合增长判断。", "is_expensive": "unknown", "confidence": "medium", "source_tools": ["valuation"]},
        "financial_interpretation": {"summary": "财务证据有限。", "growth_quality": "unknown", "confidence": "low", "source_tools": ["financial_report"]},
        "analyst_interpretation": {"summary": "预期偏中性。", "market_expectation": "neutral", "confidence": "medium", "source_tools": ["analyst_estimates"]},
        "news_interpretation": {"summary": "新闻影响未知。", "event_impact": "unknown", "confidence": "low", "source_tools": ["news_search"]},
        "trend_interpretation": {"summary": "趋势证据有限。", "trend": "unknown", "confidence": "low", "source_tools": ["history_candlesticks"]},
        "conflicts": [],
        "missing_information": [],
        "data_limitations": [],
        "confidence": "medium",
        "evidence_used": ["valuation", "analyst_estimates", "financial_report", "news_search"],
        "risk_disclaimer": "以上仅基于公开市场数据做证据整理，不包含你的账户、仓位、成本或交易历史，也不构成确定性买卖建议。",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_synthesize_success() -> None:
    llm = FakeLLMService(valid_semantic_payload())
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert result["ok"] is True
    assert result["semantic_evidence_id"]
    assert result["source_evidence_id"] == "pm_ev_test123"
    assert result["data_sources"]["public_market_data"] == "LONGBRIDGE_PUBLIC_ONLY"
    assert result["executive_summary"]
    assert isinstance(result["bull_case_evidence"], list)
    assert isinstance(result["bear_case_evidence"], list)
    assert result["risk_disclaimer"]


def test_synthesize_does_not_call_tools() -> None:
    llm = FakeLLMService(valid_semantic_payload())
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert result["ok"] is True
    assert len(llm.calls) == 1


def test_synthesize_rejects_trading_instruction() -> None:
    llm = FakeLLMService(valid_semantic_payload(executive_summary="建议买入 AMD。"))
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert "建议买入" not in json.dumps(result, ensure_ascii=False)
    assert result["ok"] is False
    assert any("trading instruction rejected" in item.lower() for item in result["data_limitations"])


def test_synthesize_invalid_json_fallback() -> None:
    llm = FakeLLMService("not json")
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert result["ok"] is False
    assert result["confidence"] == "low"
    assert result["executive_summary"]
    assert any("deterministic fallback" in item for item in result["data_limitations"])


def test_synthesize_llm_error_fallback() -> None:
    llm = FakeLLMService(raises=True)
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert result["ok"] is False
    assert result["confidence"] == "low"
    assert result["executive_summary"]


def test_input_budget_compaction_preserves_core_fields() -> None:
    pack = sample_evidence_pack()
    pack["tool_results"][0]["data"] = {"rows": ["x" * 1000 for _ in range(20)]}
    pack["news_summary"]["data"]["items"] = [{"title": str(index), "summary": "y" * 1000} for index in range(30)]
    subagent = PublicMarketEvidenceSubAgent(FakeLLMService(valid_semantic_payload()), max_input_chars=1200)
    compacted = subagent._compact_input_evidence_pack(pack)
    assert compacted["evidence_id"] == "pm_ev_test123"
    assert compacted["symbol"] == "AMD.US"
    assert compacted["data_sources"]["public_market_data"] == "LONGBRIDGE_PUBLIC_ONLY"
    assert "missing_information" in compacted
    assert "data_limitations" in compacted
    assert compacted["input_compacted"] is True


def test_output_data_sources_cannot_include_private_data() -> None:
    payload = json.loads(valid_semantic_payload())
    payload["data_sources"]["account_data"] = "INCLUDED"
    llm = FakeLLMService(json.dumps(payload, ensure_ascii=False))
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    assert result["data_sources"]["account_data"] == "NOT_INCLUDED"
    assert any("account_data" in item for item in result["data_limitations"])


def test_no_hidden_chain_of_thought_leak() -> None:
    payload = json.loads(valid_semantic_payload())
    payload["reasoning"] = "hidden"
    payload["chain_of_thought"] = "hidden"
    payload["thinking"] = "hidden"
    llm = FakeLLMService(json.dumps(payload, ensure_ascii=False))
    result = PublicMarketEvidenceSubAgent(llm).synthesize(sample_evidence_pack())
    output = json.dumps(result, ensure_ascii=False)
    assert "chain_of_thought" not in output
    assert "reasoning" not in output
    assert "thinking" not in output
