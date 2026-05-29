from __future__ import annotations

from typing import Any, TypedDict


class AccountCopilotState(TypedDict, total=False):
    session_id: str
    run_id: str
    user_message_id: str
    user_input: str
    rolling_summary: str
    pinned_facts: dict[str, Any]
    retrieved_memories: list[dict[str, Any]]
    non_compressible_constraints: list[str]
    messages: list[dict[str, Any]]
    planner_output: dict[str, Any]
    actions: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    skill_requests: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    memory_snapshot: dict[str, Any]
    final_answer: str | None
    errors: list[dict[str, Any]]
