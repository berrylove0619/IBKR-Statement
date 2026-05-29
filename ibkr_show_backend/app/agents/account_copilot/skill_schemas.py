from __future__ import annotations

from typing import Any

NULLABLE_STRING = {"type": ["string", "null"]}

TRADE_DECISION_ENTRY_SKILL = {
    "name": "trade_decision_entry_skill",
    "display_name": "交易决策-建仓分析",
    "description": "分析某只股票是否适合当前账户建仓。需要用户审批后执行，只读取 IBKR 账户事实和长桥公开市场数据。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "minLength": 1},
            "question": NULLABLE_STRING,
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
    "output_schema": {"type": "object", "additionalProperties": True},
    "data_access": ["IBKR_ACCOUNT_FACTS", "LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "medium",
}

TRADE_DECISION_HOLDING_SKILL = {
    "name": "trade_decision_holding_skill",
    "display_name": "交易决策-持仓分析",
    "description": "分析某只已持仓股票是否适合继续持有、加仓或减仓。需要用户审批后执行。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "minLength": 1},
            "question": NULLABLE_STRING,
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
    "output_schema": {"type": "object", "additionalProperties": True},
    "data_access": ["IBKR_ACCOUNT_FACTS", "IBKR_POSITION_FACTS", "LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "medium",
}

TRADE_REVIEW_SYMBOL_SKILL = {
    "name": "trade_review_symbol_skill",
    "display_name": "交易复盘-Symbol",
    "description": "复盘某个 symbol 的历史交易表现、买卖点、行为问题和改进方向。需要用户审批后执行。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "minLength": 1},
            "start_date": NULLABLE_STRING,
            "end_date": NULLABLE_STRING,
            "question": NULLABLE_STRING,
        },
        "required": ["symbol"],
        "additionalProperties": False,
    },
    "output_schema": {"type": "object", "additionalProperties": True},
    "data_access": ["IBKR_TRADE_HISTORY", "IBKR_POSITION_FACTS", "LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "medium",
}

DAILY_POSITION_REVIEW_SKILL = {
    "name": "daily_position_review_skill",
    "display_name": "每日持仓复盘",
    "description": "生成某个 report_date 的账户每日持仓复盘。需要用户审批后执行。",
    "input_schema": {
        "type": "object",
        "properties": {
            "report_date": NULLABLE_STRING,
            "question": NULLABLE_STRING,
        },
        "required": [],
        "additionalProperties": False,
    },
    "output_schema": {"type": "object", "additionalProperties": True},
    "data_access": ["IBKR_ACCOUNT_FACTS", "IBKR_POSITION_FACTS", "LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "low",
}

RISK_ASSESSMENT_SKILL = {
    "name": "risk_assessment_skill",
    "display_name": "账户风险评估",
    "description": "生成账户级风险评估，覆盖集中度、流动性、保证金和主要风险暴露。需要用户审批后执行。",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": NULLABLE_STRING,
        },
        "required": [],
        "additionalProperties": False,
    },
    "output_schema": {"type": "object", "additionalProperties": True},
    "data_access": ["IBKR_ACCOUNT_FACTS", "IBKR_POSITION_FACTS", "LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "low",
}

ACCOUNT_COPILOT_SKILL_SCHEMAS: list[dict[str, Any]] = [
    TRADE_DECISION_ENTRY_SKILL,
    TRADE_DECISION_HOLDING_SKILL,
    TRADE_REVIEW_SYMBOL_SKILL,
    DAILY_POSITION_REVIEW_SKILL,
    RISK_ASSESSMENT_SKILL,
]

ACCOUNT_COPILOT_SKILL_SCHEMAS_BY_NAME = {
    schema["name"]: schema for schema in ACCOUNT_COPILOT_SKILL_SCHEMAS
}
