"""
Agent Harness 版本常量和元信息定义。

版本编号约定：
- harness: p1.0 表示 P1 版本
- agent: _v2 表示第二个主要版本（与 P0 stable 对齐）
- prompt/toolset: 日期+阶段后缀，方便审计
"""

from datetime import datetime, timezone

# Harness 整体版本
AGENT_HARNESS_VERSION = "p1.0"
CONTEXT_BUDGET_VERSION = "context_budget_v1"
EVIDENCE_SCHEMA_VERSION = "evidence_schema_v1"
OUTPUT_SCHEMA_VERSION = "output_schema_v1"
INVARIANT_VERSION = "invariant_v1"
RUNTIME_VERSION = "runtime_v1"

# Agent 版本
TRADE_DECISION_AGENT_VERSION = "trade_decision_v2"
TRADE_REVIEW_AGENT_VERSION = "trade_review_v2"
DAILY_POSITION_REVIEW_AGENT_VERSION = "daily_position_review_v2"

# Prompt 版本
TRADE_DECISION_PROMPT_VERSION = "trade_decision_prompt_2026_05_p1"
TRADE_REVIEW_PROMPT_VERSION = "trade_review_prompt_2026_05_p1"
DAILY_POSITION_REVIEW_PROMPT_VERSION = "daily_position_review_prompt_2026_05_p1"

# Toolset 版本
TRADE_DECISION_TOOLSET_VERSION = "trade_decision_tools_v2"
TRADE_REVIEW_TOOLSET_VERSION = "trade_review_tools_v2"
DAILY_POSITION_REVIEW_TOOLSET_VERSION = "daily_position_review_tools_v2"

# Evidence Builder 版本
TRADE_DECISION_EVIDENCE_BUILDER_VERSION = "trade_decision_evidence_builder_v2"
TRADE_REVIEW_EVIDENCE_BUILDER_VERSION = "trade_review_evidence_builder_v2"
DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION = "daily_position_review_evidence_builder_v2"

# Agent 模式枚举
AGENT_MODE_FIXED_EVIDENCE = "fixed_evidence"
AGENT_MODE_FIXED_EVIDENCE_WITH_SINGLE_TOOL = "fixed_evidence_with_single_tool"
AGENT_MODE_TOOL_CALLING = "tool_calling"
AGENT_MODE_LEGACY_TOOL_CALLING = "legacy_tool_calling"
DAILY_POSITION_REVIEW_AGENT_MODE_SUBAGENT_CARDS = "daily_review_subagent_cards"
TRADE_DECISION_AGENT_MODE_SUBAGENT_CARDS = "subagent_cards"
TRADE_DECISION_AGENT_MODE_LANGGRAPH = "trade_decision_langgraph_v1"

# Card schema version
TRADE_DECISION_CARD_SCHEMA_VERSION = "card_schema_v1"

# LangGraph versions
TRADE_DECISION_GRAPH_VERSION = "trade_decision_graph_v1"
TRADE_DECISION_GRAPH_SCHEMA_VERSION = "trade_decision_graph_state_v1"

# Risk Assessment Agent
RISK_ASSESSMENT_AGENT_VERSION = "risk_assessment_v1"
RISK_ASSESSMENT_PROMPT_VERSION = "risk_assessment_prompt_2026_05_p1"
RISK_ASSESSMENT_TOOLSET_VERSION = "risk_assessment_tools_v1"
RISK_ASSESSMENT_EVIDENCE_BUILDER_VERSION = "risk_assessment_evidence_builder_v1"
RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH = "risk_assessment_langgraph_v1"
RISK_ASSESSMENT_GRAPH_VERSION = "risk_assessment_graph_v1"
RISK_ASSESSMENT_GRAPH_SCHEMA_VERSION = "risk_assessment_graph_state_v1"
RISK_ASSESSMENT_CARD_SCHEMA_VERSION = "risk_assessment_card_schema_v1"

# Daily Position Review LangGraph
DAILY_POSITION_REVIEW_AGENT_MODE_LANGGRAPH = "daily_position_review_langgraph_v1"
DAILY_POSITION_REVIEW_GRAPH_VERSION = "daily_position_review_graph_v1"
DAILY_POSITION_REVIEW_GRAPH_SCHEMA_VERSION = "daily_position_review_graph_state_v1"
DAILY_POSITION_REVIEW_CARD_SCHEMA_VERSION = "daily_position_review_card_schema_v1"

# Trade Review LangGraph
TRADE_REVIEW_AGENT_MODE_LANGGRAPH = "trade_review_langgraph_v1"
TRADE_REVIEW_GRAPH_VERSION = "trade_review_graph_v1"
TRADE_REVIEW_GRAPH_SCHEMA_VERSION = "trade_review_graph_state_v1"


def build_metadata(
    *,
    agent_version: str,
    prompt_version: str,
    schema_version: str,
    toolset_version: str,
    evidence_builder_version: str,
    agent_mode: str,
    model_provider_snapshot: dict | None = None,
) -> dict:
    """构建 metadata 字典，包含完整版本信息和生成时间。"""
    return {
        "agent_version": agent_version,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "toolset_version": toolset_version,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_builder_version": evidence_builder_version,
        "context_budget_version": CONTEXT_BUDGET_VERSION,
        "invariant_version": INVARIANT_VERSION,
        "harness_version": AGENT_HARNESS_VERSION,
        "agent_mode": agent_mode,
        "model_provider_snapshot": model_provider_snapshot or {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }