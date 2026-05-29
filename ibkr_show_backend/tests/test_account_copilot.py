from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.api.deps import get_account_copilot_repository, get_account_copilot_skill_registry, get_llm_service
from app.core.config import get_settings
from app.main import app
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
            term = item.get("term", {})
            for key, expected in term.items():
                values = [value for value in values if value.get(key) == expected]

        for sort_item in reversed(body.get("sort", [])):
            key, config = next(iter(sort_item.items()))
            reverse = config.get("order") == "desc"
            values.sort(key=lambda item: item.get(key) or "", reverse=reverse)

        size = body.get("size", 20)
        return {"hits": {"hits": [{"_source": dict(item)} for item in values[:size]]}}


class DummyLLMService:
    def health(self):
        return {"enabled": True, "has_active_provider": True}

    def chat(self, messages, **kwargs):
        return """
        {
          "action_type": "final_answer",
          "thought_summary": "基础链路测试直接返回回答",
          "evidence_sufficiency": {"is_sufficient": true, "missing_information": [], "confidence": "medium"},
          "tool_name": null,
          "tool_arguments": {},
          "skill_name": null,
          "skill_arguments": {},
          "approval_message": null,
          "final_answer": "Account Copilot ReAct 基础链路已打通。"
        }
        """


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


def _client_with_repo() -> tuple[TestClient, AccountCopilotRepository]:
    repository = AccountCopilotRepository(StubESClient(), DummySettings())

    def _repo_override() -> AccountCopilotRepository:
        return repository

    app.dependency_overrides[get_account_copilot_repository] = _repo_override
    app.dependency_overrides[get_llm_service] = lambda: DummyLLMService()
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: AccountCopilotSkillRegistry()
    client = TestClient(app)
    _login(client)
    return client, repository


def test_create_session_and_list_sessions() -> None:
    client, _repository = _client_with_repo()
    try:
        response = client.post("/api/agent/account-copilot/sessions", json={"title": "账户问答"})
        assert response.status_code == 200
        session = response.json()
        assert session["title"] == "账户问答"
        assert session["status"] == "active"
        assert session["message_count"] == 0

        list_response = client.get("/api/agent/account-copilot/sessions")
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()["items"]] == [session["id"]]
    finally:
        app.dependency_overrides.clear()


def test_send_message_generates_messages_and_run() -> None:
    client, _repository = _client_with_repo()
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "Copilot"}).json()

        response = client.post(
            f"/api/agent/account-copilot/sessions/{session['id']}/messages",
            json={"content": "我的账户今天怎么样？"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user_message"]["role"] == "user"
        assert data["user_message"]["run_id"] == data["run"]["id"]
        assert data["assistant_message"]["role"] == "assistant"
        assert "Account Copilot ReAct 基础链路已打通" in data["assistant_message"]["content"]
        assert data["run"]["status"] == "completed"
        assert data["run"]["assistant_message_id"] == data["assistant_message"]["id"]
        assert data["run"]["actions"][0]["action_type"] == "final_answer"
        assert data["run"]["tool_calls"] == []
    finally:
        app.dependency_overrides.clear()


def test_list_messages_order_is_created_at_ascending() -> None:
    client, _repository = _client_with_repo()
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "Copilot"}).json()
        client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages", json={"content": "第一条"})
        client.post(f"/api/agent/account-copilot/sessions/{session['id']}/messages", json={"content": "第二条"})

        response = client.get(f"/api/agent/account-copilot/sessions/{session['id']}/messages")
        assert response.status_code == 200
        messages = response.json()["items"]
        assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[0]["content"] == "第一条"
        assert messages[2]["content"] == "第二条"
    finally:
        app.dependency_overrides.clear()


def test_get_run_detail() -> None:
    client, _repository = _client_with_repo()
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "Copilot"}).json()
        send_response = client.post(
            f"/api/agent/account-copilot/sessions/{session['id']}/messages",
            json={"content": "查询 run"},
        ).json()

        response = client.get(f"/api/agent/account-copilot/runs/{send_response['run']['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == send_response["run"]["id"]
        assert response.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()


def test_update_session_title() -> None:
    client, _repository = _client_with_repo()
    try:
        session = client.post("/api/agent/account-copilot/sessions", json={"title": "Old"}).json()
        response = client.patch(
            f"/api/agent/account-copilot/sessions/{session['id']}",
            json={"title": "New"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "New"
    finally:
        app.dependency_overrides.clear()


def test_missing_session_returns_404() -> None:
    client, _repository = _client_with_repo()
    try:
        response = client.post(
            "/api/agent/account-copilot/sessions/missing-session/messages",
            json={"content": "hello"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
