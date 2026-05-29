from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MemoryCompressionOutput(BaseModel):
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    user_intent: str = ""
    important_facts: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_facts: list[dict[str, Any]] = Field(default_factory=list)
    skill_facts: list[dict[str, Any]] = Field(default_factory=list)
    non_compressible_constraints: list[str] = Field(default_factory=list)


class AccountCopilotMemoryDocument(BaseModel):
    id: str
    session_id: str
    memory_type: Literal["conversation_segment", "pinned_fact", "tool_fact", "skill_fact", "constraint"]
    status: Literal["active", "superseded", "deleted"] = "active"
    created_at: str
    updated_at: str
    message_start_id: str | None = None
    message_end_id: str | None = None
    message_count: int = 0
    message_range_created_at: dict[str, str | None] = Field(default_factory=dict)
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    user_intent: str = ""
    important_facts: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_facts: list[dict[str, Any]] = Field(default_factory=list)
    skill_facts: list[dict[str, Any]] = Field(default_factory=list)
    non_compressible_constraints: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    source_message_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
