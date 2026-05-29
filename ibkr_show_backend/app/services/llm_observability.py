from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_call_id() -> str:
    return f"llm_call_{uuid4().hex[:16]}"


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    @classmethod
    def from_response_usage(cls, usage: Any) -> "LLMUsage":
        if not isinstance(usage, dict):
            return cls()
        completion_details = usage.get("completion_tokens_details")
        prompt_details = usage.get("prompt_tokens_details")
        return cls(
            prompt_tokens=_safe_int(usage.get("prompt_tokens")),
            completion_tokens=_safe_int(usage.get("completion_tokens")),
            total_tokens=_safe_int(usage.get("total_tokens")),
            reasoning_tokens=_safe_int(completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else 0),
            cached_tokens=_safe_int(prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else 0),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class LLMCallMetadata:
    call_id: str
    provider_id: str | None
    provider_name: str | None
    provider_type: str | None
    model: str
    call_type: str = "unknown"
    agent_name: str | None = None
    node_name: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    prompt_source: str | None = None
    response_format: dict | None = None
    tool_calling: bool = False
    tool_count: int = 0
    temperature: float | None = None
    max_tokens: int | None = None
    latency_ms: int = 0
    ok: bool = True
    error_code: str | None = None
    error_message: str | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    estimated_cost: float | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["usage"] = self.usage.to_dict()
        return value


@dataclass
class LLMCallResult:
    content: str | None
    message: dict[str, Any] | None
    raw_response_metadata: dict[str, Any]
    call_metadata: LLMCallMetadata


def extract_prompt_metadata(prompt_metadata: dict | None) -> dict[str, str | None]:
    value = prompt_metadata if isinstance(prompt_metadata, dict) else {}
    return {
        "prompt_key": _as_optional_str(value.get("prompt_key")),
        "prompt_version": _as_optional_str(value.get("version")),
        "prompt_hash": _as_optional_str(value.get("content_hash")),
        "prompt_source": _as_optional_str(value.get("source")),
    }


def safe_response_metadata(data: dict[str, Any]) -> dict[str, Any]:
    choice = _first_choice(data)
    message = choice.get("message") if isinstance(choice, dict) else {}
    return {
        "id": data.get("id"),
        "object": data.get("object"),
        "created": data.get("created"),
        "model": data.get("model"),
        "system_fingerprint": data.get("system_fingerprint"),
        "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
        "tool_calls_count": len(message.get("tool_calls") or []) if isinstance(message, dict) else 0,
    }


def response_format_type(response_format: dict | None) -> str | None:
    if not isinstance(response_format, dict):
        return None
    value = response_format.get("type")
    return str(value) if value else None


def estimate_llm_cost(provider_config: Any, usage: LLMUsage) -> float | None:
    input_price = float(getattr(provider_config, "input_price_per_1m_tokens", 0) or 0)
    output_price = float(getattr(provider_config, "output_price_per_1m_tokens", 0) or 0)
    if input_price <= 0 and output_price <= 0:
        return None
    return (usage.prompt_tokens * input_price + usage.completion_tokens * output_price) / 1_000_000


def _first_choice(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
