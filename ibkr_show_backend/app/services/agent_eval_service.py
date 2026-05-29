from __future__ import annotations

from typing import Any

from app.agents.eval_cases import list_builtin_eval_cases
from app.agents.eval_checks import run_eval_checks
from app.agents.eval_harness import EvalCase, EvalCaseResult, EvalRun, build_eval_case_from_replay, new_eval_run_id, utc_now_iso
from app.services.agent_eval_repository import EvalCaseRepository, EvalRunRepository
from app.services.agent_replay_service import AgentReplayService


class AgentEvalService:
    def __init__(
        self,
        case_repository: EvalCaseRepository,
        run_repository: EvalRunRepository,
        replay_service: AgentReplayService | None = None,
    ) -> None:
        self.case_repository = case_repository
        self.run_repository = run_repository
        self.replay_service = replay_service

    def list_cases(self, *, agent_name: str | None = None, source: str | None = None, limit: int = 100) -> list[dict]:
        stored = self.case_repository.list_cases(agent_name=agent_name, source=source, limit=limit)
        if stored:
            return stored
        cases = [case.to_dict() for case in list_builtin_eval_cases()]
        if agent_name:
            cases = [case for case in cases if case.get("agent_name") == agent_name]
        if source:
            cases = [case for case in cases if case.get("source") == source]
        return cases[:limit]

    def get_case(self, case_id: str) -> dict | None:
        stored = self.case_repository.get_case(case_id)
        if stored:
            return stored
        return next((case.to_dict() for case in list_builtin_eval_cases() if case.case_id == case_id), None)

    def create_case(self, payload: dict) -> dict:
        case = EvalCase(**payload)
        return self.case_repository.save_case(case.to_dict())

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        return self.case_repository.seed_builtin_cases(force=force)

    def build_case_from_replay(self, replay_id: str, *, save: bool = False) -> dict | None:
        if self.replay_service is None:
            return None
        snapshot = self.replay_service.get_snapshot(replay_id)
        if snapshot is None:
            return None
        case = build_eval_case_from_replay(snapshot)
        if save:
            return self.case_repository.save_case(case.to_dict())
        return case.to_dict()

    def run_eval(
        self,
        *,
        case_ids: list[str] | None = None,
        agent_name: str | None = None,
        replay_ids: list[str] | None = None,
        mode: str = "static",
        name: str | None = None,
    ) -> dict:
        eval_run = EvalRun(
            eval_run_id=new_eval_run_id(),
            name=name or "Static eval run",
            agent_name=agent_name,
            case_ids=list(case_ids or []),
            config={"mode": mode},
        )
        results: list[dict] = []
        if mode != "static":
            results.append(
                EvalCaseResult(
                    case_id="live_mode_not_implemented",
                    agent_name=agent_name or "unknown",
                    status="warning",
                    score=0,
                    max_score=0,
                    checks=[],
                    error_code="LIVE_MODE_NOT_IMPLEMENTED",
                    error_message="P0 supports static mode only",
                ).to_dict()
            )
        for replay_id in replay_ids or []:
            result = self._evaluate_replay(replay_id)
            if result:
                results.append(result)
        for case_id in case_ids or []:
            result = self._evaluate_case_id(case_id)
            if result:
                results.append(result)
        if not results and agent_name:
            for case in self.list_cases(agent_name=agent_name, limit=100):
                results.append(self._evaluate_case(case, output=(case.get("metadata") or {}).get("output") or {}))

        eval_run.finished_at = utc_now_iso()
        eval_run.status = "completed"
        eval_run.results = results
        eval_run.case_ids = [result.get("case_id") for result in results if result.get("case_id")]
        eval_run.summary = self._summary(results)
        return self.run_repository.save_run(eval_run.to_dict())

    def get_eval_run(self, eval_run_id: str) -> dict | None:
        return self.run_repository.get_run(eval_run_id)

    def list_eval_runs(self, *, hours: int = 24, agent_name: str | None = None, limit: int = 100) -> dict:
        items = self.run_repository.list_runs(hours=hours, agent_name=agent_name, limit=limit)
        return {"items": items, "summary": {"run_count": len(items)}}

    def _evaluate_replay(self, replay_id: str) -> dict | None:
        if self.replay_service is None:
            return None
        snapshot = self.replay_service.get_snapshot(replay_id)
        if snapshot is None:
            return EvalCaseResult(
                case_id=f"replay_missing_{replay_id}",
                agent_name="unknown",
                status="error",
                score=0,
                max_score=0,
                checks=[],
                error_code="REPLAY_NOT_FOUND",
                error_message="Replay snapshot not found",
                replay_id=replay_id,
            ).to_dict()
        case = build_eval_case_from_replay(snapshot)
        return self._evaluate_case(case.to_dict(), output=snapshot.get("final_output") or {}, replay=snapshot)

    def _evaluate_case_id(self, case_id: str) -> dict | None:
        case = self.get_case(case_id)
        if case is None:
            return EvalCaseResult(
                case_id=case_id,
                agent_name="unknown",
                status="error",
                score=0,
                max_score=0,
                checks=[],
                error_code="CASE_NOT_FOUND",
                error_message="Eval case not found",
            ).to_dict()
        output = (case.get("metadata") or {}).get("output")
        if output is None:
            return EvalCaseResult(
                case_id=case_id,
                agent_name=case.get("agent_name", "unknown"),
                status="warning",
                score=0,
                max_score=0,
                checks=[],
                error_code="NO_OUTPUT_TO_EVALUATE",
                error_message="Static mode requires replay_ids or metadata.output",
            ).to_dict()
        return self._evaluate_case(case, output=output)

    def _evaluate_case(self, case: dict, *, output: dict, replay: dict | None = None) -> dict:
        checks = run_eval_checks(output, case, replay=replay)
        score = sum(check.score for check in checks)
        max_score = sum(check.max_score for check in checks)
        fatal_failed = any(not check.passed and check.severity == "fatal" for check in checks)
        warning_failed = any(not check.passed for check in checks)
        status = "failed" if fatal_failed else "warning" if warning_failed else "passed"
        return EvalCaseResult(
            case_id=case["case_id"],
            agent_name=case.get("agent_name", "unknown"),
            status=status,
            score=score,
            max_score=max_score,
            checks=[check.to_dict() for check in checks],
            output_summary={"fields": sorted(output.keys()) if isinstance(output, dict) else [], "type": type(output).__name__},
            replay_id=(replay or {}).get("replay_id"),
            run_id=(replay or {}).get("run_id"),
            metadata={"source": case.get("source")},
        ).to_dict()

    def _summary(self, results: list[dict]) -> dict:
        count = len(results)
        total_score = sum(float(item.get("score") or 0) for item in results)
        max_score = sum(float(item.get("max_score") or 0) for item in results)
        return {
            "case_count": count,
            "passed_count": sum(1 for item in results if item.get("status") == "passed"),
            "warning_count": sum(1 for item in results if item.get("status") == "warning"),
            "failed_count": sum(1 for item in results if item.get("status") == "failed"),
            "error_count": sum(1 for item in results if item.get("status") == "error"),
            "avg_score": total_score / count if count else 0,
            "max_score": max_score,
            "pass_rate": sum(1 for item in results if item.get("status") == "passed") / count if count else 0,
            "by_agent": _bucket(results, "agent_name"),
        }


def _bucket(items: list[dict], key: str) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = buckets.setdefault(name, {"case_count": 0, "passed_count": 0, "warning_count": 0, "failed_count": 0, "error_count": 0})
        bucket["case_count"] += 1
        status = item.get("status")
        if status in {"passed", "warning", "failed", "error"}:
            bucket[f"{status}_count"] += 1
    return buckets
