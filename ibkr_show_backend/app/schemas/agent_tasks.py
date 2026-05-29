from pydantic import BaseModel, Field


class AgentTaskResponse(BaseModel):
    id: str
    agent: str
    task_type: str
    label: str
    status: str
    payload: dict = Field(default_factory=dict)
    result_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
    updated_seq: int = 0
    graph_snapshot: dict | None = None
    graph_progress_summary: dict = Field(default_factory=dict)
    graph_events: list[dict] = Field(default_factory=list)


class AgentTaskListResponse(BaseModel):
    items: list[AgentTaskResponse]
