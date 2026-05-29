"""Base graph state shared across all agent graphs."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _merge_str_list(left: list[str], right: list[str]) -> list[str]:
    """Reducer: concatenate and deduplicate string lists."""
    return list(dict.fromkeys((left or []) + (right or [])))


def _merge_trace_list(left: list[dict], right: list[dict]) -> list[dict]:
    """Reducer: concatenate trace dicts."""
    return (left or []) + (right or [])


class BaseGraphState(TypedDict, total=False):
    request_id: str
    agent_name: str
    progress_reporter: Any
    started_at: str
    finished_at: str
    errors: Annotated[list[str], _merge_str_list]
    warnings: Annotated[list[str], _merge_str_list]
    data_limitations: Annotated[list[str], _merge_str_list]
    node_traces: Annotated[list[dict], _merge_trace_list]
    fallback_used: bool
    fallback_reason: str | None
    metadata: dict
