from app.agents.agent_run_trace import build_agent_run_trace
from app.agents.run_replay import build_replay_snapshot, sanitize_replay_payload, summarize_large_payload, truncate_replay_payload
from app.services.agent_replay_service import AgentReplayService


def test_sanitize_replay_payload_redacts_secrets_and_prompt_content() -> None:
    payload = {
        "authorization": "Bearer abc",
        "session_cookie": "cookie",
        "system_prompt": "full prompt",
        "content": "ordinary news content",
        "messages": [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "question"}],
        "nested": {"api_key": "secret", "normal": "ok"},
    }

    assert sanitize_replay_payload(payload) == {
        "authorization": "***",
        "session_cookie": "***",
        "system_prompt": "[prompt omitted]",
        "content": "ordinary news content",
        "messages": [{"role": "system", "content": "[prompt omitted]"}, {"role": "user", "content": "question"}],
        "nested": {"api_key": "***", "normal": "ok"},
    }


def test_truncate_replay_payload_limits_large_strings() -> None:
    result = truncate_replay_payload({"large": "x" * 100}, max_chars=40)
    assert result["large"].startswith("x")
    assert "truncated" in result["large"]


def test_sanitize_replay_payload_keeps_ordinary_content_with_truncation() -> None:
    payload = {"article": {"content": "n" * 4000}, "prompt": "secret prompt"}

    result = sanitize_replay_payload(payload)

    assert result["article"]["content"].startswith("n")
    assert "[truncated" in result["article"]["content"]
    assert result["prompt"] == "[prompt omitted]"


def test_build_replay_snapshot_omits_full_system_prompt_and_extracts_refs() -> None:
    document = {
        "id": "AMD",
        "symbol": "AMD",
        "metadata": {
            "agent_version": "trade_review_v2",
            "agent_mode": "trade_review_langgraph_v1",
            "prompt_metadata": {
                "trade_review_main": {
                    "prompt_key": "trade_review_main",
                    "version": "v2",
                    "content_hash": "abc",
                    "source": "admin_active",
                    "content": "do not store",
                }
            },
        },
        "evidence_pack": {"system_prompt": "secret prompt", "symbol": "AMD"},
        "raw_llm_response": '{"ok": true}',
        "summary": "good",
        "data_limitations": [],
    }
    trace = build_agent_run_trace(
        run_id="run-1",
        agent_name="trade_review",
        document=document,
        node_traces=[
            {
                "node_name": "compose",
                "status": "success",
                "runtime_trace": [
                    {
                        "event": "llm_finish",
                        "call_id": "call-1",
                        "model": "model-a",
                        "prompt_key": "trade_review_main",
                        "prompt_version": "v2",
                        "prompt_hash": "abc",
                        "prompt_source": "admin_active",
                        "total_tokens": 12,
                    }
                ],
            }
        ],
    )

    snapshot = build_replay_snapshot(
        run_id="run-1",
        agent_name="trade_review",
        request={"symbol": "AMD", "api_key": "secret"},
        document=document,
        agent_run_trace=trace,
    ).to_dict()

    assert snapshot["request"]["api_key"] == "***"
    assert snapshot["prompt_refs"] == [
        {
            "prompt_key": "trade_review_main",
            "prompt_version": "v2",
            "prompt_hash": "abc",
            "prompt_source": "admin_active",
        }
    ]
    assert snapshot["context_snapshot"]["evidence_pack"]["system_prompt"] == "[prompt omitted]"
    assert "do not store" not in str(snapshot["prompt_refs"])
    assert snapshot["llm_snapshots"][0]["call_id"] == "call-1"
    assert snapshot["llm_snapshots"][0]["input_messages_summary"] == "system prompt omitted; see prompt_refs"
    assert snapshot["final_output"]["summary"] == "good"


def test_summarize_large_payload_reports_truncation() -> None:
    summary = summarize_large_payload({"items": ["x" * 200]}, max_chars=50)
    assert summary["truncated"] is True
    assert summary["char_count"] > 50


class FakeReplayRepository:
    def __init__(self) -> None:
        self.saved = {}

    def save_snapshot(self, document: dict) -> dict:
        self.saved[document["replay_id"]] = document
        return document

    def get_snapshot(self, replay_id: str) -> dict | None:
        return self.saved.get(replay_id)

    def get_by_run_id(self, run_id: str) -> dict | None:
        return next((item for item in self.saved.values() if item.get("run_id") == run_id), None)

    def list_snapshots(self, **kwargs) -> list[dict]:
        return list(self.saved.values())


def test_agent_replay_service_records_queries_and_exports() -> None:
    repository = FakeReplayRepository()
    service = AgentReplayService(repository)
    stored = service.record_snapshot(
        {
            "replay_id": "replay-1",
            "run_id": "run-1",
            "agent_name": "trade_review",
            "created_at": "2026-05-26T00:00:00+00:00",
            "final_status": "success",
            "prompt_refs": [{"prompt_key": "trade_review_main"}],
            "model_config": {"model": "model-a"},
            "tool_snapshots": [{"tool_name": "get_context"}],
            "llm_snapshots": [{"call_id": "call-1"}],
        }
    )

    assert stored["prompt_keys"] == ["trade_review_main"]
    assert stored["tool_names"] == ["get_context"]
    assert stored["llm_call_ids"] == ["call-1"]
    assert service.get_snapshot("replay-1")["run_id"] == "run-1"
    assert service.get_by_run_id("run-1")["replay_id"] == "replay-1"
    assert service.list_snapshots()["summary"]["snapshot_count"] == 1
    assert service.export_replay_package("replay-1")["snapshot"]["replay_id"] == "replay-1"
