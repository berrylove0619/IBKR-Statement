import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents.account_copilot.approval import compute_plan_hash
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry, AccountCopilotSkillSpec
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.api.deps import (
    get_account_copilot_event_bus,
    get_account_copilot_memory_service,
    get_account_copilot_repository,
    get_account_copilot_skill_registry,
    get_account_copilot_tool_registry,
    get_llm_service,
    require_authenticated_session,
)
from app.api.routes.account_copilot import _execute_stream_run
from app.main import app
from app.services.account_copilot import (
    AccountCopilotEventBus,
    AccountCopilotEventRepository,
    AccountCopilotMessageService,
    AccountCopilotRepository,
    AccountCopilotRunService,
    AccountCopilotSessionService,
)
from app.services.account_copilot.approval_service import AccountCopilotApprovalError, AccountCopilotApprovalService
from app.services.account_copilot.event_bus import TERMINAL_EVENTS
from app.services.account_copilot.event_sanitizer import sanitize_event_payload


@dataclass
class DummySettings:
    es_copilot_session_index: str = "sessions"
    es_copilot_message_index: str = "messages"
    es_copilot_run_index: str = "runs"
    es_copilot_memory_index: str = "memories"
    es_copilot_event_index: str = "events"
    account_copilot_run_timeout_seconds: int = 180
    account_copilot_max_react_rounds: int = 8
    account_copilot_max_event_payload_chars: int = 6000


class StubES:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict]] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        self.docs.setdefault(index, {})

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.docs.setdefault(index, {})[id] = dict(document)
        return {"ok": True}

    def get(self, index: str, id: str) -> dict | None:
        document = self.docs.get(index, {}).get(id)
        return {"_source": dict(document)} if document else None

    def search(self, index: str, body: dict) -> dict:
        values = list(self.docs.get(index, {}).values())
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        for item in filters:
            for key, expected in (item.get("term") or {}).items():
                values = [value for value in values if value.get(key) == expected]
        for sort_item in reversed(body.get("sort", [])):
            key, config = next(iter(sort_item.items()))
            values.sort(key=lambda value: value.get(key) or "", reverse=config.get("order") == "desc")
        return {"hits": {"hits": [{"_source": dict(value)} for value in values[: body.get("size", 20)]]}}


class FakeLLM:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])

    def health(self) -> dict:
        return {"ok": True}

    def chat(self, messages, **kwargs) -> str:
        if self.responses:
            return self.responses.pop(0)
        return planner_action("final_answer", final_answer="final")


class FakeSkillService:
    def __init__(self) -> None:
        self.executions: list[tuple[str, dict, dict]] = []

    def execute(self, spec, arguments: dict, approval: dict) -> dict:
        self.executions.append((spec.name, dict(arguments), dict(approval)))
        return {"ok": True, "skill": spec.name, "arguments": arguments, "data": {"summary": "ok"}, "data_limitations": [], "metadata": {}}


class FakeMemoryService:
    def load_context_for_run(self, session_id: str, user_input: str) -> dict:
        return {
            "recent_messages": [],
            "rolling_summary": "",
            "pinned_facts": {},
            "retrieved_memories": [],
            "non_compressible_constraints": [],
            "memory_snapshot": {},
        }

    def maybe_update_after_run(self, session_id: str, run_id: str) -> dict:
        return {"ok": True}


def planner_action(action_type: str, **kwargs) -> str:
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
    return json.dumps(payload, ensure_ascii=False)


def make_repo_bus() -> tuple[AccountCopilotRepository, AccountCopilotEventBus]:
    es = StubES()
    settings = DummySettings()
    repo = AccountCopilotRepository(es, settings)
    bus = AccountCopilotEventBus(AccountCopilotEventRepository(es, settings))
    return repo, bus


def make_skill_registry() -> AccountCopilotSkillRegistry:
    registry = AccountCopilotSkillRegistry()
    registry.register(
        AccountCopilotSkillSpec(
            name="risk_skill",
            display_name="Risk",
            description="risk",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object"},
            data_access=["account"],
            risk_level="low",
            handler=lambda: {},
        )
    )
    return registry


def make_approval_service(repo: AccountCopilotRepository, bus: AccountCopilotEventBus, skill_service: FakeSkillService | None = None) -> AccountCopilotApprovalService:
    return AccountCopilotApprovalService(
        AccountCopilotRunService(repo),
        AccountCopilotMessageService(repo),
        AccountCopilotSessionService(repo),
        make_skill_registry(),
        skill_service or FakeSkillService(),
        FakeLLM([planner_action("final_answer", final_answer="after skill")]),
        AccountCopilotToolRegistry(),
        event_bus=bus,
    )


def create_approval_run(repo: AccountCopilotRepository, *, expires_at: str | None = None) -> dict:
    session = repo.create_session("approval")
    user = repo.create_message(session["id"], "user", "approve?")
    run = repo.create_run(session["id"], user["id"], "approve?")
    pending = {
        "approval_id": "approval_1",
        "run_id": run["id"],
        "session_id": session["id"],
        "skill_name": "risk_skill",
        "skill_display_name": "Risk",
        "skill_arguments": {},
        "approval_message": "approve?",
        "plan_hash": "",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "data_access": ["account"],
    }
    pending["plan_hash"] = compute_plan_hash(run["id"], pending["approval_id"], pending["skill_name"], {})
    return repo.mark_run_awaiting_approval(run["id"], "assistant_1", "approve?", pending, {"skill_requests": [pending]})


def test_approval_expiry_marks_pending_expired_and_does_not_execute_skill() -> None:
    repo, bus = make_repo_bus()
    expired_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    run = create_approval_run(repo, expires_at=expired_at)
    skill_service = FakeSkillService()
    service = make_approval_service(repo, bus, skill_service)

    with pytest.raises(AccountCopilotApprovalError) as exc:
        service.handle_approval(run_id=run["id"], approval_id="approval_1", approved=True, plan_hash=run["pending_approval"]["plan_hash"])

    assert exc.value.status_code == 400
    assert exc.value.message == "Approval has expired"
    saved = repo.get_run(run["id"])
    assert saved["status"] == "completed"
    assert saved["pending_approval"]["status"] == "expired"
    assert skill_service.executions == []


def test_cancel_run_api_marks_run_cancelled_and_publishes_event() -> None:
    repo, bus = make_repo_bus()
    session = repo.create_session("cancel")
    user = repo.create_message(session["id"], "user", "stop")
    run = repo.create_run(session["id"], user["id"], "stop")
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.post(f"/api/agent/account-copilot/runs/{run['id']}/cancel", json={"reason": "stop now"})
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert response.json()["error_code"] == "USER_CANCELLED"
        assert [event["event_type"] for event in bus.repository.list_events(run["id"])] == ["run_cancelled"]
    finally:
        app.dependency_overrides.clear()


def test_cancelled_run_cannot_be_approved() -> None:
    repo, bus = make_repo_bus()
    run = create_approval_run(repo)
    repo.mark_run_cancelled(run["id"], "user stopped")
    service = make_approval_service(repo, bus)

    with pytest.raises(AccountCopilotApprovalError) as exc:
        service.handle_approval(run_id=run["id"], approval_id="approval_1", approved=True, plan_hash=run["pending_approval"]["plan_hash"])

    assert exc.value.status_code == 400


def test_terminal_events_include_run_cancelled() -> None:
    assert "run_cancelled" in TERMINAL_EVENTS


def test_event_payload_sanitizer_removes_sensitive_and_reasoning_fields() -> None:
    payload = sanitize_event_payload(
        "tool_finished",
        {
            "token": "secret",
            "api_key": "secret",
            "chain_of_thought": "hidden",
            "nested": {"authorization": "Bearer secret", "safe": "ok"},
        },
        max_chars=6000,
    )
    assert "token" not in payload
    assert "api_key" not in payload
    assert "chain_of_thought" not in payload
    assert "authorization" not in payload["nested"]
    assert payload["nested"]["safe"] == "ok"


def test_event_payload_sanitizer_truncates_large_payload() -> None:
    payload = sanitize_event_payload("tool_finished", {"data": "x" * 1000}, max_chars=120)
    assert "truncated_json" in payload
    assert payload["data_limitations"] == ["Event payload was truncated by Account Copilot."]


def test_list_run_events_api_returns_persisted_events() -> None:
    repo, bus = make_repo_bus()
    session = repo.create_session("events")
    user = repo.create_message(session["id"], "user", "hello")
    run = repo.create_run(session["id"], user["id"], "hello")
    bus.publish(run["id"], session["id"], "planner_started", {"round": 1})
    bus.publish(run["id"], session["id"], "planner_finished", {"round": 1})
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.get(f"/api/agent/account-copilot/runs/{run['id']}/events/list?after_seq=1")
        assert response.status_code == 200
        assert [item["event_type"] for item in response.json()["items"]] == ["planner_finished"]
    finally:
        app.dependency_overrides.clear()


def test_active_run_blocks_stream_send_in_same_session() -> None:
    repo, bus = make_repo_bus()
    session = repo.create_session("active")
    user = repo.create_message(session["id"], "user", "first")
    repo.create_run(session["id"], user["id"], "first")
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[get_account_copilot_memory_service] = lambda: FakeMemoryService()
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: AccountCopilotToolRegistry()
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: AccountCopilotSkillRegistry()
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM()
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages/stream", json={"content": "second"})
        assert response.status_code == 409
        assert response.json()["detail"] == "This session already has an active Account Copilot run."
    finally:
        app.dependency_overrides.clear()


def test_runtime_timeout_stops_safely() -> None:
    runtime = AccountCopilotRuntime(
        FakeLLM([planner_action("final_answer", final_answer="should not be used")]),
        AccountCopilotToolRegistry(),
        timeout_seconds=0,
    )
    state = runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "hello"})
    assert state["metadata"]["timeout"] is True
    assert state["metadata"]["error_code"] == "RUN_TIMEOUT"
    assert "最大执行时间" in state["final_answer"]


def test_cancelled_stream_run_is_not_overwritten_by_background_completion() -> None:
    repo, bus = make_repo_bus()
    session = repo.create_session("cancelled stream")
    user = repo.create_message(session["id"], "user", "hello")
    run = repo.create_run(session["id"], user["id"], "hello")
    repo.mark_run_cancelled(run["id"], "already cancelled")

    _execute_stream_run(
        session,
        user,
        run,
        "hello",
        AccountCopilotSessionService(repo),
        AccountCopilotMessageService(repo),
        AccountCopilotRunService(repo),
        FakeMemoryService(),
        AccountCopilotToolRegistry(),
        AccountCopilotSkillRegistry(),
        FakeLLM([planner_action("final_answer", final_answer="done")]),
        bus,
    )

    saved = repo.get_run(run["id"])
    assert saved["status"] == "cancelled"
    assert saved["assistant_message_id"] is None
