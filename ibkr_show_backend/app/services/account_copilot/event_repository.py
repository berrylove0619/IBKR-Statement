from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

COPILOT_EVENT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "event_type": {"type": "keyword"},
            "seq": {"type": "long"},
            "created_at": {"type": "date"},
            "payload": {"type": "object", "enabled": True},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotEventRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_event(self, run_id: str, session_id: str, event_type: str, payload: dict, seq: int | None = None) -> dict:
        self._ensure_event_index()
        event_seq = seq if seq is not None else self.next_seq(run_id)
        event_id = f"evt_{uuid4().hex[:12]}"
        document = {
            "id": event_id,
            "run_id": run_id,
            "session_id": session_id,
            "event_type": event_type,
            "seq": event_seq,
            "created_at": utc_now_iso(),
            "payload": payload or {},
        }
        self.es_client.index_document(index=self.settings.es_copilot_event_index, id=event_id, document=document)
        return document

    def list_events(self, run_id: str, after_seq: int | None = None, limit: int = 200) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_copilot_event_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"run_id": run_id}}]}},
                    "sort": [{"seq": {"order": "asc"}}],
                    "size": max(limit, 1),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        events = [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]
        if after_seq is not None:
            events = [event for event in events if int(event.get("seq") or 0) > after_seq]
        return events[:limit]

    def next_seq(self, run_id: str) -> int:
        events = self.list_events(run_id, after_seq=None, limit=10000)
        if not events:
            return 1
        return max(int(event.get("seq") or 0) for event in events) + 1

    def _ensure_event_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_event_index, COPILOT_EVENT_INDEX_BODY)
