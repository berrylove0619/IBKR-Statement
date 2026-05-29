from unittest.mock import MagicMock

from app.agents.trade_review_graph.nodes import make_persist_trade_review_node
from app.schemas.trade_review import TradeReviewDetailResult


def test_persist_trade_review_saves_run_trace_and_evidence_pack_before_repository_call() -> None:
    captured: dict = {}
    deps = MagicMock()
    deps.llm_service.get_active_provider.return_value = None

    def save_review(document: dict) -> dict:
        captured.update(document)
        document["id"] = "review-1"
        return document

    deps.repository.save_review.side_effect = save_review
    node = make_persist_trade_review_node(deps)
    state = {
        "review_type": "symbol_level_review",
        "symbol": "AMD.US",
        "trade_facts": {"trades": [{"trade_id": "t1"}]},
        "merged_review_context": {"trade_facts": {"trades": [{"trade_id": "t1"}]}},
        "trade_review_output": {
            "overall_score": 70,
            "rating": "good",
            "score_detail": {"entry_quality": {"score": 8, "max_score": 10, "reason": "ok"}},
            "summary": "ok",
            "strengths": ["ok"],
            "weaknesses": [],
            "mistake_tags": [],
            "improvement_suggestions": ["keep reviewing"],
            "data_limitations": [],
            "evidence_used": ["IBKR trades"],
        },
        "node_traces": [{"node_name": "load_trade_facts", "status": "success"}],
    }

    result = node(state)
    saved = result["saved_document"]
    detail = TradeReviewDetailResult(**saved)

    assert captured["run_trace"]
    assert captured["evidence_summary"] is not None
    assert captured["evidence_pack"]["data_sources"]["trade_data"] == "IBKR_ONLY"
    assert captured["evidence_pack"]["data_sources"]["account_data"] == "IBKR_ONLY"
    assert captured["evidence_pack"]["data_sources"]["position_data"] == "IBKR_ONLY"
    assert captured["evidence_pack"]["data_sources"]["public_market_data"] == "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"
    assert "persist_trade_review" in [item.node_name for item in detail.run_trace]
