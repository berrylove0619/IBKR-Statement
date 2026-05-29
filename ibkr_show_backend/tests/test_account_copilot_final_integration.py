import json
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry, AccountCopilotSkillSpec
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.api.deps import (
    get_account_copilot_demo_service,
    get_account_copilot_event_bus,
    get_account_copilot_memory_service,
    get_account_copilot_repository,
    get_account_copilot_skill_registry,
    get_account_copilot_tool_registry,
    get_llm_service,
    require_authenticated_session,
)
from app.api.routes import account_copilot as account_copilot_routes
from app.main import app
from app.services.account_copilot import (
    AccountCopilotDemoService,
    AccountCopilotEventBus,
    AccountCopilotEventRepository,
    AccountCopilotMemoryRepository,
    AccountCopilotMemoryService,
    AccountCopilotRepository,
)


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
    account_copilot_demo_mode: bool = False


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
        return {"enabled": True, "has_active_provider": True, "active_provider": {"name": "fake"}}

    def chat(self, messages, **kwargs) -> str:
        if self.responses:
            return self.responses.pop(0)
        return planner_action("final_answer", final_answer="Demo final answer.")


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


def make_tool_registry() -> AccountCopilotToolRegistry:
    registry = AccountCopilotToolRegistry()
    for index in range(9):
        registry.register(AccountCopilotToolSpec(name=f"ibkr_demo_tool_{index}", description="ibkr", schema={"parameters": {"type": "object"}}, category="ibkr_account"))
    for index in range(6):
        registry.register(AccountCopilotToolSpec(name=f"longbridge_demo_tool_{index}", description="longbridge", schema={"parameters": {"type": "object"}}, category="longbridge_public_market"))
    return registry


def make_skill_registry() -> AccountCopilotSkillRegistry:
    registry = AccountCopilotSkillRegistry()
    for index in range(5):
        registry.register(
            AccountCopilotSkillSpec(
                name=f"skill_{index}",
                display_name=f"Skill {index}",
                description="demo skill",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object"},
                data_access=[],
                risk_level="low",
            )
        )
    return registry


def make_context(monkeypatch, demo_mode: bool = False) -> tuple[TestClient, AccountCopilotRepository, AccountCopilotMemoryRepository, AccountCopilotEventBus, DummySettings]:
    settings = DummySettings(account_copilot_demo_mode=demo_mode)
    es = StubES()
    repository = AccountCopilotRepository(es, settings)
    memory_repository = AccountCopilotMemoryRepository(es, settings)
    event_bus = AccountCopilotEventBus(AccountCopilotEventRepository(es, settings))
    memory_service = AccountCopilotMemoryService(repository, memory_repository, FakeLLM())
    demo_service = AccountCopilotDemoService(repository, memory_repository, event_bus)
    app.dependency_overrides[get_account_copilot_repository] = lambda: repository
    app.dependency_overrides[get_account_copilot_memory_service] = lambda: memory_service
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: event_bus
    app.dependency_overrides[get_account_copilot_tool_registry] = make_tool_registry
    app.dependency_overrides[get_account_copilot_skill_registry] = make_skill_registry
    app.dependency_overrides[get_account_copilot_demo_service] = lambda: demo_service
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM()
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    monkeypatch.setattr(account_copilot_routes, "get_settings", lambda: settings)
    return TestClient(app), repository, memory_repository, event_bus, settings


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_health_api_returns_status_without_secrets(monkeypatch) -> None:
    client, *_ = make_context(monkeypatch)
    try:
        response = client.get("/api/agent/account-copilot/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["checks"]["ibkr_tools"]["count"] == 9
        assert payload["checks"]["longbridge_meta_tools"]["count"] == 6
        assert payload["checks"]["skills"]["count"] == 5
        raw = json.dumps(payload).lower()
        assert "api_key" not in raw
        assert "token" not in raw
    finally:
        clear_overrides()


def test_health_passes_with_six_longbridge_meta_tools(monkeypatch) -> None:
    client, *_ = make_context(monkeypatch)
    try:
        response = client.get("/api/agent/account-copilot/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["checks"]["longbridge_meta_tools"]["ok"] is True
        assert payload["checks"]["longbridge_meta_tools"]["count"] == 6
    finally:
        clear_overrides()


def test_demo_seed_forbidden_when_demo_mode_disabled(monkeypatch) -> None:
    client, *_ = make_context(monkeypatch, demo_mode=False)
    try:
        response = client.post("/api/agent/account-copilot/demo/seed")
        assert response.status_code == 403
    finally:
        clear_overrides()


def test_demo_seed_creates_recoverable_session_messages_runs_and_memory(monkeypatch) -> None:
    client, _repo, _memory_repo, _bus, _settings = make_context(monkeypatch, demo_mode=True)
    try:
        response = client.post("/api/agent/account-copilot/demo/seed")
        assert response.status_code == 200
        payload = response.json()
        session_id = payload["session"]["id"]
        assert len(payload["messages"]) == 6
        assert len(payload["runs"]) == 3
        assert payload["runs"][-1]["status"] == "awaiting_approval"
        assert payload["memories"][0]["memory_type"] == "conversation_segment"

        assert any(item["id"] == session_id for item in client.get("/api/agent/account-copilot/sessions").json()["items"])
        assert len(client.get(f"/api/agent/account-copilot/sessions/{session_id}/messages").json()["items"]) == 6
        assert client.get(f"/api/agent/account-copilot/runs/{payload['runs'][0]['id']}").json()["status"] == "completed"
        assert len(client.get(f"/api/agent/account-copilot/sessions/{session_id}/memories").json()["items"]) == 1
        assert client.get(f"/api/agent/account-copilot/runs/{payload['runs'][1]['id']}/events/list").json()["items"]
    finally:
        clear_overrides()


def test_stream_run_completion_is_recoverable_from_messages_run_and_events(monkeypatch) -> None:
    client, _repo, _memory_repo, _bus, _settings = make_context(monkeypatch)
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "stream"}).json()
        response = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages/stream", json={"content": "hello"})
        assert response.status_code == 200
        run_id = response.json()["run"]["id"]
        messages = client.get(f"/api/agent/account-copilot/sessions/{session['id']}/messages").json()["items"]
        run = client.get(f"/api/agent/account-copilot/runs/{run_id}").json()
        events = client.get(f"/api/agent/account-copilot/runs/{run_id}/events/list").json()["items"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert run["status"] == "completed"
        assert "run_completed" in [event["event_type"] for event in events]
    finally:
        clear_overrides()


def test_awaiting_approval_demo_run_keeps_pending_approval_after_refresh(monkeypatch) -> None:
    client, *_ = make_context(monkeypatch, demo_mode=True)
    try:
        payload = client.post("/api/agent/account-copilot/demo/seed").json()
        run_id = payload["runs"][-1]["id"]
        run = client.get(f"/api/agent/account-copilot/runs/{run_id}").json()
        assert run["status"] == "awaiting_approval"
        assert run["pending_approval"]["skill_name"] == "trade_decision_entry_skill"
    finally:
        clear_overrides()


def test_cancelled_run_does_not_block_later_message_but_active_run_does(monkeypatch) -> None:
    client, repository, _memory_repo, _bus, _settings = make_context(monkeypatch)
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "cancel"}).json()
        user = repository.create_message(session["id"], "user", "first")
        active_run = repository.create_run(session["id"], user["id"], "first")
        blocked = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages/stream", json={"content": "second"})
        assert blocked.status_code == 409
        cancel = client.post(f"/api/agent/account-copilot/runs/{active_run['id']}/cancel", json={"reason": "stop"})
        assert cancel.status_code == 200
        allowed = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages/stream", json={"content": "second"})
        assert allowed.status_code == 200
    finally:
        clear_overrides()


def test_account_copilot_documentation_exists_with_core_keywords() -> None:
    text = Path(__file__).resolve().parents[2].joinpath("docs", "account_copilot.md").read_text(encoding="utf-8")
    for keyword in ["ReAct", "Skill", "Memory", "SSE", "HITL"]:
        assert keyword in text
