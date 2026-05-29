from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

COPILOT_TOOL_PROBE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "probe_run_id": {"type": "keyword"},
            "tool_name": {"type": "keyword"},
            "tool_domain": {"type": "keyword"},
            "category": {"type": "keyword"},
            "probe_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "ok": {"type": "boolean"},
            "latency_ms": {"type": "long"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "arguments_preview": {"type": "object", "enabled": True},
            "data_empty": {"type": "boolean"},
            "data_size": {"type": "long"},
            "data_limitations": {"type": "keyword"},
            "created_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotToolReliabilityRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_result(self, document: dict) -> dict:
        self._ensure_index()
        doc = {
            "id": document.get("id") or f"probe_{uuid4().hex[:12]}",
            "created_at": document.get("created_at") or utc_now_iso(),
            **document,
        }
        self.es_client.index_document(index=self.settings.es_copilot_tool_probe_index, id=doc["id"], document=doc)
        return doc

    def list_results(self, probe_run_id: str | None = None, limit: int = 200) -> list[dict]:
        filters = []
        if probe_run_id:
            filters.append({"term": {"probe_run_id": probe_run_id}})
        try:
            response = self.es_client.search(
                index=self.settings.es_copilot_tool_probe_index,
                body={
                    "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": max(limit, 1),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def latest_probe_run_id(self) -> str | None:
        results = self.list_results(limit=1)
        return results[0].get("probe_run_id") if results else None

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_tool_probe_index, COPILOT_TOOL_PROBE_INDEX_BODY)
