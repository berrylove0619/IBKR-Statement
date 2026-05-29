from __future__ import annotations


PUBLIC_MARKET_RESEARCH_SUBAGENT_SCHEMA = {
    "name": "public_market_research_subagent",
    "display_name": "公开市场研究子Agent",
    "description": "用于探索公开市场信息，如新闻、财报、估值、分析师预期、K线和公司信息，并返回压缩后的结构化证据。",
    "when_to_use": [
        "用户问题需要公开市场研究",
        "需要调用多个公开市场工具",
        "任务有探索性，中间证据很多，不希望污染主 Agent 上下文",
        "问题不需要读取用户账户、持仓、交易和风险数据",
    ],
    "when_not_to_use": [
        "用户要求建仓、加仓、减仓、买入、卖出、继续持有建议",
        "用户要求复盘自己的历史交易",
        "用户要求账户风险、仓位、保证金、现金流分析",
        "用户问题可以由已注册 Skill 直接解决",
    ],
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "minLength": 1},
            "question": {"type": "string", "minLength": 1},
            "intent": {"type": ["string", "null"]},
        },
        "required": ["symbol", "question"],
        "additionalProperties": False,
    },
    "output_contract": {
        "type": "object",
        "required_fields": [
            "summary",
            "key_facts",
            "bull_case_evidence",
            "bear_case_evidence",
            "missing_information",
            "data_limitations",
        ],
    },
    "read_only": True,
    "approval_required": False,
    "data_access": ["LONGBRIDGE_PUBLIC_MARKET"],
    "risk_level": "low",
}


ACCOUNT_COPILOT_SUBAGENT_SCHEMAS = [PUBLIC_MARKET_RESEARCH_SUBAGENT_SCHEMA]
