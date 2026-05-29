from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.agent_run_trace import AgentRunTrace


REPLAY_SCHEMA_VERSION = "v1"
DEFAULT_SECTION_MAX_CHARS = 30000
SENSITIVE_KEY_RE = re.compile(
    r"(^authorization$|^cookie$|password|secret|private[_-]?key|api[_-]?key|access[_-]?token|refresh[_-]?token|session|token)",
    re.IGNORECASE,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_replay_id(agent_name: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", agent_name.strip().lower()).strip("_") or "agent"
    return f"{safe_name}_replay_{uuid4().hex[:16]}"


@dataclass
class AgentReplaySnapshot:
    replay_id: str
    run_id: str
    agent_name: str
    agent_version: str | None = None
    agent_mode: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    source: str = "runtime"
    replay_schema_version: str = REPLAY_SCHEMA_VERSION
    request: dict = field(default_factory=dict)
    prompt_refs: list[dict] = field(default_factory=list)
    model_config: dict = field(default_factory=dict)
    context_snapshot: dict = field(default_factory=dict)
    tool_snapshots: list[dict] = field(default_factory=list)
    llm_snapshots: list[dict] = field(default_factory=list)
    final_output: dict = field(default_factory=dict)
    persisted_document_id: str | None = None
    final_status: str = "success"
    data_limitations: list[str] = field(default_factory=list)
    trace_ref: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_replay_payload(asdict(self))


def build_replay_snapshot(
    *,
    run_id: str,
    agent_name: str,
    request: dict,
    document: dict,
    agent_run_trace: dict | AgentRunTrace | None,
    node_traces: list[dict] | None = None,
    context_snapshot: dict | None = None,
) -> AgentReplaySnapshot:
    trace_dict = _trace_to_dict(agent_run_trace)
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    prompt_refs = _prompt_refs(metadata.get("prompt_metadata"), trace_dict.get("prompt_metadata"))
    llm_calls = trace_dict.get("llm_calls") if isinstance(trace_dict.get("llm_calls"), list) else []
    tool_calls = trace_dict.get("tool_calls") if isinstance(trace_dict.get("tool_calls"), list) else []
    model_config = _model_config_from_llm_calls(llm_calls)
    raw_output = document.get("raw_llm_response")
    return AgentReplaySnapshot(
        replay_id=new_replay_id(agent_name),
        run_id=run_id,
        agent_name=agent_name,
        agent_version=metadata.get("agent_version") or trace_dict.get("agent_version"),
        agent_mode=metadata.get("agent_mode") or trace_dict.get("agent_mode") or document.get("agent_mode"),
        request=sanitize_replay_payload(request),
        prompt_refs=prompt_refs,
        model_config=model_config,
        context_snapshot=truncate_replay_payload(
            sanitize_replay_payload(context_snapshot or _default_context_snapshot(document)),
            DEFAULT_SECTION_MAX_CHARS,
        ),
        tool_snapshots=_tool_snapshots(tool_calls),
        llm_snapshots=_llm_snapshots(llm_calls, raw_output=raw_output, node_traces=node_traces or trace_dict.get("node_traces") or []),
        final_output=truncate_replay_payload(sanitize_replay_payload(_final_output(document)), DEFAULT_SECTION_MAX_CHARS),
        persisted_document_id=str(document.get("id")) if document.get("id") is not None else None,
        final_status=str(trace_dict.get("final_status") or document.get("status") or ("partial" if document.get("fallback_used") else "success")),
        data_limitations=[str(item) for item in (document.get("data_limitations") or [])],
        trace_ref={"run_id": run_id, "agent_run_trace_exists": bool(agent_run_trace)},
        metadata={
            "document_id": document.get("id"),
            "review_type": document.get("review_type"),
            "decision_type": document.get("decision_type"),
            "symbol": document.get("symbol"),
            "report_date": document.get("report_date"),
            "truncated": True,
        },
    )


def sanitize_replay_payload(value: Any, *, _parent: dict | None = None, _key: str | None = None) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                sanitized[key] = "***"
            elif _is_full_prompt_field(str(key), value):
                sanitized[key] = "[prompt omitted]"
            else:
                sanitized[key] = sanitize_replay_payload(item, _parent=value, _key=str(key))
        return sanitized
    if isinstance(value, list):
        return [sanitize_replay_payload(item, _parent=_parent, _key=_key) for item in value]
    if isinstance(value, str) and _key == "content" and isinstance(_parent, dict) and _parent.get("role") == "system":
        return "[prompt omitted]"
    if isinstance(value, str) and _key == "content" and len(value) > 3000:
        return value[:2900].rstrip() + f"\n...[truncated {len(value) - 2900} chars]"
    return value


def truncate_replay_payload(value: Any, max_chars: int = DEFAULT_SECTION_MAX_CHARS) -> Any:
    if isinstance(value, dict):
        return {key: truncate_replay_payload(item, max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [truncate_replay_payload(item, max_chars) for item in value]
    if isinstance(value, str) and len(value) > max_chars:
        return value[: max_chars - 100].rstrip() + f"\n...[truncated {len(value) - max_chars + 100} chars]"
    return value


def summarize_large_payload(value: Any, max_chars: int = 2000) -> dict:
    text = json.dumps(sanitize_replay_payload(value), ensure_ascii=False, default=str)
    return {
        "type": type(value).__name__,
        "char_count": len(text),
        "truncated": len(text) > max_chars,
        "preview": text[:max_chars],
    }


def _trace_to_dict(trace: dict | AgentRunTrace | None) -> dict:
    if isinstance(trace, AgentRunTrace):
        return trace.to_dict()
    return trace if isinstance(trace, dict) else {}


def _prompt_refs(*values: Any) -> list[dict]:
    refs: dict[str, dict] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if isinstance(item, dict):
                prompt_key = str(item.get("prompt_key") or key)
                refs[prompt_key] = {
                    "prompt_key": prompt_key,
                    "prompt_version": item.get("version") or item.get("prompt_version"),
                    "prompt_hash": item.get("content_hash") or item.get("prompt_hash"),
                    "prompt_source": item.get("source") or item.get("prompt_source"),
                }
    return list(refs.values())


def _model_config_from_llm_calls(llm_calls: list[dict]) -> dict:
    first = next((item for item in llm_calls if isinstance(item, dict)), {})
    return {
        "provider_id": first.get("provider_id"),
        "provider_name": first.get("provider_name"),
        "provider_type": first.get("provider_type"),
        "model": first.get("model"),
        "temperature": first.get("temperature"),
        "max_tokens": first.get("max_tokens"),
        "response_format_type": first.get("response_format_type"),
    }


def _tool_snapshots(tool_calls: list[dict]) -> list[dict]:
    snapshots = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        snapshots.append(
            truncate_replay_payload(
                sanitize_replay_payload(
                    {
                        "tool_name": item.get("tool") or item.get("tool_name"),
                        "arguments": item.get("arguments_preview") or item.get("arguments") or {},
                        "output": item.get("output"),
                        "ok": item.get("ok"),
                        "latency_ms": item.get("latency_ms"),
                        "error_code": item.get("error_code"),
                        "error_message": item.get("error_message"),
                        "data_limitations": item.get("data_limitations") or [],
                        "output_summary": item.get("summary") or item.get("output_summary"),
                    }
                ),
                DEFAULT_SECTION_MAX_CHARS,
            )
        )
    return snapshots


def _llm_snapshots(llm_calls: list[dict], *, raw_output: Any, node_traces: list[dict]) -> list[dict]:
    raw_output_text = str(raw_output or "")
    snapshots = []
    for index, item in enumerate(llm_calls):
        if not isinstance(item, dict):
            continue
        snapshots.append(
            {
                "call_id": item.get("call_id"),
                "agent_name": item.get("agent_name"),
                "node_name": item.get("node_name"),
                "prompt_key": item.get("prompt_key"),
                "prompt_version": item.get("prompt_version"),
                "prompt_hash": item.get("prompt_hash"),
                "model": item.get("model"),
                "input_messages_summary": "system prompt omitted; see prompt_refs",
                "raw_output": truncate_replay_payload(raw_output_text, DEFAULT_SECTION_MAX_CHARS) if index == len(llm_calls) - 1 else "",
                "parsed_output": _parsed_output_summary(item.get("node_name"), node_traces),
                "usage": {
                    "prompt_tokens": item.get("prompt_tokens", 0),
                    "completion_tokens": item.get("completion_tokens", 0),
                    "total_tokens": item.get("total_tokens", 0),
                },
                "latency_ms": item.get("latency_ms"),
                "ok": item.get("ok", True),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
            }
        )
    if not snapshots and raw_output_text:
        snapshots.append(
            {
                "call_id": None,
                "input_messages_summary": "system prompt omitted; raw output from document",
                "raw_output": truncate_replay_payload(raw_output_text, DEFAULT_SECTION_MAX_CHARS),
                "parsed_output": {},
                "usage": {},
                "ok": True,
            }
        )
    return snapshots


def _parsed_output_summary(node_name: str | None, node_traces: list[dict]) -> dict:
    trace = next((item for item in node_traces if isinstance(item, dict) and item.get("node_name") == node_name), None)
    if not trace:
        return {}
    return {
        "node_name": trace.get("node_name"),
        "status": trace.get("status"),
        "fallback_used": trace.get("fallback_used"),
        "data_limitations": trace.get("data_limitations") or [],
    }


def _default_context_snapshot(document: dict) -> dict:
    return {
        "evidence_pack": document.get("evidence_pack"),
        "evidence_summary": document.get("evidence_summary"),
        "run_trace_summary": document.get("run_trace_summary"),
        "deterministic_context": document.get("deterministic_context"),
        "subagent_card_pack": document.get("subagent_card_pack"),
        "card_pack": document.get("card_pack"),
        "subagent_trace": document.get("subagent_trace"),
    }


def _final_output(document: dict) -> dict:
    excluded = {
        "evidence_pack",
        "deterministic_context",
        "run_trace",
        "graph_node_traces",
        "raw_llm_response",
        "subagent_card_pack",
        "card_pack",
        "agent_run_trace",
    }
    return {key: value for key, value in document.items() if key not in excluded}


def _is_full_prompt_field(key: str, parent: dict | None = None) -> bool:
    lowered = key.lower()
    if lowered in {"system_prompt", "default_content", "prompt"} or lowered.endswith("_prompt"):
        return True
    if lowered == "content" and isinstance(parent, dict):
        prompt_like = any(field in parent for field in ("prompt_key", "display_name", "module_name", "agent_name"))
        return prompt_like
    return False
