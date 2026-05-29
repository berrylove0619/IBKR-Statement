from app.services.agent_eval_service import AgentEvalService


class FakeCaseRepository:
    def __init__(self) -> None:
        self.cases = {}

    def save_case(self, case: dict) -> dict:
        self.cases[case["case_id"]] = case
        return case

    def get_case(self, case_id: str) -> dict | None:
        return self.cases.get(case_id)

    def list_cases(self, **kwargs) -> list[dict]:
        items = list(self.cases.values())
        agent_name = kwargs.get("agent_name")
        if agent_name:
            items = [item for item in items if item.get("agent_name") == agent_name]
        return items

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        self.cases["builtin"] = {"case_id": "builtin", "agent_name": "trade_review", "title": "Builtin", "source": "manual"}
        return {"created": ["builtin"], "skipped": [], "created_count": 1, "skipped_count": 0}


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs = {}

    def save_run(self, run: dict) -> dict:
        self.runs[run["eval_run_id"]] = run
        return run

    def get_run(self, eval_run_id: str) -> dict | None:
        return self.runs.get(eval_run_id)

    def list_runs(self, **kwargs) -> list[dict]:
        return list(self.runs.values())


class FakeReplayService:
    def __init__(self) -> None:
        self.snapshot = {
            "replay_id": "replay-1",
            "run_id": "run-1",
            "agent_name": "trade_review",
            "request": {"symbol": "AMD"},
            "context_snapshot": {},
            "tool_snapshots": [{"tool_name": "get_context"}],
            "prompt_refs": [{"prompt_key": "trade_review_main"}],
            "final_output": {
                "summary": "有风险，需要观察",
                "overall_score": 70,
                "rating": "good",
                "data_limitations": [],
            },
        }

    def get_snapshot(self, replay_id: str):
        return self.snapshot if replay_id == "replay-1" else None


def test_agent_eval_service_seed_list_get_case() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    seeded = service.seed_builtin_cases()
    assert seeded["created_count"] == 1
    assert service.get_case("builtin")["case_id"] == "builtin"
    assert service.list_cases(agent_name="trade_review")[0]["case_id"] == "builtin"


def test_agent_eval_service_list_cases_falls_back_to_builtin_cases() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    cases = service.list_cases(agent_name="trade_decision")

    assert cases
    assert all(case["agent_name"] == "trade_decision" for case in cases)


def test_agent_eval_service_build_case_from_replay() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    case = service.build_case_from_replay("replay-1")

    assert case["source"] == "replay"
    assert case["metadata"]["replay_id"] == "replay-1"
    assert case["metadata"]["run_id"] == "run-1"


def test_agent_eval_service_run_eval_with_replay_static_mode() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    run = service.run_eval(replay_ids=["replay-1"], mode="static", name="Replay eval")

    assert run["status"] == "completed"
    assert run["summary"]["case_count"] == 1
    assert run["results"][0]["replay_id"] == "replay-1"
    assert run["results"][0]["run_id"] == "run-1"
    assert run["summary"]["by_agent"]["trade_review"]["case_count"] == 1
    for key in ("case_count", "passed_count", "warning_count", "failed_count", "error_count", "pass_rate", "by_agent"):
        assert key in run["summary"]


def test_agent_eval_service_case_without_output_returns_warning() -> None:
    case_repo = FakeCaseRepository()
    case_repo.save_case(
        {
            "case_id": "case-no-output",
            "agent_name": "trade_review",
            "title": "No output",
            "source": "manual",
            "metadata": {},
            "expected_output_fields": ["summary"],
            "forbidden_behavior": [],
            "expected_behavior": {},
        }
    )
    service = AgentEvalService(case_repo, FakeRunRepository(), FakeReplayService())
    run = service.run_eval(case_ids=["case-no-output"])

    assert run["results"][0]["status"] == "warning"
    assert run["results"][0]["error_code"] == "NO_OUTPUT_TO_EVALUATE"


def test_agent_eval_service_non_static_mode_reports_not_implemented_warning() -> None:
    service = AgentEvalService(FakeCaseRepository(), FakeRunRepository(), FakeReplayService())
    run = service.run_eval(mode="live", agent_name="trade_review")

    assert run["results"][0]["status"] == "warning"
    assert run["results"][0]["error_code"] == "LIVE_MODE_NOT_IMPLEMENTED"
