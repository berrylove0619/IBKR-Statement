import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.planner_prompts import build_planner_messages
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.api.deps import (
    get_account_copilot_memory_repository,
    get_account_copilot_repository,
    get_account_copilot_skill_registry,
    get_account_copilot_tool_registry,
    get_llm_service,
)
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.core.config import get_settings
from app.main import app
from app.services.account_copilot.memory_repository import AccountCopilotMemoryRepository
from app.services.account_copilot.memory_service import AccountCopilotMemoryService
from app.services.account_copilot.repository import AccountCopilotRepository


@dataclass
class DummySettings:
    es_copilot_session_index: str = "copilot-session-index"
    es_copilot_message_index: str = "copilot-message-index"
    es_copilot_run_index: str = "copilot-run-index"
    es_copilot_memory_index: str = "copilot-memory-index"


class StubESClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, dict]] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        self.documents.setdefault(index, {})

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.documents.setdefault(index, {})[id] = dict(document)
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        document = self.documents.get(index, {}).get(id)
        return {"_source": dict(document)} if document else None

    def search(self, index: str, body: dict) -> dict:
        values = list(self.documents.get(index, {}).values())
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        for item in filters:
            for key, expected in (item.get("term") or {}).items():
                values = [value for value in values if value.get(key) == expected]
        for sort_item in reversed(body.get("sort", [])):
            key, config = next(iter(sort_item.items()))
            values.sort(key=lambda item: item.get(key) or "", reverse=config.get("order") == "desc")
        return {"hits": {"hits": [{"_source": dict(item)} for item in values[: body.get("size", 20)]]}}


class FakeLLMService:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls = []

    def health(self):
        return {"enabled": True}

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return json.dumps(
            {
                "summary": "这段会话主要讨论 AMD 仓位风险和是否减仓。",
                "symbols": ["AMD"],
                "topics": ["risk", "position_sizing"],
                "user_intent": "评估 AMD 仓位集中度",
                "important_facts": ["用户关注半导体仓位集中风险"],
                "user_preferences": ["用户倾向长期持有"],
                "open_questions": ["是否需要给出具体减仓方案"],
                "tool_facts": [{"tool": "ibkr_get_symbol_position", "symbol": "AMD", "fact_summary": "AMD 是主要持仓之一"}],
                "skill_facts": [],
                "non_compressible_constraints": ["涉及交易建议时必须说明风险"],
            },
            ensure_ascii=False,
        )


def final_answer() -> str:
    return json.dumps(
        {
            "action_type": "final_answer",
            "thought_summary": "answer",
            "evidence_sufficiency": {"is_sufficient": True, "missing_information": [], "confidence": "medium"},
            "tool_name": None,
            "tool_arguments": {},
            "skill_name": None,
            "skill_arguments": {},
            "approval_message": None,
            "final_answer": "ok",
        },
        ensure_ascii=False,
    )


def _service(llm: FakeLLMService | None = None):
    settings = DummySettings()
    es = StubESClient()
    repo = AccountCopilotRepository(es, settings)
    memory_repo = AccountCopilotMemoryRepository(es, settings)
    return repo, memory_repo, AccountCopilotMemoryService(repo, memory_repo, llm or FakeLLMService())


def _seed_messages(repo: AccountCopilotRepository, session_id: str, count: int) -> list[dict]:
    messages = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        content = "AMD risk and position sizing" if index < 8 else f"recent message {index}"
        messages.append(repo.create_message(session_id, role, content, run_id=None))
    repo.touch_session(session_id, message_count_delta=count, last_message_at=messages[-1]["created_at"])
    return messages


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post("/api/auth/login", json={"username": settings.auth_username, "password": settings.auth_password})
    assert response.status_code == 200


def test_load_context_without_memory_returns_recent_messages_and_empty_memories() -> None:
    repo, _memory_repo, service = _service()
    session = repo.create_session("memory")
    _seed_messages(repo, session["id"], 3)
    context = service.load_context_for_run(session["id"], "AMD 风险")
    assert len(context["recent_messages"]) == 3
    assert context["retrieved_memories"] == []
    assert context["memory_snapshot"]["retrieved_memory_count"] == 0


def test_maybe_compress_session_creates_memory_and_updates_session_summary() -> None:
    repo, memory_repo, service = _service()
    session = repo.create_session("memory")
    messages = _seed_messages(repo, session["id"], 14)
    result = service.maybe_compress_session(session["id"])
    assert result["compressed"] is True
    memories = memory_repo.list_memories(session["id"], limit=10)
    assert len(memories) == 1
    saved_session = repo.get_session(session["id"])
    assert saved_session["compressed_until_message_id"] == memories[0]["message_end_id"]
    assert "AMD 仓位风险" in saved_session["rolling_summary"]
    assert len(repo.list_messages(session["id"], limit=100)) == len(messages)


def test_retrieve_relevant_memories_by_symbol_and_topic() -> None:
    repo, memory_repo, service = _service()
    session = repo.create_session("memory")
    memory_repo.create_memory(
        session["id"],
        "conversation_segment",
        {
            "summary": "AMD risk discussion",
            "symbols": ["AMD"],
            "topics": ["risk"],
            "user_intent": "risk review",
        },
    )
    assert service.retrieve_relevant_memories(session["id"], "AMD 怎么看", limit=8)[0]["symbols"] == ["AMD"]
    assert service.retrieve_relevant_memories(session["id"], "账户 risk 有没有问题", limit=8)[0]["topics"] == ["risk"]


def test_invalid_memory_json_does_not_break_send_message() -> None:
    settings = DummySettings()
    es = StubESClient()
    repo = AccountCopilotRepository(es, settings)
    memory_repo = AccountCopilotMemoryRepository(es, settings)
    llm = FakeLLMService([final_answer(), "not json"])
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_memory_repository] = lambda: memory_repo
    app.dependency_overrides[get_llm_service] = lambda: llm
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: AccountCopilotToolRegistry()
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: AccountCopilotSkillRegistry()
    client = TestClient(app)
    try:
        _login(client)
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "memory"}).json()
        _seed_messages(repo, session["id"], 10)
        response = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages", json={"content": "AMD risk?"})
        assert response.status_code == 200
        assert response.json()["run"]["metadata"]["memory_update_error"]
    finally:
        app.dependency_overrides.clear()


def test_llm_unavailable_during_memory_update_does_not_500() -> None:
    class BrokenMemoryLLM(FakeLLMService):
        def chat(self, messages, **kwargs):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return final_answer()
            raise RuntimeError("llm unavailable")

    settings = DummySettings()
    es = StubESClient()
    repo = AccountCopilotRepository(es, settings)
    memory_repo = AccountCopilotMemoryRepository(es, settings)
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_memory_repository] = lambda: memory_repo
    app.dependency_overrides[get_llm_service] = lambda: BrokenMemoryLLM()
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: AccountCopilotToolRegistry()
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: AccountCopilotSkillRegistry()
    client = TestClient(app)
    try:
        _login(client)
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "memory"}).json()
        _seed_messages(repo, session["id"], 10)
        response = client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages", json={"content": "AMD risk?"})
        assert response.status_code == 200
        assert "memory_update_error" in response.json()["run"]["metadata"]
    finally:
        app.dependency_overrides.clear()


def test_planner_prompt_includes_memory_layers() -> None:
    messages = build_planner_messages(
        {
            "user_input": "AMD risk?",
            "retrieved_memories": [{"summary": "AMD risk history"}],
            "non_compressible_constraints": ["must mention risk"],
            "memory_snapshot": {"retrieved_memory_count": 1},
        },
        AccountCopilotToolRegistry(),
        [],
        [],
        AccountCopilotSkillRegistry(),
    )
    content = messages[-1]["content"]
    assert "retrieved_memories" in content
    assert "non_compressible_constraints" in content
    assert "AMD risk history" in content


def test_list_session_memories_endpoint_returns_items() -> None:
    settings = DummySettings()
    es = StubESClient()
    repo = AccountCopilotRepository(es, settings)
    memory_repo = AccountCopilotMemoryRepository(es, settings)
    app.dependency_overrides[get_account_copilot_repository] = lambda: repo
    app.dependency_overrides[get_account_copilot_memory_repository] = lambda: memory_repo
    app.dependency_overrides[get_llm_service] = lambda: FakeLLMService()
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: AccountCopilotToolRegistry()
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: AccountCopilotSkillRegistry()
    client = TestClient(app)
    try:
        _login(client)
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "memory"}).json()
        memory_repo.create_memory(session["id"], "conversation_segment", {"summary": "AMD risk", "symbols": ["AMD"], "topics": ["risk"]})
        response = client.get(f"/api/agent/account-copilot/sessions/{session['id']}/memories")
        assert response.status_code == 200
        assert response.json()["items"][0]["summary"] == "AMD risk"
    finally:
        app.dependency_overrides.clear()
