from __future__ import annotations

import time
from typing import Any

from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentSpec


class AccountCopilotSubAgentService:
    def execute(self, spec: AccountCopilotSubAgentSpec | None, arguments: dict) -> dict:
        started = time.perf_counter()
        if spec is None:
            return self._envelope(False, "unknown", arguments, {}, ["Requested SubAgent is not registered."], {"error_code": "SUBAGENT_UNKNOWN"}, started)
        if not spec.read_only or spec.approval_required:
            return self._envelope(False, spec.name, arguments, {}, ["SubAgent is not configured as read-only without approval."], {"error_code": "SUBAGENT_NOT_ALLOWED"}, started)
        if spec.handler is None:
            return self._envelope(False, spec.name, arguments, {}, ["SubAgent handler is not available."], {"error_code": "SUBAGENT_HANDLER_UNAVAILABLE"}, started)
        validation_error = self._validate_arguments(spec.input_schema, arguments or {})
        if validation_error:
            return self._envelope(False, spec.name, arguments, {}, [validation_error], {"error_code": "SUBAGENT_INVALID_ARGUMENT"}, started)
        try:
            data = spec.handler(**(arguments or {}))
            return self._envelope(True, spec.name, arguments, data, data.get("data_limitations") if isinstance(data, dict) else [], {}, started)
        except Exception as exc:
            return self._envelope(False, spec.name, arguments, {}, [str(exc)[:500]], {"error_code": "SUBAGENT_EXECUTION_ERROR", "message": str(exc)[:500]}, started)

    def _validate_arguments(self, input_schema: dict, arguments: dict) -> str | None:
        required = input_schema.get("required") or []
        for key in required:
            if key not in arguments or arguments.get(key) in {None, ""}:
                return f"Missing required subagent argument: {key}"
        if input_schema.get("additionalProperties") is False:
            allowed = set((input_schema.get("properties") or {}).keys())
            extra = sorted(set(arguments.keys()) - allowed)
            if extra:
                return f"Unknown subagent arguments: {', '.join(extra)}"
        for key, schema in (input_schema.get("properties") or {}).items():
            if key not in arguments or arguments.get(key) is None:
                continue
            expected = schema.get("type")
            if expected == "string" and not isinstance(arguments[key], str):
                return f"SubAgent argument must be a string: {key}"
            if isinstance(expected, list) and "string" in expected and arguments[key] is not None and not isinstance(arguments[key], str):
                return f"SubAgent argument must be a string or null: {key}"
            min_length = schema.get("minLength")
            if isinstance(arguments.get(key), str) and min_length and len(arguments[key].strip()) < int(min_length):
                return f"SubAgent argument is too short: {key}"
        return None

    def _envelope(
        self,
        ok: bool,
        subagent: str,
        arguments: dict,
        data: Any,
        limitations: list[str],
        metadata: dict,
        started: float,
    ) -> dict:
        return {
            "ok": ok,
            "subagent": subagent,
            "arguments": arguments or {},
            "data": data,
            "data_source": "ACCOUNT_COPILOT_SUBAGENT",
            "data_limitations": limitations or [],
            "metadata": {
                "read_only": True,
                "approval_required": False,
                **metadata,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            },
        }
