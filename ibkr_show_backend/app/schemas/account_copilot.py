from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CopilotSessionCreateRequest(BaseModel):
    title: str | None = None


class CopilotSessionUpdateRequest(BaseModel):
    title: str | None = None
    status: Literal["active", "archived"] | None = None


class CopilotSessionResponse(BaseModel):
    id: str
    title: str
    status: Literal["active", "archived"]
    created_at: str
    updated_at: str
    last_message_at: str | None = None
    message_count: int
    rolling_summary: str = ""
    compressed_until_message_id: str | None = None
    pinned_facts: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class CopilotSessionListResponse(BaseModel):
    items: list[CopilotSessionResponse]


class CopilotMessageResponse(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str
    run_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class CopilotMessageListResponse(BaseModel):
    items: list[CopilotMessageResponse]


class CopilotRunResponse(BaseModel):
    id: str
    session_id: str
    user_message_id: str
    assistant_message_id: str | None = None
    status: Literal["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"]
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    user_input: str
    planner_output: dict = Field(default_factory=dict)
    actions: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    skill_requests: list[dict] = Field(default_factory=list)
    pending_approval: dict | None = None
    memory_snapshot: dict = Field(default_factory=dict)
    final_answer: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)


class CopilotSendMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class CopilotSendMessageResponse(BaseModel):
    user_message: CopilotMessageResponse
    assistant_message: CopilotMessageResponse
    run: CopilotRunResponse


class CopilotSendMessageStreamResponse(BaseModel):
    user_message: CopilotMessageResponse
    run: CopilotRunResponse
    events_url: str


class CopilotCancelRunRequest(BaseModel):
    reason: str | None = None


class CopilotEventResponse(BaseModel):
    id: str
    run_id: str
    session_id: str
    event_type: str
    seq: int
    created_at: str
    payload: dict = Field(default_factory=dict)


class CopilotEventListResponse(BaseModel):
    items: list[CopilotEventResponse]


class CopilotApprovalRequest(BaseModel):
    approval_id: str = Field(min_length=1)
    approved: bool
    plan_hash: str = Field(min_length=1)
    comment: str | None = None


class CopilotApprovalResponse(BaseModel):
    run: CopilotRunResponse
    assistant_message: CopilotMessageResponse | None = None


class CopilotMemoryResponse(BaseModel):
    id: str
    session_id: str
    memory_type: Literal["conversation_segment", "pinned_fact", "tool_fact", "skill_fact", "constraint"]
    status: Literal["active", "superseded", "deleted"]
    created_at: str
    updated_at: str
    message_start_id: str | None = None
    message_end_id: str | None = None
    message_count: int = 0
    message_range_created_at: dict = Field(default_factory=dict)
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    user_intent: str = ""
    important_facts: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_facts: list[dict] = Field(default_factory=list)
    skill_facts: list[dict] = Field(default_factory=list)
    non_compressible_constraints: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    source_message_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class CopilotMemoryListResponse(BaseModel):
    items: list[CopilotMemoryResponse]


class CopilotTraceTimelineNode(BaseModel):
    node_type: str
    round: int | None = None
    status: str = ""
    label: str = ""
    created_at: str = ""
    payload: dict = Field(default_factory=dict)


class CopilotRunTraceResponse(BaseModel):
    run_id: str
    status: str
    timeline: list[CopilotTraceTimelineNode] = Field(default_factory=list)
    events: list[CopilotEventResponse] = Field(default_factory=list)
