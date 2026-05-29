from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SystemComponentStatus(BaseModel):
    name: str
    label: str
    status: Literal["ok", "warning", "error", "disabled", "unknown"]
    configured: bool | None = None
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AdminSystemStatusResponse(BaseModel):
    overall_status: Literal["ok", "warning", "error"]
    generated_at: str
    components: list[SystemComponentStatus]
