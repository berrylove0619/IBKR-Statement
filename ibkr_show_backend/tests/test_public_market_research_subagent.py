from __future__ import annotations

import json

from app.services.public_market_research_subagent import PublicMarketResearchSubAgent


class FakePublicMarketEvidenceBuilder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def build_market_question_evidence(self, symbol: str, question: str, intent: str | None = None) -> dict:
        self.calls.append({"symbol": symbol, "question": question, "intent": intent})
        return {
            "ok": True,
            "evidence_id": "pm_ev_test",
            "symbol": symbol,
            "intent": intent or "public_market_research",
            "key_facts": [{"fact": "valuation returned public market evidence.", "source_tool": "valuation", "confidence": "medium"}],
            "bull_case_evidence": [],
            "bear_case_evidence": [],
            "missing_information": ["Optional public market tool news_search unavailable."],
            "data_limitations": ["Public market evidence is partial."],
            "data_sources": {
                "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
                "account_data": "NOT_INCLUDED",
                "position_data": "NOT_INCLUDED",
                "trade_data": "NOT_INCLUDED",
            },
        }


def test_public_market_research_subagent_uses_builder() -> None:
    builder = FakePublicMarketEvidenceBuilder()
    result = PublicMarketResearchSubAgent(builder).run("AMD.US", "AMD 最近为什么大跌？", "public_market_research")
    assert builder.calls == [{"symbol": "AMD.US", "question": "AMD 最近为什么大跌？", "intent": "public_market_research"}]
    assert result["ok"] is True
    assert result["subagent_name"] == "public_market_research_subagent"
    assert result["summary"]
    assert result["key_facts"]
    assert result["missing_information"]
    assert result["data_limitations"]
    assert result["data_sources"]["account_data"] == "NOT_INCLUDED"


def test_public_market_research_subagent_does_not_include_private_account_terms() -> None:
    result = PublicMarketResearchSubAgent(FakePublicMarketEvidenceBuilder()).run("AMD.US", "AMD 最近为什么大跌？")
    payload = json.dumps(result, ensure_ascii=False).lower()
    for term in ("account_balance", "positions", "trades", "orders", "executions", "margin", "cash_flow"):
        assert term not in payload
