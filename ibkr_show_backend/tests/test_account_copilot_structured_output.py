import json

from app.agents.account_copilot import planner_prompts
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry


def planner_action(action_type: str, **kwargs) -> str:
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


def after_approval_answer(final_answer: str = "基于 Skill 结果，AMD 风险需要关注。", **kwargs) -> str:
    payload = {
        "final_answer": final_answer,
        "confidence": kwargs.pop("confidence", "medium"),
        "data_limitations": kwargs.pop("data_limitations", []),
        "evidence_used": kwargs.pop("evidence_used", ["risk_assessment_skill"]),
    }
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


class FakeLLMService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def health(self):
        return {"enabled": True, "has_active_provider": True}

    def get_active_provider(self):
        return type("Provider", (), {"name": "deepseek", "default_model": "deepseek-v4-flash"})()

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if not self.responses:
            return after_approval_answer()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeMonitoringService:
    def __init__(self):
        self.llm_calls = []

    def record_llm_call(self, **kwargs):
        self.llm_calls.append(kwargs)


def base_state() -> dict:
    return {
        "session_id": "session-1",
        "run_id": "run-1",
        "id": "run-1",
        "user_message_id": "message-1",
        "user_input": "目前我的 AMD 持仓有哪些潜在的风险",
        "messages": [],
    }


def skill_observation(data: dict | None = None) -> dict:
    return {
        "id": "obs-skill",
        "observation_type": "skill_result",
        "skill_name": "risk_assessment_skill",
        "ok": True,
        "data": data
        or {
            "risk_level": "medium",
            "summary": "AMD 仓位风险中等。",
            "key_risks": ["仓位集中度", "半导体周期波动"],
            "data_limitations": ["公开市场数据存在延迟"],
            "confidence": "medium",
        },
        "data_summary": "risk summary",
        "data_limitations": [],
    }


def approval_state_without_run_id() -> dict:
    return {
        "id": "run-approval-1",
        "session_id": "session-approval-1",
        "user_input": "目前我的 AMD 持仓有哪些潜在的风险",
        "pending_approval": {
            "approval_id": "approval-1",
            "run_id": "run-approval-1",
            "session_id": "session-approval-1",
            "skill_name": "risk_assessment_skill",
            "skill_arguments": {"symbol": "AMD"},
        },
        "observations": [],
        "messages": [],
    }


def test_planner_uses_structured_runtime_for_normal_final_answer() -> None:
    llm = FakeLLMService([planner_action("final_answer", final_answer="可以回答。")])
    result = AccountCopilotRuntime(llm, AccountCopilotToolRegistry()).run(base_state())

    assert result["final_answer"] == "可以回答。"
    assert result["planner_output"]["structured_output"]["contract_name"] == "account_copilot_planner"
    assert result["planner_output"]["structured_output"]["schema_validation_passed"] is True


def test_planner_missing_fields_triggers_repair() -> None:
    llm = FakeLLMService([
        '{"action_type": "final_answer", "thought_summary": "missing schema"}',
        planner_action("final_answer", final_answer="修复后回答。"),
    ])
    result = AccountCopilotRuntime(llm, AccountCopilotToolRegistry()).run(base_state())

    assert result["final_answer"] == "修复后回答。"
    assert result["planner_output"]["repaired"] is True
    assert result["planner_output"]["structured_output"]["repair_attempts"] == 1


def test_planner_repair_failure_has_structured_error_not_llm_not_configured() -> None:
    llm = FakeLLMService(['{"action_type": "final_answer"}', '{"action_type": "final_answer"}'])
    result = AccountCopilotRuntime(llm, AccountCopilotToolRegistry()).run(base_state())

    assert "未能解析" in result["final_answer"]
    assert result["errors"][0]["code"] in {"LLM_REPAIR_SCHEMA_INVALID", "LLM_SCHEMA_INVALID"}
    assert result["errors"][0]["code"] != "LLM_NOT_CONFIGURED"


def test_planner_prompt_contains_complete_action_examples() -> None:
    messages = planner_prompts.build_planner_messages(base_state(), AccountCopilotToolRegistry(), [], [])
    content = messages[-1]["content"]

    assert "planner_action_examples" in content
    assert "ibkr_get_symbol_position" in content
    assert "risk_assessment_skill" in content
    assert "根据最新 IBKR 持仓和风险快照" in content
    assert "不要省略字段" in planner_prompts.SYSTEM_PROMPT


def test_after_approval_final_answer_uses_dedicated_schema() -> None:
    llm = FakeLLMService([after_approval_answer("基于风险评估 Skill，AMD 当前风险中等。")])
    monitoring = FakeMonitoringService()
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry(), monitoring_service=monitoring)

    result = runtime.compose_final_answer_after_approval(approval_state_without_run_id(), skill_observation())

    assert result["final_answer"] == "基于风险评估 Skill，AMD 当前风险中等。"
    structured = result["metadata"]["structured_output"]
    assert structured["contract_name"] == "account_copilot_after_approval_final_answer"
    assert structured["fallback_used"] is False
    assert monitoring.llm_calls[-1]["call_type"] == "after_approval_final_answer"
    assert monitoring.llm_calls[-1]["run_id"] == "run-approval-1"
    assert monitoring.llm_calls[-1]["session_id"] == "session-approval-1"


def test_after_approval_natural_language_repairs_successfully() -> None:
    llm = FakeLLMService([
        "基于 Skill 结果，AMD 风险中等。",
        after_approval_answer("修复后：AMD 风险中等，需关注仓位集中度。"),
    ])
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry())

    result = runtime.compose_final_answer_after_approval(approval_state_without_run_id(), skill_observation())

    assert result["final_answer"] == "修复后：AMD 风险中等，需关注仓位集中度。"
    assert result["metadata"]["structured_output"]["repaired"] is True


def test_after_approval_repair_failure_falls_back_to_readable_skill_summary() -> None:
    llm = FakeLLMService(["自然语言非 JSON", "still not json"])
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry())

    result = runtime.compose_final_answer_after_approval(approval_state_without_run_id(), skill_observation())

    assert "模型输出格式异常，已基于 Skill 结果生成保守摘要" in result["final_answer"]
    assert "仓位集中度" in result["final_answer"]
    assert "object keys=" not in result["final_answer"]
    assert "当前 LLM 不可用" not in result["final_answer"]
    assert result["metadata"]["fallback_used"] is True


def test_after_approval_schema_invalid_does_not_report_llm_unavailable() -> None:
    llm = FakeLLMService(['{"confidence": "medium"}', '{"confidence": "medium"}'])
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry())

    result = runtime.compose_final_answer_after_approval(approval_state_without_run_id(), skill_observation())

    structured = result["metadata"]["structured_output"]
    assert structured["initial_error_code"] == "LLM_SCHEMA_INVALID"
    assert "当前 LLM 不可用" not in result["final_answer"]
    assert "模型输出字段不完整" in result["final_answer"] or "模型输出格式异常" in result["final_answer"]


def test_risk_assessment_fallback_is_readable_chinese_summary() -> None:
    llm = FakeLLMService(["bad", "bad again"])
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry())

    result = runtime.compose_final_answer_after_approval(
        approval_state_without_run_id(),
        skill_observation(
            {
                "risk_level": "high",
                "key_risks": ["单一标的集中度高", "行业波动"],
                "data_limitations": ["缺少实时新闻"],
                "confidence": "medium",
            }
        ),
    )

    assert "风险等级：high" in result["final_answer"]
    assert "主要风险包括：单一标的集中度高、行业波动" in result["final_answer"]
    assert "缺少实时新闻" in result["final_answer"]
    assert "object keys=" not in result["final_answer"]


class FakeMonitoringServiceWithSO:
    def __init__(self):
        self.llm_calls = []
        self.so_events = []

    def record_llm_call(self, **kwargs):
        self.llm_calls.append(kwargs)

    def record_structured_output_event(self, metadata):
        self.so_events.append(metadata)


def test_structured_output_runtime_receives_monitoring_service() -> None:
    monitoring = FakeMonitoringServiceWithSO()
    llm = FakeLLMService([planner_action("final_answer", final_answer="可以回答。")])
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry(), monitoring_service=monitoring)
    runtime.run(base_state())

    planner_events = [e for e in monitoring.so_events if e.get("contract_name") == "account_copilot_planner"]
    assert len(planner_events) >= 1
    assert planner_events[0]["ok"] is True


def test_planner_structured_output_metric_has_run_ids() -> None:
    monitoring = FakeMonitoringServiceWithSO()
    llm = FakeLLMService([planner_action("final_answer", final_answer="可以回答。")])
    state = base_state()
    state["run_id"] = "run-abc"
    state["session_id"] = "sess-xyz"
    state["user_message_id"] = "msg-123"
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry(), monitoring_service=monitoring)
    runtime.run(state)

    planner_events = [e for e in monitoring.so_events if e.get("contract_name") == "account_copilot_planner"]
    assert len(planner_events) >= 1
    event = planner_events[0]
    assert event["run_id"] == "run-abc"
    assert event["session_id"] == "sess-xyz"
    assert event["task_id"] == "msg-123"


def test_after_approval_metric_has_run_ids() -> None:
    monitoring = FakeMonitoringServiceWithSO()
    llm = FakeLLMService([after_approval_answer("基于 Skill 结果，AMD 风险中等。")])
    state = {
        "id": "run-approval-2",
        "session_id": "session-approval-2",
        "user_input": "AMD 风险",
        "pending_approval": {
            "approval_id": "approval-2",
            "run_id": "run-approval-2",
            "session_id": "session-approval-2",
            "skill_name": "risk_assessment_skill",
            "skill_arguments": {"symbol": "AMD"},
        },
        "observations": [],
        "messages": [],
    }
    runtime = AccountCopilotRuntime(llm, AccountCopilotToolRegistry(), monitoring_service=monitoring)
    runtime.compose_final_answer_after_approval(state, skill_observation())

    events = [e for e in monitoring.so_events if e.get("contract_name") == "account_copilot_after_approval_final_answer"]
    assert len(events) >= 1
    event = events[0]
    assert event["run_id"] == "run-approval-2"
    assert event["session_id"] == "session-approval-2"
    assert event["ok"] is True

