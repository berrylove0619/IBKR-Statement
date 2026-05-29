from app.api.routes.trade_decision_agent import _public_decision
from app.schemas.trade_decision import TradeDecisionHealthResponse, TradeDecisionResult


def test_health_contract_exposes_langgraph_and_public_data_status() -> None:
    health = TradeDecisionHealthResponse(
        enabled=True,
        llm_configured=True,
        longbridge_configured=True,
        mcp_enabled=True,
        mcp_available=True,
        mcp_auth_status="connected",
        sdk_fallback_available=True,
        longbridge_sdk_configured=True,
        public_data_mode="mcp",
        trade_review_available=True,
        account_data_source="IBKR_ONLY",
        public_market_data_source="LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY",
        agent_mode="trade_decision_langgraph_v1",
        graph_version="trade_decision_graph_v1",
        message="ok",
    )

    assert health.agent_mode == "trade_decision_langgraph_v1"
    assert health.graph_version == "trade_decision_graph_v1"
    assert health.mcp_available is True


def test_public_decision_result_keeps_top_level_card_pack() -> None:
    document = {
        "id": "decision-1",
        "decision_type": "entry_decision",
        "symbol": "AMD.US",
        "overall_score": 60,
        "rating": "neutral",
        "action": "watchlist",
        "confidence": "medium",
        "decision_summary": "ok",
        "score_detail": {"account_fit": {"score": 10, "max_score": 20, "reason": "ok"}},
        "position_advice": {"position_size_label": "small"},
        "execution_plan": {"should_act_now": False},
        "key_reasons": ["ok"],
        "major_risks": [],
        "review_warnings": [],
        "data_limitations": [],
        "evidence_used": [],
        "data_source_summary": {},
        "card_pack": {
            "account_fit_card": {"summary": "account"},
            "market_trend_card": {"summary": "market"},
            "fundamental_valuation_card": {"summary": "fundamental"},
            "event_catalyst_card": {"summary": "event"},
            "risk_reward_card": {"summary": "risk"},
        },
        "run_trace": [{"event": "node_success", "node_name": "persist_decision"}],
        "metadata": {"agent_mode": "trade_decision_langgraph_v1", "graph_version": "trade_decision_graph_v1"},
        "created_at": "2026-05-20T00:00:00+00:00",
        "updated_at": "2026-05-20T00:00:00+00:00",
    }

    result = _public_decision(document)

    assert isinstance(result, TradeDecisionResult)
    assert result.card_pack["market_trend_card"]["summary"] == "market"
