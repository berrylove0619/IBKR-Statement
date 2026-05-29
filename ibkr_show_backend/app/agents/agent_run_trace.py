from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SENSITIVE_KEY_RE = re.compile(
    r"(^authorization$|^cookie$|password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|id[_-]?token)",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_agent_run_id(agent_name: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", agent_name.strip().lower()).strip("_") or "agent"
    return f"{safe_name}_run_{uuid4().hex[:16]}"


@dataclass
class AgentRunTrace:
    run_id: str
    agent_name: str
    agent_version: str | None = None
    agent_mode: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    latency_ms: int = 0
    final_status: str = "success"
    error_code: str | None = None
    error_message: str | None = None
    prompt_metadata: dict = field(default_factory=dict)
    context_manifest: dict = field(default_factory=dict)
    llm_calls: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    repair_attempts: list[dict] = field(default_factory=list)
    fallback: dict = field(default_factory=lambda: {"used": False, "reason": None})
    quality_score: dict = field(default_factory=dict)
    node_traces: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_trace_payload(asdict(self))


def build_agent_run_trace(
    *,
    run_id: str,
    agent_name: str,
    document: dict | None = None,
    node_traces: list[dict] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    final_status: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> AgentRunTrace:
    doc = document or {}
    doc_metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    all_metadata = {**doc_metadata, **(metadata or {})}
    traces = node_traces if node_traces is not None else list(doc.get("run_trace") or doc.get("graph_node_traces") or [])
    normalized = normalize_runtime_trace_events(traces)
    status = final_status or summarize_trace_status(doc, traces)
    fallback = {
        "used": bool(doc.get("fallback_used") or all_metadata.get("fallback_used") or normalized.get("fallback_used")),
        "reason": doc.get("fallback_reason") or all_metadata.get("fallback_reason") or normalized.get("fallback_reason"),
    }
    start = started_at or doc.get("started_at") or _first_started_at(traces) or utc_now_iso()
    finish = finished_at or doc.get("updated_at") or doc.get("created_at") or _last_finished_at(traces)
    latency_ms = _latency_from_times(start, finish) or int(normalized.get("latency_ms") or 0)
    prompt_metadata = _merge_prompt_metadata(all_metadata.get("prompt_metadata"), normalized.get("prompt_metadata"))
    return AgentRunTrace(
        run_id=run_id,
        agent_name=agent_name,
        agent_version=all_metadata.get("agent_version"),
        agent_mode=all_metadata.get("agent_mode") or doc.get("agent_mode"),
        started_at=start,
        finished_at=finish,
        latency_ms=latency_ms,
        final_status=status,
        error_code=error_code or _first_error_code(traces),
        error_message=error_message or _first_error_message(doc, traces),
        prompt_metadata=prompt_metadata,
        context_manifest=_build_context_manifest(doc),
        llm_calls=normalized["llm_calls"],
        tool_calls=normalized["tool_calls"],
        validation=_build_validation(doc, traces),
        repair_attempts=_extract_repair_attempts(traces),
        fallback=fallback,
        quality_score={},
        node_traces=sanitize_trace_payload(traces),
        metadata={
            "document_id": doc.get("id"),
            "review_type": doc.get("review_type"),
            "decision_type": doc.get("decision_type"),
            "symbol": doc.get("symbol"),
            "report_date": doc.get("report_date"),
            "graph_version": all_metadata.get("graph_version") or doc.get("graph_version"),
        },
    )


def normalize_runtime_trace_events(events: list[dict]) -> dict[str, Any]:
    flat_events = _flatten_runtime_events(events)
    llm_calls = extract_llm_calls_from_trace(flat_events)
    tool_calls = extract_tool_calls_from_trace(flat_events)
    prompt_metadata = _prompt_metadata_from_events(events, llm_calls)
    return {
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in llm_calls),
        "estimated_cost": sum(float(item.get("estimated_cost") or 0) for item in llm_calls),
        "prompt_metadata": prompt_metadata,
        "fallback_used": any(bool(item.get("fallback_used")) or item.get("status") == "fallback" for item in events if isinstance(item, dict)),
        "fallback_reason": next((item.get("fallback_reason") for item in events if isinstance(item, dict) and item.get("fallback_reason")), None),
        "latency_ms": sum(int(item.get("elapsed_ms") or item.get("latency_ms") or 0) for item in events if isinstance(item, dict)),
    }


def extract_llm_calls_from_trace(trace: list[dict]) -> list[dict]:
    calls: list[dict] = []
    for event in trace:
        if not isinstance(event, dict) or event.get("event") != "llm_finish":
            continue
        calls.append(
            {
                "call_id": event.get("call_id"),
                "model": event.get("model"),
                "agent_name": event.get("agent_name"),
                "node_name": event.get("node_name"),
                "prompt_key": event.get("prompt_key"),
                "prompt_version": event.get("prompt_version"),
                "prompt_hash": event.get("prompt_hash"),
                "prompt_source": event.get("prompt_source"),
                "prompt_tokens": int(event.get("prompt_tokens") or 0),
                "completion_tokens": int(event.get("completion_tokens") or 0),
                "total_tokens": int(event.get("total_tokens") or 0),
                "latency_ms": int(event.get("latency_ms") or 0),
                "estimated_cost": event.get("estimated_cost"),
                "ok": event.get("ok", True),
            }
        )
    return calls


def extract_tool_calls_from_trace(trace: list[dict]) -> list[dict]:
    calls: list[dict] = []
    starts: dict[str, dict] = {}
    for event in trace:
        if not isinstance(event, dict):
            continue
        if event.get("event") == "tool_start":
            call_id = str(event.get("tool_call_id") or f"tool-{len(starts) + 1}")
            starts[call_id] = event
        if event.get("event") in {"tool_finish", "tool_error"}:
            call_id = str(event.get("tool_call_id") or f"tool-{len(calls) + 1}")
            start = starts.get(call_id, {})
            calls.append(
                {
                    "tool": event.get("tool") or start.get("tool"),
                    "arguments_preview": sanitize_trace_payload(start.get("arguments") or event.get("arguments") or {}),
                    "ok": event.get("event") == "tool_finish" and bool(event.get("ok", True)),
                    "latency_ms": int(event.get("latency_ms") or event.get("elapsed_ms") or 0),
                    "summary": event.get("summary"),
                    "data_limitations": _data_limitations_from_event(event),
                }
            )
    return calls


def summarize_trace_status(document: dict, node_traces: list[dict]) -> str:
    if document.get("status") in {"success", "partial", "failed"}:
        return str(document["status"])
    if any(item.get("status") == "failed" for item in node_traces if isinstance(item, dict)):
        return "failed"
    if document.get("fallback_used") or any(item.get("fallback_used") for item in node_traces if isinstance(item, dict)):
        return "partial"
    return "success"


def sanitize_trace_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_trace_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_trace_payload(item) for item in value]
    if isinstance(value, str) and len(value) > 2000:
        return value[:1997] + "..."
    return value


def _flatten_runtime_events(events: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") in {"llm_start", "llm_finish", "tool_start", "tool_finish", "tool_error", "final"}:
            flat.append(event)
        runtime_trace = event.get("runtime_trace")
        if isinstance(runtime_trace, list):
            for child in runtime_trace:
                if isinstance(child, dict):
                    child_copy = {**child}
                    child_copy.setdefault("node_name", event.get("node_name"))
                    flat.append(child_copy)
    return flat


def _prompt_metadata_from_events(events: list[dict], llm_calls: list[dict]) -> dict:
    result: dict[str, dict] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        metadata = event.get("prompt_metadata")
        if isinstance(metadata, dict):
            if metadata.get("prompt_key"):
                result[str(metadata["prompt_key"])] = metadata
            else:
                for key, value in metadata.items():
                    if isinstance(value, dict):
                        result[str(key)] = value
    for call in llm_calls:
        key = call.get("prompt_key")
        if key and key not in result:
            result[str(key)] = {
                "prompt_key": key,
                "version": call.get("prompt_version"),
                "content_hash": call.get("prompt_hash"),
                "source": call.get("prompt_source"),
            }
    return result


def _merge_prompt_metadata(*values: Any) -> dict:
    merged: dict = {}
    for value in values:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, dict):
                    merged[str(key)] = item
            if value.get("prompt_key"):
                merged[str(value["prompt_key"])] = value
    return merged


def _build_context_manifest(document: dict) -> dict:
    return {
        "data_limitations": document.get("data_limitations") or [],
        "run_trace_summary": document.get("run_trace_summary") or {},
        "evidence_summary_keys": list((document.get("evidence_summary") or {}).keys())[:20] if isinstance(document.get("evidence_summary"), dict) else [],
    }


def _build_validation(document: dict, traces: list[dict]) -> dict:
    repair_count = len(_extract_repair_attempts(traces))
    failed = bool(document.get("fallback_used")) and not document.get("raw_llm_response")
    return {
        "json_parse_ok": not failed,
        "schema_validate_ok": not failed,
        "normalize_ok": not failed,
        "repair_count": repair_count,
    }


def _extract_repair_attempts(traces: list[dict]) -> list[dict]:
    attempts = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if "repair" in str(trace.get("node_name") or trace.get("event") or "").lower():
            attempts.append(sanitize_trace_payload(trace))
    return attempts


def _data_limitations_from_event(event: dict) -> list[str]:
    observation = event.get("observation") if isinstance(event.get("observation"), dict) else {}
    value = observation.get("data_limitations") or event.get("data_limitations") or []
    return list(value) if isinstance(value, list) else [str(value)] if value else []


def _first_started_at(traces: list[dict]) -> str | None:
    return next((item.get("started_at") for item in traces if isinstance(item, dict) and item.get("started_at")), None)


def _last_finished_at(traces: list[dict]) -> str | None:
    values = [item.get("finished_at") for item in traces if isinstance(item, dict) and item.get("finished_at")]
    return values[-1] if values else None


def _latency_from_times(started_at: str | None, finished_at: str | None) -> int:
    if not started_at or not finished_at:
        return 0
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        finish = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
        return max(0, int((finish - start).total_seconds() * 1000))
    except ValueError:
        return 0


def _first_error_code(traces: list[dict]) -> str | None:
    return next((str(item.get("error_code")) for item in traces if isinstance(item, dict) and item.get("error_code")), None)


def _first_error_message(document: dict, traces: list[dict]) -> str | None:
    if document.get("fallback_reason"):
        return str(document["fallback_reason"])
    return next((str(item.get("error")) for item in traces if isinstance(item, dict) and item.get("error")), None)
