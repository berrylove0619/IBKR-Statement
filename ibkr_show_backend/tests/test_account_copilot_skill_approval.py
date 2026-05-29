import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.agents.account_copilot.skill_registry import build_default_skill_registry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.api.deps import (
    get_account_copilot_repository,
    get_account_copilot_skill_registry,
    get_account_copilot_skill_service,
    get_account_copilot_tool_registry,
    get_llm_service,
)
from app.core.config import get_settings
from app.main import app
from app.services.account_copilot.repository import AccountCopilotRepository


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
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def health(self):
        return {"enabled": True}

    def chat(self, messages, **kwargs):
        if self.responses:
            return self.responses.pop(0)
        return planner_action("final_answer", final_answer="fallback final")


class FakeSkillService:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.executions: list[tuple[str, dict, dict]] = []

    def trade_decision_entry_skill(self, symbol: str, question: str | None = None) -> dict:
        return {"summary": f"entry analysis for {symbol}", "confidence": "medium", "key_risks": ["valuation"]}

    def trade_decision_holding_skill(self, symbol: str, question: str | None = None) -> dict:
        return {"summary": f"holding analysis for {symbol}"}

    def trade_review_symbol_skill(self, symbol: str, start_date: str | None = None, end_date: str | None = None, question: str | None = None) -> dict:
        return {"summary": f"review for {symbol}"}

    def daily_position_review_skill(self, report_date: str | None = None, question: str | None = None) -> dict:
        return {"summary": f"daily review for {report_date}"}

    def risk_assessment_skill(self, question: str | None = None) -> dict:
        return {"summary": "risk assessment"}

    def execute(self, spec, arguments: dict, approval: dict) -> dict:
        self.executions.append((spec.name, dict(arguments), dict(approval)))
        if self.fail:
            return {
                "ok": False,
                "skill": spec.name,
                "arguments": arguments,
                "data": {},
                "data_source": "ACCOUNT_COPILOT_SKILL",
                "data_limitations": ["boom"],
                "metadata": {"read_only": True, "approval_id": approval["approval_id"], "error_code": "SKILL_EXECUTION_ERROR"},
            }
        return {
            "ok": True,
            "skill": spec.name,
            "arguments": arguments,
            "data": {"summary": "Skill says MU entry is not automatic.", "confidence": "medium"},
            "data_source": "ACCOUNT_COPILOT_SKILL",
            "data_limitations": [],
            "metadata": {"read_only": True, "approval_id": approval["approval_id"]},
        }


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post("/api/auth/login", json={"username": settings.auth_username, "password": settings.auth_password})
    assert response.status_code == 200


def _client(llm: FakeLLMService, skill_service: FakeSkillService | None = None) -> tuple[TestClient, FakeSkillService]:
    repository = AccountCopilotRepository(StubESClient(), DummySettings())
    skill_service = skill_service or FakeSkillService()
    app.dependency_overrides[get_account_copilot_repository] = lambda: repository
    app.dependency_overrides[get_llm_service] = lambda: llm
    app.dependency_overrides[get_account_copilot_tool_registry] = lambda: AccountCopilotToolRegistry()
    app.dependency_overrides[get_account_copilot_skill_service] = lambda: skill_service
    app.dependency_overrides[get_account_copilot_skill_registry] = lambda: build_default_skill_registry(skill_service)
    client = TestClient(app)
    _login(client)
    return client, skill_service


def _create_approval_run(client: TestClient) -> dict:
    session = client.post("/api/agent/account-copilot/sessions", json={"title": "Skill approval"}).json()
    response = client.post(
        f"/api/agent/account-copilot/sessions/{session['id']}/messages",
        json={"content": "MU 现在能不能建仓？"},
    )
    assert response.status_code == 200
    return response.json()


def test_send_message_enters_awaiting_approval_without_executing_skill() -> None:
    client, skill_service = _client(
        FakeLLMService(
            [
                planner_action(
                    "request_skill_approval",
                    skill_name="trade_decision_entry_skill",
                    skill_arguments={"symbol": "MU.US", "question": "MU 现在能不能建仓？"},
                    approval_message="建议调用【交易决策-建仓分析】Skill。是否继续？",
                )
            ]
        )
    )
    try:
        data = _create_approval_run(client)
        run = data["run"]
        assert run["status"] == "awaiting_approval"
        assert run["pending_approval"]["approval_id"]
        assert run["pending_approval"]["skill_name"] == "trade_decision_entry_skill"
        assert run["pending_approval"]["skill_arguments"]["symbol"] == "MU.US"
        assert run["pending_approval"]["plan_hash"]
        assert skill_service.executions == []
    finally:
        app.dependency_overrides.clear()


def test_approval_id_or_plan_hash_mismatch_returns_400() -> None:
    client, _skill_service = _client(
        FakeLLMService(
            [
                planner_action(
                    "request_skill_approval",
                    skill_name="trade_decision_entry_skill",
                    skill_arguments={"symbol": "MU.US"},
                    approval_message="approve?",
                )
            ]
        )
    )
    try:
        run = _create_approval_run(client)["run"]
        pending = run["pending_approval"]
        bad_id = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": "wrong", "approved": True, "plan_hash": pending["plan_hash"]},
        )
        assert bad_id.status_code == 400
        bad_hash = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": True, "plan_hash": "wrong"},
        )
        assert bad_hash.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_reject_approval_completes_run_and_prevents_repeat() -> None:
    client, skill_service = _client(
        FakeLLMService(
            [
                planner_action(
                    "request_skill_approval",
                    skill_name="trade_decision_entry_skill",
                    skill_arguments={"symbol": "MU.US"},
                    approval_message="approve?",
                )
            ]
        )
    )
    try:
        run = _create_approval_run(client)["run"]
        pending = run["pending_approval"]
        response = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": False, "plan_hash": pending["plan_hash"]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["run"]["status"] == "completed"
        assert payload["run"]["pending_approval"]["status"] == "rejected"
        assert skill_service.executions == []
        repeat = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": False, "plan_hash": pending["plan_hash"]},
        )
        assert repeat.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_approve_returns_running_immediately_then_background_executes() -> None:
    client, skill_service = _client(
        FakeLLMService(
            [
                planner_action(
                    "request_skill_approval",
                    skill_name="trade_decision_entry_skill",
                    skill_arguments={"symbol": "MU.US"},
                    approval_message="approve?",
                ),
                planner_action("final_answer", final_answer="基于 Skill 结果，MU 建仓需要谨慎。"),
            ]
        )
    )
    try:
        run = _create_approval_run(client)["run"]
        pending = run["pending_approval"]
        response = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": True, "plan_hash": pending["plan_hash"]},
        )
        assert response.status_code == 200
        payload = response.json()
        saved_run = payload["run"]
        assert saved_run["status"] == "running"
        assert saved_run["pending_approval"]["status"] == "approved"
        assert payload["assistant_message"] is None
        # Background tasks execute after response in TestClient
        assert skill_service.executions[0][0] == "trade_decision_entry_skill"
        assert skill_service.executions[0][2]["status"] == "approved"
        assert skill_service.executions[0][2]["execution_status"] == "running"
        # Verify background task completed the run
        final_run = client.get(f"/api/agent/account-copilot/runs/{run['id']}").json()
        assert final_run["status"] == "completed"
        assert final_run["pending_approval"]["status"] == "executed"
        skill_observations = [item for item in final_run["observations"] if item.get("observation_type") == "skill_result"]
        assert skill_observations
        assert skill_observations[0]["ok"] is True
        # Duplicate approval should fail
        repeat = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": True, "plan_hash": pending["plan_hash"]},
        )
        assert repeat.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_skill_failure_records_failed_observation_without_500() -> None:
    client, _skill_service = _client(
        FakeLLMService(
            [
                planner_action(
                    "request_skill_approval",
                    skill_name="trade_decision_entry_skill",
                    skill_arguments={"symbol": "MU.US"},
                    approval_message="approve?",
                ),
                planner_action("final_answer", final_answer="Skill 失败后给出有限结论。"),
            ]
        ),
        skill_service=FakeSkillService(fail=True),
    )
    try:
        run = _create_approval_run(client)["run"]
        pending = run["pending_approval"]
        response = client.post(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            json={"approval_id": pending["approval_id"], "approved": True, "plan_hash": pending["plan_hash"]},
        )
        assert response.status_code == 200
        assert response.json()["run"]["status"] == "running"
        # Background task handles the failure
        final_run = client.get(f"/api/agent/account-copilot/runs/{run['id']}").json()
        assert final_run["status"] == "completed"
        assert final_run["pending_approval"]["status"] == "failed"
        skill_observation = [item for item in final_run["observations"] if item.get("observation_type") == "skill_result"][0]
        assert skill_observation["ok"] is False
        assert "boom" in skill_observation["data_limitations"]
    finally:
        app.dependency_overrides.clear()
