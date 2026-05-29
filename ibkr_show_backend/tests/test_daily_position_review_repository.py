from dataclasses import dataclass

from app.services.daily_position_review_repository import DailyPositionReviewRepository


@dataclass
class DummySettings:
    es_daily_position_review_index: str = "daily-review-index"


class StubESClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        self.index_body = body

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.documents[id] = document
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        document = self.documents.get(id)
        return {"_source": document} if document else None


def test_daily_review_repository_does_not_store_detail_payloads_in_es() -> None:
    es = StubESClient()
    repository = DailyPositionReviewRepository(es, DummySettings())

    stored = repository.save_review(
        {
            "id": "2026-05-21",
            "report_date": "2026-05-21",
            "summary": "ok",
            "account_conclusion": "ok",
            "attribution_summary": "ok",
            "major_contributors_analysis": [{"symbol": "AMD", "custom_llm_key": {"nested": "value"}}],
            "major_drags_analysis": [],
            "focus_symbol_analyses": [],
            "market_context": "ok",
            "risk_analysis": "ok",
            "tomorrow_watchlist": [{"symbol": "AMD", "reason": "watch", "unexpected_field": {"a": 1}}],
            "operation_observation": "ok",
            "data_limitations": [],
            "evidence_used": [],
            "data_source_summary": {"account_data": "IBKR_ONLY", "random_source": "ignored"},
            "agent_mode": "daily_position_review_langgraph_v1",
            "deterministic_context": {"positions": [{"symbol": "AMD"}]},
            "subagent_card_pack": {"symbol_cards": [{"many": "fields"}]},
            "evidence_pack": {"huge": "payload"},
            "graph_node_traces": [{"node_name": "persist_daily_review"}],
            "run_trace": [{"node_name": "persist_daily_review"}],
            "metadata": {"graph_version": "daily_position_review_graph_v1", "dynamic_provider_key": "ignored"},
            "evidence_summary": {"dynamic": "ignored"},
            "run_trace_summary": {"dynamic": "ignored"},
        }
    )

    for forbidden in [
        "deterministic_context",
        "subagent_card_pack",
        "evidence_pack",
        "graph_node_traces",
        "run_trace",
        "metadata",
        "evidence_summary",
        "run_trace_summary",
    ]:
        assert forbidden not in stored
    assert stored["major_contributors_analysis"][0]["symbol"] == "AMD"
    assert "details" in stored["major_contributors_analysis"][0]
    assert stored["tomorrow_watchlist"][0] == {"symbol": "AMD", "reason": "watch", "conditions": ""}
    assert stored["data_source_summary"] == {"account_data": "IBKR_ONLY"}
    assert stored["agent_mode"] == "daily_position_review_langgraph_v1"
    assert es.index_body["mappings"]["dynamic"] is False
