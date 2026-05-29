from __future__ import annotations

IBKR_TOOL_CATEGORY = "ibkr_account"
IBKR_DATA_SENSITIVITY = "account_private"


def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        "category": IBKR_TOOL_CATEGORY,
        "data_sensitivity": IBKR_DATA_SENSITIVITY,
        "read_only": True,
    }


IBKR_ACCOUNT_TOOL_SCHEMAS = [
    _schema(
        "ibkr_get_account_overview",
        "Return the latest IBKR account overview, including equity, cash, asset buckets, PnL and return metrics.",
        {},
    ),
    _schema(
        "ibkr_get_current_positions",
        "Return latest IBKR position snapshots sorted by position value. Use for current holdings and exposure questions.",
        {
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            "include_cash_equivalents": {"type": "boolean", "default": True},
        },
    ),
    _schema(
        "ibkr_get_symbol_position",
        "Return the latest IBKR position for one symbol, accepting forms like AMD, AMD.US or US.AMD.",
        {"symbol": {"type": "string", "minLength": 1}},
        ["symbol"],
    ),
    _schema(
        "ibkr_get_symbol_trades",
        "Return historical IBKR trades for one symbol. Use when the user asks about entries, exits, fills or realized PnL.",
        {
            "symbol": {"type": "string", "minLength": 1},
            "start_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD start date."},
            "end_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD end date."},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        ["symbol"],
    ),
    _schema(
        "ibkr_get_position_history",
        "Return daily IBKR position snapshots for one symbol over time. Use for sizing, weight and PnL history.",
        {
            "symbol": {"type": "string", "minLength": 1},
            "start_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD start date."},
            "end_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD end date."},
            "limit": {"type": "integer", "default": 365, "minimum": 1, "maximum": 2000},
        },
        ["symbol"],
    ),
    _schema(
        "ibkr_get_equity_curve",
        "Return the IBKR account equity curve and summary for a date range.",
        {
            "start_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD start date."},
            "end_date": {"type": ["string", "null"], "description": "Inclusive YYYY-MM-DD end date."},
        },
    ),
    _schema(
        "ibkr_get_daily_attribution",
        "Return one report day's IBKR-only PnL attribution, rankings and risk facts without public market data.",
        {"report_date": {"type": ["string", "null"], "description": "YYYY-MM-DD report date. Defaults to latest."}},
    ),
    _schema(
        "ibkr_get_risk_snapshot",
        "Return the latest IBKR account risk snapshot, including concentration, cash and top position metrics.",
        {},
    ),
    _schema(
        "ibkr_get_cash_flow_summary",
        "Return aggregated IBKR cash-flow summary for a date range and a small sample of records.",
        {
            "start_date": {"type": ["string", "null"], "description": "Inclusive date or datetime lower bound."},
            "end_date": {"type": ["string", "null"], "description": "Inclusive date or datetime upper bound."},
        },
    ),
]

IBKR_ACCOUNT_TOOL_SCHEMAS_BY_NAME = {tool["name"]: tool for tool in IBKR_ACCOUNT_TOOL_SCHEMAS}
