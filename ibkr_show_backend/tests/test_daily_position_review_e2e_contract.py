from unittest.mock import MagicMock

from app.agents.daily_position_review_graph.runner import DailyPositionReviewGraphRunner
from app.schemas.daily_position_review import DailyPositionReviewResult


def test_graph_completed_without_saved_document_is_failed_fallback() -> None:
    runner = DailyPositionReviewGraphRunner(MagicMock(), MagicMock(), MagicMock())
    runner.graph = MagicMock()
    runner.graph.invoke.return_value = {"errors": ["persist_daily_review: ES down"], "node_traces": []}
    runner.deps.repository.save_review.side_effect = lambda doc: doc

    document = runner.generate_review("2026-05-20")
    result = DailyPositionReviewResult(**document)

    assert result.fallback_used is True
    assert result.status == "failed"
    assert "persist_daily_review" in result.fallback_reason
    assert any("graph_failed" in item for item in result.data_limitations)


def test_final_saved_daily_review_trace_includes_optional_email_summary() -> None:
    runner = DailyPositionReviewGraphRunner(MagicMock(), MagicMock(), MagicMock())
    runner.graph = MagicMock()
    runner.deps.repository.save_review.side_effect = lambda doc: doc
    saved = {
        "id": "2026-05-20",
        "report_date": "2026-05-20",
        "summary": "ok",
        "account_conclusion": "ok",
        "attribution_summary": "ok",
        "major_contributors_analysis": [],
        "major_drags_analysis": [],
        "focus_symbol_analyses": [],
        "market_context": "ok",
        "risk_analysis": "ok",
        "tomorrow_watchlist": [],
        "operation_observation": "ok",
        "data_limitations": [],
        "evidence_used": [],
        "data_source_summary": {},
        "run_trace": [{"event": "node_success", "node_name": "persist_daily_review", "status": "success"}],
        "metadata": {"agent_mode": "daily_position_review_langgraph_v1", "graph_version": "daily_position_review_graph_v1"},
        "created_at": "2026-05-20T00:00:00+00:00",
        "updated_at": "2026-05-20T00:00:00+00:00",
    }
    runner.graph.invoke.return_value = {
        "saved_document": saved,
        "node_traces": [
            {"node_name": "persist_daily_review", "status": "success"},
            {"node_name": "optional_email_summary", "status": "success"},
        ],
    }

    document = runner.generate_review("2026-05-20")

    assert runner.deps.repository.save_review.call_count == 1
    assert "optional_email_summary" in [item.get("node_name") for item in document["run_trace"]]
