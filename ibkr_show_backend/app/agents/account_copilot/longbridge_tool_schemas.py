from __future__ import annotations

LONGBRIDGE_TOOL_CATEGORY = "longbridge_public_market"
LONGBRIDGE_DATA_SENSITIVITY = "public_market"


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
        "category": LONGBRIDGE_TOOL_CATEGORY,
        "data_sensitivity": LONGBRIDGE_DATA_SENSITIVITY,
        "read_only": True,
        "approval_required": False,
    }


LONGBRIDGE_META_TOOL_SCHEMAS = [
    _schema(
        "longbridge_list_public_tool_categories",
        "List business categories for Longbridge public market readonly tools. Use this before listing concrete tools when the user needs public market data such as quotes, candles, news, financials, valuation, analyst estimates, company info, calendar, or market status.",
        {
            "include_empty": {"type": "boolean", "default": False},
        },
    ),
    _schema(
        "longbridge_list_public_tools",
        "List concrete Longbridge public market readonly tools as grouped business categories. category/categories are structured filters; query is used only for ranking, not filtering, so unmatched query terms will not remove tools from selected categories.",
        {
            "query": {"type": ["string", "null"]},
            "category": {"type": ["string", "null"]},
            "categories": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "maxItems": 4,
            },
            "limit_per_category": {"type": "integer", "default": 10, "minimum": 1, "maximum": 10},
            "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100},
        },
    ),
    _schema(
        "longbridge_get_public_tool_schema",
        "Get the parameter schema for one Longbridge public readonly tool when you are preparing to call it.",
        {"tool_name": {"type": "string", "minLength": 1}},
        ["tool_name"],
    ),
    _schema(
        "longbridge_get_public_tool_schemas",
        "Get parameter schemas for multiple confirmed Longbridge public readonly tools. Use this to reduce ReAct rounds before preparing a batch public market call.",
        {
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 6,
            },
        },
        ["tool_names"],
    ),
    _schema(
        "longbridge_call_public_tool",
        "Call one confirmed Longbridge public market readonly tool for quotes, candles, news, financials, valuation, company information, analyst views, calendars, or market status. Never use this for accounts, orders, executions, positions, deposits, withdrawals, or trading writes.",
        {
            "tool_name": {"type": "string", "minLength": 1},
            "arguments": {"type": "object", "additionalProperties": True},
        },
        ["tool_name"],
    ),
    _schema(
        "longbridge_call_public_tools",
        "Call multiple confirmed Longbridge public market readonly tools in one backend-executed batch. Use this for complex public market questions that need valuation, analyst estimates, news, candles, financials, company info, calendar, or market status. Never use this for accounts, orders, executions, positions, deposits, withdrawals, or trading writes.",
        {
            "intent": {"type": ["string", "null"], "maxLength": 120},
            "calls": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string", "minLength": 1},
                        "arguments": {"type": "object", "additionalProperties": True},
                        "priority": {"type": "string", "enum": ["required", "optional"], "default": "required"},
                        "purpose": {"type": ["string", "null"], "maxLength": 120},
                        "max_chars": {"type": "integer", "minimum": 1000, "maximum": 6000, "default": 4000},
                    },
                    "required": ["tool_name", "arguments"],
                    "additionalProperties": False,
                },
            },
            "max_total_chars": {"type": "integer", "minimum": 6000, "maximum": 24000, "default": 18000},
        },
        ["calls"],
    ),
]

LONGBRIDGE_META_TOOL_SCHEMAS_BY_NAME = {tool["name"]: tool for tool in LONGBRIDGE_META_TOOL_SCHEMAS}
