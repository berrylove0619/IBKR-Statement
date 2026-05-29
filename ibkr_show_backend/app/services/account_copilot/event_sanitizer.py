from __future__ import annotations

import json
from typing import Any

SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "secret",
    "password",
    "cookie",
    "set_cookie",
    "reasoning",
    "thinking",
    "chain_of_thought",
}


def sanitize_event_payload(event_type: str, payload: dict, max_chars: int = 6000) -> dict:
    sanitized = _sanitize(payload or {})
    text = json.dumps(sanitized, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return sanitized
    return {
        "event_type": event_type,
        "truncated_json": text[:max_chars],
        "data_limitations": ["Event payload was truncated by Account Copilot."],
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS:
                continue
            if normalized == "arguments":
                cleaned[key] = _preview(_sanitize(item), 1000)
            elif normalized in {"data", "raw_data", "tool_data"}:
                cleaned[key] = _preview(_sanitize(item), 1500)
            else:
                cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:50]]
    return value


def _preview(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {"truncated_json": text[:limit], "data_limitations": ["Preview was truncated by Account Copilot."]}
