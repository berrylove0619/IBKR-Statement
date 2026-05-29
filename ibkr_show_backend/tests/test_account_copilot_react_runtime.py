import json
from dataclasses import dataclass

from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry, AccountCopilotSkillSpec
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.services.account_copilot.repository import AccountCopilotRepository


def action(action_type, **kwargs):
    payload = {
        "action_type": action_type,
        "thought_summary": kwargs.pop("thought_summary", "brief plan"),
        "evidence_sufficiency": kwargs.pop(
            "evidence_sufficiency",
            {"is_sufficient": action_type == "final_answer", "missing_information": [], "confidence": "medium"},
        ),
        "tool_name": None,
        "tool_arguments": {},
        "skill_name": None,
        "skill_arguments": {},
        "approval_message": None,
        "final_answer": None,
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


class FakeLLMService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def health(self):
        return {"enabled": True, "has_active_provider": True}

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if not self.responses:
            return action("final_answer", final_answer="done")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_registry(handler=None):
    registry = AccountCopilotToolRegistry()
    registry.register(
        AccountCopilotToolSpec(
            name="fake_tool",
            description="Fake readonly tool",
            schema={"parameters": {"type": "object", "properties": {}}},
            handler=handler or (lambda **kwargs: {"ok": True, "tool": "fake_tool", "arguments": kwargs, "data": {"value": 1}, "data_limitations": []}),
            category="test",
            data_sensitivity="test",
            read_only=True,
            approval_required=False,
        )
    )
    return registry


def base_state():
    return {"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "help"}


def make_skill_registry():
    registry = AccountCopilotSkillRegistry()
    registry.register(
        AccountCopilotSkillSpec(
            name="risk_deep_dive",
            display_name="Risk Deep Dive",
            description="Fake approval skill",
            input_schema={"type": "object", "properties": {"scope": {"type": "string"}}, "required": ["scope"]},
            output_schema={"type": "object"},
            data_access=["IBKR_ACCOUNT_FACTS"],
            risk_level="low",
        )
    )
    return registry


def test_runtime_calls_tool_then_final_answer() -> None:
    llm = FakeLLMService([
        action("call_tool", tool_name="fake_tool", tool_arguments={"x": 1}),
        action("final_answer", final_answer="Here is the answer."),
    ])
    result = AccountCopilotRuntime(llm, make_registry()).run(base_state())
    assert result["final_answer"] == "Here is the answer."
    assert result["actions"][0]["action_type"] == "call_tool"
    assert result["observations"][0]["ok"] is True
    assert result["tool_calls"][0]["tool_name"] == "fake_tool"


def test_tool_failure_observation_is_available_to_next_planner_round() -> None:
    llm = FakeLLMService([
        action("call_tool", tool_name="fake_tool"),
        action("final_answer", final_answer="Limited answer."),
    ])
    registry = make_registry(lambda **kwargs: {"ok": False, "tool": "fake_tool", "arguments": {}, "data": {}, "data_limitations": ["failed"]})
    result = AccountCopilotRuntime(llm, registry).run(base_state())
    assert result["observations"][0]["ok"] is False
    assert "failed" in result["observations"][0]["data_limitations"]
    second_prompt = llm.calls[1][-1]["content"]
    assert "failed" in second_prompt


def test_missing_tool_records_error_observation_without_500() -> None:
    llm = FakeLLMService([
        action("call_tool", tool_name="missing_tool"),
        action("final_answer", final_answer="Could not call it."),
    ])
    result = AccountCopilotRuntime(llm, make_registry()).run(base_state())
    assert result["observations"][0]["ok"] is False
    assert "Tool is not registered" in result["observations"][0]["data_limitations"]


def test_request_skill_approval_creates_pending_approval() -> None:
    llm = FakeLLMService([
        action(
            "request_skill_approval",
            skill_name="risk_deep_dive",
            skill_arguments={"scope": "portfolio"},
            approval_message="Need approval",
        )
    ])
    result = AccountCopilotRuntime(llm, make_registry(), skill_registry=make_skill_registry()).run(base_state())
    assert result["pending_approval"]["skill_name"] == "risk_deep_dive"
    assert result["pending_approval"]["plan_hash"]
    assert result["skill_requests"]
    assert result["metadata"]["requires_approval"] is True
    assert result["final_answer"] == "Need approval"


def test_invalid_json_repairs_once() -> None:
    llm = FakeLLMService([
        "not json",
        action("final_answer", final_answer="Repaired answer."),
    ])
    result = AccountCopilotRuntime(llm, make_registry()).run(base_state())
    assert result["final_answer"] == "Repaired answer."
    assert result["planner_output"]["repaired"] is True


def test_repair_failure_returns_fallback() -> None:
    llm = FakeLLMService(["not json", "still not json"])
    result = AccountCopilotRuntime(llm, make_registry()).run(base_state())
    assert "未能解析" in result["final_answer"]
    assert result["metadata"]["fallback_used"] is True


def test_max_rounds_returns_fallback() -> None:
    llm = FakeLLMService([
        action("call_tool", tool_name="fake_tool"),
        action("call_tool", tool_name="fake_tool"),
    ])
    result = AccountCopilotRuntime(llm, make_registry(), max_rounds=2).run(base_state())
    assert "最大工具调用轮数" in result["final_answer"]
    assert len(result["observations"]) == 2


def test_long_observation_is_truncated() -> None:
    registry = make_registry(lambda **kwargs: {"ok": True, "tool": "fake_tool", "arguments": {}, "data": {"blob": "x" * 500}, "data_limitations": []})
    llm = FakeLLMService([
        action("call_tool", tool_name="fake_tool"),
        action("final_answer", final_answer="done"),
    ])
    result = AccountCopilotRuntime(llm, registry, max_observation_chars=80).run(base_state())
    assert "truncated_json" in result["observations"][0]["data"]
    assert "Observation was truncated by Account Copilot runtime." in result["observations"][0]["data_limitations"]


@dataclass
class DummySettings:
    es_copilot_session_index: str = "sessions"
    es_copilot_message_index: str = "messages"
    es_copilot_run_index: str = "runs"
    es_copilot_memory_index: str = "memories"


class StubES:
    def __init__(self):
        self.docs = {}

    def create_index_if_missing(self, index, body): self.docs.setdefault(index, {})
    def index_document(self, index, id, document):
        self.docs.setdefault(index, {})[id] = dict(document)
        return {"ok": True}
    def get(self, index, id):
        doc = self.docs.get(index, {}).get(id)
        return {"_source": dict(doc)} if doc else None
    def search(self, index, body): return {"hits": {"hits": []}}


def test_repository_saves_react_trace_fields() -> None:
    repo = AccountCopilotRepository(StubES(), DummySettings())
    run = repo.create_run("s1", "m1", "hello")
    saved = repo.mark_run_completed(
        run["id"],
        "am1",
        "answer",
        payload={
            "planner_output": {"round": 1},
            "actions": [{"id": "act"}],
            "observations": [{"id": "obs"}],
            "tool_calls": [{"id": "tool"}],
            "memory_snapshot": {"x": 1},
        },
    )
    assert saved["actions"] == [{"id": "act"}]
    assert saved["observations"] == [{"id": "obs"}]
    assert saved["tool_calls"] == [{"id": "tool"}]
    assert saved["planner_output"] == {"round": 1}
