from app.agents.trade_review_graph.runner import TradeReviewGraphRunner


class FakeGraph:
    def invoke(self, initial_state: dict) -> dict:
        run_trace = [
            {
                "node_name": "compose_trade_review",
                "status": "success",
                "runtime_trace": [
                    {
                        "event": "llm_finish",
                        "call_id": "call-1",
                        "model": "model-a",
                        "agent_name": "trade_review",
                        "node_name": "compose_trade_review",
                        "prompt_key": "trade_review_main",
                        "prompt_version": "v2",
                        "prompt_hash": "abc",
                        "prompt_source": "admin_active",
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                        "latency_ms": 99,
                        "estimated_cost": 0.01,
                    }
                ],
            }
        ]
        return {
            **initial_state,
            "node_traces": run_trace,
            "saved_document": {
                "id": "AMD",
                "review_type": "symbol_level_review",
                "symbol": "AMD",
                "metadata": {
                    "agent_version": "trade_review_v2",
                    "agent_mode": "trade_review_langgraph_v1",
                    "prompt_metadata": {"trade_review_main": {"version": "v2", "content_hash": "abc", "source": "admin_active"}},
                },
                "run_trace": run_trace,
                "fallback_used": False,
            },
        }


class FakeRepository:
    def __init__(self) -> None:
        self.saved = []

    def save_review(self, document: dict) -> dict:
        self.saved.append(document)
        return document


class FakeTraceService:
    def __init__(self) -> None:
        self.traces = []

    def record_trace(self, trace) -> None:
        self.traces.append(trace)


class FakeReplayService:
    def __init__(self) -> None:
        self.snapshots = []

    def record_snapshot(self, snapshot) -> None:
        self.snapshots.append(snapshot)


def test_trade_review_runner_records_agent_run_trace(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.trade_review_graph.runner.build_trade_review_graph", lambda deps: FakeGraph())
    repository = FakeRepository()
    trace_service = FakeTraceService()
    replay_service = FakeReplayService()
    runner = TradeReviewGraphRunner(
        evidence_builder=object(),
        llm_service=object(),
        repository=repository,
        trace_service=trace_service,
        replay_service=replay_service,
    )

    result = runner.generate_symbol_review("AMD")

    assert result["agent_run_id"].startswith("trade_review_run_")
    assert result["agent_run_trace"]["final_status"] == "success"
    assert trace_service.traces
    trace = trace_service.traces[0]
    assert trace.final_status == "success"
    assert trace.prompt_metadata["trade_review_main"]["content_hash"] == "abc"
    assert trace.llm_calls[0]["call_id"] == "call-1"
    assert trace.llm_calls[0]["prompt_key"] == "trade_review_main"
    assert replay_service.snapshots
    snapshot = replay_service.snapshots[0]
    assert snapshot.run_id == result["agent_run_id"]
    assert snapshot.agent_name == "trade_review"
    assert snapshot.request["symbol"] == "AMD"
    assert snapshot.final_output["symbol"] == "AMD"
