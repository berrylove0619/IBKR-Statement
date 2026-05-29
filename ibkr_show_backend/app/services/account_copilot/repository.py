from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

COPILOT_SESSION_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "last_message_at": {"type": "date"},
            "message_count": {"type": "long"},
            "rolling_summary": {"type": "text"},
            "compressed_until_message_id": {"type": "keyword"},
            "pinned_facts": {"type": "object", "enabled": True},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}

COPILOT_MESSAGE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "role": {"type": "keyword"},
            "content": {"type": "text"},
            "created_at": {"type": "date"},
            "run_id": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}

COPILOT_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "user_message_id": {"type": "keyword"},
            "assistant_message_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "started_at": {"type": "date"},
            "completed_at": {"type": "date"},
            "user_input": {"type": "text"},
            "planner_output": {"type": "object", "enabled": False},
            "actions": {"type": "object", "enabled": False},
            "observations": {"type": "object", "enabled": False},
            "tool_calls": {"type": "object", "enabled": False},
            "skill_requests": {"type": "object", "enabled": False},
            "pending_approval": {"type": "object", "enabled": False},
            "memory_snapshot": {"type": "object", "enabled": False},
            "final_answer": {"type": "text"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "metadata": {"type": "object", "enabled": False},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_session(self, title: str | None = None) -> dict:
        self._ensure_session_index()
        now = utc_now_iso()
        session_id = str(uuid4())
        document = {
            "id": session_id,
            "title": title or "New account copilot session",
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "last_message_at": None,
            "message_count": 0,
            "rolling_summary": "",
            "compressed_until_message_id": None,
            "pinned_facts": {},
            "metadata": {},
        }
        self.es_client.index_document(index=self.settings.es_copilot_session_index, id=session_id, document=document)
        return document

    def get_session(self, session_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_copilot_session_index, id=session_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_sessions(self, limit: int) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_copilot_session_index,
                body={
                    "query": {"match_all": {}},
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def update_session(self, session_id: str, payload: dict) -> dict | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        allowed = {key: value for key, value in payload.items() if key in {"title", "status"} and value is not None}
        if not allowed:
            return session
        allowed["updated_at"] = utc_now_iso()
        session.update(allowed)
        self.es_client.index_document(index=self.settings.es_copilot_session_index, id=session_id, document=session)
        return session

    def update_session_memory(
        self,
        session_id: str,
        *,
        rolling_summary: str | None = None,
        compressed_until_message_id: str | None = None,
        pinned_facts: dict | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        session["updated_at"] = utc_now_iso()
        if rolling_summary is not None:
            session["rolling_summary"] = rolling_summary
        if compressed_until_message_id is not None:
            session["compressed_until_message_id"] = compressed_until_message_id
        if pinned_facts is not None:
            session["pinned_facts"] = pinned_facts
        if metadata:
            session["metadata"] = {**(session.get("metadata") or {}), **metadata}
        self.es_client.index_document(index=self.settings.es_copilot_session_index, id=session_id, document=session)
        return session

    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self._ensure_message_index()
        now = utc_now_iso()
        message_id = str(uuid4())
        document = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": now,
            "run_id": run_id,
            "metadata": metadata or {},
        }
        self.es_client.index_document(index=self.settings.es_copilot_message_index, id=message_id, document=document)
        return document

    def update_message_run_id(self, message_id: str, run_id: str) -> dict | None:
        message = self.get_message(message_id)
        if message is None:
            return None
        message["run_id"] = run_id
        self.es_client.index_document(index=self.settings.es_copilot_message_index, id=message_id, document=message)
        return message

    def get_message(self, message_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_copilot_message_index, id=message_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_messages(self, session_id: str, limit: int) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_copilot_message_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"session_id": session_id}}]}},
                    "sort": [{"created_at": {"order": "asc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def create_run(self, session_id: str, user_message_id: str, user_input: str) -> dict:
        self._ensure_run_index()
        now = utc_now_iso()
        run_id = str(uuid4())
        document = {
            "id": run_id,
            "session_id": session_id,
            "user_message_id": user_message_id,
            "assistant_message_id": None,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "completed_at": None,
            "user_input": user_input,
            "planner_output": {},
            "actions": [],
            "observations": [],
            "tool_calls": [],
            "skill_requests": [],
            "pending_approval": None,
            "memory_snapshot": {},
            "final_answer": None,
            "error_code": None,
            "error_message": None,
            "metadata": {},
        }
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=document)
        return document

    def find_active_run_by_session(self, session_id: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_copilot_run_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"session_id": session_id}}]}},
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "size": 20,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return None
        for hit in response.get("hits", {}).get("hits", []):
            run = hit.get("_source") or {}
            if run.get("status") in {"queued", "running", "awaiting_approval"}:
                return run
        return None

    def mark_run_running(self, run_id: str) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        now = utc_now_iso()
        run.update({"status": "running", "started_at": run.get("started_at") or now, "updated_at": now})
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def mark_run_completed(
        self,
        run_id: str,
        assistant_message_id: str,
        final_answer: str,
        payload: dict | None = None,
    ) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        now = utc_now_iso()
        run.update(
            {
                "assistant_message_id": assistant_message_id,
                "status": "completed",
                "completed_at": now,
                "updated_at": now,
                "final_answer": final_answer,
                "error_code": None,
                "error_message": None,
            }
        )
        if payload:
            allowed = {
                key: value
                for key, value in payload.items()
                if key in {
                    "planner_output",
                    "actions",
                    "observations",
                    "tool_calls",
                    "skill_requests",
                    "pending_approval",
                    "memory_snapshot",
                    "metadata",
                }
            }
            run.update(allowed)
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def mark_run_awaiting_approval(
        self,
        run_id: str,
        assistant_message_id: str,
        final_answer: str,
        pending_approval: dict,
        payload: dict | None = None,
    ) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        now = utc_now_iso()
        run.update(
            {
                "assistant_message_id": assistant_message_id,
                "status": "awaiting_approval",
                "completed_at": None,
                "updated_at": now,
                "final_answer": final_answer,
                "pending_approval": pending_approval,
                "error_code": None,
                "error_message": None,
            }
        )
        if payload:
            allowed = {
                key: value
                for key, value in payload.items()
                if key in {
                    "planner_output",
                    "actions",
                    "observations",
                    "tool_calls",
                    "skill_requests",
                    "memory_snapshot",
                    "metadata",
                }
            }
            run.update(allowed)
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def update_run_fields(self, run_id: str, payload: dict) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        run.update(payload)
        run["updated_at"] = utc_now_iso()
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def mark_run_failed(self, run_id: str, error_code: str, error_message: str) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        now = utc_now_iso()
        run.update(
            {
                "status": "failed",
                "completed_at": now,
                "updated_at": now,
                "error_code": error_code,
                "error_message": error_message,
            }
        )
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def mark_run_cancelled(self, run_id: str, reason: str | None = None) -> dict | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        now = utc_now_iso()
        run.update(
            {
                "status": "cancelled",
                "completed_at": now,
                "updated_at": now,
                "error_code": "USER_CANCELLED",
                "error_message": reason or "User cancelled the run",
                "metadata": {**(run.get("metadata") or {}), "cancelled": True, "cancel_reason": reason or ""},
            }
        )
        self.es_client.index_document(index=self.settings.es_copilot_run_index, id=run_id, document=run)
        return run

    def get_run(self, run_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_copilot_run_index, id=run_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def touch_session(self, session_id: str, *, message_count_delta: int = 0, last_message_at: str | None = None) -> dict | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        now = utc_now_iso()
        session.update(
            {
                "updated_at": now,
                "last_message_at": last_message_at or session.get("last_message_at"),
                "message_count": int(session.get("message_count") or 0) + message_count_delta,
            }
        )
        self.es_client.index_document(index=self.settings.es_copilot_session_index, id=session_id, document=session)
        return session

    def append_session_message_count(self, session_id: str, count: int = 1) -> dict | None:
        return self.touch_session(session_id, message_count_delta=count)

    def _ensure_session_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_session_index, COPILOT_SESSION_INDEX_BODY)

    def _ensure_message_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_message_index, COPILOT_MESSAGE_INDEX_BODY)

    def _ensure_run_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_copilot_run_index, COPILOT_RUN_INDEX_BODY)
