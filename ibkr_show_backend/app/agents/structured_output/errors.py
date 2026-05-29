from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LLM_CALL_FAILED = "LLM_CALL_FAILED"
LLM_OUTPUT_EMPTY = "LLM_OUTPUT_EMPTY"
LLM_JSON_PARSE_FAILED = "LLM_JSON_PARSE_FAILED"
LLM_OUTPUT_NOT_OBJECT = "LLM_OUTPUT_NOT_OBJECT"
LLM_SCHEMA_INVALID = "LLM_SCHEMA_INVALID"
LLM_REPAIR_FAILED = "LLM_REPAIR_FAILED"
LLM_REPAIR_SCHEMA_INVALID = "LLM_REPAIR_SCHEMA_INVALID"
STRUCTURED_FALLBACK_USED = "STRUCTURED_FALLBACK_USED"
STRUCTURED_OUTPUT_UNKNOWN_ERROR = "STRUCTURED_OUTPUT_UNKNOWN_ERROR"


def preview_text(value: Any, *, max_chars: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated]"


@dataclass
class StructuredOutputError(Exception):
    error_code: str
    message: str
    raw_response_preview: str | None = None
    validation_error: str | None = None
    repair_attempt: int | None = None
    cause: Exception | None = None

    def __post_init__(self) -> None:
        self.raw_response_preview = preview_text(self.raw_response_preview, max_chars=500)
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "raw_response_preview": self.raw_response_preview,
            "validation_error": preview_text(self.validation_error, max_chars=1000),
            "repair_attempt": self.repair_attempt,
            "cause_type": type(self.cause).__name__ if self.cause is not None else None,
            "cause_message": preview_text(str(self.cause), max_chars=500) if self.cause is not None else None,
        }
