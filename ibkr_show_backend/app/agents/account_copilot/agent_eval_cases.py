from __future__ import annotations

AGENT_EVAL_CASES = [
    {
        "id": "account_risk",
        "question": "我现在账户风险高不高？",
        "expected_tools": ["ibkr_get_risk_snapshot", "ibkr_get_account_overview", "ibkr_get_current_positions"],
        "expected_behavior": "use_ibkr_account_facts",
    },
    {
        "id": "amd_public_market",
        "question": "AMD 最近为什么涨跌？",
        "expected_tools": ["longbridge_list_public_tools", "longbridge_get_public_tool_schema", "longbridge_call_public_tool"],
        "expected_behavior": "use_longbridge_public_tools_only",
    },
    {
        "id": "mu_entry_skill",
        "question": "MU 现在适合建仓吗？",
        "expected_tools": [],
        "expected_behavior": "request_skill_approval",
    },
    {
        "id": "loss_attribution",
        "question": "我最近亏损主要来自哪些股票？",
        "expected_tools": ["ibkr_get_daily_attribution", "ibkr_get_current_positions", "ibkr_get_equity_curve"],
        "expected_behavior": "use_ibkr_attribution_or_positions",
    },
    {
        "id": "longbridge_degraded",
        "question": "如果长桥不可用，请基于账户事实给有限结论。",
        "expected_tools": ["ibkr_get_account_overview", "ibkr_get_risk_snapshot"],
        "expected_behavior": "degrade_without_fabricating_public_market_facts",
    },
]


FORBIDDEN_AGENT_TOOL_PATTERNS = [
    "submit_order",
    "replace_order",
    "cancel_order",
    "orders",
    "account_balance",
    "stock_positions",
    "withdrawal",
    "deposit",
    "bank_cards",
]
