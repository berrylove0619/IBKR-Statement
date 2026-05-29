from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.agents.graph.progress import make_graph_snapshot, summarize_trace_for_progress
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

AGENT_TASK_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "agent": {"type": "keyword"},
            "task_type": {"type": "keyword"},
            "label": {"type": "text"},
            "status": {"type": "keyword"},
            "payload": {"type": "object", "enabled": True},
            "result_id": {"type": "keyword"},
            "error_code": {"type": "keyword"},
            "error_message": {"type": "text"},
            "created_at": {"type": "date"},
            "started_at": {"type": "date"},
            "completed_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "updated_seq": {"type": "long"},
            "graph_snapshot": {"type": "object", "enabled": True},
            "graph_progress_summary": {"type": "object", "enabled": True},
            "graph_events": {"type": "object", "enabled": True},
        }
    },
}

MAX_GRAPH_EVENTS = 120
_TASK_UPDATE_LOCKS: dict[str, RLock] = {}
_TASK_UPDATE_LOCKS_GUARD = RLock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentTaskRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def create_task(self, *, agent: str, task_type: str, label: str, payload: dict) -> dict:
        self._ensure_index()
        now = utc_now_iso()
        task_id = str(uuid4())
        document = {
            "id": task_id,
            "agent": agent,
            "task_type": task_type,
            "label": label,
            "status": "queued",
            "payload": payload,
            "result_id": None,
            "error_code": None,
            "error_message": None,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "updated_at": now,
            "updated_seq": 0,
            "graph_snapshot": None,
            "graph_progress_summary": {},
            "graph_events": [],
        }
        self.es_client.index_document(index=self.settings.es_agent_task_index, id=task_id, document=document)
        return document

    def mark_running(self, task_id: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        now = utc_now_iso()
        task.update({"status": "running", "started_at": task.get("started_at") or now, "updated_at": now})
        self.es_client.index_document(index=self.settings.es_agent_task_index, id=task_id, document=task)
        return task

    def init_graph_progress(self, task_id: str, *, graph_version: str, nodes: list[dict], edges: list[dict]) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        snapshot = make_graph_snapshot(graph_version=graph_version, nodes=nodes, edges=edges, status="pending")
        task["graph_snapshot"] = snapshot
        task["graph_progress_summary"] = self._build_graph_progress_summary(snapshot)
        self._append_graph_event(task, "graph_initialized", {"graph_version": graph_version})
        self._save(task)
        return task

    def mark_node_running(self, task_id: str, node_id: str) -> dict | None:
        with self._task_update_lock(task_id):
            task = self.get_task(task_id)
            if task is None:
                return None
            snapshot = self._snapshot(task)
            now = utc_now_iso()
            for node in snapshot.get("nodes", []):
                if node.get("id") == node_id:
                    node.update({"status": "running", "started_at": node.get("started_at") or now, "finished_at": None, "error": None})
                    break
            snapshot["status"] = "running"
            snapshot["started_at"] = snapshot.get("started_at") or now
            snapshot["updated_at"] = now
            snapshot["current_nodes"] = [node.get("id") for node in snapshot.get("nodes", []) if node.get("status") == "running"]
            self._set_snapshot(task, snapshot)
            self._append_graph_event(task, "node_started", {"node_id": node_id})
            self._save(task)
            return task

    def mark_node_finished(self, task_id: str, node_id: str, trace: dict | None = None) -> dict | None:
        with self._task_update_lock(task_id):
            task = self.get_task(task_id)
            if task is None:
                return None
            snapshot = self._snapshot(task)
            summary = summarize_trace_for_progress(trace)
            now = utc_now_iso()
            for node in snapshot.get("nodes", []):
                if node.get("id") == node_id:
                    node.update(summary)
                    node["finished_at"] = node.get("finished_at") or now
                    node["started_at"] = node.get("started_at") or summary.get("started_at") or now
                    break
            snapshot["updated_at"] = now
            snapshot["current_nodes"] = [node.get("id") for node in snapshot.get("nodes", []) if node.get("status") == "running"]
            snapshot["status"] = self._infer_graph_status(snapshot)
            self._set_snapshot(task, snapshot)
            self._append_graph_event(task, "node_finished", {"node_id": node_id, **summary})
            self._save(task)
            return task

    def mark_node_failed(self, task_id: str, node_id: str, error_message: str) -> dict | None:
        with self._task_update_lock(task_id):
            task = self.get_task(task_id)
            if task is None:
                return None
            now = utc_now_iso()
            snapshot = self._snapshot(task)
            for node in snapshot.get("nodes", []):
                if node.get("id") == node_id:
                    node.update({"status": "failed", "finished_at": now, "error": error_message[:500]})
                    break
            snapshot["status"] = "failed"
            snapshot["updated_at"] = now
            snapshot["current_nodes"] = []
            self._set_snapshot(task, snapshot)
            self._append_graph_event(task, "node_failed", {"node_id": node_id, "error": error_message[:500]})
            self._save(task)
            return task

    def sync_graph_from_run_trace(self, task_id: str, run_trace: list[dict], *, final_status: str | None = None) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        snapshot = self._snapshot(task)
        traces_by_node = {trace.get("node_name"): trace for trace in run_trace if isinstance(trace, dict)}
        for node in snapshot.get("nodes", []):
            trace = traces_by_node.get(node.get("id"))
            if trace:
                node.update(summarize_trace_for_progress(trace))
        snapshot["current_nodes"] = []
        snapshot["status"] = final_status or self._infer_graph_status(snapshot)
        snapshot["updated_at"] = utc_now_iso()
        self._set_snapshot(task, snapshot)
        self._append_graph_event(task, "graph_synced", {"status": snapshot["status"]})
        self._save(task)
        return task

    def mark_graph_failed(self, task_id: str, error_message: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        snapshot = self._snapshot(task)
        now = utc_now_iso()
        for node in snapshot.get("nodes", []):
            if node.get("status") == "running":
                node.update({"status": "failed", "finished_at": now, "error": error_message[:500]})
        snapshot["status"] = "failed"
        snapshot["current_nodes"] = []
        snapshot["updated_at"] = now
        self._set_snapshot(task, snapshot)
        self._append_graph_event(task, "graph_failed", {"error": error_message[:500]})
        self._save(task)
        return task

    def list_graph_events(self, task_id: str, *, after_seq: int = 0) -> list[dict]:
        task = self.get_task(task_id)
        if task is None:
            return []
        return [event for event in task.get("graph_events") or [] if int(event.get("seq") or 0) > after_seq]

    def mark_completed(self, task_id: str, *, result_id: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        now = utc_now_iso()
        task.update(
            {
                "status": "completed",
                "result_id": result_id,
                "error_code": None,
                "error_message": None,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self.es_client.index_document(index=self.settings.es_agent_task_index, id=task_id, document=task)
        return task

    def mark_failed(self, task_id: str, *, error_code: str, error_message: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        now = utc_now_iso()
        task.update(
            {
                "status": "failed",
                "error_code": error_code,
                "error_message": error_message,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self.es_client.index_document(index=self.settings.es_agent_task_index, id=task_id, document=task)
        return task

    def mark_stale_tasks_failed(self) -> int:
        """Mark all running or queued tasks as failed after a backend restart.

        Any task that is still ``running`` or ``queued`` when the backend starts
        is stale because the previous process that owned it is gone.  Returns
        the number of tasks that were updated.
        """
        self._ensure_index()
        now = utc_now_iso()
        update_body = {
            "script": {
                "source": """
                    ctx._source.status = 'failed';
                    ctx._source.error_code = 'BACKEND_RESTART';
                    ctx._source.error_message = '后端服务重启，Agent 任务被中断';
                    ctx._source.completed_at = params.now;
                    ctx._source.updated_at = params.now;
                """,
                "lang": "painless",
                "params": {"now": now},
            },
            "query": {"bool": {"filter": [{"terms": {"status": ["running", "queued"]}}]}},
        }
        try:
            response = self.es_client.update_by_query(
                index=self.settings.es_agent_task_index,
                body=update_body,
            )
        except ESIndexNotFoundError:
            return 0
        return int(response.get("updated") or 0)

    def get_task(self, task_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_agent_task_index, id=task_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def list_tasks(self, *, agent: str | None = None, limit: int = 20) -> list[dict]:
        filters = []
        if agent:
            filters.append({"term": {"agent": agent}})
        try:
            response = self.es_client.search(
                index=self.settings.es_agent_task_index,
                body={
                    "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.settings.es_agent_task_index, AGENT_TASK_INDEX_BODY)

    def _save(self, task: dict) -> None:
        task["updated_at"] = utc_now_iso()
        self.es_client.index_document(index=self.settings.es_agent_task_index, id=task["id"], document=task)

    def _task_update_lock(self, task_id: str) -> RLock:
        with _TASK_UPDATE_LOCKS_GUARD:
            lock = _TASK_UPDATE_LOCKS.get(task_id)
            if lock is None:
                lock = RLock()
                _TASK_UPDATE_LOCKS[task_id] = lock
            return lock

    def _snapshot(self, task: dict) -> dict:
        snapshot = task.get("graph_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
        snapshot = make_graph_snapshot(graph_version="", nodes=[], edges=[])
        task["graph_snapshot"] = snapshot
        return snapshot

    def _set_snapshot(self, task: dict, snapshot: dict) -> None:
        snapshot["updated_seq"] = int(task.get("updated_seq") or 0) + 1
        task["updated_seq"] = snapshot["updated_seq"]
        task["graph_snapshot"] = snapshot
        task["graph_progress_summary"] = self._build_graph_progress_summary(snapshot)

    def _append_graph_event(self, task: dict, event_type: str, payload: dict) -> None:
        seq = int(task.get("updated_seq") or 0) + 1
        task["updated_seq"] = seq
        snapshot = task.get("graph_snapshot")
        if isinstance(snapshot, dict):
            snapshot["updated_seq"] = seq
        events = list(task.get("graph_events") or [])
        events.append({"seq": seq, "type": event_type, "created_at": utc_now_iso(), **payload})
        task["graph_events"] = events[-MAX_GRAPH_EVENTS:]

    def _infer_graph_status(self, snapshot: dict) -> str:
        nodes = snapshot.get("nodes") or []
        if not nodes:
            return snapshot.get("status") or "pending"
        statuses = {node.get("status") for node in nodes}
        if "failed" in statuses:
            return "failed"
        if "running" in statuses:
            return "running"
        if statuses <= {"success", "fallback", "skipped"}:
            return "fallback" if "fallback" in statuses else "success"
        return "pending"

    def _build_graph_progress_summary(self, snapshot: dict) -> dict:
        nodes = snapshot.get("nodes") or []
        total = len(nodes)
        counts: dict[str, int] = {status: 0 for status in GRAPH_PROGRESS_STATUSES}
        elapsed_ms = 0
        tool_call_count = 0
        for node in nodes:
            status = str(node.get("status") or "pending")
            counts[status] = counts.get(status, 0) + 1
            elapsed_ms += int(node.get("elapsed_ms") or 0)
            tool_call_count += int(node.get("tool_call_count") or 0)
        done = counts.get("success", 0) + counts.get("failed", 0) + counts.get("fallback", 0) + counts.get("skipped", 0)
        return {
            "status": snapshot.get("status") or "pending",
            "total_nodes": total,
            "completed_nodes": done,
            "running_nodes": counts.get("running", 0),
            "failed_nodes": counts.get("failed", 0),
            "fallback_nodes": counts.get("fallback", 0),
            "elapsed_ms": elapsed_ms,
            "tool_call_count": tool_call_count,
        }


GRAPH_PROGRESS_STATUSES = ("pending", "running", "success", "failed", "fallback", "skipped")
