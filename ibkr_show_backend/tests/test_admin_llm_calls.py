from fastapi.testclient import TestClient

from app.api.deps import get_llm_call_metrics_service, require_admin_session
from app.main import app

client = TestClient(app)


class FakeLLMCallMetricsService:
    def list_calls(self, **kwargs):
        return {
            "items": [
                {
                    "call_id": "call-1",
                    "agent_name": "trade_review",
                    "prompt_key": "trade_review_main",
                    "model": "model-a",
                    "ok": True,
                    "latency_ms": 100,
                    "total_tokens": 42,
                }
            ],
            "summary": {
                "call_count": 1,
                "success_rate": 1.0,
                "total_tokens": 42,
                "total_estimated_cost": 0,
                "avg_latency_ms": 100,
                "p95_latency_ms": 100,
                "by_model": {"model-a": {"call_count": 1, "total_tokens": 42, "avg_latency_ms": 100}},
                "by_agent": {"trade_review": {"call_count": 1, "total_tokens": 42, "avg_latency_ms": 100}},
                "by_prompt_key": {"trade_review_main": {"call_count": 1, "total_tokens": 42, "avg_latency_ms": 100}},
            },
            "received": kwargs,
        }


def test_admin_llm_calls_requires_login() -> None:
    response = client.get("/api/admin/llm-calls")
    assert response.status_code == 401


def test_admin_llm_calls_returns_items_and_summary() -> None:
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_llm_call_metrics_service] = lambda: FakeLLMCallMetricsService()
    try:
        response = client.get("/api/admin/llm-calls?hours=6&agent_name=trade_review&prompt_key=trade_review_main&ok=true&limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["call_id"] == "call-1"
    assert payload["summary"]["call_count"] == 1
    assert payload["summary"]["by_model"]["model-a"]["total_tokens"] == 42
