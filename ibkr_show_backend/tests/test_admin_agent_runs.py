from fastapi.testclient import TestClient

from app.api.deps import get_agent_run_trace_service, require_admin_session
from app.main import app

client = TestClient(app)


class FakeAgentRunTraceService:
    def list_traces(self, **kwargs):
        return {
            "items": [{"run_id": "run-1", "agent_name": "trade_review", "final_status": "success"}],
            "summary": {
                "run_count": 1,
                "success_rate": 1.0,
                "partial_rate": 0,
                "failure_rate": 0,
                "avg_latency_ms": 100,
                "p95_latency_ms": 100,
                "total_tokens": 12,
                "total_estimated_cost": 0.02,
                "by_agent": {"trade_review": {"run_count": 1, "avg_latency_ms": 100, "total_tokens": 12}},
                "by_status": {"success": {"run_count": 1, "avg_latency_ms": 100, "total_tokens": 12}},
            },
            "received": kwargs,
        }

    def get_trace(self, run_id: str):
        if run_id == "missing":
            return None
        return {"run_id": run_id, "agent_name": "trade_review", "llm_calls": []}


def test_admin_agent_runs_requires_login() -> None:
    response = client.get("/api/admin/agent-runs")
    assert response.status_code == 401


def test_admin_agent_runs_list_and_detail() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_agent_run_trace_service] = lambda: FakeAgentRunTraceService()
    try:
        list_response = client.get("/api/admin/agent-runs?hours=6&agent_name=trade_review&final_status=success&limit=10")
        detail_response = client.get("/api/admin/agent-runs/run-1")
        missing_response = client.get("/api/admin/agent-runs/missing")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["summary"]["run_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["run_id"] == "run-1"
    assert missing_response.status_code == 404
