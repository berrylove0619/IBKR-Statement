import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry, AccountCopilotSkillSpec
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.api.deps import get_account_copilot_event_bus, get_account_copilot_repository, get_llm_service, require_authenticated_session
from app.main import app
from app.services.account_copilot import (
    AccountCopilotEventBus,
    AccountCopilotMessageService,
    AccountCopilotRepository,
    AccountCopilotRunService,
    AccountCopilotSessionService,
)
from app.services.account_copilot.approval_service import AccountCopilotApprovalService
from app.services.account_copilot.event_repository import AccountCopilotEventRepository


@dataclass
class DummySettings:
    es_copilot_session_index: str = "sessions"
    es_copilot_message_index: str = "messages"
    es_copilot_run_index: str = "runs"
    es_copilot_memory_index: str = "memories"
    es_copilot_event_index: str = "events"
    auth_username: str = "admin"
    auth_password: str = "change-me"
    auth_session_secret: str = "secret"
    auth_session_max_age_seconds: int = 604800


class StubES:
    def __init__(self):
        self.docs = {}

    def create_index_if_missing(self, index, body):
        self.docs.setdefault(index, {})

    def index_document(self, index, id, document):
        self.docs.setdefault(index, {})[id] = dict(document)
        return {"ok": True}

    def get(self, index, id):
        doc = self.docs.get(index, {}).get(id)
        return {"_source": dict(doc)} if doc else None

    def search(self, index, body):
        values = list(self.docs.get(index, {}).values())
        for item in body.get("query", {}).get("bool", {}).get("filter", []):
            for key, expected in (item.get("term") or {}).items():
                values = [value for value in values if value.get(key) == expected]
        for sort_item in reversed(body.get("sort", [])):
            key, config = next(iter(sort_item.items()))
            values.sort(key=lambda value: value.get(key) or 0, reverse=config.get("order") == "desc")
        return {"hits": {"hits": [{"_source": dict(value)} for value in values[: body.get("size", 20)]]}}


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def health(self): return {"ok": True}

    def chat(self, messages, **kwargs):
        return self.responses.pop(0)


def action(action_type, **kwargs):
    payload = {
        "action_type": action_type,
        "thought_summary": "brief",
        "evidence_sufficiency": {"is_sufficient": action_type == "final_answer", "missing_information": [], "confidence": "medium"},
        "tool_name": None,
        "tool_arguments": {},
        "skill_name": None,
        "skill_arguments": {},
        "approval_message": None,
        "final_answer": None,
    }
    payload.update(kwargs)
    return json.dumps(payload)


def make_event_bus():
    es = StubES()
    settings = DummySettings()
    return AccountCopilotEventBus(AccountCopilotEventRepository(es, settings)), es, settings


def make_tool_registry():
    registry = AccountCopilotToolRegistry()
    registry.register(
        AccountCopilotToolSpec(
            name="fake_tool",
            description="fake",
            schema={"parameters": {"type": "object", "properties": {}}},
            handler=lambda **kwargs: {"ok": True, "tool": "fake_tool", "arguments": kwargs, "data": {"value": 1}, "data_limitations": []},
            category="test",
            data_sensitivity="test",
            read_only=True,
        )
    )
    return registry


def test_event_repository_create_list_and_after_seq() -> None:
    bus, _es, _settings = make_event_bus()
    first = bus.publish("r1", "s1", "run_started", {})
    second = bus.publish("r1", "s1", "planner_started", {"round": 1})
    events = bus.repository.list_events("r1")
    assert [event["seq"] for event in events] == [first["seq"], second["seq"]]
    assert [event["event_type"] for event in bus.repository.list_events("r1", after_seq=1)] == ["planner_started"]


def test_runtime_publishes_react_events() -> None:
    bus, _es, _settings = make_event_bus()
    runtime = AccountCopilotRuntime(
        FakeLLM([action("call_tool", tool_name="fake_tool"), action("final_answer", final_answer="done")]),
        make_tool_registry(),
        event_bus=bus,
    )
    runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "hello"})
    types = [event["event_type"] for event in bus.repository.list_events("r1")]
    assert "planner_started" in types
    assert "planner_finished" in types
    assert "tool_started" in types
    assert "tool_finished" in types
    assert "observation_created" in types
    assert "final_answer" in types
    assert "run_completed" in types


def test_runtime_skill_approval_event() -> None:
    bus, _es, _settings = make_event_bus()
    skills = AccountCopilotSkillRegistry()
    skills.register(
        AccountCopilotSkillSpec(
            name="risk_skill",
            display_name="Risk",
            description="risk",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object"},
            data_access=[],
            risk_level="low",
        )
    )
    runtime = AccountCopilotRuntime(
        FakeLLM([action("request_skill_approval", skill_name="risk_skill", approval_message="approve?")]),
        AccountCopilotToolRegistry(),
        skill_registry=skills,
        event_bus=bus,
    )
    runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "hello"})
    assert "skill_approval_requested" in [event["event_type"] for event in bus.repository.list_events("r1")]


def test_sse_endpoint_missing_run_returns_404() -> None:
    bus, es, settings = make_event_bus()
    repo = AccountCopilotRepository(es, settings)
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM([])
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.get("/api/agent/account-copilot/runs/missing/events")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_approval_rejected_and_approved_publish_events() -> None:
    bus, es, settings = make_event_bus()
    repo = AccountCopilotRepository(es, settings)
    session = repo.create_session("s")
    user = repo.create_message(session["id"], "user", "hello")
    run = repo.create_run(session["id"], user["id"], "hello")
    pending = {
        "approval_id": "approval_1",
        "skill_name": "risk_skill",
        "skill_display_name": "Risk",
        "skill_arguments": {},
        "approval_message": "approve?",
        "plan_hash": "",
        "status": "pending",
        "data_access": [],
    }
    from app.agents.account_copilot.approval import compute_plan_hash
    pending["plan_hash"] = compute_plan_hash(run["id"], pending["approval_id"], pending["skill_name"], {})
    repo.mark_run_awaiting_approval(run["id"], "am1", "approve?", pending, {"skill_requests": [pending]})

    class SkillService:
        def execute(self, spec, arguments, approval):
            return {"ok": True, "skill": spec.name, "arguments": {}, "data": {"summary": "ok"}, "data_limitations": [], "metadata": {}}

    skills = AccountCopilotSkillRegistry()
    skills.register(AccountCopilotSkillSpec("risk_skill", "Risk", "risk", {"type": "object", "properties": {}}, {"type": "object"}, data_access=[], risk_level="low", handler=lambda: {}))
    service = AccountCopilotApprovalService(
        AccountCopilotRunService(repo),
        AccountCopilotMessageService(repo),
        AccountCopilotSessionService(repo),
        skills,
        SkillService(),
        FakeLLM([action("final_answer", final_answer="final")]),
        AccountCopilotToolRegistry(),
        event_bus=bus,
    )
    service.handle_approval(run_id=run["id"], approval_id="approval_1", approved=True, plan_hash=pending["plan_hash"])
    service.execute_approved_skill(run["id"], "approval_1")
    types = [event["event_type"] for event in bus.repository.list_events(run["id"])]
    assert "skill_approval_approved" in types
    assert "skill_started" in types
    assert "skill_finished" in types
    assert "run_completed" in types
