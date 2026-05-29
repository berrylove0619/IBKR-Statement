from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.agents.structured_output.contracts import StructuredOutputContract
from app.agents.structured_output.errors import LLM_CALL_FAILED, STRUCTURED_FALLBACK_USED, StructuredOutputError
from app.agents.structured_output.runtime import StructuredOutputRuntime
from app.services.llm_observability import LLMCallMetadata, LLMCallResult, LLMUsage


class DemoOutput(BaseModel):
    summary: str
    confidence: Literal["low", "medium", "high"]
    data_limitations: list[str] = []


class MockLLMService:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None, with_metadata: bool = True) -> None:
        self.responses = responses or []
        self.error = error
        self.with_metadata = with_metadata
        self.calls: list[dict[str, Any]] = []
        self.messages: list[list[dict[str, Any]]] = []

    def chat_with_metadata(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMCallResult:
        if not self.with_metadata:
            raise AttributeError("metadata disabled")
        self.calls.append(kwargs)
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        content = self.responses.pop(0)
        return LLMCallResult(
            content=content,
            message={"role": "assistant", "content": content},
            raw_response_metadata={},
            call_metadata=LLMCallMetadata(
                call_id=f"mock-{len(self.calls)}",
                provider_id="provider-1",
                provider_name="Provider",
                provider_type="openai_compatible",
                model="mock-model",
                call_type=kwargs.get("call_type") or "chat",
                agent_name=kwargs.get("agent_name"),
                node_name=kwargs.get("node_name"),
                latency_ms=7,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            ),
        )

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        self.calls.append(kwargs)
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def demo_contract(**overrides: Any) -> StructuredOutputContract:
    values = {
        "name": "demo_contract",
        "agent_name": "demo_agent",
        "node_name": "demo_node",
        "output_model": DemoOutput,
        "schema_hint": {"summary": "string", "confidence": "low|medium|high", "data_limitations": []},
        "examples": [{"summary": "ok", "confidence": "medium", "data_limitations": []}],
        "max_repair_attempts": 1,
    }
    values.update(overrides)
    return StructuredOutputContract(**values)


def test_parse_validate_repair_success_for_valid_json_model() -> None:
    runtime = StructuredOutputRuntime(MockLLMService())
    result = runtime.parse_validate_repair(
        '{"summary": "ok", "confidence": "high", "data_limitations": []}',
        demo_contract(),
    )

    assert result.ok is True
    assert result.payload == {"summary": "ok", "confidence": "high", "data_limitations": []}
    assert isinstance(result.model, DemoOutput)
    assert result.metadata["schema_validation_passed"] is True


def test_schema_missing_field_triggers_repair_and_succeeds() -> None:
    llm = MockLLMService(['{"summary": "fixed", "confidence": "medium", "data_limitations": []}'])
    runtime = StructuredOutputRuntime(llm)

    result = runtime.parse_validate_repair('{"summary": "broken"}', demo_contract())

    assert result.ok is True
    assert result.repaired is True
    assert result.repair_attempts == 1
    assert result.payload["confidence"] == "medium"
    assert llm.calls[0]["call_type"] == "repair"
    assert any(event["event"] == "structured_output_repair_start" for event in result.trace)


def test_repair_invalid_then_fallback_success() -> None:
    def fallback_builder(context: dict[str, Any] | None, last_error: StructuredOutputError, raw: str) -> dict[str, Any]:
        return {"summary": "fallback", "confidence": "low", "data_limitations": [last_error.error_code]}

    llm = MockLLMService(['{"summary": "still broken"}'])
    runtime = StructuredOutputRuntime(llm)

    result = runtime.parse_validate_repair(
        '{"summary": "broken"}',
        demo_contract(fallback_builder=fallback_builder),
        context={"symbol": "AMD.US"},
    )

    assert result.ok is True
    assert result.fallback_used is True
    assert result.error_code == STRUCTURED_FALLBACK_USED
    assert result.payload["summary"] == "fallback"
    assert any(event["event"] == "structured_output_fallback_used" for event in result.trace)


def test_fallback_invalid_returns_failure() -> None:
    def bad_fallback(context: dict[str, Any] | None, last_error: StructuredOutputError, raw: str) -> dict[str, Any]:
        return {"summary": "fallback without confidence"}

    llm = MockLLMService(['{"summary": "still broken"}'])
    runtime = StructuredOutputRuntime(llm)

    result = runtime.parse_validate_repair('{"summary": "broken"}', demo_contract(fallback_builder=bad_fallback))

    assert result.ok is False
    assert result.payload is None
    assert result.error_code is not None
    assert result.metadata["schema_validation_passed"] is False


def test_generate_llm_call_failed_returns_error_result() -> None:
    runtime = StructuredOutputRuntime(MockLLMService(error=RuntimeError("provider down")))

    result = runtime.generate([{"role": "user", "content": "hi"}], demo_contract())

    assert result.ok is False
    assert result.error_code == LLM_CALL_FAILED
    assert result.errors[0]["cause_type"] == "RuntimeError"
    assert any(event["event"] == "structured_output_llm_finish" and event["ok"] is False for event in result.trace)


def test_generate_success_with_markdown_wrapped_json_and_metadata() -> None:
    llm = MockLLMService(['```json\n{"summary": "ok", "confidence": "high"}\n```'])
    runtime = StructuredOutputRuntime(llm)

    result = runtime.generate(
        [{"role": "user", "content": "hi"}],
        demo_contract(),
        run_id="run-1",
        session_id="session-1",
        task_id="task-1",
    )

    assert result.ok is True
    assert result.payload["confidence"] == "high"
    assert result.metadata["llm_call_metadata"]["call_id"] == "mock-1"
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_output_model_none_only_parses_json_object() -> None:
    runtime = StructuredOutputRuntime(MockLLMService())
    contract = demo_contract(output_model=None, repair_enabled=False)

    result = runtime.parse_validate_repair('{"any": "object"}', contract)

    assert result.ok is True
    assert result.payload == {"any": "object"}
    assert result.model is None
    assert result.metadata["output_model_name"] is None


def test_trace_contains_parse_repair_fallback_events() -> None:
    def fallback_builder(context: dict[str, Any] | None, last_error: StructuredOutputError, raw: str) -> dict[str, Any]:
        return {"summary": "fallback", "confidence": "low", "data_limitations": []}

    llm = MockLLMService(["not json"])
    runtime = StructuredOutputRuntime(llm)

    result = runtime.parse_validate_repair("not json", demo_contract(fallback_builder=fallback_builder))

    events = [event["event"] for event in result.trace]
    assert "structured_output_parse_start" in events
    assert "structured_output_parse_failed" in events
    assert "structured_output_repair_start" in events
    assert "structured_output_repair_failed" in events
    assert "structured_output_fallback_used" in events
