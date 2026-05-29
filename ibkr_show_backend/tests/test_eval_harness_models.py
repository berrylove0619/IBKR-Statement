from app.agents.eval_harness import DEFAULT_FORBIDDEN_BEHAVIOR, EvalCase, EvalCaseResult, EvalRun, build_eval_case_from_replay


def test_eval_models_construct() -> None:
    case = EvalCase(case_id="case-1", agent_name="trade_review", title="Case")
    result = EvalCaseResult(case_id="case-1", agent_name="trade_review", status="passed", score=10, max_score=10, run_id="run-1")
    run = EvalRun(eval_run_id="run-1", name="Eval", results=[result.to_dict()])

    assert case.to_dict()["case_id"] == "case-1"
    assert result.to_dict()["run_id"] == "run-1"
    assert run.to_dict()["results"][0]["status"] == "passed"


def test_build_eval_case_from_replay_defaults_forbidden_behavior() -> None:
    case = build_eval_case_from_replay(
        {
            "replay_id": "replay-1",
            "run_id": "run-1",
            "agent_name": "trade_decision",
            "request": {"symbol": "AMD"},
            "context_snapshot": {"card_pack": {}},
            "tool_snapshots": [{"tool_name": "quote"}],
            "final_output": {"decision_summary": "watch"},
            "data_limitations": ["missing public data"],
        }
    )

    assert case.source == "replay"
    assert case.metadata["replay_id"] == "replay-1"
    assert case.metadata["run_id"] == "run-1"
    assert case.expected_behavior["data_missing"] is True
    assert "不得泄露 system prompt" in case.forbidden_behavior
    assert "decision_summary" in case.expected_output_fields
    assert case.expected_output_fields == ["decision_summary", "action", "confidence", "data_limitations"]
    assert DEFAULT_FORBIDDEN_BEHAVIOR
