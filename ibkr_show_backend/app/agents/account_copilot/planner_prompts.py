from __future__ import annotations

import json
from typing import Any

from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry

SYSTEM_PROMPT = """
你是 Account Copilot 的账户级多轮 ReAct 规划器，负责在每一轮根据用户问题、历史上下文、可用工具和已有 observation 选择下一步动作。

核心决策规则：
1. 每一轮只能选择一个 action_type：call_tool、request_skill_approval、delegate_to_subagent 或 final_answer。
2. 当缺少最新账户事实、持仓、交易、现金、盈亏、风险暴露等私有数据时，优先选择 call_tool 调用已暴露的 IBKR 只读工具。
3. 当问题需要公开市场、新闻、估值、财报、宏观或行业背景时，只能通过 Longbridge 渐进式 public-market meta tools 获取，不要编造公开市场事实。
4. 当问题需要执行 Skill 时，只能返回 request_skill_approval 申请用户审批；不得直接执行 Skill，也不得绕过审批。
5. 当已有证据足以回答，或继续调用工具不会显著提高答案质量时，选择 final_answer。
6. 如果同一类工具或 SubAgent 连续返回空数据或失败（ok=false、data 为空），说明该数据源当前不可用，不要重试相同或类似工具。应基于已有证据选择 final_answer，即使证据不完整也要给出当前最佳回答。重试空数据工具是浪费时间，会导致超时。

能力选择优先级：
1. Skill 优先。如果用户问题可以由已注册 Skill 解决，优先使用 Skill。Skill 适合完整、高阶、账户相关或需要审批的工作流，例如交易决策（建仓、加仓、减仓、继续持有、是否买入/卖出）、交易复盘（追高、卖飞、买卖点、机会成本、历史交易行为）、每日持仓复盘、账户风险评估（集中度、保证金、流动性、风险暴露）。
   特别注意：只要用户问题涉及以下任何内容，必须优先申请 Skill，不得用单个工具直接回答完整建议：
   - 涉及"我"或"我的账户"的分析类问题（如"帮我分析"、"我的账户为什么涨跌"、"昨天为什么亏钱"）应使用 daily_position_review_skill，不要用 ibkr_get_daily_attribution 等单个工具替代完整的每日复盘流程。
   - 涉及"加仓/减仓/建仓/清仓/继续持有/买入/卖出"的问题应使用 trade_decision_holding_skill 或 trade_decision_entry_skill。
   - 涉及"复盘/卖飞/追高/买卖点/机会成本"的问题应使用 trade_review_symbol_skill。
   - 涉及"风险/仓位集中/保证金/流动性"的问题应使用 risk_assessment_skill。
2. 如果没有合适 Skill，但问题是探索性的、需要多步研究、会产生大量中间证据，查看是否有可用 SubAgent。SubAgent 适合公开市场研究、多轮信息探索、需要调用多个工具但不希望污染主 Agent 上下文、需要先探索再压缩为结构化结论的任务。
3. 如果 Skill 和 SubAgent 都不适合，再使用普通只读工具。
4. 不要用 SubAgent 替代 Skill。如果问题涉及用户账户、持仓、成本、历史交易、建仓、加仓、减仓、复盘、账户风险，应优先申请 Skill，而不是委托 SubAgent。
5. SubAgent 返回的是压缩后的研究结果。不要要求 SubAgent 暴露完整中间推理或 chain-of-thought。

事实优先级：
1. 最新 IBKR 工具结果优先级最高。
2. 本轮 observation 优先于 memory。
3. memory 只是历史对话上下文和用户偏好，不是最新账户事实。
4. 用户主观描述可以作为意图或偏好，但不能覆盖 IBKR 工具返回的账户事实。
5. 如果 memory 或用户描述与最新 IBKR 工具结果冲突，必须信任 IBKR 工具结果，并在答案中说明不确定性。

风险边界：
- 只能请求只读工具；绝不能请求交易写操作、下单、撤单、转账或修改账户设置。
- 不提供确定性买卖指令，不承诺收益，不把观察条件包装成必须执行的交易命令。
- 涉及投资观点时，必须包含不确定性、风险提示和证据局限。
- 必须尊重用户偏好、pinned_facts 和 non_compressible_constraints。

输出要求：
- 必须严格输出 planner action schema 对应的 JSON object。
- 只能输出 JSON object，不要 Markdown，不要代码块，不要额外解释。
- 不要省略字段；不适用的字段必须填 null、{} 或 []。
- thought_summary 只能是简短高层理由，不要输出 hidden chain-of-thought。
- 如果证据不足，要在 evidence_sufficiency.missing_information 中说明还缺什么。
""".strip()

PLANNER_SCHEMA_HINT = {
    "action_type": "call_tool | final_answer | request_skill_approval | delegate_to_subagent",
    "thought_summary": "简短高层理由",
    "evidence_sufficiency": {
        "is_sufficient": False,
        "missing_information": [],
        "confidence": "low | medium | high",
    },
    "tool_name": None,
    "tool_arguments": {},
    "skill_name": None,
    "skill_arguments": {},
    "subagent_name": None,
    "subagent_arguments": {},
    "approval_message": None,
    "final_answer": None,
}

CALL_TOOL_EXAMPLE = {
    "action_type": "call_tool",
    "thought_summary": "需要先读取最新 AMD 持仓数据。",
    "evidence_sufficiency": {
        "is_sufficient": False,
        "missing_information": ["AMD 当前持仓数量、成本、浮盈浮亏"],
        "confidence": "low",
    },
    "tool_name": "ibkr_get_symbol_position",
    "tool_arguments": {"symbol": "AMD"},
    "skill_name": None,
    "skill_arguments": {},
    "subagent_name": None,
    "subagent_arguments": {},
    "approval_message": None,
    "final_answer": None,
}

REQUEST_SKILL_APPROVAL_EXAMPLE = {
    "action_type": "request_skill_approval",
    "thought_summary": "已有持仓和风险快照，风险评估需要执行只读 Skill。",
    "evidence_sufficiency": {
        "is_sufficient": False,
        "missing_information": ["需要风险评估 Skill 汇总集中度、回撤和账户风险"],
        "confidence": "medium",
    },
    "tool_name": None,
    "tool_arguments": {},
    "skill_name": "risk_assessment_skill",
    "skill_arguments": {"symbol": "AMD"},
    "subagent_name": None,
    "subagent_arguments": {},
    "approval_message": "我将基于当前 AMD 持仓和账户风险快照执行风险评估 Skill，需要你的审批后继续。",
    "final_answer": None,
}

DELEGATE_TO_SUBAGENT_EXAMPLE = {
    "action_type": "delegate_to_subagent",
    "thought_summary": "问题需要公开市场探索研究，且不涉及账户或交易决策。",
    "evidence_sufficiency": {
        "is_sufficient": False,
        "missing_information": ["需要压缩后的公开市场新闻、估值和预期证据"],
        "confidence": "low",
    },
    "tool_name": None,
    "tool_arguments": {},
    "skill_name": None,
    "skill_arguments": {},
    "subagent_name": "public_market_research_subagent",
    "subagent_arguments": {"symbol": "AMD.US", "question": "AMD 最近为什么大跌？", "intent": "public_market_research"},
    "approval_message": None,
    "final_answer": None,
}

FINAL_ANSWER_EXAMPLE = {
    "action_type": "final_answer",
    "thought_summary": "已有证据足以回答用户问题。",
    "evidence_sufficiency": {
        "is_sufficient": True,
        "missing_information": [],
        "confidence": "medium",
    },
    "tool_name": None,
    "tool_arguments": {},
    "skill_name": None,
    "skill_arguments": {},
    "subagent_name": None,
    "subagent_arguments": {},
    "approval_message": None,
    "final_answer": "根据最新 IBKR 持仓和风险快照，AMD 当前主要风险包括仓位集中度、半导体周期波动、估值波动和单一标的回撤风险。以上仅用于风险识别，不构成确定性买卖建议。",
}

PLANNER_ACTION_EXAMPLES = [
    CALL_TOOL_EXAMPLE,
    REQUEST_SKILL_APPROVAL_EXAMPLE,
    DELEGATE_TO_SUBAGENT_EXAMPLE,
    FINAL_ANSWER_EXAMPLE,
]

AFTER_APPROVAL_FINAL_SCHEMA_HINT = {
    "final_answer": "面向用户的中文最终回答，必填非空",
    "confidence": "low | medium | high",
    "data_limitations": [],
    "evidence_used": [],
}

AFTER_APPROVAL_FINAL_EXAMPLE = {
    "final_answer": "基于已执行的风险评估 Skill，AMD 当前主要风险包括仓位集中度、半导体行业波动、估值回撤风险和单一标的对账户净值的影响。由于公开市场数据和模型判断存在不确定性，建议把这些结论作为风险识别和复盘依据，而不是确定性买卖指令。",
    "confidence": "medium",
    "data_limitations": [],
    "evidence_used": ["ibkr_get_symbol_position", "ibkr_get_risk_snapshot", "risk_assessment_skill"],
}

ACCOUNT_COPILOT_AFTER_APPROVAL_FINAL_SYSTEM_PROMPT = """
你是 Account Copilot 的最终回答生成器，不是 ReAct Planner。
用户已审批只读 Skill，Skill 已执行。
只能基于 skill_observation、已有 observations、用户问题、历史上下文回答。
不得再请求工具。
不得再请求审批。
不得编造账户事实、市场事实、新闻或交易建议。
投资风险问题必须包含不确定性和风险提示。
只输出严格 JSON object，符合 CopilotFinalAnswerAfterApproval schema。
不要 Markdown，不要代码块，不要额外解释。
""".strip()


def build_planner_messages(
    state: dict,
    registry: AccountCopilotToolRegistry,
    actions: list[dict],
    observations: list[dict],
    skill_registry: AccountCopilotSkillRegistry | None = None,
    subagent_registry: AccountCopilotSubAgentRegistry | None = None,
    system_prompt: str | None = None,
    system_prompt_override: str | None = None,
) -> list[dict[str, str]]:
    payload = {
        "user_input": state.get("user_input"),
        "rolling_summary": state.get("rolling_summary") or "",
        "pinned_facts": state.get("pinned_facts") or {},
        "retrieved_memories": state.get("retrieved_memories") or [],
        "non_compressible_constraints": state.get("non_compressible_constraints") or [],
        "memory_snapshot": state.get("memory_snapshot") or {},
        "recent_messages": state.get("messages") or [],
        "available_top_level_tools": [_tool_prompt_item(spec) for spec in registry.list_exposed_specs()],
        "available_skills": skill_registry.to_prompt_items() if skill_registry is not None else [],
        "available_subagents": subagent_registry.to_prompt_items() if subagent_registry is not None else [],
        "previous_actions": [_compact_action(item) for item in actions[-8:]],
        "observations": [_compact_observation(item) for item in observations[-8:]],
        "planner_action_schema": PLANNER_SCHEMA_HINT,
        "planner_action_examples": PLANNER_ACTION_EXAMPLES,
    }
    return [
        {"role": "system", "content": system_prompt_override or system_prompt or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请根据以下状态规划下一步 Account Copilot ReAct 动作。"
                "只输出完整 JSON object，不要省略字段。\n\n"
                f"{json.dumps(payload, ensure_ascii=False, default=str)}"
            ),
        },
    ]


def build_repair_messages(raw_content: str, error: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "请把 planner 输出修复为符合 schema 的严格 JSON。只输出 JSON。"},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "raw_content": raw_content,
                    "validation_error": error,
                    "schema": PLANNER_SCHEMA_HINT,
                    "examples": PLANNER_ACTION_EXAMPLES,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_after_approval_final_messages(state: dict, observations: list[dict], skill_observation: dict) -> list[dict[str, str]]:
    payload = {
        "user_input": state.get("user_input"),
        "recent_messages": state.get("messages") or [],
        "pending_approval": state.get("pending_approval"),
        "skill_observation": _compact_observation(skill_observation),
        "observations": [_compact_observation(item) for item in observations[-8:]],
        "final_answer_schema": AFTER_APPROVAL_FINAL_SCHEMA_HINT,
        "final_answer_example": AFTER_APPROVAL_FINAL_EXAMPLE,
    }
    return [
        {"role": "system", "content": ACCOUNT_COPILOT_AFTER_APPROVAL_FINAL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请基于已审批 Skill 的结果生成最终回答。"
                "只输出符合 schema 的 JSON object，不要 Markdown，不要代码块。\n\n"
                f"{json.dumps(payload, ensure_ascii=False, default=str)}"
            ),
        },
    ]


def _tool_prompt_item(spec) -> dict:
    return {
        "name": spec.name,
        "description": spec.description,
        "category": spec.category,
        "data_sensitivity": spec.data_sensitivity,
        "read_only": spec.read_only,
        "approval_required": spec.approval_required,
        "parameters": spec.schema.get("parameters", {}),
    }


def _compact_action(action: dict[str, Any]) -> dict:
    return {
        "id": action.get("id"),
        "round": action.get("round"),
        "action_type": action.get("action_type"),
        "tool_name": action.get("tool_name"),
        "skill_name": action.get("skill_name"),
        "subagent_name": action.get("subagent_name"),
        "thought_summary": action.get("thought_summary"),
        "evidence_sufficiency": action.get("evidence_sufficiency"),
    }


def _compact_observation(observation: dict[str, Any]) -> dict:
    return {
        "id": observation.get("id"),
        "round": observation.get("round"),
        "action_id": observation.get("action_id"),
        "observation_type": observation.get("observation_type"),
        "tool_name": observation.get("tool_name"),
        "skill_name": observation.get("skill_name"),
        "subagent_name": observation.get("subagent_name"),
        "ok": observation.get("ok"),
        "summary": observation.get("data_summary"),
        "data_limitations": observation.get("data_limitations") or [],
        "data_preview": observation.get("data"),
    }
