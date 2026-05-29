"""Repository for persisting risk assessment results to Elasticsearch."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

RISK_ASSESSMENT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "assessment_type": {"type": "keyword"},
            "overall_risk_score": {"type": "double"},
            "risk_level": {"type": "keyword"},
            "risk_summary": {"type": "text"},
            "score_detail": {"type": "object", "enabled": True},
            "key_risks": {"type": "text"},
            "suggested_actions": {"type": "text"},
            "concentration_warnings": {"type": "text"},
            "event_warnings": {"type": "text"},
            "stress_test_summary": {"type": "object", "enabled": True},
            "data_limitations": {"type": "text"},
            "evidence_used": {"type": "text"},
            "confidence": {"type": "keyword"},
            "card_pack": {"type": "object", "enabled": True},
            "run_trace": {"type": "object", "enabled": True},
            "run_trace_summary": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
            "fallback_used": {"type": "boolean"},
            "fallback_reason": {"type": "text"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RiskAssessmentRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def _index(self) -> str:
        return self.settings.es_risk_assessment_index

    def save_assessment(self, document: dict) -> dict:
        self.es_client.create_index_if_missing(self._index, RISK_ASSESSMENT_INDEX_BODY)
        now = utc_now_iso()
        doc_id = document.get("id") or str(uuid4())
        card_pack = document.get("card_pack")
        stored = {
            **document,
            "id": doc_id,
            "card_pack": _compact_card_pack(card_pack),
            "created_at": document.get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=self._index, id=doc_id, document=stored)
        return stored

    def get_assessment(self, assessment_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self._index, id=assessment_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_recent(self, limit: int = 20) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self._index,
                body={
                    "query": {"match_all": {}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]


def _compact_card_pack(card_pack: object) -> dict:
    if not isinstance(card_pack, dict):
        return {}
    return {
        "data_quality_summary": card_pack.get("data_quality_summary"),
        "concentration_card": _compact_card(card_pack.get("concentration_card")),
        "sector_theme_card": _compact_card(card_pack.get("sector_theme_card")),
        "correlation_card": _compact_card(card_pack.get("correlation_card")),
        "earnings_calendar_card": _compact_card(card_pack.get("earnings_calendar_card")),
        "stress_test_card": _compact_card(card_pack.get("stress_test_card")),
    }


def _compact_card(card: object) -> dict:
    if not isinstance(card, dict):
        return {}
    return {
        "card_type": card.get("card_type"),
        "summary": str(card.get("summary", ""))[:300],
        "score": card.get("score"),
        "max_score": card.get("max_score"),
        "risk_level": card.get("risk_level"),
        "evidence_quality": card.get("evidence_quality"),
        "key_risks": (card.get("key_risks") or [])[:5],
        "suggested_actions": (card.get("suggested_actions") or [])[:5],
    }
