import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry, AccountCopilotSubAgentSpec
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.api.deps import (
    get_account_copilot_event_bus,
    get_account_copilot_repository,
    get_account_copilot_run_service,
    get_account_copilot_subagent_registry,
    get_account_copilot_subagent_service,
    get_llm_service,
    require_authenticated_session,
)
from app.main import app
from app.services.account_copilot import (
    AccountCopilotEventBus,
    AccountCopilotRepository,
    AccountCopilotRunService,
    AccountCopilotSubAgentService,
)
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
        "subagent_name": None,
        "subagent_arguments": {},
        "approval_message": None,
        "final_answer": None,
    }
    payload.update(kwargs)
    return json.dumps(payload)


def make_infra():
    es = StubES()
    settings = DummySettings()
    bus = AccountCopilotEventBus(AccountCopilotEventRepository(es, settings))
    repo = AccountCopilotRepository(es, settings)
    run_service = AccountCopilotRunService(repo)
    return es, settings, bus, repo, run_service


def make_subagent_registry(read_only=True, handler=None):
    registry = AccountCopilotSubAgentRegistry()
    registry.register(AccountCopilotSubAgentSpec(
        name="public_market_research",
        display_name="Public Market Research",
        description="research",
        when_to_use=["research a stock"],
        when_not_to_use=["trade execution"],
        input_schema={"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"], "additionalProperties": False},
        output_contract={"type": "object"},
        handler=handler or (lambda symbol: {"ok": True, "data": {"summary": f"Research for {symbol}", "price": 150.0}, "data_limitations": []}),
        read_only=read_only,
        approval_required=False,
    ))
    return registry


def test_subagent_started_and_finished_events() -> None:
    _es, _settings, bus, _repo, _run_service = make_infra()
    subagent_registry = make_subagent_registry()
    subagent_service = AccountCopilotSubAgentService()
    runtime = AccountCopilotRuntime(
        FakeLLM([
            action("delegate_to_subagent", subagent_name="public_market_research", subagent_arguments={"symbol": "AAPL"}),
            action("final_answer", final_answer="AAPL research complete"),
        ]),
        AccountCopilotToolRegistry(),
        event_bus=bus,
        subagent_registry=subagent_registry,
        subagent_service=subagent_service,
    )
    result = runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "research AAPL"})
    types = [event["event_type"] for event in bus.repository.list_events("r1")]
    assert "subagent_started" in types
    assert "subagent_finished" in types
    assert "subagent_failed" not in types
    assert result["final_answer"] is not None
    assert len(result["errors"]) == 0


def test_subagent_failed_event() -> None:
    _es, _settings, bus, _repo, _run_service = make_infra()
    def failing_handler(symbol):
        raise RuntimeError("subagent execution exploded")
    subagent_registry = make_subagent_registry(handler=failing_handler)
    subagent_service = AccountCopilotSubAgentService()
    runtime = AccountCopilotRuntime(
        FakeLLM([
            action("delegate_to_subagent", subagent_name="public_market_research", subagent_arguments={"symbol": "AAPL"}),
            action("final_answer", final_answer="subagent failed, here is a fallback"),
        ]),
        AccountCopilotToolRegistry(),
        event_bus=bus,
        subagent_registry=subagent_registry,
        subagent_service=subagent_service,
    )
    result = runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "research AAPL"})
    events = bus.repository.list_events("r1")
    types = [event["event_type"] for event in events]
    assert "subagent_started" in types
    assert "subagent_failed" in types
    assert "subagent_finished" not in types
    failed_event = next(e for e in events if e["event_type"] == "subagent_failed")
    assert "error_code" in failed_event.get("payload", {})


def test_subagent_started_event_has_arguments_preview() -> None:
    _es, _settings, bus, _repo, _run_service = make_infra()
    subagent_registry = make_subagent_registry()
    subagent_service = AccountCopilotSubAgentService()
    runtime = AccountCopilotRuntime(
        FakeLLM([
            action("delegate_to_subagent", subagent_name="public_market_research", subagent_arguments={"symbol": "TSLA"}),
            action("final_answer", final_answer="TSLA research done"),
        ]),
        AccountCopilotToolRegistry(),
        event_bus=bus,
        subagent_registry=subagent_registry,
        subagent_service=subagent_service,
    )
    runtime.run({"session_id": "s1", "run_id": "r1", "user_message_id": "m1", "user_input": "research TSLA"})
    events = bus.repository.list_events("r1")
    started = next(e for e in events if e["event_type"] == "subagent_started")
    payload = started.get("payload", {})
    assert payload.get("subagent_name") == "public_market_research"
    assert "arguments_preview" in payload
    assert payload["arguments_preview"].get("symbol") == "TSLA"


def test_trace_endpoint_returns_timeline_and_redacts_sensitive() -> None:
    es, settings, bus, repo, run_service = make_infra()
    session = repo.create_session("s")
    user = repo.create_message(session["id"], "user", "hello")
    run = repo.create_run(session["id"], user["id"], "hello")

    repo.mark_run_completed(
        run["id"], "am1", "final answer here",
        {
            "planner_output": {"repaired": False, "latency_ms": 120, "raw_action": {}},
            "actions": [{"id": "a1", "round": 0, "action_type": "call_tool", "tool_name": "fake_tool", "thought_summary": "thinking"}],
            "tool_calls": [{"id": "tc1", "round": 0, "tool_name": "fake_tool", "ok": True, "data": "secret"}],
            "observations": [{"id": "obs1", "round": 0, "observation_type": "tool_result", "ok": True, "data_summary": "ok"}],
        },
    )

    bus.publish(run["id"], session["id"], "planner_started", {"round": 0})
    bus.publish(run["id"], session["id"], "planner_finished", {"round": 0, "action_type": "call_tool"})
    bus.publish(run["id"], session["id"], "tool_started", {"tool_name": "fake_tool", "round": 0})
    bus.publish(run["id"], session["id"], "tool_finished", {"tool_name": "fake_tool", "round": 0})
    bus.publish(run["id"], session["id"], "final_answer", {"content": "final answer here"})
    bus.publish(run["id"], session["id"], "run_completed", {})

    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[get_account_copilot_run_service] = lambda: run_service
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM([])
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.get(f"/api/agent/account-copilot/runs/{run['id']}/trace")
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run["id"]
        assert data["status"] == "completed"
        assert len(data["timeline"]) > 0
        assert len(data["events"]) > 0

        node_types = [n["node_type"] for n in data["timeline"]]
        assert "planner" in node_types
        assert "tool" in node_types
        assert "final_answer" in node_types

        # Sensitive fields should be redacted from tool_call payload
        for node in data["timeline"]:
            if node["node_type"] == "tool":
                assert "data" not in node.get("payload", {})

        # Events should have sensitive fields redacted
        for event in data["events"]:
            payload = event.get("payload", {})
            for key in ("token", "api_key", "password", "secret", "reasoning", "thinking", "chain_of_thought"):
                assert key not in payload
    finally:
        app.dependency_overrides.clear()


def test_trace_endpoint_404_for_missing_run() -> None:
    es, settings, bus, repo, run_service = make_infra()
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[get_account_copilot_run_service] = lambda: run_service
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM([])
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.get("/api/agent/account-copilot/runs/nonexistent/trace")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_trace_timeline_no_nested_es_mapping_dependency() -> None:
    """Timeline is built from run payload + events list, not from deep ES nested field queries."""
    es, settings, bus, repo, run_service = make_infra()
    session = repo.create_session("s")
    user = repo.create_message(session["id"], "user", "hello")
    run = repo.create_run(session["id"], user["id"], "hello")

    repo.mark_run_completed(
        run["id"], "am1", "answer",
        {
            "planner_output": {"repaired": False, "latency_ms": 50},
            "actions": [
                {"id": "a1", "round": 0, "action_type": "delegate_to_subagent", "subagent_name": "public_market_research", "subagent_arguments": {"symbol": "AMD"}},
            ],
            "observations": [
                {"id": "obs1", "round": 0, "observation_type": "subagent_result", "ok": True, "subagent_name": "public_market_research", "data_summary": "AMD research data", "data_limitations": []},
            ],
        },
    )

    bus.publish(run["id"], session["id"], "subagent_started", {"round": 0, "subagent_name": "public_market_research", "arguments_preview": {"symbol": "AMD"}})
    bus.publish(run["id"], session["id"], "subagent_finished", {"round": 0, "subagent_name": "public_market_research", "ok": True, "latency_ms": 1234, "data_summary": "AMD research data", "data_limitations": []})
    bus.publish(run["id"], session["id"], "final_answer", {"content": "answer"})
    bus.publish(run["id"], session["id"], "run_completed", {})

    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_event_bus] = lambda: bus
    app.dependency_overrides[get_account_copilot_run_service] = lambda: run_service
    app.dependency_overrides[get_llm_service] = lambda: FakeLLM([])
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    client = TestClient(app)
    try:
        response = client.get(f"/api/agent/account-copilot/runs/{run['id']}/trace")
        assert response.status_code == 200
        data = response.json()
        timeline = data["timeline"]

        subagent_nodes = [n for n in timeline if n["node_type"] == "subagent"]
        assert len(subagent_nodes) >= 2  # started + finished

        obs_nodes = [n for n in timeline if n["node_type"] == "observation"]
        assert len(obs_nodes) >= 1
        assert obs_nodes[0]["label"].startswith("SubAgent Result")

        # Verify no raw_data/data deep nesting in timeline payloads
        for node in timeline:
            payload_str = json.dumps(node.get("payload", {}))
            # Should not contain deeply nested observation.data.summary raw objects
            assert '"raw_data"' not in payload_str
    finally:
        app.dependency_overrides.clear()
