from fastapi.testclient import TestClient

from app.api.deps import get_agent_eval_service, require_admin_session
from app.main import app

client = TestClient(app)


class FakeAgentEvalService:
    def list_cases(self, **kwargs):
        return [{"case_id": "case-1", "agent_name": "trade_review"}]

    def get_case(self, case_id: str):
        return None if case_id == "missing" else {"case_id": case_id}

    def seed_builtin_cases(self, *, force: bool = False):
        return {"created_count": 1, "skipped_count": 0, "created": ["case-1"], "skipped": []}

    def build_case_from_replay(self, replay_id: str, *, save: bool = False):
        return None if replay_id == "missing" else {"case_id": "case-from-replay", "metadata": {"replay_id": replay_id}}

    def run_eval(self, **kwargs):
        return {"eval_run_id": "eval-1", "status": "completed", "summary": {"case_count": 1}, "results": []}

    def list_eval_runs(self, **kwargs):
        return {"items": [{"eval_run_id": "eval-1"}], "summary": {"run_count": 1}}

    def get_eval_run(self, eval_run_id: str):
        return None if eval_run_id == "missing" else {"eval_run_id": eval_run_id}


def test_admin_agent_eval_requires_login() -> None:
    response = client.get("/api/admin/agent-eval/cases")
    assert response.status_code == 401


def test_admin_agent_eval_routes() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_eval_service] = lambda: FakeAgentEvalService()
    try:
        cases = client.get("/api/admin/agent-eval/cases")
        case = client.get("/api/admin/agent-eval/cases/case-1")
        seed = client.post("/api/admin/agent-eval/cases/seed")
        from_replay = client.post("/api/admin/agent-eval/cases/from-replay/replay-1")
        run = client.post("/api/admin/agent-eval/runs", json={"replay_ids": ["replay-1"], "mode": "static"})
        runs = client.get("/api/admin/agent-eval/runs")
        run_detail = client.get("/api/admin/agent-eval/runs/eval-1")
        missing = client.get("/api/admin/agent-eval/runs/missing")
    finally:
        app.dependency_overrides.clear()

    assert cases.status_code == 200
    assert cases.json()["items"][0]["case_id"] == "case-1"
    assert case.json()["case_id"] == "case-1"
    assert seed.json()["created_count"] == 1
    assert from_replay.json()["metadata"]["replay_id"] == "replay-1"
    assert run.json()["status"] == "completed"
    assert runs.json()["summary"]["run_count"] == 1
    assert run_detail.json()["eval_run_id"] == "eval-1"
    assert missing.status_code == 404
