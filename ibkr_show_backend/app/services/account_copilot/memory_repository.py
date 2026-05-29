from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

COPILOT_MEMORY_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "memory_type": {"type": "keyword"},
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "message_start_id": {"type": "keyword"},
            "message_end_id": {"type": "keyword"},
            "message_count": {"type": "long"},
            "message_range_created_at": {"type": "object", "enabled": True},
            "summary": {"type": "text"},
            "symbols": {"type": "keyword"},
            "topics": {"type": "keyword"},
            "user_intent": {"type": "text"},
            "important_facts": {"type": "text"},
            "user_preferences": {"type": "text"},
            "open_questions": {"type": "text"},
            "tool_facts": {"type": "object", "enabled": True},
            "skill_facts": {"type": "object", "enabled": True},
            "non_compressible_constraints": {"type": "text"},
            "source_run_ids": {"type": "keyword"},
            "source_message_ids": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotMemoryRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_memory(self, session_id: str, memory_type: str, payload: dict) -> dict:
        self._ensure_memory_index()
        now = utc_now_iso()
        memory_id = f"mem_{uuid4().hex[:12]}"
        document = {
            "id": memory_id,
            "session_id": session_id,
            "memory_type": memory_type,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "message_start_id": payload.get("message_start_id"),
            "message_end_id": payload.get("message_end_id"),
            "message_count": int(payload.get("message_count") or 0),
            "message_range_created_at": payload.get("message_range_created_at") or {},
            "summary": payload.get("summary") or "",
            "symbols": payload.get("symbols") or [],
            "topics": payload.get("topics") or [],
            "user_intent": payload.get("user_intent") or "",
            "important_facts": payload.get("important_facts") or [],
            "user_preferences": payload.get("user_preferences") or [],
            "open_questions": payload.get("open_questions") or [],
            "tool_facts": payload.get("tool_facts") or [],
            "skill_facts": payload.get("skill_facts") or [],
            "non_compressible_constraints": payload.get("non_compressible_constraints") or [],
            "source_run_ids": payload.get("source_run_ids") or [],
            "source_message_ids": payload.get("source_message_ids") or [],
            "metadata": payload.get("metadata") or {},
        }
        self.es_client.index_document(index=self.settings.es_copilot_memory_index, id=memory_id, document=document)
        return document

    def list_memories(self, session_id: str, limit: int = 20, memory_type: str | None = None) -> list[dict]:
        try:
            filters = [{"term": {"session_id": session_id}}, {"term": {"status": "active"}}]
            if memory_type:
                filters.append({"term": {"memory_type": memory_type}})
            response = self.es_client.search(
                index=self.settings.es_copilot_memory_index,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def retrieve_relevant(self, session_id: str, *, symbols: list[str], topics: list[str], query: str, limit: int = 8) -> list[dict]:
        memories = self.list_memories(session_id=session_id, limit=200)
        scored = []
        query_lower = query.lower()
        for memory in memories:
            score = 0
            memory_symbols = {str(item).upper() for item in memory.get("symbols") or []}
            memory_topics = {str(item).lower() for item in memory.get("topics") or []}
            score += 5 * len(memory_symbols.intersection({item.upper() for item in symbols}))
            score += 3 * len(memory_topics.intersection({item.lower() for item in topics}))
            haystack = " ".join(
                [
                    str(memory.get("summary") or ""),
                    str(memory.get("user_intent") or ""),
                    " ".join(memory.get("important_facts") or []),
                    " ".join(memory.get("user_preferences") or []),
                ]
            ).lower()
            for token in set(query_lower.split()):
                if len(token) >= 3 and token in haystack:
                    score += 1
            if score > 0:
                scored.append((score, memory.get("updated_at") or "", memory))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:limit]]

    def _ensure_memory_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_memory_index, COPILOT_MEMORY_INDEX_BODY)
