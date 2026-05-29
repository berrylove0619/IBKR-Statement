"""Lightweight LangGraph task progress helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


GRAPH_NODE_STATUSES = {"pending", "running", "success", "failed", "fallback", "skipped"}


def make_graph_snapshot(*, graph_version: str, nodes: list[dict], edges: list[dict], status: str = "pending") -> dict:
    return {
        "graph_version": graph_version,
        "nodes": [
            {
                "id": node["id"],
                "label": node.get("label") or node["id"],
                "status": node.get("status") or "pending",
                "started_at": None,
                "finished_at": None,
                "elapsed_ms": 0,
                "fallback_used": False,
                "fallback_reason": None,
                "error": None,
                "rounds_used": 0,
                "tools_called": [],
                "tool_calls": [],
                "tool_call_count": 0,
                "data_limitations_count": 0,
            }
            for node in nodes
        ],
        "edges": edges,
        "current_nodes": [],
        "status": status,
        "updated_seq": 0,
        "started_at": None,
        "updated_at": None,
    }


def summarize_trace_for_progress(trace: dict | None) -> dict:
    trace = trace or {}
    runtime_trace = _extract_runtime_trace(trace)

    top_tools = trace.get("tools_called") or trace.get("tool_calls") or []
    inferred_tool_calls = _infer_tool_calls(trace, runtime_trace)
    inferred_tools_called = _infer_tools_called(trace, runtime_trace)

    tool_calls_out = _compact_tool_calls(top_tools) if top_tools else _compact_tool_calls(inferred_tool_calls)
    tools_called_out = _compact_tools_called(top_tools) if top_tools else _compact_tools_called(inferred_tools_called)
    tool_call_count = int(trace.get("tool_call_count") or 0) or len(tool_calls_out) or len(tools_called_out)

    status = str(trace.get("status") or "success")
    if trace.get("fallback_used") and status == "success":
        status = "fallback"
    return {
        "status": status if status in GRAPH_NODE_STATUSES else "success",
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "elapsed_ms": int(trace.get("elapsed_ms") or 0),
        "fallback_used": bool(trace.get("fallback_used")),
        "fallback_reason": trace.get("fallback_reason"),
        "error": trace.get("error"),
        "rounds_used": _infer_rounds_used(trace, runtime_trace),
        "tools_called": tools_called_out,
        "tool_calls": tool_calls_out,
        "tool_call_count": tool_call_count,
        "data_limitations_count": _infer_data_limitations_count(trace, runtime_trace),
    }


def _extract_runtime_trace(trace: dict) -> list[dict]:
    for key in ("runtime_trace", "trace", "events"):
        value = trace.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def _infer_rounds_used(trace: dict, runtime_trace: list[dict]) -> int:
    top = int(trace.get("rounds_used") or 0)
    if top > 0:
        return top
    if not runtime_trace:
        return 0
    llm_starts = sum(1 for e in runtime_trace if e.get("event") in {"llm_start", "structured_output_llm_start"})
    return max(llm_starts, 1) if llm_starts else 0


def _infer_tool_calls(trace: dict, runtime_trace: list[dict]) -> list[dict]:
    top = trace.get("tool_calls")
    if isinstance(top, list) and top:
        return top
    if not runtime_trace:
        return []
    terminal_events = {"tool_finish", "tool_error", "tool_result"}
    all_events = terminal_events | {"tool_start", "tool_call"}
    has_terminal = any(e.get("event") in terminal_events for e in runtime_trace)
    target_events = terminal_events if has_terminal else all_events
    seen: set[str] = set()
    calls: list[dict] = []
    for event in runtime_trace:
        event_name = event.get("event") or ""
        if event_name not in target_events:
            continue
        tool_name = str(event.get("tool") or event.get("tool_name") or event.get("name") or "tool")
        key = event.get("tool_call_id") or event.get("call_id") or event.get("id") or f"{tool_name}:{len(calls)}"
        if key in seen:
            continue
        seen.add(key)
        if event_name in terminal_events:
            success = event.get("ok") if "ok" in event else (event_name != "tool_error")
            calls.append({"tool_name": tool_name, "success": success, "error_type": event.get("error_type") or (event.get("error") if event_name == "tool_error" else None)})
        else:
            calls.append({"tool_name": tool_name, "success": None})
    return calls


def _infer_tools_called(trace: dict, runtime_trace: list[dict]) -> list[str]:
    top = trace.get("tools_called")
    if isinstance(top, list) and top:
        return [str(t) for t in top[:20] if t]
    tool_calls = _infer_tool_calls(trace, runtime_trace)
    seen: set[str] = set()
    names: list[str] = []
    for call in tool_calls:
        name = call.get("tool_name") or "tool"
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names[:20]


def _infer_data_limitations_count(trace: dict, runtime_trace: list[dict]) -> int:
    top = trace.get("data_limitations")
    if isinstance(top, list):
        return len(top)
    top_count = int(trace.get("data_limitations_count") or 0)
    if top_count > 0:
        return top_count
    count = 0
    for event in runtime_trace:
        if event.get("event") == "structured_output_result":
            count = max(count, int(event.get("data_limitations_count") or 0))
        limitations = event.get("data_limitations")
        if isinstance(limitations, list):
            count = max(count, len(limitations))
    return count


def _compact_tools_called(tools_called: Any) -> list[str]:
    if not isinstance(tools_called, list):
        return []
    values: list[str] = []
    for item in tools_called[:20]:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            values.append(str(item.get("tool_name") or item.get("name") or item.get("mcp_tool_name") or "tool"))
    return values


def _compact_tool_calls(tool_calls: Any) -> list[dict]:
    if not isinstance(tool_calls, list):
        return []
    compact: list[dict] = []
    for item in tool_calls[:20]:
        if isinstance(item, str):
            compact.append({"tool_name": item, "success": None})
            continue
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "tool_name": item.get("tool_name") or item.get("name") or item.get("mcp_tool_name") or "tool",
                "mcp_tool_name": item.get("mcp_tool_name"),
                "success": item.get("success"),
                "empty_result": item.get("empty_result"),
                "error_type": item.get("error_type"),
            }
        )
    return compact


def find_node_trace(result: Any, node_name: str) -> dict | None:
    if not isinstance(result, dict):
        return None
    traces = result.get("node_traces") or []
    for trace in reversed(traces):
        if isinstance(trace, dict) and trace.get("node_name") == node_name:
            return trace
    return traces[-1] if traces and isinstance(traces[-1], dict) else None


def instrument_graph_node(node_name: str, node_fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
    """Wrap a LangGraph node and report lightweight progress if state carries a reporter."""

    def wrapped(state: dict) -> dict:
        reporter = state.get("progress_reporter") if isinstance(state, dict) else None
        if reporter is not None:
            try:
                reporter.node_started(node_name)
            except Exception:
                pass
        try:
            result = node_fn(state)
        except Exception as exc:
            if reporter is not None:
                try:
                    reporter.node_failed(node_name, str(exc))
                except Exception:
                    pass
            raise
        if reporter is not None:
            try:
                reporter.node_finished(node_name, find_node_trace(result, node_name))
            except Exception:
                pass
        return result

    return wrapped
