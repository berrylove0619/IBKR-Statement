from __future__ import annotations

from datetime import date, timedelta
from typing import Any

FORBIDDEN_ARGUMENT_KEYS = {
    "account_id",
    "order_id",
    "trade_id",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "secret",
}


def build_safe_longbridge_arguments(
    tool_name: str,
    schema: dict[str, Any] | None,
    *,
    symbol: str = "AMD.US",
    keyword: str = "AMD",
) -> tuple[dict[str, Any] | None, str | None]:
    """Build conservative read-only arguments for public Longbridge probes."""
    properties = (schema or {}).get("properties") or {}
    required = list((schema or {}).get("required") or [])
    today = date.today()
    values = {
        "symbol": symbol,
        "ticker": symbol,
        "security": symbol,
        "code": symbol,
        "symbols": [symbol],
        "keyword": keyword,
        "query": keyword,
        "market": "US",
        "period": "day",
        "start": (today - timedelta(days=30)).isoformat(),
        "end": today.isoformat(),
        "start_date": (today - timedelta(days=30)).isoformat(),
        "end_date": today.isoformat(),
        "count": 5,
        "limit": 5,
        "language": "zh-CN",
        "lang": "zh-CN",
    }
    args: dict[str, Any] = {}
    for key, value in values.items():
        if key in properties:
            args[key] = value

    unsupported = []
    for key in required:
        normalized = str(key).lower()
        if normalized in FORBIDDEN_ARGUMENT_KEYS:
            return None, "SKIPPED_FORBIDDEN_ARGS"
        if key not in args:
            if key in values:
                args[key] = values[key]
            else:
                unsupported.append(key)
    if unsupported:
        return None, "SKIPPED_UNSUPPORTED_ARGS"
    return args, None


IBKR_PROBE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "ibkr_get_account_overview": {},
    "ibkr_get_current_positions": {"limit": 20, "include_cash_equivalents": True},
    "ibkr_get_symbol_position": {"symbol": "AMD"},
    "ibkr_get_symbol_trades": {"symbol": "AMD", "limit": 20},
    "ibkr_get_position_history": {"symbol": "AMD", "limit": 60},
    "ibkr_get_equity_curve": {},
    "ibkr_get_daily_attribution": {},
    "ibkr_get_risk_snapshot": {},
    "ibkr_get_cash_flow_summary": {},
}
