from __future__ import annotations

DEMO_MEMORY = {
    "summary": "Demo 会话讨论了账户风险、AMD 公开市场信息，以及 MU 建仓 Skill 审批。",
    "symbols": ["AMD", "MU"],
    "topics": ["risk", "news", "trade_decision"],
    "user_intent": "演示 Account Copilot 的账户事实、公开市场数据、Skill 审批和记忆恢复能力。",
    "important_facts": [
        "Demo 账户最大持仓集中在半导体方向。",
        "用户希望交易建议必须说明风险，不要给确定性指令。",
    ],
    "user_preferences": ["偏好先看风险和证据，再决定是否调用高阶 Skill。"],
    "open_questions": ["MU 是否适合建仓仍等待用户审批 Skill。"],
    "tool_facts": [
        {"tool": "ibkr_get_risk_snapshot", "fact_summary": "Demo 风险快照显示集中度偏高。"},
        {"tool": "longbridge_call_public_tool", "symbol": "AMD", "fact_summary": "Demo 公开信息显示 AMD 受 AI 芯片和财报预期影响。"},
    ],
    "skill_facts": [],
    "non_compressible_constraints": [
        "涉及交易建议时必须说明风险",
        "不要把分析结果表述成确定性交易指令",
    ],
}


DEMO_RUN_EVENTS = {
    "risk": [
        ("run_started", {}),
        ("planner_started", {"round": 1}),
        ("planner_finished", {"round": 1, "action_type": "call_tool", "tool_name": "ibkr_get_risk_snapshot"}),
        ("tool_started", {"round": 1, "tool_name": "ibkr_get_risk_snapshot"}),
        ("tool_finished", {"round": 1, "tool_name": "ibkr_get_risk_snapshot", "ok": True, "data_summary": "Demo risk snapshot"}),
        ("observation_created", {"observation": {"tool_name": "ibkr_get_risk_snapshot", "ok": True, "data_summary": "账户集中度偏高，现金比例中等。"}}),
        ("final_answer", {"content": "Demo：当前账户风险中等偏高，主要来自半导体仓位集中。"}),
        ("run_completed", {"fallback_used": False}),
    ],
    "longbridge": [
        ("run_started", {}),
        ("planner_started", {"round": 1}),
        ("planner_finished", {"round": 1, "action_type": "call_tool", "tool_name": "longbridge_list_public_tools"}),
        ("tool_finished", {"round": 1, "tool_name": "longbridge_list_public_tools", "ok": True, "data_summary": "quote/news/company tools"}),
        ("planner_finished", {"round": 2, "action_type": "call_tool", "tool_name": "longbridge_get_public_tool_schema"}),
        ("tool_finished", {"round": 2, "tool_name": "longbridge_get_public_tool_schema", "ok": True, "data_summary": "quote schema"}),
        ("planner_finished", {"round": 3, "action_type": "call_tool", "tool_name": "longbridge_call_public_tool"}),
        ("tool_finished", {"round": 3, "tool_name": "longbridge_call_public_tool", "ok": True, "data_summary": "AMD public market demo"}),
        ("final_answer", {"content": "Demo：AMD 近期波动与 AI 需求预期、同业估值和新闻催化有关。"}),
        ("run_completed", {"fallback_used": False}),
    ],
    "approval": [
        ("run_started", {}),
        ("planner_started", {"round": 1}),
        ("planner_finished", {"round": 1, "action_type": "request_skill_approval", "skill_name": "trade_decision_entry_skill"}),
        ("skill_approval_requested", {}),
    ],
}
