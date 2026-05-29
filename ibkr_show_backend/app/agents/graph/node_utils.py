"""Shared node utilities for LangGraph nodes."""

from __future__ import annotations

import re
from typing import Any, Callable


_THINK_TAG_PATTERNS = [
    re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE),
    re.compile(r"<thinking>[\s\S]*?</thinking>", re.IGNORECASE),
    re.compile(r"<think>[\s\S]*$", re.IGNORECASE),
]


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think>, <thinking>...</thinking>, and unclosed <think> blocks."""
    if not isinstance(text, str):
        return text
    result = text
    for pattern in _THINK_TAG_PATTERNS:
        result = pattern.sub("", result)
    return result.strip()


def safe_node(
    node_name: str,
    fn: Callable[..., dict],
    fallback_fn: Callable[..., dict] | None = None,
) -> Callable[..., dict]:
    """Wrap a node function with error handling. Returns partial state dict."""

    def wrapper(state: dict) -> dict:
        from app.agents.graph.trace import (
            start_node_trace,
            finish_node_trace,
            fallback_node_trace,
            append_node_trace,
        )

        trace = start_node_trace(node_name)
        try:
            result = fn(state)
            trace = finish_node_trace(trace, "success")
            append_node_trace(result, trace)
            return result
        except Exception as exc:
            if fallback_fn is not None:
                try:
                    result = fallback_fn(state, exc)
                    trace = finish_node_trace(trace, "fallback", fallback_reason=str(exc)[:200], fallback_used=True)
                    append_node_trace(result, trace)
                    return result
                except Exception:
                    pass
            error_msg = str(exc)[:200]
            errors = list(state.get("errors") or [])
            errors.append(f"{node_name}: {error_msg}")
            return {
                "errors": errors,
                "node_traces": list(state.get("node_traces") or []) + [fallback_node_trace(node_name, exc)],
            }

    return wrapper


def merge_data_limitations(*items: Any) -> list[str]:
    """Merge multiple data limitation sources into a deduplicated list."""
    result: list[str] = []
    for item in items:
        if isinstance(item, list):
            result.extend(str(x)[:200] for x in item if x)
        elif isinstance(item, str) and item:
            result.append(item[:200])
    return list(dict.fromkeys(result))[:10]


def compact_error(exc: Exception | str) -> str:
    return str(exc)[:200]


def ensure_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
