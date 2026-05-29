"""LangGraph StateGraph for trade decision analysis.

Parallel fan-out/fan-in:
  START → build_account_facts
        → [account_fit | market_trend | fundamental_valuation | event_catalyst]  (parallel)
        → risk_reward  (fan-in: waits for all 4)
        → build_card_pack
        → compose_decision
        → persist_decision
        → END

All nodes receive deps via closure, not via state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.graph.progress import instrument_graph_node
from app.agents.trade_decision_graph.nodes import (
    make_account_fit_node,
    make_build_account_facts_node,
    make_build_card_pack_node,
    make_compose_decision_node,
    make_event_catalyst_node,
    make_fundamental_valuation_node,
    make_market_trend_node,
    make_persist_decision_node,
    make_risk_reward_node,
)
from app.agents.trade_decision_graph.state import TradeDecisionGraphState
from app.services.llm_service import LLMService
from app.services.mcp.longbridge_mcp_tools import LongbridgeMCPToolAdapter
from app.services.trade_decision_account_facts import TradeDecisionAccountFactsBuilder
from app.services.trade_decision_composer import TradeDecisionComposer
from app.services.trade_decision_repository import TradeDecisionRepository

TRADE_DECISION_GRAPH_NODES = [
    {"id": "build_account_facts", "label": "账户事实"},
    {"id": "account_fit", "label": "账户适配"},
    {"id": "market_trend", "label": "市场趋势"},
    {"id": "fundamental_valuation", "label": "基本面估值"},
    {"id": "event_catalyst", "label": "事件催化"},
    {"id": "risk_reward", "label": "风险收益"},
    {"id": "build_card_pack", "label": "构建卡片"},
    {"id": "compose_decision", "label": "生成决策"},
    {"id": "persist_decision", "label": "保存结果"},
]

TRADE_DECISION_GRAPH_EDGES = [
    {"source": "build_account_facts", "target": "account_fit"},
    {"source": "build_account_facts", "target": "market_trend"},
    {"source": "build_account_facts", "target": "fundamental_valuation"},
    {"source": "build_account_facts", "target": "event_catalyst"},
    {"source": "account_fit", "target": "risk_reward"},
    {"source": "market_trend", "target": "risk_reward"},
    {"source": "fundamental_valuation", "target": "risk_reward"},
    {"source": "event_catalyst", "target": "risk_reward"},
    {"source": "risk_reward", "target": "build_card_pack"},
    {"source": "build_card_pack", "target": "compose_decision"},
    {"source": "compose_decision", "target": "persist_decision"},
]


@dataclass
class TradeDecisionGraphDeps:
    account_facts_builder: TradeDecisionAccountFactsBuilder
    llm_service: LLMService
    repository: TradeDecisionRepository
    mcp_adapter: LongbridgeMCPToolAdapter | None
    prompt_service: Any | None = None
    monitoring_service: Any | None = None


def build_trade_decision_graph(deps: TradeDecisionGraphDeps) -> Any:
    """Build and compile the trade decision LangGraph with parallel fan-out/fan-in."""
    graph = StateGraph(TradeDecisionGraphState)

    # Add nodes — each factory closes over deps
    graph.add_node("build_account_facts", instrument_graph_node("build_account_facts", make_build_account_facts_node(deps)))
    graph.add_node("account_fit", instrument_graph_node("account_fit", make_account_fit_node(deps)))
    graph.add_node("market_trend", instrument_graph_node("market_trend", make_market_trend_node(deps)))
    graph.add_node("fundamental_valuation", instrument_graph_node("fundamental_valuation", make_fundamental_valuation_node(deps)))
    graph.add_node("event_catalyst", instrument_graph_node("event_catalyst", make_event_catalyst_node(deps)))
    graph.add_node("risk_reward", instrument_graph_node("risk_reward", make_risk_reward_node(deps)))
    graph.add_node("build_card_pack", instrument_graph_node("build_card_pack", make_build_card_pack_node(deps)))
    graph.add_node("compose_decision", instrument_graph_node("compose_decision", make_compose_decision_node(deps)))
    graph.add_node("persist_decision", instrument_graph_node("persist_decision", make_persist_decision_node(deps)))

    # Fan-out: build_account_facts → 4 parallel sub-agent nodes
    graph.add_edge(START, "build_account_facts")
    graph.add_edge("build_account_facts", "account_fit")
    graph.add_edge("build_account_facts", "market_trend")
    graph.add_edge("build_account_facts", "fundamental_valuation")
    graph.add_edge("build_account_facts", "event_catalyst")

    # Fan-in: all 4 → risk_reward (LangGraph auto-waits for all predecessors)
    graph.add_edge("account_fit", "risk_reward")
    graph.add_edge("market_trend", "risk_reward")
    graph.add_edge("fundamental_valuation", "risk_reward")
    graph.add_edge("event_catalyst", "risk_reward")

    # Sequential tail
    graph.add_edge("risk_reward", "build_card_pack")
    graph.add_edge("build_card_pack", "compose_decision")
    graph.add_edge("compose_decision", "persist_decision")
    graph.add_edge("persist_decision", END)

    return graph.compile()
