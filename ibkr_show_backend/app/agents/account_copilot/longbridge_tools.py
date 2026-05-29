from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter, classify_mcp_tool

DATA_SOURCE = "LONGBRIDGE_MCP_PUBLIC"
PUBLIC_CLASSIFICATION = "public_market_readonly"
SENSITIVE_KEYWORDS = ("token", "authorization", "cookie", "secret", "password", "oauth", "header", "api_key", "apikey")
PUBLIC_TOOL_CATEGORY_ORDER = [
    "quote",
    "candles",
    "news",
    "financial",
    "valuation",
    "analyst",
    "calendar",
    "market",
    "company",
    "other_public",
]
PUBLIC_TOOL_CATEGORY_METADATA = {
    "quote": {
        "label": "行情快照",
        "description": "获取标的当前价格、涨跌幅、成交量、交易状态等",
        "typical_questions": ["AMD 现在价格是多少", "今天涨跌幅是多少"],
    },
    "candles": {
        "label": "K线",
        "description": "获取历史 K 线、区间涨跌幅和价格走势等",
        "typical_questions": ["AMD 最近一个月走势如何", "这只股票过去 20 天涨了多少"],
    },
    "news": {
        "label": "新闻",
        "description": "搜索公司、行业和市场相关新闻",
        "typical_questions": ["AMD 最近有什么新闻", "今天半导体板块为什么波动"],
    },
    "financial": {
        "label": "财务报表",
        "description": "获取收入、利润、EPS、现金流、资产负债表等财务数据",
        "typical_questions": ["AMD 最近财报怎么样", "收入和净利润趋势如何"],
    },
    "valuation": {
        "label": "估值",
        "description": "获取 PE/PB/PS、同业估值、估值区间等",
        "typical_questions": ["AMD 估值贵不贵", "和同业相比 PE 如何"],
    },
    "analyst": {
        "label": "分析师预期",
        "description": "获取评级、目标价、机构观点、EPS 预测和一致预期等",
        "typical_questions": ["分析师怎么看 AMD", "AMD 未来 EPS 预期如何"],
    },
    "calendar": {
        "label": "财经日历",
        "description": "获取财报日期、分红日历和市场事件等",
        "typical_questions": ["AMD 什么时候发财报", "近期有什么重要分红或财报事件"],
    },
    "market": {
        "label": "市场状态",
        "description": "获取市场交易状态、开闭市信息等",
        "typical_questions": ["美股现在开盘了吗", "港股今天是否交易"],
    },
    "company": {
        "label": "公司信息",
        "description": "获取公司简介、静态资料、业务分部和证券基础信息等",
        "typical_questions": ["AMD 是做什么的", "AMD 收入来自哪些业务"],
    },
    "other_public": {
        "label": "其他公开市场数据",
        "description": "其他 Longbridge 公开市场只读工具",
        "typical_questions": ["还有哪些公开市场数据可用"],
    },
}
OUTPUT_FIELDS_BY_CATEGORY = {
    "quote": ["symbol", "price", "prev_close", "change_pct", "volume", "market_time", "trade_status"],
    "candles": ["sample_points", "time_range", "return_pct", "max_drawdown_pct", "volatility_summary", "trend_summary", "latest_close"],
    "news": ["items.title", "items.published_at", "items.source", "items.summary", "total_returned"],
    "valuation": ["pe_ttm", "forward_pe", "pb_ratio", "ps_ttm", "market_cap", "pe_range"],
    "analyst": ["consensus", "target_price", "target_price_high", "target_price_low", "eps_forward", "revenue_estimate"],
    "financial": ["revenue", "net_income", "eps", "gross_margin", "net_margin", "free_cash_flow", "latest_period"],
    "company": ["name", "symbol", "market", "sector", "industry", "description", "business_segments"],
    "calendar": ["next_earnings_date", "dividend_date", "important_events"],
    "market": ["status", "session"],
}


class AccountCopilotLongbridgeToolService:
    def __init__(self, adapter: LongbridgeMCPToolAdapter | None) -> None:
        self.adapter = adapter

    def list_public_tools(
        self,
        query: str | None = None,
        category: str | None = None,
        categories: list[str] | None = None,
        limit_per_category: int = 10,
        limit: int | None = None,
    ) -> dict:
        arguments = {
            "category": category,
            "categories": categories,
            "query": query,
            "limit_per_category": self._clamp_limit_per_category(limit_per_category if limit_per_category is not None else limit),
        }
        raw_category_count = self._raw_category_count(category, categories)
        if raw_category_count > 4:
            return self._error(
                "longbridge_list_public_tools",
                arguments,
                "LONG_BRIDGE_TOO_MANY_CATEGORIES",
                "At most 4 Longbridge public tool categories can be requested at once.",
                ["Request fewer Longbridge public tool categories, then list concrete tools progressively."],
            )
        wanted_categories = self._normalize_categories(category, categories)
        try:
            catalog = self._catalog()
            tools = catalog.get("tools") or []
            blocked_count = len([item for item in tools if not self._is_public_tool_item(item)])
            public_items = [self._public_summary(item, query=query) for item in tools if self._is_public_tool_item(item)]
            filtered = self._filter_items(public_items, categories=wanted_categories)
            grouped = self._group_items(filtered, limit_per_category=arguments["limit_per_category"], include_empty=False)
            flat_items = [item for group in grouped for item in group["items"]]
            limitations = self._catalog_limitations(catalog)
            return self._envelope(
                "longbridge_list_public_tools",
                arguments,
                {
                    "source": catalog.get("source") or "static_fallback",
                    "groups": grouped,
                    "items": flat_items[: self._clamp_limit(limit)] if limit is not None else flat_items,
                    "total_public_tool_count": len(public_items),
                    "filtered_public_tool_count": len(filtered),
                    "total": len(public_items),
                    "filtered_total": len(filtered),
                    "blocked_count": blocked_count,
                    "ranking_strategy": "query_ranking_only_no_filtering",
                },
                limitations,
            )
        except Exception as exc:
            return self._error("longbridge_list_public_tools", arguments, "LONGBRIDGE_CATALOG_UNAVAILABLE", str(exc), ["Longbridge MCP tool catalog is unavailable."])

    def list_public_tool_categories(self, include_empty: bool = False) -> dict:
        arguments = {"include_empty": bool(include_empty)}
        try:
            catalog = self._catalog()
            tools = catalog.get("tools") or []
            blocked_count = len([item for item in tools if not self._is_public_tool_item(item)])
            public_items = [self._public_summary(item) for item in tools if self._is_public_tool_item(item)]
            counts = {category: 0 for category in PUBLIC_TOOL_CATEGORY_ORDER}
            for item in public_items:
                category = str(item.get("category") or "other_public")
                counts[category] = counts.get(category, 0) + 1
            categories = []
            for category in PUBLIC_TOOL_CATEGORY_ORDER:
                count = counts.get(category, 0)
                if not include_empty and count <= 0:
                    continue
                meta = PUBLIC_TOOL_CATEGORY_METADATA[category]
                categories.append(
                    {
                        "category": category,
                        "label": meta["label"],
                        "description": meta["description"],
                        "tool_count": count,
                        "typical_questions": meta["typical_questions"],
                    }
                )
            return self._envelope(
                "longbridge_list_public_tool_categories",
                arguments,
                {
                    "source": catalog.get("source") or "static_fallback",
                    "categories": categories,
                    "total_public_tool_count": len(public_items),
                    "blocked_count": blocked_count,
                },
                self._catalog_limitations(catalog),
            )
        except Exception as exc:
            return self._error("longbridge_list_public_tool_categories", arguments, "LONGBRIDGE_CATALOG_UNAVAILABLE", str(exc), ["Longbridge MCP tool catalog is unavailable."])

    def get_public_tool_schema(self, tool_name: str) -> dict:
        arguments = {"tool_name": tool_name}
        try:
            item = self._get_public_catalog_item(tool_name)
            if item is None:
                return self._not_allowed("longbridge_get_public_tool_schema", arguments, tool_name)
            schema = item.get("input_schema") or self._fallback_input_schema(item.get("name"))
            limitations = [] if item.get("input_schema") else ["MCP catalog did not include input_schema; returned a generic fallback schema."]
            return self._envelope(
                "longbridge_get_public_tool_schema",
                arguments,
                {
                    "name": item.get("name"),
                    "description": item.get("description") or self._fallback_description(item.get("name")),
                    "category": self._category_for_tool(item),
                    "input_schema": schema,
                },
                limitations,
            )
        except Exception as exc:
            return self._error("longbridge_get_public_tool_schema", arguments, "LONGBRIDGE_SCHEMA_UNAVAILABLE", str(exc), ["Longbridge public tool schema lookup failed."])

    def get_public_tool_schemas(self, tool_names: list[str]) -> dict:
        arguments = {"tool_names": tool_names}
        if not isinstance(tool_names, list):
            return self._error(
                "longbridge_get_public_tool_schemas",
                arguments,
                "LONG_BRIDGE_INVALID_SCHEMA_BATCH",
                "tool_names must be a list.",
                ["Longbridge schema batch requires a list of tool names."],
            )
        if len(tool_names) > 6:
            return self._error(
                "longbridge_get_public_tool_schemas",
                arguments,
                "LONG_BRIDGE_SCHEMA_BATCH_TOO_LARGE",
                "At most 6 Longbridge public tool schemas can be requested at once.",
                ["Request fewer Longbridge public tool schemas, then continue progressively."],
            )
        if not tool_names:
            return self._error(
                "longbridge_get_public_tool_schemas",
                arguments,
                "LONG_BRIDGE_INVALID_SCHEMA_BATCH",
                "tool_names must include at least one tool.",
                ["Longbridge schema batch requires at least one tool name."],
            )
        try:
            schemas = [self._schema_result_for_tool(str(tool_name or "").strip()) for tool_name in tool_names]
            success_count = len([item for item in schemas if item.get("ok")])
            return self._envelope(
                "longbridge_get_public_tool_schemas",
                arguments,
                {
                    "schemas": schemas,
                    "requested_count": len(tool_names),
                    "success_count": success_count,
                    "failed_count": len(tool_names) - success_count,
                },
                [],
            )
        except Exception as exc:
            return self._error("longbridge_get_public_tool_schemas", arguments, "LONGBRIDGE_SCHEMA_UNAVAILABLE", str(exc), ["Longbridge public tool schema batch lookup failed."])

    def call_public_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        call_arguments = {"tool_name": tool_name, "arguments": arguments or {}}
        item = self._get_public_catalog_item(tool_name)
        if item is None:
            return self._not_allowed("longbridge_call_public_tool", call_arguments, tool_name)
        if self.adapter is None:
            return self._error("longbridge_call_public_tool", call_arguments, "LONGBRIDGE_MCP_UNAVAILABLE", "MCP adapter is not available", ["Longbridge MCP is disabled or not configured."])

        result = self.adapter.call(tool_name, arguments or {})
        if not result.get("ok"):
            return self._error(
                "longbridge_call_public_tool",
                call_arguments,
                str(result.get("error_code") or "LONGBRIDGE_MCP_ERROR"),
                str(result.get("message") or "Longbridge MCP tool call failed"),
                result.get("data_limitations") or ["Longbridge MCP tool call failed."],
                metadata={"mcp_tool": result.get("mcp_tool") or tool_name},
            )
        return self._envelope(
            "longbridge_call_public_tool",
            call_arguments,
            {"called_tool": tool_name, "result": self._sanitize(result.get("data"))},
            result.get("data_limitations") or [],
            metadata={"mcp_tool": result.get("mcp_tool") or tool_name},
        )

    def call_public_tools(
        self,
        calls: list[dict],
        intent: str | None = None,
        max_total_chars: int = 18000,
    ) -> dict:
        arguments = {
            "intent": intent,
            "calls": calls,
            "max_total_chars": self._clamp_max_total_chars(max_total_chars),
        }
        if not isinstance(calls, list):
            return self._error(
                "longbridge_call_public_tools",
                arguments,
                "LONG_BRIDGE_INVALID_TOOL_BATCH",
                "calls must be a list.",
                ["Longbridge batch calls require a list of call objects."],
            )
        if len(calls) > 5:
            return self._error(
                "longbridge_call_public_tools",
                arguments,
                "LONG_BRIDGE_TOOL_BATCH_TOO_LARGE",
                "At most 5 Longbridge public tools can be called in one batch.",
                ["Request fewer Longbridge public tool calls in one backend batch."],
            )
        if not calls:
            return self._error(
                "longbridge_call_public_tools",
                arguments,
                "LONG_BRIDGE_INVALID_TOOL_BATCH",
                "calls must include at least one call.",
                ["Longbridge batch calls require at least one call object."],
            )

        prepared_results: list[dict | None] = [None] * len(calls)
        executable_calls: list[tuple[int, dict, dict]] = []
        for index, raw_call in enumerate(calls):
            call = raw_call if isinstance(raw_call, dict) else {}
            tool_name = str(call.get("tool_name") or "").strip()
            priority = self._normalize_priority(call.get("priority"))
            purpose = self._safe_text(call.get("purpose") or "") if call.get("purpose") is not None else None
            call_max_chars = self._clamp_call_max_chars(call.get("max_chars"))
            item = self._get_public_catalog_item(tool_name)
            if item is None:
                prepared_results[index] = self._forbidden_call_result(tool_name, priority, purpose)
                continue
            if self.adapter is None:
                prepared_results[index] = self._failed_call_result(
                    tool_name,
                    priority,
                    purpose,
                    "mcp_unavailable",
                    "LONGBRIDGE_MCP_UNAVAILABLE",
                    "MCP adapter is not available",
                    ["Longbridge MCP is disabled or not configured."],
                    0,
                )
                continue
            call_arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            executable_calls.append(
                (
                    index,
                    {
                        "tool_name": tool_name,
                        "arguments": call_arguments,
                        "priority": priority,
                        "purpose": purpose,
                        "max_chars": call_max_chars,
                    },
                    item,
                )
            )

        if executable_calls:
            with ThreadPoolExecutor(max_workers=min(len(executable_calls), 5)) as executor:
                future_map = {
                    executor.submit(self._execute_public_tool_call, call, item): index
                    for index, call, item in executable_calls
                }
                for future in as_completed(future_map):
                    prepared_results[future_map[future]] = future.result()

        results = [result for result in prepared_results if result is not None]
        required_results = [result for result in results if result.get("priority") == "required"]
        success_count = len([result for result in results if result.get("ok")])
        failed_count = len([result for result in results if not result.get("ok") and result.get("status") != "forbidden"])
        forbidden_count = len([result for result in results if result.get("status") == "forbidden"])
        executed_count = len(executable_calls)
        required_success_count = len([result for result in required_results if result.get("ok")])
        has_required = bool(required_results)
        batch_ok = (required_success_count > 0) if has_required else success_count > 0
        if not success_count:
            batch_status = "failed"
        elif success_count == len(results):
            batch_status = "success"
        else:
            batch_status = "partial_success"
        if not batch_ok:
            batch_status = "failed"

        budget_limit = arguments["max_total_chars"]
        budget_truncated = self._apply_batch_budget(results, budget_limit)
        data_limitations = []
        if budget_truncated:
            data_limitations.append("Batch result was compacted or truncated to fit Account Copilot context budget.")
        batch_data = {
            "intent": intent,
            "status": batch_status,
            "results": results,
            "requested_count": len(calls),
            "executed_count": executed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "forbidden_count": forbidden_count,
            "budget": {
                "max_total_chars": budget_limit,
                "used_chars": self._json_chars(results),
                "truncated": budget_truncated,
            },
        }
        if batch_ok:
            return self._envelope("longbridge_call_public_tools", arguments, batch_data, data_limitations)
        failure = self._error(
            "longbridge_call_public_tools",
            arguments,
            "LONG_BRIDGE_TOOL_BATCH_FAILED",
            "All required Longbridge public tool calls failed.",
            data_limitations or ["Longbridge public tool batch did not return usable required data."],
            metadata={"batch_status": batch_status},
        )
        failure["data"] = batch_data
        return failure

    def _catalog(self) -> dict:
        if self.adapter is None:
            return {"source": "static_fallback", "tools": [], "public_market_readonly": [], "blocked": [], "list_error": "MCP adapter unavailable"}
        catalog = self.adapter.get_tool_catalog()
        tools = catalog.get("tools") or []
        return {**catalog, "tools": tools}

    def _get_public_catalog_item(self, tool_name: str) -> dict | None:
        if not tool_name or not str(tool_name).strip():
            return None
        requested = str(tool_name).strip()
        for item in self._catalog().get("tools") or []:
            if item.get("name") == requested and self._is_public_tool_item(item):
                return item
        return None

    def _is_public_tool_item(self, item: dict) -> bool:
        name = str(item.get("name") or "")
        classification = item.get("classification") or classify_mcp_tool(item)
        return bool(item.get("allowed")) and classification == PUBLIC_CLASSIFICATION and classify_mcp_tool(item) == PUBLIC_CLASSIFICATION and name

    def _public_summary(self, item: dict, query: str | None = None) -> dict:
        category = self._category_for_tool(item)
        rank_score, rank_reason = self._rank_item(item, category, query)
        return {
            "name": item.get("name"),
            "category": category,
            "description": item.get("description") or self._fallback_description(item.get("name")),
            "required_identifiers": self._required_identifiers(item),
            "rank_score": rank_score,
            "rank_reason": rank_reason,
            "next_step": "调用 longbridge_get_public_tool_schema 获取入参要求",
        }

    def _filter_items(self, items: list[dict], *, categories: list[str]) -> list[dict]:
        filtered = items
        if categories:
            wanted = {category.lower() for category in categories}
            filtered = [item for item in filtered if str(item.get("category") or "").lower() in wanted]
        return filtered

    _QUERY_STOPWORDS = frozenset({"stock", "symbol", "ticker", "company", "the", "a", "an", "is", "are", "what", "how", "do", "does", "can", "could", "would", "should", "will", "about", "for", "and", "or", "of", "in", "on", "to", "it", "its", "my", "me", "i", "we", "you", "they", "this", "that", "these", "those", "us", "hk", "cn", "sh", "sz"})
    _QUERY_DOMAIN_WORDS = frozenset({"quote", "price", "news", "valuation", "analyst", "estimate", "estimates", "forecast", "financial", "earnings", "calendar", "company", "market", "candle", "candles", "history", "institution", "rating", "consensus", "peer", "segment", "static", "info", "search"})

    def _query_tokens(self, query: str | None) -> list[str]:
        raw = str(query or "").strip().lower()
        if not raw:
            return []
        tokens = re.split(r"[^a-z0-9_]+", raw)
        result = []
        for token in tokens:
            if not token or token in self._QUERY_STOPWORDS:
                continue
            if token in self._QUERY_DOMAIN_WORDS:
                result.append(token)
                continue
            if len(token) <= 5 and token.isalpha():
                continue
            result.append(token)
        return result

    def _category_for_tool(self, item: dict | str | None) -> str:
        name = str(item.get("name") if isinstance(item, dict) else item or "").lower()
        description = str(item.get("description") if isinstance(item, dict) else "" or "").lower()
        text = f"{name} {description}"
        if self._has_any(text, ("quote",)):
            return "quote"
        if self._has_any(text, ("candle", "candlestick", "history_candlestick", "history")):
            return "candles"
        if self._has_any(text, ("news",)):
            return "news"
        if self._has_any(text, ("valuation", "industry_valuation", "peer", "peers")) or re.search(r"(^|[^a-z0-9])(pe|pb|ps)([^a-z0-9]|$)", text):
            return "valuation"
        if self._has_any(text, ("analyst", "rating", "institution", "consensus", "estimate", "estimates", "forecast_eps", "target_price")):
            return "analyst"
        if self._has_any(text, ("calendar", "earnings date", "dividend calendar")):
            return "calendar"
        if self._has_any(text, ("market_status", "market")):
            return "market"
        if self._has_any(text, ("company", "static_info", "business_segments", "business_segments_history", "segment", "profile", "security")):
            return "company"
        if self._has_any(text, ("financial", "financial_report", "statement", "balance_sheet", "income", "cash_flow", "eps", "revenue", "net_income")):
            return "financial"
        return "other_public"

    def _has_any(self, text: str, needles: tuple[str, ...]) -> bool:
        return any(needle in text for needle in needles)

    def _normalize_categories(self, category: str | None, categories: list[str] | None) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        raw_values: list[str] = []
        if category:
            raw_values.append(str(category))
        if categories:
            raw_values.extend(str(item) for item in categories if item is not None)
        for raw in raw_values:
            value = raw.strip().lower()
            if not value or value not in PUBLIC_TOOL_CATEGORY_METADATA or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _raw_category_count(self, category: str | None, categories: list[str] | None) -> int:
        values: list[str] = []
        if category and str(category).strip():
            values.append(str(category).strip().lower())
        if categories:
            values.extend(str(item).strip().lower() for item in categories if item is not None and str(item).strip())
        return len(set(values))

    def _group_items(self, items: list[dict], *, limit_per_category: int, include_empty: bool) -> list[dict]:
        groups = []
        items_by_category = {category: [] for category in PUBLIC_TOOL_CATEGORY_ORDER}
        for item in items:
            items_by_category.setdefault(str(item.get("category") or "other_public"), []).append(item)
        for category in PUBLIC_TOOL_CATEGORY_ORDER:
            category_items = sorted(items_by_category.get(category, []), key=lambda item: (-int(item.get("rank_score") or 0), str(item.get("name") or "")))
            if not include_empty and not category_items:
                continue
            meta = PUBLIC_TOOL_CATEGORY_METADATA[category]
            groups.append(
                {
                    "category": category,
                    "label": meta["label"],
                    "description": meta["description"],
                    "items": category_items[:limit_per_category],
                }
            )
        return groups

    def _rank_item(self, item: dict, category: str, query: str | None) -> tuple[int, str]:
        tokens = self._query_tokens(query)
        if not tokens:
            return 0, "default_order"
        name = str(item.get("name") or "").lower()
        description = str(item.get("description") or "").lower()
        category_text = category.lower()
        typical_text = " ".join(PUBLIC_TOOL_CATEGORY_METADATA.get(category, {}).get("typical_questions", [])).lower()
        score = 0
        reasons: list[str] = []
        for token in tokens:
            matched = False
            if token in name:
                score += 5
                matched = True
            if token in category_text:
                score += 4
                matched = True
            if token in description:
                score += 2
                matched = True
            if token in typical_text:
                score += 1
                matched = True
            if matched:
                reasons.append(token)
        if reasons:
            return score, "matched: " + ", ".join(reasons[:4])
        return 0, "query_no_match_not_filtered"

    def _required_identifiers(self, item: dict) -> list[str]:
        schema = item.get("input_schema") or item.get("inputSchema") or {}
        required = schema.get("required") if isinstance(schema, dict) else []
        if isinstance(required, list) and "symbol" in required:
            return ["symbol"]
        name = str(item.get("name") or "").lower()
        if name in {"quote", "valuation", "financial_report", "financial_report_latest", "financial_report_snapshot", "financial_statement", "analyst_estimates", "company", "static_info"}:
            return ["symbol"]
        return []

    def _schema_result_for_tool(self, tool_name: str) -> dict:
        item = self._get_public_catalog_item(tool_name)
        if item is None:
            return {
                "tool_name": tool_name,
                "ok": False,
                "status": "forbidden",
                "error_code": "LONG_BRIDGE_TOOL_NOT_ALLOWED",
                "message": "Requested Longbridge tool is forbidden, private, write-capable, unknown, or unavailable.",
                "data_limitations": ["Requested Longbridge tool is forbidden, private, write-capable, unknown, or unavailable."],
            }
        schema = item.get("input_schema") or self._fallback_input_schema(item.get("name"))
        category = self._category_for_tool(item)
        limitations = [] if item.get("input_schema") else ["MCP catalog did not include input_schema; returned a generic fallback schema."]
        return {
            "tool_name": item.get("name"),
            "ok": True,
            "status": "success",
            "category": category,
            "description": item.get("description") or self._fallback_description(item.get("name")),
            "input_schema": schema,
            "example_arguments": self._example_arguments(item, category),
            "output_fields": self._output_fields(item, category),
            "data_limitations": limitations,
        }

    def _example_arguments(self, item: dict, category: str) -> dict:
        name = str(item.get("name") or "").lower()
        if name == "news_search":
            return {"keyword": "AMD", "limit": 8}
        if name == "finance_calendar" or category == "calendar":
            return {"category": "report"}
        if name == "market_status" or category == "market":
            return {}
        if "symbol" in self._required_identifiers(item):
            return {"symbol": "AMD.US"}
        return {}

    def _output_fields(self, item: dict, category: str) -> list[str]:
        name = str(item.get("name") or "").lower()
        if name == "news_search":
            return OUTPUT_FIELDS_BY_CATEGORY["news"]
        return OUTPUT_FIELDS_BY_CATEGORY.get(category, [])

    def _execute_public_tool_call(self, call: dict, item: dict) -> dict:
        tool_name = call["tool_name"]
        priority = call["priority"]
        purpose = call.get("purpose")
        started = time.perf_counter()
        try:
            result = self.adapter.call(tool_name, call.get("arguments") or {}) if self.adapter is not None else {"ok": False, "error_code": "LONGBRIDGE_MCP_UNAVAILABLE", "message": "MCP adapter is not available", "data_limitations": ["Longbridge MCP is disabled or not configured."]}
            latency_ms = int((time.perf_counter() - started) * 1000)
            if not result.get("ok"):
                error_code = str(result.get("error_code") or "LONGBRIDGE_MCP_ERROR")
                return self._failed_call_result(
                    tool_name,
                    priority,
                    purpose,
                    "mcp_error",
                    error_code,
                    str(result.get("message") or "Longbridge MCP tool call failed"),
                    result.get("data_limitations") or ["Longbridge MCP tool call failed."],
                    latency_ms,
                )
            data = self._sanitize(result.get("data"))
            if self._is_empty_result(data):
                return {
                    "tool_name": tool_name,
                    "ok": False,
                    "status": "empty_result",
                    "priority": priority,
                    "purpose": purpose,
                    "summary": f"{tool_name} returned empty result.",
                    "data": {},
                    "error_code": "LONG_BRIDGE_EMPTY_RESULT",
                    "data_limitations": result.get("data_limitations") or ["Longbridge MCP tool returned empty result."],
                    "latency_ms": latency_ms,
                }
            status = "success"
            limitations = list(result.get("data_limitations") or [])
            data, status, truncated = self._fit_tool_data(data, call["max_chars"])
            if truncated:
                limitations.append("Tool result was truncated to fit per-tool context budget.")
            return {
                "tool_name": tool_name,
                "ok": True,
                "status": status,
                "priority": priority,
                "purpose": purpose,
                "summary": f"{tool_name} returned compacted public market data.",
                "data": data,
                "data_limitations": limitations,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return self._failed_call_result(
                tool_name,
                priority,
                purpose,
                "execution_error",
                "LONG_BRIDGE_TOOL_EXECUTION_ERROR",
                str(exc),
                ["Longbridge MCP tool execution failed."],
                latency_ms,
            )

    def _forbidden_call_result(self, tool_name: str, priority: str, purpose: str | None) -> dict:
        return {
            "tool_name": tool_name,
            "ok": False,
            "status": "forbidden",
            "priority": priority,
            "purpose": purpose,
            "summary": f"{tool_name or 'unknown'} failed: LONG_BRIDGE_TOOL_NOT_ALLOWED",
            "data": {},
            "error_code": "LONG_BRIDGE_TOOL_NOT_ALLOWED",
            "message": "Requested Longbridge tool is forbidden, private, write-capable, unknown, or unavailable.",
            "data_limitations": ["Requested Longbridge tool is forbidden, private, write-capable, unknown, or unavailable."],
            "latency_ms": 0,
        }

    def _failed_call_result(
        self,
        tool_name: str,
        priority: str,
        purpose: str | None,
        status: str,
        error_code: str,
        message: str,
        data_limitations: list[str],
        latency_ms: int,
    ) -> dict:
        return {
            "tool_name": tool_name,
            "ok": False,
            "status": status,
            "priority": priority,
            "purpose": purpose,
            "summary": f"{tool_name} failed: {error_code}",
            "data": {},
            "error_code": error_code,
            "message": self._safe_text(message),
            "data_limitations": data_limitations,
            "latency_ms": latency_ms,
        }

    def _fit_tool_data(self, data: Any, max_chars: int) -> tuple[Any, str, bool]:
        if self._json_chars(data) <= max_chars:
            return data, "success", False
        text = self._json_text(data)
        return {"truncated_json": text[:max_chars]}, "success_truncated", True

    def _apply_batch_budget(self, results: list[dict], max_total_chars: int) -> bool:
        if self._json_chars(results) <= max_total_chars:
            return False
        truncated = False
        for priority in ("optional", "required"):
            for result in results:
                if result.get("priority") != priority or not result.get("data"):
                    continue
                result["data"] = {}
                result["status"] = "success_truncated" if result.get("ok") else result.get("status")
                limitations = list(result.get("data_limitations") or [])
                if "Batch result was compacted or truncated to fit Account Copilot context budget." not in limitations:
                    limitations.append("Batch result was compacted or truncated to fit Account Copilot context budget.")
                result["data_limitations"] = limitations
                truncated = True
                if self._json_chars(results) <= max_total_chars:
                    return True
        return truncated

    def _normalize_priority(self, value: Any) -> str:
        return "optional" if str(value or "required").lower() == "optional" else "required"

    def _is_empty_result(self, value: Any) -> bool:
        if value in (None, "", [], {}):
            return True
        if isinstance(value, dict):
            if value.get("segments") == []:
                return True
            if value.get("report") == "" and value.get("report_txt") == "":
                return True
            non_count = {k: v for k, v in value.items() if k not in {"total_returned", "sample_points"} and v not in (None, "", [], {})}
            return not non_count
        return False

    def _catalog_limitations(self, catalog: dict) -> list[str]:
        limitations = []
        if catalog.get("source") == "static_fallback":
            limitations.append("MCP tools/list was unavailable; using static public readonly fallback catalog.")
        if catalog.get("list_error"):
            limitations.append("MCP tools/list returned an error; blocked tool details were not exposed.")
        return limitations

    def _fallback_description(self, tool_name: str | None) -> str:
        return f"Longbridge public market readonly tool: {tool_name or 'unknown'}"

    def _fallback_input_schema(self, tool_name: str | None) -> dict:
        if tool_name in {"quote", "company", "valuation", "financial_report", "static_info"}:
            return {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"], "additionalProperties": True}
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": True}

    def _envelope(self, tool: str, arguments: dict, data: dict, data_limitations: list[str] | None = None, metadata: dict | None = None) -> dict:
        return {
            "ok": True,
            "tool": tool,
            "arguments": arguments,
            "data": data,
            "data_source": DATA_SOURCE,
            "data_limitations": data_limitations or [],
            "metadata": {"read_only": True, "progressive_disclosure": True, **(metadata or {})},
        }

    def _error(
        self,
        tool: str,
        arguments: dict,
        error_code: str,
        message: str,
        data_limitations: list[str],
        metadata: dict | None = None,
    ) -> dict:
        return {
            "ok": False,
            "tool": tool,
            "arguments": arguments,
            "data": {},
            "data_source": DATA_SOURCE,
            "data_limitations": data_limitations,
            "metadata": {
                "read_only": True,
                "progressive_disclosure": True,
                "error_code": error_code,
                "message": self._safe_text(message),
                **(metadata or {}),
            },
        }

    def _not_allowed(self, tool: str, arguments: dict, requested_tool: str) -> dict:
        return self._error(
            tool,
            arguments,
            "LONG_BRIDGE_TOOL_NOT_ALLOWED",
            f"Longbridge tool '{requested_tool}' is not public market readonly or is not in the exposed catalog.",
            ["Requested Longbridge tool is forbidden, private, write-capable, unknown, or unavailable."],
        )

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._sanitize(item)
                for key, item in value.items()
                if not any(keyword in str(key).lower() for keyword in SENSITIVE_KEYWORDS)
            }
        if isinstance(value, list):
            return [self._sanitize(item) for item in value[:200]]
        if isinstance(value, str):
            return self._safe_text(value)
        return value

    def _safe_text(self, value: str) -> str:
        text = str(value)
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in text.lower():
                return "[redacted sensitive message]"
        return text[:1000]

    def _json_text(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return json.dumps(str(value), ensure_ascii=False)

    def _json_chars(self, value: Any) -> int:
        return len(self._json_text(value))

    def _clamp_limit(self, limit: int | None) -> int:
        try:
            value = int(limit if limit is not None else 30)
        except (TypeError, ValueError):
            value = 30
        return max(1, min(100, value))

    def _clamp_limit_per_category(self, limit: int | None) -> int:
        try:
            value = int(limit if limit is not None else 10)
        except (TypeError, ValueError):
            value = 10
        return max(1, min(10, value))

    def _clamp_max_total_chars(self, limit: int | None) -> int:
        try:
            value = int(limit if limit is not None else 18000)
        except (TypeError, ValueError):
            value = 18000
        return max(6000, min(24000, value))

    def _clamp_call_max_chars(self, limit: int | None) -> int:
        try:
            value = int(limit if limit is not None else 4000)
        except (TypeError, ValueError):
            value = 4000
        return max(1000, min(6000, value))
