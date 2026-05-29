from __future__ import annotations

import json
import uuid
from typing import Any

from app.agents.account_copilot.longbridge_tools import AccountCopilotLongbridgeToolService


class PublicMarketEvidenceBuilder:
    def __init__(self, longbridge_tool_service: AccountCopilotLongbridgeToolService) -> None:
        self.longbridge_tool_service = longbridge_tool_service

    def build_symbol_evidence(
        self,
        symbol: str,
        intent: str = "general_public_market_evidence",
        question: str | None = None,
        include_news: bool = True,
        include_candles: bool = True,
        include_financials: bool = True,
        include_valuation: bool = True,
        include_analyst: bool = True,
        max_total_chars: int = 18000,
    ) -> dict:
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_intent = str(intent or "general_public_market_evidence")
        available_tools = self._available_tools()
        calls = self._select_calls(
            normalized_symbol,
            available_tools,
            intent=normalized_intent,
            question=question,
            include_news=include_news,
            include_candles=include_candles,
            include_financials=include_financials,
            include_valuation=include_valuation,
            include_analyst=include_analyst,
        )
        batch = self.longbridge_tool_service.call_public_tools(
            intent=normalized_intent,
            calls=calls,
            max_total_chars=max_total_chars,
        )
        pack = self._build_pack_from_batch(
            symbol=normalized_symbol,
            intent=normalized_intent,
            question=question,
            calls=calls,
            batch=batch,
            max_total_chars=max_total_chars,
        )
        return self._fit_evidence_pack(pack, max_total_chars)

    def build_market_question_evidence(
        self,
        symbol: str,
        question: str,
        intent: str | None = None,
    ) -> dict:
        return self.build_symbol_evidence(
            symbol=symbol,
            intent=intent or self._intent_from_question(question),
            question=question,
        )

    def _available_tools(self) -> dict[str, set[str]]:
        categories = ["quote", "valuation", "analyst", "financial", "news", "candles", "company", "calendar", "market"]
        available: dict[str, set[str]] = {}
        for offset in range(0, len(categories), 4):
            result = self.longbridge_tool_service.list_public_tools(categories=categories[offset:offset + 4], limit_per_category=10)
            if not result.get("ok"):
                continue
            for group in result.get("data", {}).get("groups") or []:
                category = str(group.get("category") or "")
                available.setdefault(category, set())
                for item in group.get("items") or []:
                    name = str(item.get("name") or "")
                    if name:
                        available[category].add(name)
        return available

    def _select_calls(
        self,
        symbol: str,
        available_tools: dict[str, set[str]],
        *,
        intent: str,
        question: str | None,
        include_news: bool,
        include_candles: bool,
        include_financials: bool,
        include_valuation: bool,
        include_analyst: bool,
    ) -> list[dict]:
        text = f"{intent} {question or ''}".lower()
        wants_trend = self._contains_any(text, ("trend", "price", "走势", "回撤", "三年", "未来"))
        wants_news = self._contains_any(text, ("新闻", "为什么涨", "为什么跌", "大涨", "大跌", "催化"))
        wants_valuation = include_valuation or self._contains_any(text, ("估值", "贵不贵", "pe", "pb", "ps"))
        wants_analyst = include_analyst or self._contains_any(text, ("分析师", "目标价", "预期", "eps"))

        selected: list[dict] = []
        quote = self._pick_tool(available_tools, "quote", ("quote",))
        if quote:
            selected.append(self._call(quote, symbol, "required", "获取当前价格、涨跌幅、成交量、交易状态"))

        valuation = self._pick_tool(available_tools, "valuation", ("valuation", "industry_valuation", "industry_peers"))
        if wants_valuation and valuation:
            selected.append(self._call(valuation, symbol, "required", "判断估值水平"))

        if include_candles and wants_trend:
            candles = self._pick_tool(available_tools, "candles", ("history_candlesticks", "candlesticks"))
            if candles:
                selected.append(self._call(candles, symbol, "optional", "获取价格走势、回撤和趋势"))

        if wants_analyst:
            analyst = self._pick_tool(available_tools, "analyst", ("analyst_estimates", "consensus", "institution_rating", "forecast_eps"))
            if analyst:
                selected.append(self._call(analyst, symbol, "optional", "获取分析师预期、目标价、EPS/收入预测"))

        if include_financials:
            financial = self._pick_tool(available_tools, "financial", ("financial_report_latest", "financial_report", "financial_statement"))
            if financial:
                selected.append(self._call(financial, symbol, "optional", "获取最近财报和核心财务指标"))

        if include_news and (wants_news or not wants_trend):
            news = self._pick_tool(available_tools, "news", ("news_search",))
            if news:
                selected.append(
                    {
                        "tool_name": news,
                        "arguments": {"keyword": symbol.split(".")[0], "limit": 8},
                        "priority": "optional",
                        "purpose": "获取近期新闻和事件催化",
                        "max_chars": 4000,
                    }
                )

        return self._dedupe_calls(selected)[:5]

    def _call(self, tool_name: str, symbol: str, priority: str, purpose: str) -> dict:
        return {
            "tool_name": tool_name,
            "arguments": {"symbol": symbol},
            "priority": priority,
            "purpose": purpose,
            "max_chars": 4000,
        }

    def _build_pack_from_batch(
        self,
        *,
        symbol: str,
        intent: str,
        question: str | None,
        calls: list[dict],
        batch: dict,
        max_total_chars: int,
    ) -> dict:
        batch_data = batch.get("data") or {}
        results = batch_data.get("results") or []
        pack = {
            "ok": bool(batch.get("ok")),
            "evidence_id": f"pm_ev_{uuid.uuid4().hex[:12]}",
            "evidence_type": "public_market",
            "symbol": symbol,
            "intent": intent,
            "question": question,
            "data_sources": {
                "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
                "account_data": "NOT_INCLUDED",
                "position_data": "NOT_INCLUDED",
                "trade_data": "NOT_INCLUDED",
            },
            "tool_plan": {"calls": [{"tool_name": call.get("tool_name"), "priority": call.get("priority", "required"), "purpose": call.get("purpose")} for call in calls]},
            "key_facts": [],
            "quote_summary": {},
            "price_trend_summary": {},
            "valuation_summary": {},
            "financial_summary": {},
            "analyst_summary": {},
            "news_summary": {},
            "company_summary": {},
            "calendar_summary": {},
            "market_status_summary": {},
            "bull_case_evidence": [],
            "bear_case_evidence": [],
            "missing_information": [],
            "tool_results": [],
            "budget": {
                "max_total_chars": max_total_chars,
                "used_chars": 0,
                "truncated": bool((batch_data.get("budget") or {}).get("truncated")),
            },
            "data_limitations": list(batch.get("data_limitations") or []),
        }

        for result in results:
            self._merge_result(pack, result)

        if batch_data.get("status") == "partial_success":
            pack["data_limitations"].append("Public market evidence is partial because some tools failed or returned empty results.")
        if (batch_data.get("budget") or {}).get("truncated"):
            pack["data_limitations"].append("Public market evidence was truncated to fit context budget.")
        if self._required_failed(results):
            pack["ok"] = False
            pack["data_limitations"].append("Required public market evidence is insufficient because quote or valuation failed.")
        pack["data_limitations"] = self._unique_strings(pack["data_limitations"])
        pack["budget"]["used_chars"] = self._json_chars(pack)
        return pack

    def _merge_result(self, pack: dict, result: dict) -> None:
        tool_name = str(result.get("tool_name") or "")
        summary = result.get("summary") or f"{tool_name} returned public market evidence."
        pack["tool_results"].append(
            {
                "tool_name": tool_name,
                "ok": bool(result.get("ok")),
                "status": result.get("status"),
                "summary": summary,
                "data": result.get("data") or {},
                "data_limitations": result.get("data_limitations") or [],
            }
        )
        pack["data_limitations"].extend(result.get("data_limitations") or [])
        if result.get("ok"):
            pack["key_facts"].append({"fact": f"{tool_name} returned public market evidence.", "source_tool": tool_name, "confidence": "medium"})
            self._section_for_tool(pack, tool_name).update(
                {
                    "tool_name": tool_name,
                    "status": result.get("status"),
                    "summary": summary,
                    "data": result.get("data") or {},
                    "data_limitations": result.get("data_limitations") or [],
                }
            )
            return
        if result.get("priority") == "required":
            pack["missing_information"].append(f"Required public market tool {tool_name} failed or returned empty result.")
        else:
            pack["missing_information"].append(f"Optional public market tool {tool_name} unavailable.")

    def _section_for_tool(self, pack: dict, tool_name: str) -> dict:
        name = tool_name.lower()
        if name == "quote":
            return pack["quote_summary"]
        if name in {"candlesticks", "history_candlesticks"}:
            return pack["price_trend_summary"]
        if name in {"valuation", "industry_peers", "industry_valuation"}:
            return pack["valuation_summary"]
        if name in {"financial_report", "financial_report_latest", "financial_statement"}:
            return pack["financial_summary"]
        if name in {"analyst_estimates", "consensus", "institution_rating", "forecast_eps"}:
            return pack["analyst_summary"]
        if name == "news_search":
            return pack["news_summary"]
        if name in {"company", "static_info", "business_segments", "business_segments_history"}:
            return pack["company_summary"]
        if name == "finance_calendar":
            return pack["calendar_summary"]
        if name == "market_status":
            return pack["market_status_summary"]
        return pack["company_summary"]

    def _fit_evidence_pack(self, pack: dict, max_chars: int = 18000) -> dict:
        pack["budget"]["used_chars"] = self._json_chars(pack)
        if pack["budget"]["used_chars"] <= max_chars:
            return pack
        for result in pack.get("tool_results") or []:
            result.pop("data", None)
        pack["budget"]["truncated"] = True
        self._append_limitation(pack, "Evidence pack was compacted to fit context budget.")
        if self._json_chars(pack) <= max_chars:
            pack["budget"]["used_chars"] = self._json_chars(pack)
            return pack
        items = ((pack.get("news_summary") or {}).get("data") or {}).get("items")
        if isinstance(items, list):
            pack["news_summary"]["data"]["items"] = items[:5]
        if self._json_chars(pack) <= max_chars:
            pack["budget"]["used_chars"] = self._json_chars(pack)
            return pack
        for section in ("news_summary", "financial_summary", "analyst_summary", "price_trend_summary", "company_summary", "calendar_summary", "market_status_summary"):
            if isinstance(pack.get(section), dict):
                pack[section].pop("data", None)
        pack["budget"]["used_chars"] = self._json_chars(pack)
        return pack

    def _required_failed(self, results: list[dict]) -> bool:
        for result in results:
            if result.get("priority") == "required" and not result.get("ok"):
                return True
        return False

    def _pick_tool(self, available_tools: dict[str, set[str]], category: str, candidates: tuple[str, ...]) -> str | None:
        names = available_tools.get(category) or set()
        for candidate in candidates:
            if candidate in names:
                return candidate
        return None

    def _dedupe_calls(self, calls: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result = []
        for call in calls:
            name = str(call.get("tool_name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(call)
        return result

    def _intent_from_question(self, question: str) -> str:
        text = question.lower()
        if self._contains_any(text, ("三年", "未来", "走势", "trend")):
            return "public_market_trend_evidence"
        if self._contains_any(text, ("新闻", "大涨", "大跌", "催化")):
            return "public_market_news_evidence"
        return "general_public_market_evidence"

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    def _append_limitation(self, pack: dict, limitation: str) -> None:
        if limitation not in pack["data_limitations"]:
            pack["data_limitations"].append(limitation)

    def _unique_strings(self, values: list[str]) -> list[str]:
        result = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _json_chars(self, value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
