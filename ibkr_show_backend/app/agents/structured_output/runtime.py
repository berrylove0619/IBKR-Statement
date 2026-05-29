from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.structured_output.contracts import StructuredOutputContract
from app.agents.structured_output.errors import (
    LLM_CALL_FAILED,
    LLM_REPAIR_FAILED,
    LLM_REPAIR_SCHEMA_INVALID,
    LLM_SCHEMA_INVALID,
    STRUCTURED_FALLBACK_USED,
    STRUCTURED_OUTPUT_UNKNOWN_ERROR,
    StructuredOutputError,
    preview_text,
)
from app.agents.structured_output.json_parser import extract_json_object


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StructuredOutputResult:
    ok: bool
    payload: dict[str, Any] | None
    model: BaseModel | None
    raw_response: str
    final_response: str | None = None
    repaired: bool = False
    repair_attempts: int = 0
    fallback_used: bool = False
    error_code: str | None = None
    error_message: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.model is not None:
            value["model"] = self.model.model_dump()
        return value


class StructuredOutputRuntime:
    def __init__(
        self,
        llm_service: Any,
        monitoring_service: Any | None = None,
        default_temperature: float = 0.0,
        default_max_tokens: int | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.monitoring_service = monitoring_service
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    def parse_validate_repair(
        self,
        raw_response: str,
        contract: StructuredOutputContract,
        *,
        context: dict[str, Any] | None = None,
        trace: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> StructuredOutputResult:
        events = trace if trace is not None else []
        errors: list[dict[str, Any]] = []
        raw_text = str(raw_response or "")

        parsed_result = self._parse_and_validate(raw_text, contract, events)
        if not isinstance(parsed_result, StructuredOutputError):
            payload, model = parsed_result
            self._event(events, "structured_output_success", contract=contract.name)
            result = self._result(
                ok=True,
                payload=payload,
                model=model,
                raw_response=raw_text,
                contract=contract,
                trace=events,
                errors=errors,
                schema_validation_passed=True,
                run_id=run_id,
                session_id=session_id,
                task_id=task_id,
            )
            self._record_structured_output_event(result)
            return result

        last_error = parsed_result
        errors.append(last_error.to_dict())

        final_response: str | None = None
        repaired = False
        repair_attempts = 0
        if contract.repair_enabled and contract.max_repair_attempts > 0:
            for attempt in range(1, contract.max_repair_attempts + 1):
                repair_attempts = attempt
                repair_response_or_error = self._repair(raw_text, contract, last_error, context, events, attempt)
                if isinstance(repair_response_or_error, StructuredOutputError):
                    last_error = repair_response_or_error
                    errors.append(last_error.to_dict())
                    continue
                final_response = repair_response_or_error
                repaired_result = self._parse_and_validate(final_response, contract, events, repair_attempt=attempt)
                if not isinstance(repaired_result, StructuredOutputError):
                    payload, model = repaired_result
                    repaired = True
                    self._event(events, "structured_output_success", contract=contract.name, repaired=True, repair_attempts=attempt)
                    result = self._result(
                        ok=True,
                        payload=payload,
                        model=model,
                        raw_response=raw_text,
                        final_response=final_response,
                        contract=contract,
                        trace=events,
                        errors=errors,
                        repaired=True,
                        repair_attempts=attempt,
                        schema_validation_passed=True,
                        run_id=run_id,
                        session_id=session_id,
                        task_id=task_id,
                    )
                    self._record_structured_output_event(result)
                    return result
                last_error = self._repair_validation_error(repaired_result)
                errors.append(last_error.to_dict())
                self._event(events, "structured_output_repair_failed", contract=contract.name, error_code=last_error.error_code, repair_attempt=attempt)

        if contract.fallback_enabled and contract.fallback_builder is not None:
            fallback_result = self._fallback(contract, context, last_error, raw_text, events)
            if not isinstance(fallback_result, StructuredOutputError):
                payload, model = fallback_result
                fallback_error = StructuredOutputError(
                    STRUCTURED_FALLBACK_USED,
                    f"Structured output fallback used after {last_error.error_code}: {last_error.message}",
                    raw_response_preview=raw_text,
                    cause=last_error,
                )
                self._event(events, "structured_output_fallback_used", contract=contract.name, reason=last_error.error_code)
                self._event(events, "structured_output_success", contract=contract.name, fallback_used=True)
                result = self._result(
                    ok=True,
                    payload=payload,
                    model=model,
                    raw_response=raw_text,
                    final_response=final_response,
                    contract=contract,
                    trace=events,
                    errors=errors,
                    repaired=repaired,
                    repair_attempts=repair_attempts,
                    fallback_used=True,
                    error_code=STRUCTURED_FALLBACK_USED,
                    error_message=fallback_error.message,
                    schema_validation_passed=True,
                    extra_metadata={"fallback_reason": f"{last_error.error_code}: {last_error.message}"},
                    run_id=run_id,
                    session_id=session_id,
                    task_id=task_id,
                )
                self._record_structured_output_event(result)
                return result
            last_error = fallback_result
            errors.append(last_error.to_dict())

        self._event(events, "structured_output_failed", contract=contract.name, error_code=last_error.error_code)
        result = self._result(
            ok=False,
            payload=None,
            model=None,
            raw_response=raw_text,
            final_response=final_response,
            contract=contract,
            trace=events,
            errors=errors,
            repaired=repaired,
            repair_attempts=repair_attempts,
            error_code=last_error.error_code,
            error_message=last_error.message,
            schema_validation_passed=False,
            run_id=run_id,
            session_id=session_id,
            task_id=task_id,
        )
        self._record_structured_output_event(result)
        return result

    def generate(
        self,
        messages: list[dict[str, Any]],
        contract: StructuredOutputContract,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> StructuredOutputResult:
        events: list[dict[str, Any]] = []
        self._event(events, "structured_output_llm_start", contract=contract.name, agent_name=contract.agent_name, node_name=contract.node_name)
        try:
            raw_response: str
            llm_metadata: dict[str, Any] = {}
            kwargs = {
                "temperature": self.default_temperature if temperature is None else temperature,
                "max_tokens": self.default_max_tokens if max_tokens is None else max_tokens,
                "response_format": response_format or contract.response_format,
                "call_type": "structured_output",
                "agent_name": contract.agent_name,
                "node_name": contract.node_name,
                "run_id": run_id,
                "session_id": session_id,
            }
            clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
            if hasattr(self.llm_service, "chat_with_metadata"):
                result = self.llm_service.chat_with_metadata(messages, **clean_kwargs)
                raw_response = str(getattr(result, "content", "") or "")
                call_metadata = getattr(result, "call_metadata", None)
                if call_metadata is not None and hasattr(call_metadata, "to_dict"):
                    llm_metadata = call_metadata.to_dict()
            else:
                chat_kwargs = {
                    key: value
                    for key, value in clean_kwargs.items()
                    if key in {"temperature", "max_tokens", "response_format"}
                }
                raw_response = str(self.llm_service.chat(messages, **chat_kwargs))
            self._event(events, "structured_output_llm_finish", contract=contract.name, ok=True, task_id=task_id, llm_metadata=llm_metadata)
        except Exception as exc:
            error = StructuredOutputError(
                LLM_CALL_FAILED,
                "LLM call failed before structured output parsing.",
                cause=exc,
            )
            self._event(events, "structured_output_llm_finish", contract=contract.name, ok=False, error_code=LLM_CALL_FAILED)
            self._event(events, "structured_output_failed", contract=contract.name, error_code=LLM_CALL_FAILED)
            result = self._result(
                ok=False,
                payload=None,
                model=None,
                raw_response="",
                contract=contract,
                trace=events,
                errors=[error.to_dict()],
                error_code=LLM_CALL_FAILED,
                error_message=str(exc),
                schema_validation_passed=False,
                run_id=run_id,
                session_id=session_id,
                task_id=task_id,
            )
            self._record_structured_output_event(result)
            return result

        result = self.parse_validate_repair(
            raw_response, contract, context=context, trace=events,
            run_id=run_id, session_id=session_id, task_id=task_id,
        )
        if llm_metadata := next((event.get("llm_metadata") for event in events if event.get("event") == "structured_output_llm_finish"), None):
            result.metadata["llm_call_metadata"] = llm_metadata
        return result

    def _parse_and_validate(
        self,
        raw_response: str,
        contract: StructuredOutputContract,
        trace: list[dict[str, Any]],
        *,
        repair_attempt: int | None = None,
    ) -> tuple[dict[str, Any], BaseModel | None] | StructuredOutputError:
        self._event(trace, "structured_output_parse_start", contract=contract.name, repair_attempt=repair_attempt)
        try:
            payload = extract_json_object(raw_response)
        except StructuredOutputError as exc:
            exc.repair_attempt = repair_attempt
            self._event(trace, "structured_output_parse_failed", contract=contract.name, error_code=exc.error_code, repair_attempt=repair_attempt)
            return exc

        if contract.output_model is None:
            return payload, None

        try:
            model = contract.output_model.model_validate(payload)
        except ValidationError as exc:
            error = StructuredOutputError(
                LLM_SCHEMA_INVALID,
                "LLM JSON object failed Pydantic schema validation.",
                raw_response_preview=raw_response,
                validation_error=str(exc),
                repair_attempt=repair_attempt,
                cause=exc,
            )
            self._event(trace, "structured_output_schema_failed", contract=contract.name, error_code=error.error_code, repair_attempt=repair_attempt)
            return error
        return model.model_dump(), model

    def _repair(
        self,
        raw_response: str,
        contract: StructuredOutputContract,
        error: StructuredOutputError,
        context: dict[str, Any] | None,
        trace: list[dict[str, Any]],
        attempt: int,
    ) -> str | StructuredOutputError:
        self._event(trace, "structured_output_repair_start", contract=contract.name, repair_attempt=attempt, error_code=error.error_code)
        try:
            messages = contract.build_repair_messages(raw_response=raw_response, error=error, context=context)
            kwargs = {
                "temperature": 0.0,
                "response_format": contract.response_format,
                "call_type": "repair",
                "agent_name": contract.agent_name,
                "node_name": contract.node_name,
                "disable_provider_thinking": True,
            }
            if hasattr(self.llm_service, "chat_with_metadata"):
                result = self.llm_service.chat_with_metadata(messages, **kwargs)
                repaired = str(getattr(result, "content", "") or "")
            else:
                repaired = str(self.llm_service.chat(messages, temperature=0.0, response_format=contract.response_format))
            self._event(trace, "structured_output_repair_finish", contract=contract.name, ok=True, repair_attempt=attempt)
            return repaired
        except Exception as exc:
            repair_error = StructuredOutputError(
                LLM_REPAIR_FAILED,
                "LLM repair call failed.",
                raw_response_preview=raw_response,
                validation_error=error.validation_error,
                repair_attempt=attempt,
                cause=exc,
            )
            self._event(trace, "structured_output_repair_failed", contract=contract.name, error_code=repair_error.error_code, repair_attempt=attempt)
            return repair_error

    def _fallback(
        self,
        contract: StructuredOutputContract,
        context: dict[str, Any] | None,
        last_error: StructuredOutputError,
        raw_response: str,
        trace: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], BaseModel | None] | StructuredOutputError:
        try:
            fallback_value = contract.fallback_builder(context, last_error, raw_response) if contract.fallback_builder else {}
            if isinstance(fallback_value, BaseModel):
                payload = fallback_value.model_dump()
            elif isinstance(fallback_value, dict):
                payload = fallback_value
            else:
                payload = {"value": fallback_value}

            if contract.output_model is None:
                return payload, None
            model = contract.output_model.model_validate(payload)
            return model.model_dump(), model
        except Exception as exc:
            self._event(trace, "structured_output_repair_failed", contract=contract.name, error_code=LLM_REPAIR_SCHEMA_INVALID)
            return StructuredOutputError(
                LLM_REPAIR_SCHEMA_INVALID,
                "Fallback output failed schema validation.",
                raw_response_preview=raw_response,
                validation_error=str(exc),
                cause=exc,
            )

    def _repair_validation_error(self, error: StructuredOutputError) -> StructuredOutputError:
        if error.error_code == LLM_SCHEMA_INVALID:
            return StructuredOutputError(
                LLM_REPAIR_SCHEMA_INVALID,
                "Repair output failed Pydantic schema validation.",
                raw_response_preview=error.raw_response_preview,
                validation_error=error.validation_error,
                repair_attempt=error.repair_attempt,
                cause=error.cause,
            )
        return StructuredOutputError(
            LLM_REPAIR_FAILED,
            f"Repair output failed structured parsing: {error.message}",
            raw_response_preview=error.raw_response_preview,
            validation_error=error.validation_error,
            repair_attempt=error.repair_attempt,
            cause=error.cause,
        )

    def _result(
        self,
        *,
        ok: bool,
        payload: dict[str, Any] | None,
        model: BaseModel | None,
        raw_response: str,
        contract: StructuredOutputContract,
        trace: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        final_response: str | None = None,
        repaired: bool = False,
        repair_attempts: int = 0,
        fallback_used: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
        schema_validation_passed: bool = False,
        extra_metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> StructuredOutputResult:
        metadata: dict[str, Any] = {
            "ok": ok,
            "contract_name": contract.name,
            "agent_name": contract.agent_name,
            "node_name": contract.node_name,
            "repaired": repaired,
            "repair_attempts": repair_attempts,
            "fallback_used": fallback_used,
            "error_code": error_code,
            "error_count": len(errors),
            "raw_response_preview": preview_text(raw_response, max_chars=500),
            "final_response_preview": preview_text(final_response, max_chars=500),
            "output_model_name": contract.output_model.__name__ if contract.output_model is not None else None,
            "schema_validation_passed": schema_validation_passed,
            "run_id": run_id,
            "session_id": session_id,
            "task_id": task_id,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return StructuredOutputResult(
            ok=ok,
            payload=payload,
            model=model,
            raw_response=raw_response,
            final_response=final_response,
            repaired=repaired,
            repair_attempts=repair_attempts,
            fallback_used=fallback_used,
            error_code=error_code,
            error_message=error_message,
            errors=errors,
            trace=trace,
            metadata=metadata,
        )

    def _event(self, trace: list[dict[str, Any]], event: str, **fields: Any) -> None:
        trace.append({"event": event, "created_at": utc_now_iso(), **fields})

    def _record_structured_output_event(self, result: StructuredOutputResult) -> None:
        if self.monitoring_service is None or not hasattr(self.monitoring_service, "record_structured_output_event"):
            return
        try:
            self.monitoring_service.record_structured_output_event(result.metadata)
        except Exception:
            return


def unknown_error(exc: Exception) -> StructuredOutputError:
    return StructuredOutputError(
        STRUCTURED_OUTPUT_UNKNOWN_ERROR,
        "Unknown structured output runtime error.",
        cause=exc,
    )
