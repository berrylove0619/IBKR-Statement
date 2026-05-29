"""Progress reporter used by LangGraph background tasks."""

from __future__ import annotations

from app.services.agent_task_repository import AgentTaskRepository


class AgentTaskProgressReporter:
    def __init__(self, task_repository: AgentTaskRepository, task_id: str) -> None:
        self.task_repository = task_repository
        self.task_id = task_id

    def node_started(self, node_id: str) -> None:
        self.task_repository.mark_node_running(self.task_id, node_id)

    def node_finished(self, node_id: str, trace: dict | None = None) -> None:
        self.task_repository.mark_node_finished(self.task_id, node_id, trace)

    def node_failed(self, node_id: str, error_message: str) -> None:
        self.task_repository.mark_node_failed(self.task_id, node_id, error_message)

    def graph_failed(self, error_message: str) -> None:
        self.task_repository.mark_graph_failed(self.task_id, error_message)

    def sync_from_document(self, document: dict, *, final_status: str | None = None) -> None:
        self.task_repository.sync_graph_from_run_trace(
            self.task_id,
            document.get("run_trace") or document.get("graph_node_traces") or [],
            final_status=final_status,
        )
