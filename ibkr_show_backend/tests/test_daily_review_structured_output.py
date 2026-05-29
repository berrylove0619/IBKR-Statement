from __future__ import annotations

import json

import pytest

from app.agents.daily_position_review_graph.nodes import _parse_validate_repair_daily_review
from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent, SYSTEM_PROMPT_MACRO_CARD
from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent, SYSTEM_PROMPT_SYMBOL_CARD
from app.services.daily_position_review_agent import SYSTEM_PROMPT_SUBAGENT_CARDS


class SequencedLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], **kwargs) -> str:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


def _symbol_payload(**overrides) -> dict:
    payload = {
        "symbol": "AMD",
        "normalized_symbol": "AMD.US",
        "report_date": "2026-05-20",
        "account_impact": {"daily_pnl": 100.0, "position_weight": 0.1},
        "price_action": {"day_change_percent": 2.0, "relative_to_benchmark": "跑赢 QQQ"},
        "news_summary": {"key_news": ["AI 芯片需求改善"], "catalyst": "AI 需求", "sentiment": "positive", "confidence": "medium"},
        "valuation_summary": {"market_cap": 1.0, "pe_ttm": 28.0, "ps_ttm": 8.0, "valuation_comment": "成长溢价", "data_limitations": []},
        "earnings_summary": {"latest_earnings": None, "revenue_growth": None, "profit_growth": None, "guidance": None, "data_limitations": []},
        "technical_summary": {"trend": "bullish", "support_levels": [], "resistance_levels": [], "volume_signal": None, "data_limitations": []},
        "cross_asset_summary": {"related_assets": ["SMH.US"], "relation_note": "半导体板块同步", "data_limitations": []},
        "likely_drivers": ["半导体板块偏强"],
        "watch_points": ["观察 SMH"],
        "evidence_quality": "medium",
        "data_limitations": [],
        "source_trace": ["test"],
    }
    payload.update(overrides)
    return payload


def _macro_payload(**overrides) -> dict:
    payload = {
        "report_date": "2026-05-20",
        "benchmark_context": {"QQQ": {"return_percent": 1.0}},
        "market_regime": "mixed",
        "sector_context": "科技偏强",
        "macro_events": [],
        "rate_fx_context": None,
        "risk_sentiment": "neutral",
        "tech_sentiment": "positive",
        "data_limitations": [],
        "source_trace": ["test"],
    }
    payload.update(overrides)
    return payload


def _daily_payload(**overrides) -> dict:
    payload = {
        "report_date": "2026-05-20",
        "summary": "ok",
        "account_conclusion": "ok",
        "attribution_summary": "ok",
        "major_contributors_analysis": [],
        "major_drags_analysis": [],
        "focus_symbol_analyses": [],
        "market_context": "ok",
        "risk_analysis": "ok",
        "tomorrow_watchlist": [],
        "operation_observation": "ok",
        "data_limitations": [],
        "evidence_used": [],
    }
    payload.update(overrides)
    return payload


def test_symbol_evidence_structured_output_success() -> None:
    llm = SequencedLLM([json.dumps(_symbol_payload())])
    card = DailyReviewSymbolEvidenceAgent(llm).generate_symbol_card("2026-05-20", "AMD", "AMD.US", {}, {}, {})

    assert card.normalized_symbol == "AMD.US"
    assert card.evidence_quality == "medium"
    assert any("structured_output:contract=daily_review_symbol_evidence_card" in item for item in card.source_trace)
    assert any("repaired=False" in item for item in card.source_trace)


def test_symbol_evidence_non_json_repairs_successfully() -> None:
    llm = SequencedLLM(["not json", json.dumps(_symbol_payload(evidence_quality="high"))])
    card = DailyReviewSymbolEvidenceAgent(llm).generate_symbol_card("2026-05-20", "AMD", "AMD.US", {}, {}, {})

    assert card.evidence_quality == "high"
    assert any("repaired=True" in item for item in card.source_trace)


def test_symbol_evidence_repair_failure_raises_structured_error() -> None:
    llm = SequencedLLM(["not json", "still bad", "still bad"])

    with pytest.raises(ValueError, match="LLM_REPAIR_FAILED"):
        DailyReviewSymbolEvidenceAgent(llm).generate_symbol_card("2026-05-20", "AMD", "AMD.US", {}, {}, {})


def test_macro_evidence_structured_output_success() -> None:
    llm = SequencedLLM([json.dumps(_macro_payload())])
    card = DailyReviewMacroEvidenceAgent(llm).generate_macro_card("2026-05-20", {}, [], None)

    assert card.market_regime == "mixed"
    assert card.tech_sentiment == "positive"
    assert any("structured_output:contract=daily_review_macro_evidence_card" in item for item in card.source_trace)


def test_macro_evidence_schema_error_repairs_successfully() -> None:
    invalid = _macro_payload(market_regime="unclear")
    llm = SequencedLLM([json.dumps(invalid), json.dumps(_macro_payload(market_regime="risk_off"))])
    card = DailyReviewMacroEvidenceAgent(llm).generate_macro_card("2026-05-20", {}, [], None)

    assert card.market_regime == "risk_off"
    assert any("repaired=True" in item for item in card.source_trace)


def test_macro_evidence_repair_failure_raises_structured_error() -> None:
    invalid = _macro_payload(market_regime="unclear")
    llm = SequencedLLM([json.dumps(invalid), "bad", "bad"])

    with pytest.raises(ValueError, match="LLM_REPAIR_FAILED|LLM_REPAIR_SCHEMA_INVALID"):
        DailyReviewMacroEvidenceAgent(llm).generate_macro_card("2026-05-20", {}, [], None)


def test_daily_position_review_main_output_success() -> None:
    structured = _parse_validate_repair_daily_review(
        llm_service=SequencedLLM([]),
        report_date="2026-05-20",
        raw_response=json.dumps(_daily_payload()),
        trace=[],
        deterministic_context={},
    )

    assert structured.ok
    assert structured.metadata["contract_name"] == "daily_position_review_main"
    assert structured.metadata["repaired"] is False


def test_daily_position_review_main_non_json_repairs_successfully() -> None:
    structured = _parse_validate_repair_daily_review(
        llm_service=SequencedLLM([json.dumps(_daily_payload(summary="repaired"))]),
        report_date="2026-05-20",
        raw_response="not json",
        trace=[],
        deterministic_context={},
    )

    assert structured.ok
    assert structured.payload["summary"] == "repaired"
    assert structured.metadata["repaired"] is True


def test_daily_position_review_main_repair_failure_uses_fallback() -> None:
    structured = _parse_validate_repair_daily_review(
        llm_service=SequencedLLM(["bad", "bad", "bad"]),
        report_date="2026-05-20",
        raw_response="not json",
        trace=[],
        deterministic_context={"overview": {"summary": "账户上涨"}, "rankings": {}, "risk": {}, "focus_symbols": ["AMD.US"]},
    )

    assert structured.ok
    assert structured.fallback_used is True
    assert structured.metadata["fallback_used"] is True
    assert structured.payload["summary"] == "账户上涨"


def test_daily_review_prompts_include_examples_and_json_rules() -> None:
    for prompt in (SYSTEM_PROMPT_SYMBOL_CARD, SYSTEM_PROMPT_MACRO_CARD, SYSTEM_PROMPT_SUBAGENT_CARDS):
        assert "JSON" in prompt
        assert "不要输出 Markdown" in prompt or "不要 Markdown" in prompt
        assert "不要代码块" in prompt
        assert "不要省略字段" in prompt
    assert '"source_trace"' in SYSTEM_PROMPT_SYMBOL_CARD
    assert '"market_regime"' in SYSTEM_PROMPT_MACRO_CARD
    assert '"focus_symbol_analyses"' in SYSTEM_PROMPT_SUBAGENT_CARDS
