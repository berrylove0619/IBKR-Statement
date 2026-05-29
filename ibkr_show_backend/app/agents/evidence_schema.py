from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agents.context_budget import DEFAULT_SECTION_BUDGETS, enforce_section_budget


DATA_SOURCES = {
    "account_data": "IBKR_ONLY",
    "position_data": "IBKR_ONLY",
    "trade_data": "IBKR_ONLY",
    "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
}

EVIDENCE_SECTIONS = (
    "account_context",
    "position_context",
    "trade_history_context",
    "review_context",
    "market_context",
    "company_context",
    "valuation_context",
    "external_events",
    "macro_context",
    "daily_position_context",
    "risk_context",
    "data_quality",
)


def empty_evidence_pack(
    *,
    agent_name: str,
    agent_task: str,
    symbol: str | None = None,
    report_date: str | None = None,
    user_question: str | None = None,
) -> dict:
    return {
        "agent_name": agent_name,
        "agent_task": agent_task,
        "symbol": symbol,
        "report_date": report_date,
        "user_question": user_question,
        "data_sources": dict(DATA_SOURCES),
        "facts": [],
        "derived_metrics": [],
        "account_context": {},
        "position_context": {},
        "trade_history_context": {},
        "review_context": {},
        "market_context": {},
        "company_context": {},
        "valuation_context": {},
        "external_events": {},
        "macro_context": {},
        "daily_position_context": {},
        "risk_context": {},
        "data_quality": {"missing_fields": [], "warnings": [], "limitations": []},
        "budget_report": {},
        "evidence_used": [],
    }


def build_trade_decision_evidence_pack(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    pack = empty_evidence_pack(
        agent_name="trade_decision_agent",
        agent_task=str(raw.get("decision_type") or "trade_decision"),
        symbol=raw.get("symbol"),
        user_question=raw.get("user_question"),
    )
    pack.update(
        {
            "decision_type": raw.get("decision_type"),
            "objective": raw.get("objective") or {},
            "data_sources": {**DATA_SOURCES, **(raw.get("data_sources") or {})},
            "facts": [
                "IBKR account, position, and trade records are private account facts",
                "Longbridge data is public market/company/event context only",
            ],
            "derived_metrics": ["market_context", "valuation_metrics", "review mistake summary"],
            "account_context": raw.get("account_context") or {},
            "position_context": raw.get("position_context") or {},
            "trade_history_context": raw.get("trade_history_context") or {},
            "review_context": raw.get("review_context") or {},
            "market_context": raw.get("market_context") or {},
            "company_context": raw.get("company_context") or {},
            "valuation_context": raw.get("valuation_context") or {},
            "external_events": raw.get("external_events") or {},
            "data_quality": _stable_data_quality(raw.get("data_quality")),
            "evidence_used": [
                "account_context: IBKR account snapshot",
                "position_context: IBKR current position",
                "trade_history_context: IBKR recent trades",
                "public_context: Longbridge public market/company/event data",
            ],
        }
    )
    return _apply_section_budgets(pack)


def build_trade_review_evidence_pack(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    trade_facts = raw.get("trade_facts") if isinstance(raw.get("trade_facts"), dict) else {}
    performance = raw.get("performance_metrics") if isinstance(raw.get("performance_metrics"), dict) else {}
    pack = empty_evidence_pack(
        agent_name="trade_review_agent",
        agent_task=str(raw.get("review_type") or "trade_review"),
        symbol=raw.get("symbol"),
    )
    pack.update(
        {
            "review_type": raw.get("review_type"),
            "objective": raw.get("objective") or {},
            "facts": [
                {"source": "IBKR_ONLY", "section": "trade_facts", "description": "IBKR transaction facts"},
                {"source": "IBKR_ONLY", "section": "account_context", "description": "IBKR account context near trade dates"},
            ],
            "derived_metrics": [
                {"source": "program_calculated", "section": "performance_metrics", "description": "Program-calculated trade return and drawdown metrics"},
                {"source": "program_calculated", "section": "benchmark_context", "description": "Longbridge public benchmark return comparison"},
            ],
            "account_context": raw.get("account_context") or {},
            "position_context": trade_facts.get("current_position") or {},
            "trade_history_context": {
                "source": "IBKR",
                "trades": trade_facts.get("trades") or [],
                "related_symbol_trades": _select_review_trades(trade_facts.get("related_symbol_trades") or trade_facts.get("trades") or []),
                "first_buy_date": trade_facts.get("first_buy_date"),
                "last_trade_date": trade_facts.get("last_trade_date"),
                "is_currently_holding": trade_facts.get("is_currently_holding"),
                "lifecycle_stage": trade_facts.get("lifecycle_stage"),
                "reviewed_trade_id": trade_facts.get("reviewed_trade_id"),
            },
            "review_context": {"trade_facts": trade_facts, "performance_metrics": performance},
            "market_context": raw.get("price_context") or {},
            "external_events": raw.get("external_events") or {},
            "data_quality": _stable_data_quality(raw.get("data_quality")),
            "evidence_used": [
                "trade_facts: IBKR transaction facts",
                "performance_metrics: program-calculated returns and drawdown",
                "benchmark_context: Longbridge public benchmark returns",
                "external_events: Longbridge public news/events summaries",
            ],
        }
    )
    compacted = _apply_section_budgets(pack)
    # Keep legacy keys for repository/tests while giving LLM a stable pack shape.
    compacted["trade_facts"] = trade_facts
    compacted["performance_metrics"] = performance
    compacted["price_context"] = raw.get("price_context") or {}
    compacted["benchmark_context"] = raw.get("benchmark_context") or {}
    return compacted


def build_daily_position_review_evidence_pack(raw: dict, *, daily_position_context_budget: int | None = None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    pack = empty_evidence_pack(
        agent_name="daily_position_review_agent",
        agent_task="daily_position_review",
        report_date=raw.get("report_date"),
    )
    daily_context = {
        "report_date": raw.get("report_date"),
        "overview": raw.get("overview") or {},
        "rankings": raw.get("rankings") or {},
        "risk": raw.get("risk") or {},
        "benchmarks": raw.get("benchmarks") or {},
        "focus_symbols": raw.get("focus_symbols") or [],
        "symbol_public_context": raw.get("symbol_public_context") or {},
        "attribution_quality": raw.get("attribution_quality") or {},
        "data_quality": _stable_data_quality(raw.get("data_quality")),
    }
    pack.update(
        {
            "data_sources": {**DATA_SOURCES, **(raw.get("data_sources") or {})},
            "facts": [
                {"source": "IBKR_ONLY", "section": "overview", "description": "IBKR account snapshot and daily PnL facts"},
                {"source": "IBKR_ONLY", "section": "rankings", "description": "IBKR position contribution rankings"},
            ],
            "derived_metrics": [
                {"source": "program_calculated", "section": "risk", "description": "Program-calculated concentration and posture metrics"},
                {"source": "program_calculated", "section": "attribution_quality", "description": "Program-calculated explained/unexplained PnL checks"},
            ],
            "account_context": raw.get("overview") or {},
            "position_context": {},
            "market_context": raw.get("benchmarks") or {},
            "daily_position_context": daily_context,
            "risk_context": raw.get("risk") or {},
            "data_quality": _stable_data_quality(raw.get("data_quality")),
            "evidence_used": [
                "overview/rankings: deterministic IBKR account and position attribution",
                "risk/attribution_quality: program-calculated risk and attribution checks",
                "symbol_public_context: Longbridge public context for focus symbols",
            ],
        }
    )
    budget_overrides = {"daily_position_context": daily_position_context_budget} if daily_position_context_budget else None
    return _apply_section_budgets(pack, budget_overrides=budget_overrides)


def _apply_section_budgets(pack: dict, *, budget_overrides: dict[str, int] | None = None) -> dict:
    result = deepcopy(pack)
    reports = {}
    for section in EVIDENCE_SECTIONS:
        result.setdefault(section, {} if section != "data_quality" else {"missing_fields": [], "warnings": [], "limitations": []})
        budget = (budget_overrides or {}).get(section, DEFAULT_SECTION_BUDGETS.get(section))
        result[section] = enforce_section_budget(section, result[section], budget)
        if isinstance(result[section], dict) and "budget_report" in result[section]:
            reports[section] = result[section]["budget_report"]
    result["budget_report"] = reports
    return result


def _stable_data_quality(value: Any) -> dict:
    payload = value if isinstance(value, dict) else {}
    return {
        "missing_fields": [str(item) for item in payload.get("missing_fields") or []],
        "warnings": [str(item) for item in payload.get("warnings") or []],
        "limitations": [str(item) for item in payload.get("limitations") or []],
    }


def build_daily_position_review_evidence_pack_from_cards(card_pack: dict) -> dict:
    """
    Build evidence pack from sub-agent card pack.

    This is used when the main agent runs in sub-agent card mode.
    The pack structure is compatible with existing evidence_summary/trace logic,
    but public market context now comes from symbol_cards and macro_card
    instead of raw symbol_public_context.
    """
    pack = empty_evidence_pack(
        agent_name="daily_position_review_agent",
        agent_task="daily_position_review",
        report_date=card_pack.get("report_date"),
    )

    report_date = card_pack.get("report_date", "")
    account_facts = card_pack.get("account_facts", {})
    position_facts = card_pack.get("position_facts", [])
    rankings = card_pack.get("rankings", {})
    risk = card_pack.get("risk", {})
    attribution_quality = card_pack.get("attribution_quality", {})
    symbol_cards = card_pack.get("symbol_cards", [])
    macro_card = card_pack.get("macro_card")
    data_quality = card_pack.get("data_quality", {})
    subagent_trace = card_pack.get("subagent_trace", {})
    budget_report = card_pack.get("budget_report", {})

    # Core IBKR facts - always complete
    daily_context = {
        "report_date": report_date,
        "overview": account_facts.get("overview", {}),
        "rankings": rankings,
        "risk": risk,
        "benchmarks": card_pack.get("benchmarks", {}),
        "focus_symbols": [card.get("normalized_symbol") or card.get("symbol") for card in symbol_cards],
        "symbol_public_context": {},  # Replaced by symbol_cards
        "attribution_quality": attribution_quality,
        "data_quality": _stable_data_quality(data_quality),
    }

    pack.update(
        {
            "data_sources": {
                "account_data": "IBKR_ONLY",
                "position_data": "IBKR_ONLY",
                "trade_data": "IBKR_ONLY",
                "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
            },
            "facts": [
                {"source": "IBKR_ONLY", "section": "overview", "description": "IBKR account snapshot and daily PnL facts"},
                {"source": "IBKR_ONLY", "section": "rankings", "description": "IBKR position contribution rankings"},
            ],
            "derived_metrics": [
                {"source": "program_calculated", "section": "risk", "description": "Program-calculated concentration and posture metrics"},
                {"source": "program_calculated", "section": "attribution_quality", "description": "Program-calculated explained/unexplained PnL checks"},
            ],
            "account_context": account_facts.get("overview", {}),
            "position_context": {},
            "market_context": card_pack.get("benchmarks", {}),
            "daily_position_context": daily_context,
            "risk_context": risk,
            "data_quality": _stable_data_quality(data_quality),
            "evidence_used": [
                "overview/rankings: deterministic IBKR account and position attribution",
                "risk/attribution_quality: program-calculated risk and attribution checks",
                f"symbol_cards: {len(symbol_cards)} evidence cards from sub-agents",
                f"macro_card: {'present' if macro_card else 'not generated'}",
                f"subagent_trace: {len(subagent_trace.get('symbol_agent_calls', []))} symbol calls, {len(subagent_trace.get('macro_agent_calls', []))} macro calls",
            ],
            # Sub-agent card mode specific fields
            "symbol_cards": symbol_cards,
            "macro_card": macro_card,
            "subagent_trace": subagent_trace,
        }
    )

    # Budget report - separate budgets for core facts vs card summaries
    pack["budget_report"] = {
        "core_account_facts_budget": budget_report,
        "symbol_cards_budget": {
            "card_count": len(symbol_cards),
            "card_limit": 6,
        },
        "macro_card_budget": {
            "present": macro_card is not None,
        },
        "subagent_fallback_count": sum(
            1 for call in subagent_trace.get("symbol_agent_calls", [])
            if call.get("status") == "fallback"
        ),
    }

    return pack


def _select_review_trades(trades: Any, limit: int = 20) -> list[dict]:
    if not isinstance(trades, list):
        return []
    selected: list[dict] = []

    def add(item: Any) -> None:
        if isinstance(item, dict) and item not in selected:
            selected.append(item)

    buys = [item for item in trades if isinstance(item, dict) and str(item.get("side") or "").upper() == "BUY"]
    sells = [item for item in trades if isinstance(item, dict) and str(item.get("side") or "").upper() == "SELL"]
    if buys:
        add(buys[0])
    for item in sells:
        add(item)
    for item in sorted(
        [item for item in trades if isinstance(item, dict)],
        key=lambda item: abs(float(item.get("amount") or 0.0)),
        reverse=True,
    )[:5]:
        add(item)
    for item in sorted(
        [item for item in trades if isinstance(item, dict) and item.get("realized_pnl") is not None],
        key=lambda item: abs(float(item.get("realized_pnl") or 0.0)),
        reverse=True,
    )[:5]:
        add(item)
    for item in trades[-8:]:
        add(item)
    return selected[:limit]
