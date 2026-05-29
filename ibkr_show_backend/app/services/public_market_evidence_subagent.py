from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from typing import Any

from app.services.llm_service import LLMService

PUBLIC_MARKET_DATA_SOURCE = "LONGBRIDGE_PUBLIC_ONLY"
NOT_INCLUDED = "NOT_INCLUDED"
RISK_DISCLAIMER = "以上仅基于公开市场数据做证据整理，不包含你的账户、仓位、成本或交易历史，也不构成确定性买卖建议。"
FORBIDDEN_OUTPUT_FIELDS = {"reasoning", "chain_of_thought", "thinking"}
TRADING_INSTRUCTION_PATTERNS = (
    "建议买入",
    "建议卖出",
    "必须加仓",
    "必须减仓",
    "应该买入",
    "应该卖出",
    "立即买入",
    "立即卖出",
    "buy now",
    "sell now",
)
CONFIDENCE_VALUES = {"low", "medium", "high"}


class PublicMarketEvidenceSubAgent:
    def __init__(
        self,
        llm_service: LLMService,
        prompt_service=None,
        max_input_chars: int = 24000,
        max_output_tokens: int | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.prompt_service = prompt_service
        self.max_input_chars = max_input_chars
        self.max_output_tokens = max_output_tokens

    def synthesize(
        self,
        evidence_pack: dict,
        question: str | None = None,
        intent: str | None = None,
    ) -> dict:
        try:
            compacted = self._compact_input_evidence_pack(evidence_pack)
            messages = self._build_messages(compacted, question=question, intent=intent)
            response = self._call_llm(messages)
            parsed = self._parse_json_object(response)
            pack = self._normalize_semantic_pack(parsed, evidence_pack, question=question, intent=intent)
            validation_limitations = self._validate_semantic_pack(pack)
            if validation_limitations:
                pack["data_limitations"] = self._unique_strings([*pack.get("data_limitations", []), *validation_limitations])
            return pack
        except Exception as exc:
            return self._fallback_semantic_pack(evidence_pack, f"LLM semantic synthesis failed: {exc}", question=question, intent=intent)

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        if hasattr(self.llm_service, "chat_with_metadata"):
            result = self.llm_service.chat_with_metadata(
                messages=messages,
                temperature=0.0,
                max_tokens=self.max_output_tokens,
                response_format={"type": "json_object"},
                call_type="sub_agent",
                agent_name="public_market_evidence",
                node_name="semantic_synthesis",
                prompt_metadata={"prompt_key": "public_market_evidence_subagent"},
            )
            return str(getattr(result, "content", "") or "")
        return str(
            self.llm_service.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=self.max_output_tokens,
                response_format={"type": "json_object"},
            )
            or ""
        )

    def _build_messages(self, evidence_pack: dict, *, question: str | None, intent: str | None) -> list[dict[str, str]]:
        system_prompt = (
            "你是 Public Market Evidence SubAgent。\n"
            "你只做公开市场证据语义压缩。你不是交易决策 Agent，也不是交易复盘 Agent。\n"
            "你不能给出买入、卖出、加仓、减仓等指令，不能承诺收益。\n"
            "你不能使用 IBKR 私有账户事实，不能编造 Evidence Pack 里没有的事实。\n"
            "你必须输出严格 JSON object，不能输出 hidden chain-of-thought，只能输出简短高层理由和证据结论。"
        )
        user_payload = {
            "question": question or evidence_pack.get("question"),
            "intent": intent or evidence_pack.get("intent"),
            "evidence_pack": evidence_pack,
            "output_schema": self._output_schema_hint(),
        }
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
        ]

    def _output_schema_hint(self) -> dict:
        return {
            "ok": True,
            "semantic_evidence_id": "pm_sem_xxx",
            "source_evidence_id": "pm_ev_xxx",
            "evidence_type": "public_market_semantic",
            "symbol": "AMD.US",
            "intent": "estimate_amd_three_year_scenario",
            "question": "...",
            "data_sources": {
                "public_market_data": PUBLIC_MARKET_DATA_SOURCE,
                "account_data": NOT_INCLUDED,
                "position_data": NOT_INCLUDED,
                "trade_data": NOT_INCLUDED,
            },
            "executive_summary": "...",
            "key_facts": [{"claim": "...", "source_tools": ["valuation"], "confidence": "medium"}],
            "bull_case_evidence": [],
            "bear_case_evidence": [],
            "valuation_interpretation": {},
            "financial_interpretation": {},
            "analyst_interpretation": {},
            "news_interpretation": {},
            "trend_interpretation": {},
            "conflicts": [],
            "missing_information": [],
            "data_limitations": [],
            "confidence": "low|medium|high",
            "evidence_used": [],
            "risk_disclaimer": RISK_DISCLAIMER,
        }

    def _compact_input_evidence_pack(self, evidence_pack: dict) -> dict:
        allowed_keys = {
            "evidence_id",
            "symbol",
            "intent",
            "question",
            "data_sources",
            "key_facts",
            "quote_summary",
            "valuation_summary",
            "financial_summary",
            "analyst_summary",
            "news_summary",
            "price_trend_summary",
            "missing_information",
            "data_limitations",
            "budget",
            "tool_results",
        }
        compacted = {key: deepcopy(value) for key, value in evidence_pack.items() if key in allowed_keys}
        if self._json_chars(compacted) <= self.max_input_chars:
            return compacted
        compacted["input_compacted"] = True
        for result in compacted.get("tool_results") or []:
            if isinstance(result, dict):
                result.pop("data", None)
        self._trim_news_items(compacted, limit=8)
        if self._json_chars(compacted) <= self.max_input_chars:
            return compacted
        for section in ("quote_summary", "valuation_summary", "financial_summary", "analyst_summary", "news_summary", "price_trend_summary"):
            value = compacted.get(section)
            if isinstance(value, dict) and "data" in value:
                text = self._json_text(value["data"])
                if len(text) > 2000:
                    value["data"] = {"truncated_json": text[:2000]}
        return compacted

    def _trim_news_items(self, pack: dict, limit: int) -> None:
        news_data = (pack.get("news_summary") or {}).get("data")
        if isinstance(news_data, dict) and isinstance(news_data.get("items"), list):
            news_data["items"] = news_data["items"][:limit]

    def _parse_json_object(self, response: str) -> dict:
        text = str(response or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM response must be a JSON object")
        return payload

    def _normalize_semantic_pack(self, payload: dict, evidence_pack: dict, *, question: str | None, intent: str | None) -> dict:
        cleaned = self._strip_hidden_fields(deepcopy(payload))
        source_id = evidence_pack.get("evidence_id")
        cleaned["ok"] = bool(cleaned.get("ok", True))
        cleaned["semantic_evidence_id"] = str(cleaned.get("semantic_evidence_id") or f"pm_sem_{uuid.uuid4().hex[:12]}")
        cleaned["source_evidence_id"] = str(cleaned.get("source_evidence_id") or source_id or "")
        cleaned["evidence_type"] = "public_market_semantic"
        cleaned["symbol"] = str(cleaned.get("symbol") or evidence_pack.get("symbol") or "")
        cleaned["intent"] = str(cleaned.get("intent") or intent or evidence_pack.get("intent") or "public_market_semantic_evidence")
        cleaned["question"] = cleaned.get("question") or question or evidence_pack.get("question")
        cleaned["data_limitations"] = self._ensure_list(cleaned.get("data_limitations") or evidence_pack.get("data_limitations"))
        cleaned["data_sources"] = self._safe_data_sources(cleaned.get("data_sources"), cleaned)
        cleaned["executive_summary"] = str(cleaned.get("executive_summary") or "").strip()
        cleaned["key_facts"] = self._ensure_list(cleaned.get("key_facts"))
        cleaned["bull_case_evidence"] = self._ensure_list(cleaned.get("bull_case_evidence"))
        cleaned["bear_case_evidence"] = self._ensure_list(cleaned.get("bear_case_evidence"))
        cleaned["valuation_interpretation"] = self._ensure_interpretation(cleaned.get("valuation_interpretation"), "valuation")
        cleaned["financial_interpretation"] = self._ensure_interpretation(cleaned.get("financial_interpretation"), "financial")
        cleaned["analyst_interpretation"] = self._ensure_interpretation(cleaned.get("analyst_interpretation"), "analyst")
        cleaned["news_interpretation"] = self._ensure_interpretation(cleaned.get("news_interpretation"), "news")
        cleaned["trend_interpretation"] = self._ensure_interpretation(cleaned.get("trend_interpretation"), "trend")
        cleaned["conflicts"] = self._ensure_list(cleaned.get("conflicts"))
        cleaned["missing_information"] = self._ensure_list(cleaned.get("missing_information") or evidence_pack.get("missing_information"))
        cleaned["confidence"] = str(cleaned.get("confidence") or "low").lower()
        cleaned["evidence_used"] = self._ensure_list(cleaned.get("evidence_used"))
        cleaned["risk_disclaimer"] = str(cleaned.get("risk_disclaimer") or RISK_DISCLAIMER).strip()
        return cleaned

    def _safe_data_sources(self, value: Any, pack: dict) -> dict:
        limitations = pack.setdefault("data_limitations", [])
        data_sources = value if isinstance(value, dict) else {}
        safe = {
            "public_market_data": PUBLIC_MARKET_DATA_SOURCE,
            "account_data": NOT_INCLUDED,
            "position_data": NOT_INCLUDED,
            "trade_data": NOT_INCLUDED,
        }
        for key in ("account_data", "position_data", "trade_data"):
            if data_sources.get(key) and data_sources.get(key) != NOT_INCLUDED:
                limitations.append(f"Private data source field {key} was reset to NOT_INCLUDED.")
        return safe

    def _validate_semantic_pack(self, pack: dict) -> list[str]:
        limitations: list[str] = []
        if not pack.get("executive_summary"):
            raise ValueError("executive_summary is required")
        confidence = str(pack.get("confidence") or "").lower()
        if confidence not in CONFIDENCE_VALUES:
            pack["confidence"] = "low"
            limitations.append("Invalid confidence was reset to low.")
        if not isinstance(pack.get("evidence_used"), list):
            pack["evidence_used"] = []
            limitations.append("Invalid evidence_used was reset to an empty list.")
        if pack.get("data_sources", {}).get("public_market_data") != PUBLIC_MARKET_DATA_SOURCE:
            pack["data_sources"]["public_market_data"] = PUBLIC_MARKET_DATA_SOURCE
            limitations.append("Public market data source was reset to LONGBRIDGE_PUBLIC_ONLY.")
        for key in ("account_data", "position_data", "trade_data"):
            if pack.get("data_sources", {}).get(key) != NOT_INCLUDED:
                pack["data_sources"][key] = NOT_INCLUDED
                limitations.append(f"Private data source field {key} was reset to NOT_INCLUDED.")
        if not pack.get("risk_disclaimer"):
            pack["risk_disclaimer"] = RISK_DISCLAIMER
        if self._contains_trading_instruction(pack):
            raise ValueError("trading instruction rejected")
        return limitations

    def _fallback_semantic_pack(self, evidence_pack: dict, reason: str, *, question: str | None = None, intent: str | None = None) -> dict:
        facts = evidence_pack.get("key_facts") or []
        fact_text = "；".join(str(item.get("fact") or item.get("claim") or item) for item in facts[:5]) if isinstance(facts, list) else ""
        limitations = self._ensure_list(evidence_pack.get("data_limitations"))
        reason_text = str(reason)
        if "trading instruction rejected" in reason_text:
            limitations.append("LLM semantic synthesis trading instruction rejected; returned deterministic fallback.")
        limitations.append("LLM semantic synthesis failed; returned deterministic fallback.")
        summary = fact_text or "公开市场 Evidence Pack 可用信息有限，已返回保守的 deterministic fallback。"
        return {
            "ok": False,
            "semantic_evidence_id": f"pm_sem_{uuid.uuid4().hex[:12]}",
            "source_evidence_id": str(evidence_pack.get("evidence_id") or ""),
            "evidence_type": "public_market_semantic",
            "symbol": str(evidence_pack.get("symbol") or ""),
            "intent": str(intent or evidence_pack.get("intent") or "public_market_semantic_evidence"),
            "question": question or evidence_pack.get("question"),
            "data_sources": {
                "public_market_data": PUBLIC_MARKET_DATA_SOURCE,
                "account_data": NOT_INCLUDED,
                "position_data": NOT_INCLUDED,
                "trade_data": NOT_INCLUDED,
            },
            "executive_summary": summary,
            "key_facts": [{"claim": summary, "source_tools": self._evidence_used_from_pack(evidence_pack), "confidence": "low"}],
            "bull_case_evidence": [],
            "bear_case_evidence": [],
            "valuation_interpretation": self._empty_interpretation("valuation"),
            "financial_interpretation": self._empty_interpretation("financial"),
            "analyst_interpretation": self._empty_interpretation("analyst"),
            "news_interpretation": self._empty_interpretation("news"),
            "trend_interpretation": self._empty_interpretation("trend"),
            "conflicts": [],
            "missing_information": self._ensure_list(evidence_pack.get("missing_information")),
            "data_limitations": self._unique_strings(limitations),
            "confidence": "low",
            "evidence_used": self._evidence_used_from_pack(evidence_pack),
            "risk_disclaimer": RISK_DISCLAIMER,
        }

    def _contains_trading_instruction(self, value: Any) -> bool:
        text = self._json_text(value).lower()
        return any(pattern.lower() in text for pattern in TRADING_INSTRUCTION_PATTERNS)

    def _strip_hidden_fields(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._strip_hidden_fields(item) for key, item in value.items() if key not in FORBIDDEN_OUTPUT_FIELDS}
        if isinstance(value, list):
            return [self._strip_hidden_fields(item) for item in value]
        return value

    def _ensure_interpretation(self, value: Any, label: str) -> dict:
        if isinstance(value, dict):
            return value
        return self._empty_interpretation(label)

    def _empty_interpretation(self, label: str) -> dict:
        return {"summary": "", "confidence": "low", "source_tools": [], f"{label}_status": "unknown"}

    def _ensure_list(self, value: Any) -> list:
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    def _evidence_used_from_pack(self, evidence_pack: dict) -> list[str]:
        tools = []
        for result in evidence_pack.get("tool_results") or []:
            if isinstance(result, dict) and result.get("tool_name") and result.get("ok", True):
                tools.append(str(result["tool_name"]))
        if tools:
            return self._unique_strings(tools)
        facts = evidence_pack.get("key_facts") or []
        for fact in facts if isinstance(facts, list) else []:
            if isinstance(fact, dict) and fact.get("source_tool"):
                tools.append(str(fact["source_tool"]))
        return self._unique_strings(tools)

    def _unique_strings(self, values: list[Any]) -> list[str]:
        result = []
        for value in values:
            text = str(value)
            if text and text not in result:
                result.append(text)
        return result

    def _json_text(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def _json_chars(self, value: Any) -> int:
        return len(self._json_text(value))
