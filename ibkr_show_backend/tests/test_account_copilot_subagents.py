from __future__ import annotations

import json

from app.agents.account_copilot.planner_prompts import SYSTEM_PROMPT, build_planner_messages
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry, AccountCopilotSubAgentSpec, build_default_subagent_registry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.services.account_copilot.subagent_service import AccountCopilotSubAgentService


def planner_action(action_type: str, **kwargs) -> str:
    payload = {
        "action_type": action_type,
        "thought_summary": kwargs.pop("thought_summary", "brief plan"),
        "evidence_sufficiency": kwargs.pop("evidence_sufficiency", {"is_sufficient": False, "missing_information": [], "confidence": "medium"}),
        "tool_name": None,
        "tool_arguments": {},
        "skill_name": None,
        "skill_arguments": {},
        "subagent_name": None,
        "subagent_arguments": {},
        "approval_message": None,
        "final_answer": None,
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


class FakeLLMService:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def health(self):
        return {"enabled": True}

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.responses.pop(0) if self.responses else planner_action("final_answer", final_answer="done", evidence_sufficiency={"is_sufficient": True, "missing_information": [], "confidence": "medium"})


def make_subagent_spec(handler=None) -> AccountCopilotSubAgentSpec:
    return AccountCopilotSubAgentSpec(
        name="public_market_research_subagent",
        display_name="公开市场研究子Agent",
        description="公开市场研究",
        when_to_use=["用户问题需要公开市场研究"],
        when_not_to_use=["用户问题可以由已注册 Skill 直接解决"],
        input_schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "minLength": 1},
                "question": {"type": "string", "minLength": 1},
                "intent": {"type": ["string", "null"]},
            },
            "required": ["symbol", "question"],
            "additionalProperties": False,
        },
        output_contract={"type": "object", "required_fields": ["summary"]},
        read_only=True,
        approval_required=False,
        data_access=["LONGBRIDGE_PUBLIC_MARKET"],
        risk_level="low",
        handler=handler or (lambda **kwargs: {"ok": True, "summary": "研究完成", "key_facts": [], "missing_information": [], "data_limitations": []}),
    )


def make_subagent_registry(handler=None) -> AccountCopilotSubAgentRegistry:
    registry = AccountCopilotSubAgentRegistry()
    registry.register(make_subagent_spec(handler))
    return registry


def test_subagent_registry_exposes_public_market_research_card() -> None:
    registry = build_default_subagent_registry(object())
    items = registry.to_prompt_items()
    card = next(item for item in items if item["name"] == "public_market_research_subagent")
    assert card["when_to_use"]
    assert card["when_not_to_use"]
    assert card["approval_required"] is False
    assert card["read_only"] is True


def test_subagent_service_executes_registered_subagent() -> None:
    service = AccountCopilotSubAgentService()
    spec = make_subagent_spec(lambda **kwargs: {"ok": True, "summary": "ok", "data_limitations": []})
    result = service.execute(spec, {"symbol": "AMD.US", "question": "AMD 最近为什么大跌？"})
    assert result["ok"] is True
    assert result["data_source"] == "ACCOUNT_COPILOT_SUBAGENT"
    assert result["data"]["summary"] == "ok"


def test_subagent_service_rejects_invalid_arguments() -> None:
    service = AccountCopilotSubAgentService()
    result = service.execute(make_subagent_spec(), {"symbol": "AMD.US"})
    assert result["ok"] is False
    assert result["metadata"]["error_code"] == "SUBAGENT_INVALID_ARGUMENT"


def test_runtime_handles_delegate_to_subagent_action() -> None:
    service = AccountCopilotSubAgentService()
    registry = make_subagent_registry(lambda **kwargs: {"ok": True, "summary": "压缩研究结果", "data_limitations": [], "key_facts": [{"fact": "x"}]})
    llm = FakeLLMService([
        planner_action(
            "delegate_to_subagent",
            subagent_name="public_market_research_subagent",
            subagent_arguments={"symbol": "AMD.US", "question": "AMD 最近为什么大跌？"},
        ),
        planner_action("final_answer", final_answer="基于子 Agent 结果回答。", evidence_sufficiency={"is_sufficient": True, "missing_information": [], "confidence": "medium"}),
    ])
    result = AccountCopilotRuntime(
        llm,
        AccountCopilotToolRegistry(),
        subagent_registry=registry,
        subagent_service=service,
    ).run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "AMD 最近为什么大跌？"})
    assert result["observations"][0]["observation_type"] == "subagent_result"
    assert result["observations"][0]["subagent_name"] == "public_market_research_subagent"
    assert result["observations"][0]["ok"] is True
    second_prompt = llm.calls[1][-1]["content"]
    assert "subagent_result" in second_prompt
    assert "压缩研究结果" in second_prompt


def test_delegate_to_unknown_subagent_returns_observation_error() -> None:
    llm = FakeLLMService([
        planner_action("delegate_to_subagent", subagent_name="missing_subagent", subagent_arguments={"symbol": "AMD.US", "question": "why"}),
        planner_action("final_answer", final_answer="无法委托。", evidence_sufficiency={"is_sufficient": True, "missing_information": [], "confidence": "low"}),
    ])
    result = AccountCopilotRuntime(
        llm,
        AccountCopilotToolRegistry(),
        subagent_registry=AccountCopilotSubAgentRegistry(),
        subagent_service=AccountCopilotSubAgentService(),
    ).run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "AMD"})
    observation = result["observations"][0]
    assert observation["ok"] is False
    assert observation["observation_type"] == "subagent_result"
    assert observation["metadata"]["error_code"] == "SUBAGENT_UNKNOWN"


def test_planner_prompt_contains_skill_first_subagent_second_policy() -> None:
    assert "Skill 优先" in SYSTEM_PROMPT
    assert "不要用 SubAgent 替代 Skill" in SYSTEM_PROMPT
    assert "如果没有合适 Skill" in SYSTEM_PROMPT
    messages = build_planner_messages(
        {"user_input": "AMD 最近为什么大跌？"},
        AccountCopilotToolRegistry(),
        [],
        [],
        subagent_registry=make_subagent_registry(),
    )
    payload = messages[-1]["content"]
    assert "available_subagents" in payload
    assert "public_market_research_subagent" in payload
