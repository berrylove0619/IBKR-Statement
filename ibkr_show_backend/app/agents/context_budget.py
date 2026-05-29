from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "account_context": 3000,
    "position_context": 3000,
    "trade_history_context": 5000,
    "review_context": 3000,
    "market_context": 5000,
    "company_context": 5000,
    "valuation_context": 4000,
    "external_events": 4000,
    "macro_context": 3000,
    "daily_position_context": 12000,
    "risk_context": 3000,
    "data_quality": 2000,
}

# Sub-agent card mode budgets - higher for core IBKR facts, structured for symbol/macro cards
CORE_FACTS_BUDGET = 15000
SYMBOL_EVIDENCE_CARDS_BUDGET = 18000
MACRO_EVIDENCE_CARD_BUDGET = 5000
FINAL_REVIEW_PROMPT_BUDGET = 8000

_LONG_TEXT_KEYS = {
    "content",
    "body",
    "text",
    "description",
    "detail",
    "details",
    "raw",
    "html",
    "markdown",
}


def trim_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def limit_list(items: Any, limit: int, from_end: bool = False) -> list:
    source = items if isinstance(items, list) else []
    if limit <= 0:
        return []
    return source[-limit:] if from_end else source[:limit]


def estimate_json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def compact_public_item(item: Any, max_items: int = 12, text_limit: int = 180) -> dict:
    if not isinstance(item, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, value in item.items():
        if len(compact) >= max_items:
            break
        if value in (None, "", [], {}):
            continue
        key_text = str(key)
        if key_text.lower() in _LONG_TEXT_KEYS:
            continue
        if isinstance(value, str):
            compact[key_text] = trim_text(value, text_limit)
        elif isinstance(value, (int, float, bool)):
            compact[key_text] = value
        elif isinstance(value, list) and value and all(isinstance(v, (str, int, float, bool)) for v in value[:5]):
            compact[key_text] = [trim_text(v, text_limit) if isinstance(v, str) else v for v in value[:5]]
        elif isinstance(value, dict):
            nested = compact_public_item(value, max_items=min(6, max_items), text_limit=text_limit)
            if nested:
                compact[key_text] = nested
    return compact


def compact_news_items(news: Any, limit: int, title_limit: int = 140, summary_limit: int = 220) -> list[dict]:
    compacted = []
    for item in limit_list(news, limit):
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") or item.get("brief") or item.get("description") or item.get("content") or ""
        compacted.append(
            {
                "title": trim_text(item.get("title") or item.get("headline") or "", title_limit),
                "summary": trim_text(summary, summary_limit),
                "published_at": item.get("published_at") or item.get("released_at") or item.get("date"),
                "source": item.get("source") or item.get("provider"),
                "url": item.get("url"),
            }
        )
    return compacted


def compact_trade_items(trades: Any, limit: int) -> list[dict]:
    keys = (
        "trade_id",
        "symbol",
        "date",
        "trade_date",
        "side",
        "buy_sell",
        "quantity",
        "price",
        "trade_price",
        "amount",
        "proceeds",
        "commission",
        "ib_commission",
        "currency",
        "realized_pnl",
        "fifo_pnl_realized",
    )
    compacted = []
    for item in limit_list(trades, limit, from_end=True):
        if isinstance(item, dict):
            compacted.append({key: item.get(key) for key in keys if key in item})
    return compacted


def compact_position_items(positions: Any, limit: int) -> list[dict]:
    keys = (
        "symbol",
        "normalized_symbol",
        "quantity",
        "avg_cost",
        "average_cost",
        "average_cost_price",
        "current_price",
        "mark_price",
        "market_value",
        "position_value",
        "position_pct",
        "weight",
        "daily_pnl",
        "contribution_ratio",
        "daily_change_percent",
        "previous_day_change_percent",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "unrealized_pnl_percent",
        "realized_pnl",
        "data_source",
    )
    compacted = []
    for item in limit_list(positions, limit):
        if isinstance(item, dict):
            compacted.append({key: item.get(key) for key in keys if key in item})
    return compacted


def compact_data_quality(data_quality: Any, warning_limit: int = 10) -> dict:
    payload = data_quality if isinstance(data_quality, dict) else {}
    return {
        "missing_fields": [trim_text(item, 160) for item in limit_list(payload.get("missing_fields"), warning_limit)],
        "warnings": [trim_text(item, 180) for item in limit_list(payload.get("warnings"), warning_limit)],
        "limitations": [trim_text(item, 180) for item in limit_list(payload.get("limitations"), warning_limit)],
    }


def build_budget_report(
    original_size: int,
    final_size: int,
    dropped_items: dict[str, int] | None = None,
    truncated_fields: list[str] | None = None,
) -> dict:
    active_drops = {k: v for k, v in (dropped_items or {}).items() if v > 0}
    return {
        "original_size": original_size,
        "final_size": final_size,
        "dropped_items": active_drops,
        "truncated_fields": truncated_fields or [],
        "truncated": bool(final_size < original_size or active_drops or (truncated_fields or [])),
    }


def enforce_section_budget(section_name: str, payload: Any, budget: int | None = None) -> Any:
    default_limit = DEFAULT_SECTION_BUDGETS.get(section_name, 4000)
    limit = budget or default_limit
    original_size = estimate_json_chars(payload)
    dropped_items: dict[str, int] = {}
    truncated_fields: list[str] = []
    if budget is not None and budget > default_limit and original_size <= limit:
        report = build_budget_report(original_size, original_size, dropped_items, truncated_fields)
        return _attach_limitations(deepcopy(payload), section_name, report)

    compacted = _compact_by_section(section_name, payload, dropped_items, truncated_fields)

    if estimate_json_chars(compacted) > limit:
        compacted = _shrink_lists(compacted, dropped_items)
    if estimate_json_chars(compacted) > limit:
        compacted = _trim_strings(compacted, truncated_fields, text_limit=140)
    if estimate_json_chars(compacted) > limit:
        compacted = _degrade_payload(compacted)
        truncated_fields.append("*")

    final_size = estimate_json_chars(compacted)
    report = build_budget_report(original_size, final_size, dropped_items, truncated_fields)
    return _attach_limitations(compacted, section_name, report)


def _compact_by_section(section_name: str, payload: Any, dropped_items: dict[str, int], truncated_fields: list[str]) -> Any:
    value = deepcopy(payload)
    if section_name == "account_context" and isinstance(value, dict):
        _limit_named_list(value, "top_positions", 5, dropped_items)
        _limit_named_list(value, "cash_equivalent_positions", 5, dropped_items)
        return value
    if section_name == "position_context":
        if isinstance(value, list):
            dropped = len(value) - 20
            if dropped > 0:
                dropped_items["positions"] = dropped
            return compact_position_items(value, 20)
        return value
    if section_name == "trade_history_context" and isinstance(value, dict):
        trades = value.get("recent_trades") or value.get("trades") or []
        key = "recent_trades" if "recent_trades" in value else "trades"
        value[key] = compact_trade_items(trades, 20)
        dropped = len(trades if isinstance(trades, list) else []) - len(value[key])
        if dropped > 0:
            dropped_items[key] = dropped
        return value
    if section_name == "review_context" and isinstance(value, dict):
        if _is_single_trade_review_context(value):
            return compact_single_trade_review_context(value, dropped_items, truncated_fields)
        _limit_named_list(value, "global_mistake_summary", 10, dropped_items)
        return _trim_strings(value, truncated_fields, text_limit=300)
    if section_name in {"external_events", "macro_context"} and isinstance(value, dict):
        news = value.get("news") or []
        value["news"] = compact_news_items(news, 5, summary_limit=220)
        dropped_count = len(news if isinstance(news, list) else []) - len(value["news"])
        if dropped_count > 0:
            dropped_items["news"] = dropped_count
            value["dropped_news_count"] = dropped_count
        else:
            value.pop("dropped_news_count", None)
        _limit_public_list(value, "filings", 3, dropped_items)
        _limit_public_list(value, "topics", 3, dropped_items)
        value["data_quality"] = compact_data_quality(value.get("data_quality"), warning_limit=5)
        return value
    if section_name in {"company_context", "valuation_context", "market_context"}:
        if isinstance(value, dict) and "financial_context" in value:
            return _compact_company_context_with_financial_context(value, dropped_items, truncated_fields)
        return _compact_public_payload(value, dropped_items, truncated_fields)
    if section_name == "daily_position_context" and isinstance(value, dict):
        return compact_daily_position_context(value, dropped_items, truncated_fields)
    if section_name == "data_quality":
        return compact_data_quality(value, warning_limit=10)
    return _compact_public_payload(value, dropped_items, truncated_fields)


def compact_daily_position_context(value: dict, dropped_items: dict[str, int] | None = None, truncated_fields: list[str] | None = None) -> dict:
    dropped = dropped_items if dropped_items is not None else {}
    truncated = truncated_fields if truncated_fields is not None else []
    payload = deepcopy(value)
    rankings = payload.get("rankings") if isinstance(payload.get("rankings"), dict) else {}
    payload["rankings"] = {
        "profit_contributors": compact_position_items(rankings.get("profit_contributors"), 5),
        "loss_drags": compact_position_items(rankings.get("loss_drags"), 5),
        "top_weights": compact_position_items(rankings.get("top_weights"), 5),
    }
    for key in ("profit_contributors", "loss_drags", "top_weights"):
        items = rankings.get(key) if isinstance(rankings.get(key), list) else []
        dropped_count = len(items) - len(payload["rankings"][key])
        if dropped_count > 0:
            dropped[f"rankings.{key}"] = dropped_count
    payload.pop("positions", None)
    public = payload.get("symbol_public_context") if isinstance(payload.get("symbol_public_context"), dict) else {}
    compact_public: dict[str, dict] = {}
    for symbol, context in public.items():
        if not isinstance(context, dict):
            continue
        item = _compact_public_payload(context, dropped, truncated)
        if isinstance(item, dict):
            news = context.get("news") or []
            item["news"] = compact_news_items(news, 3, summary_limit=180)
            dropped_count = len(news if isinstance(news, list) else []) - len(item["news"])
            if dropped_count > 0:
                item["dropped_news_count"] = dropped_count
            item["technical_levels"] = context.get("technical_levels") or {}
            compact_public[str(symbol)] = item
    payload["symbol_public_context"] = compact_public
    payload["data_quality"] = compact_data_quality(payload.get("data_quality"), warning_limit=10)
    return payload


def compact_single_trade_review_context(
    value: dict,
    dropped_items: dict[str, int] | None = None,
    truncated_fields: list[str] | None = None,
) -> dict:
    dropped = dropped_items if dropped_items is not None else {}
    truncated = truncated_fields if truncated_fields is not None else []
    context = value.get("review_context") if isinstance(value.get("review_context"), dict) else value
    facts = _extract_trade_facts(context)
    performance = _extract_performance_metrics(context)
    trade_history = context.get("trade_history_context") if isinstance(context.get("trade_history_context"), dict) else {}
    reviewed_trades = facts.get("trades") or trade_history.get("trades") or []
    related_trades = facts.get("related_symbol_trades") or trade_history.get("related_symbol_trades") or reviewed_trades
    selected_related = _select_priority_review_trades(related_trades, limit=5)
    if isinstance(related_trades, list) and len(related_trades) > len(selected_related):
        dropped["related_symbol_trades"] = len(related_trades) - len(selected_related)

    current_position = facts.get("current_position") or context.get("position_context") or {}
    compact_facts = {
        "reviewed_trade_id": facts.get("reviewed_trade_id") or trade_history.get("reviewed_trade_id") or value.get("trade_id"),
        "trades": compact_trade_items(reviewed_trades, 1),
        "related_symbol_trades": compact_trade_items(selected_related, 5),
        "first_buy_date": facts.get("first_buy_date") or trade_history.get("first_buy_date"),
        "last_trade_date": facts.get("last_trade_date") or trade_history.get("last_trade_date"),
        "is_currently_holding": facts.get("is_currently_holding", trade_history.get("is_currently_holding")),
        "lifecycle_stage": facts.get("lifecycle_stage") or trade_history.get("lifecycle_stage"),
        "has_exit_trade_after_reviewed_trade": facts.get("has_exit_trade_after_reviewed_trade"),
        "current_position": compact_position_items([current_position], 1)[0] if isinstance(current_position, dict) and current_position else {},
        "position_size_class": facts.get("position_size_class"),
    }

    market_context = _compact_single_trade_market_context(context.get("market_context") or context.get("price_context") or {}, dropped)
    external_events = _compact_review_external_events(context.get("external_events") or {}, dropped)
    compact_context = {
        "agent_name": context.get("agent_name"),
        "agent_task": context.get("agent_task"),
        "review_type": context.get("review_type") or ("single_trade_review" if compact_facts.get("reviewed_trade_id") else None),
        "symbol": context.get("symbol") or _first_trade_symbol(compact_facts.get("trades")),
        "data_sources": context.get("data_sources") or {},
        "facts": context.get("facts") or [],
        "derived_metrics": context.get("derived_metrics") or [],
        "account_context": _compact_account_context(context.get("account_context") or {}, truncated),
        "position_context": compact_facts["current_position"],
        "trade_history_context": {
            "source": "IBKR",
            "trades": compact_facts["trades"],
            "related_symbol_trades_count": len(related_trades) if isinstance(related_trades, list) else 0,
            "first_buy_date": compact_facts["first_buy_date"],
            "last_trade_date": compact_facts["last_trade_date"],
            "is_currently_holding": compact_facts["is_currently_holding"],
            "lifecycle_stage": compact_facts["lifecycle_stage"],
            "reviewed_trade_id": compact_facts["reviewed_trade_id"],
        },
        "review_context": {
            "trade_facts": compact_facts,
            "performance_metrics": _compact_performance_metrics(performance, truncated),
        },
        "market_context": market_context,
        "benchmark_context": compact_public_item(context.get("benchmark_context") or {}, max_items=8, text_limit=120),
        "external_events": external_events,
        "data_quality": compact_data_quality(context.get("data_quality"), warning_limit=8),
        "evidence_used": limit_list(context.get("evidence_used") or [], 8),
    }

    if value is context:
        return compact_context
    return {
        "source": value.get("source"),
        "trade_id": value.get("trade_id") or compact_facts["reviewed_trade_id"],
        "review_context": compact_context,
    }


def _is_single_trade_review_context(value: dict) -> bool:
    context = value.get("review_context") if isinstance(value.get("review_context"), dict) else value
    if context.get("review_type") == "single_trade_review":
        return True
    facts = _extract_trade_facts(context)
    return bool(facts.get("reviewed_trade_id") and facts.get("trades"))


def _extract_trade_facts(context: dict) -> dict:
    facts = context.get("trade_facts")
    if isinstance(facts, dict):
        return facts
    review_context = context.get("review_context")
    if isinstance(review_context, dict) and isinstance(review_context.get("trade_facts"), dict):
        return review_context["trade_facts"]
    return {}


def _extract_performance_metrics(context: dict) -> dict:
    metrics = context.get("performance_metrics")
    if isinstance(metrics, dict):
        return metrics
    review_context = context.get("review_context")
    if isinstance(review_context, dict) and isinstance(review_context.get("performance_metrics"), dict):
        return review_context["performance_metrics"]
    return {}


def _select_priority_review_trades(trades: Any, limit: int) -> list[dict]:
    if not isinstance(trades, list):
        return []
    selected: list[dict] = []

    def add(item: Any) -> None:
        if isinstance(item, dict) and item not in selected:
            selected.append(item)

    valid = [item for item in trades if isinstance(item, dict)]
    buys = [item for item in valid if str(item.get("side") or "").upper() == "BUY"]
    sells = [item for item in valid if str(item.get("side") or "").upper() == "SELL"]
    if buys:
        add(buys[0])
    for item in sells:
        add(item)
    for item in sorted(valid, key=lambda item: abs(float(item.get("amount") or 0.0)), reverse=True)[:3]:
        add(item)
    for item in sorted(
        [item for item in valid if item.get("realized_pnl") is not None],
        key=lambda item: abs(float(item.get("realized_pnl") or 0.0)),
        reverse=True,
    )[:3]:
        add(item)
    for item in valid[-4:]:
        add(item)
    return selected[:limit]


def _compact_account_context(value: Any, truncated_fields: list[str]) -> dict:
    if not isinstance(value, dict):
        return {}
    keys = (
        "start_date",
        "end_date",
        "account_value_at_start",
        "account_value_at_end",
        "cash_ratio_at_start",
        "margin_info",
    )
    result = {key: value.get(key) for key in keys if key in value}
    if len(result) < len(value):
        truncated_fields.append("account_context")
    return result


def _compact_performance_metrics(value: Any, truncated_fields: list[str]) -> dict:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            result[key] = compact_public_item(item, max_items=18, text_limit=120)
        elif isinstance(item, list):
            result[key] = limit_list(item, 5)
            if len(item) > 5:
                truncated_fields.append(key)
        elif isinstance(item, str):
            result[key] = trim_text(item, 160)
            if result[key] != item:
                truncated_fields.append(key)
        else:
            result[key] = item
    return result


def _compact_single_trade_market_context(value: Any, dropped_items: dict[str, int]) -> dict:
    if not isinstance(value, dict):
        return {}
    candles = value.get("symbol_candles") if isinstance(value.get("symbol_candles"), list) else []
    result = {
        key: value.get(key)
        for key in ("price_at_first_buy", "price_at_last_sell", "period_high", "period_low")
        if key in value
    }
    if candles:
        result["candles_count"] = len(candles)
        sample = [candles[0], candles[-1]] if len(candles) > 1 else candles
        result["candle_sample"] = [compact_public_item(item, max_items=8, text_limit=80) for item in sample if isinstance(item, dict)]
        if len(candles) > len(sample):
            dropped_items["symbol_candles"] = len(candles) - len(sample)
    return result


def _compact_review_external_events(value: Any, dropped_items: dict[str, int]) -> dict:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, list):
            result[key] = compact_news_items(item, 3, summary_limit=180)
            dropped = len(item) - len(result[key])
            if dropped > 0:
                dropped_items[key] = dropped
        else:
            result[key] = item
    return result


def _first_trade_symbol(trades: Any) -> str | None:
    if isinstance(trades, list) and trades and isinstance(trades[0], dict):
        symbol = trades[0].get("symbol")
        return str(symbol) if symbol else None
    return None


_COMPACT_FINANCIAL_METRIC_KEYS = (
    "revenue",
    "gross_profit",
    "gross_margin",
    "operating_income",
    "operating_margin",
    "net_income",
    "net_margin",
    "eps",
    "operating_cash_flow",
    "free_cash_flow",
    "cash_and_equivalents",
    "total_debt",
    "shareholders_equity",
    "roe",
)


def _compact_company_context_with_financial_context(
    value: dict, dropped_items: dict[str, int], truncated_fields: list[str]
) -> dict:
    # SymbolAnalysisService / existing financial context treats periods[0] as the latest period,
    # with latest_metrics = periods[0]["metrics"].  Therefore keep the first 4 items (most recent).
    result = dict(value)
    fc = result.get("financial_context")
    if not isinstance(fc, dict):
        return result
    currency = fc.get("currency")
    report_type = fc.get("report_type")
    period_count = fc.get("period_count")
    latest_metrics = fc.get("latest_metrics")
    periods_raw = fc.get("periods") or []
    keep_count = 4
    if len(periods_raw) > keep_count:
        periods_compact = periods_raw[:keep_count]
        dropped_items["financial_context.periods"] = len(periods_raw) - keep_count
    else:
        periods_compact = periods_raw
    compact_periods = []
    for period in periods_compact:
        if not isinstance(period, dict):
            continue
        metrics = period.get("metrics") if isinstance(period.get("metrics"), dict) else {}
        compact_metrics = {k: metrics.get(k) for k in _COMPACT_FINANCIAL_METRIC_KEYS if metrics.get(k) is not None}
        compact_periods.append({
            "label": period.get("label"),
            "fiscal_year": period.get("fiscal_year"),
            "fiscal_quarter": period.get("fiscal_quarter"),
            "end_date": period.get("end_date") or period.get("report_date"),
            "metrics": compact_metrics,
        })
    result["financial_context"] = {
        "currency": currency,
        "report_type": report_type,
        "period_count": period_count,
        "latest_metrics": latest_metrics,
        "periods": compact_periods,
    }
    return result


def _compact_public_payload(value: Any, dropped_items: dict[str, int], truncated_fields: list[str]) -> Any:
    if isinstance(value, list):
        result = []
        for item in limit_list(value, 10):
            result.append(_compact_public_payload(item, dropped_items, truncated_fields))
        dropped_items["list_items"] = max(0, len(value) - len(result))
        return result
    if not isinstance(value, dict):
        return trim_text(value, 300) if isinstance(value, str) else value
    result: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text.lower() in _LONG_TEXT_KEYS:
            truncated_fields.append(key_text)
            continue
        if key_text == "news":
            result[key_text] = compact_news_items(item, 5)
            dropped = len(item if isinstance(item, list) else []) - len(result[key_text])
            if dropped > 0:
                dropped_items["news"] = dropped
        elif isinstance(item, dict):
            result[key_text] = compact_public_item(item, max_items=30, text_limit=180)
        elif isinstance(item, list):
            result[key_text] = [compact_public_item(v, max_items=8, text_limit=140) if isinstance(v, dict) else v for v in limit_list(item, 5)]
            dropped = len(item) - len(result[key_text])
            if dropped > 0:
                dropped_items[key_text] = dropped
        elif isinstance(item, str):
            trimmed = trim_text(item, 300)
            if trimmed != item:
                truncated_fields.append(key_text)
            result[key_text] = trimmed
        else:
            result[key_text] = item
    return result


def _limit_named_list(payload: dict, key: str, limit: int, dropped_items: dict[str, int]) -> None:
    items = payload.get(key)
    if isinstance(items, list):
        payload[key] = limit_list(items, limit)
        dropped = len(items) - len(payload[key])
        if dropped > 0:
            dropped_items[key] = dropped


def _limit_public_list(payload: dict, key: str, limit: int, dropped_items: dict[str, int]) -> None:
    items = payload.get(key)
    if isinstance(items, list):
        payload[key] = [compact_public_item(item, max_items=8, text_limit=120) for item in limit_list(items, limit) if isinstance(item, dict)]
        dropped = len(items) - len(payload[key])
        if dropped > 0:
            dropped_items[key] = dropped


def _shrink_lists(value: Any, dropped_items: dict[str, int]) -> Any:
    if isinstance(value, list):
        keep = max(1, min(len(value), len(value) // 2))
        dropped_items["runtime_list_shrink"] = dropped_items.get("runtime_list_shrink", 0) + max(0, len(value) - keep)
        return [_shrink_lists(item, dropped_items) for item in value[:keep]]
    if isinstance(value, dict):
        return {key: _shrink_lists(item, dropped_items) for key, item in value.items()}
    return value


def _trim_strings(value: Any, truncated_fields: list[str], text_limit: int) -> Any:
    if isinstance(value, str):
        trimmed = trim_text(value, text_limit)
        if trimmed != value:
            truncated_fields.append("text")
        return trimmed
    if isinstance(value, list):
        return [_trim_strings(item, truncated_fields, text_limit) for item in value]
    if isinstance(value, dict):
        return {key: _trim_strings(item, truncated_fields, text_limit) for key, item in value.items()}
    return value


def _degrade_payload(value: Any) -> dict:
    preview = trim_text(json.dumps(value, ensure_ascii=False, default=str), 1000)
    return {
        "truncated": True,
        "reason": "section exceeded budget after structured compaction",
        "preview": preview,
    }


def _attach_limitations(value: Any, section_name: str, report: dict) -> Any:
    if not isinstance(value, dict):
        return value
    payload = dict(value)
    payload["budget_report"] = report
    limitations = [str(item) for item in payload.get("data_limitations") or []]
    if report.get("truncated"):
        limitations.append(f"{section_name} was compacted to fit context budget")
    if report.get("dropped_items"):
        limitations.append(f"{section_name} omitted lower-priority list items: {report['dropped_items']}")
    payload["data_limitations"] = limitations
    payload["truncated"] = bool(report.get("truncated"))
    return payload
