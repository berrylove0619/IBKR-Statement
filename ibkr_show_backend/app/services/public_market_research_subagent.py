from __future__ import annotations

from typing import Any

from app.services.public_market_evidence_builder import PublicMarketEvidenceBuilder
from app.services.llm_service import LLMService


class PublicMarketResearchSubAgent:
    def __init__(
        self,
        evidence_builder: PublicMarketEvidenceBuilder,
        llm_service: LLMService | None = None,
    ) -> None:
        self.evidence_builder = evidence_builder
        self.llm_service = llm_service

    def run(
        self,
        symbol: str,
        question: str,
        intent: str | None = None,
    ) -> dict:
        evidence_pack = self.evidence_builder.build_market_question_evidence(
            symbol=symbol,
            question=question,
            intent=intent,
        )
        ok = bool(evidence_pack.get("ok"))
        summary = (
            f"已基于 Longbridge 公开市场数据整理 {evidence_pack.get('symbol') or symbol} 的公开市场证据。"
            if ok
            else "公开市场证据不足，部分关键工具失败或返回空结果。"
        )
        limitations = list(evidence_pack.get("data_limitations") or [])
        limitations.append("This subagent only used public market data and did not access IBKR account facts or user trade facts.")
        return {
            "ok": ok,
            "subagent_name": "public_market_research_subagent",
            "symbol": evidence_pack.get("symbol") or symbol,
            "question": question,
            "intent": intent or evidence_pack.get("intent"),
            "summary": summary,
            "key_facts": self._limit_list(evidence_pack.get("key_facts"), 8),
            "bull_case_evidence": self._limit_list(evidence_pack.get("bull_case_evidence"), 8),
            "bear_case_evidence": self._limit_list(evidence_pack.get("bear_case_evidence"), 8),
            "missing_information": self._limit_list(evidence_pack.get("missing_information"), 12),
            "data_limitations": self._unique_strings(limitations),
            "evidence_id": evidence_pack.get("evidence_id"),
            "data_sources": {
                "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
                "account_data": "NOT_INCLUDED",
                "position_data": "NOT_INCLUDED",
                "trade_data": "NOT_INCLUDED",
            },
            "metadata": {
                "read_only": True,
                "approval_required": False,
                "source": "PublicMarketEvidenceBuilder",
            },
        }

    def _limit_list(self, value: Any, limit: int) -> list:
        return value[:limit] if isinstance(value, list) else []

    def _unique_strings(self, values: list[str]) -> list[str]:
        result = []
        for value in values:
            text = str(value)
            if text and text not in result:
                result.append(text)
        return result
