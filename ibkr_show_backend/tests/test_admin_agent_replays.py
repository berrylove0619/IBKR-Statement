from fastapi.testclient import TestClient

from app.api.deps import get_agent_replay_service, require_admin_session
from app.main import app

client = TestClient(app)


class FakeAgentReplayService:
    def list_snapshots(self, **kwargs):
        return {
            "items": [{"replay_id": "replay-1", "run_id": "run-1", "agent_name": "trade_review"}],
            "summary": {"snapshot_count": 1, "success_rate": 1.0, "partial_rate": 0, "failure_rate": 0, "avg_llm_calls": 1},
            "received": kwargs,
        }

    def get_snapshot(self, replay_id: str):
        if replay_id == "missing":
            return None
        return {"replay_id": replay_id, "run_id": "run-1"}

    def get_by_run_id(self, run_id: str):
        if run_id == "missing":
            return None
        return {"replay_id": "replay-1", "run_id": run_id}

    def export_replay_package(self, replay_id: str):
        if replay_id == "missing":
            return None
        return {"package_type": "agent_replay_package", "snapshot": {"replay_id": replay_id}}


def test_admin_agent_replays_requires_login() -> None:
    response = client.get("/api/admin/agent-replays")
    assert response.status_code == 401


def test_admin_agent_replays_list_detail_by_run_and_export() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_replay_service] = lambda: FakeAgentReplayService()
    try:
        list_response = client.get("/api/admin/agent-replays?agent_name=trade_review&limit=10")
        detail_response = client.get("/api/admin/agent-replays/replay-1")
        by_run_response = client.get("/api/admin/agent-replays/by-run/run-1")
        export_response = client.get("/api/admin/agent-replays/replay-1/export")
        missing_response = client.get("/api/admin/agent-replays/missing")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["summary"]["snapshot_count"] == 1
    assert detail_response.status_code == 200
    assert by_run_response.json()["run_id"] == "run-1"
    assert export_response.json()["package_type"] == "agent_replay_package"
    assert missing_response.status_code == 404
