from __future__ import annotations

import json
import time
from typing import Any

from app.agents.account_copilot.skill_registry import AccountCopilotSkillSpec


class AccountCopilotSkillService:
    def __init__(
        self,
        trade_decision_agent: Any = None,
        trade_review_agent: Any = None,
        daily_position_review_agent: Any = None,
        risk_assessment_agent: Any = None,
    ) -> None:
        self.trade_decision_agent = trade_decision_agent
        self.trade_review_agent = trade_review_agent
        self.daily_position_review_agent = daily_position_review_agent
        self.risk_assessment_agent = risk_assessment_agent

    def execute(self, spec: AccountCopilotSkillSpec, arguments: dict, approval: dict) -> dict:
        started = time.perf_counter()
        if not spec.read_only or not spec.approval_required:
            return self._envelope(
                ok=False,
                skill=spec.name,
                arguments=arguments,
                data={},
                limitations=["Skill is not configured as read-only approval-required."],
                metadata={"error_code": "SKILL_NOT_ALLOWED", "approval_id": approval.get("approval_id")},
                latency_ms=started,
            )
        if approval.get("status") not in {"approved", "executed"}:
            return self._envelope(
                ok=False,
                skill=spec.name,
                arguments=arguments,
                data={},
                limitations=["Skill approval is not approved."],
                metadata={"error_code": "SKILL_APPROVAL_REQUIRED", "approval_id": approval.get("approval_id")},
                latency_ms=started,
            )
        if spec.handler is None:
            return self._envelope(
                ok=False,
                skill=spec.name,
                arguments=arguments,
                data={},
                limitations=["Skill handler is not available."],
                metadata={"error_code": "SKILL_HANDLER_UNAVAILABLE", "approval_id": approval.get("approval_id")},
                latency_ms=started,
            )
        validation_error = self._validate_arguments(spec.input_schema, arguments or {})
        if validation_error:
            return self._envelope(
                ok=False,
                skill=spec.name,
                arguments=arguments,
                data={},
                limitations=[validation_error],
                metadata={"error_code": "SKILL_INVALID_ARGUMENT", "approval_id": approval.get("approval_id")},
                latency_ms=started,
            )
        try:
            data = spec.handler(**(arguments or {}))
            return self._envelope(
                ok=True,
                skill=spec.name,
                arguments=arguments,
                data=self.compact_skill_result(data),
                limitations=[],
                metadata={"approval_id": approval.get("approval_id")},
                latency_ms=started,
            )
        except Exception as exc:
            return self._envelope(
                ok=False,
                skill=spec.name,
                arguments=arguments,
                data={},
                limitations=[str(exc)[:500]],
                metadata={"error_code": "SKILL_EXECUTION_ERROR", "message": str(exc)[:500], "approval_id": approval.get("approval_id")},
                latency_ms=started,
            )

    def trade_decision_entry_skill(self, symbol: str, question: str | None = None) -> dict:
        if self.trade_decision_agent is None:
            raise RuntimeError("TradeDecisionAgent is not configured")
        return self.trade_decision_agent.analyze_entry(symbol, question)

    def trade_decision_holding_skill(self, symbol: str, question: str | None = None) -> dict:
        if self.trade_decision_agent is None:
            raise RuntimeError("TradeDecisionAgent is not configured")
        return self.trade_decision_agent.analyze_holding(symbol, question)

    def trade_review_symbol_skill(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        question: str | None = None,
    ) -> dict:
        if self.trade_review_agent is None:
            raise RuntimeError("TradeReviewAgent is not configured")
        result = self.trade_review_agent.generate_symbol_review(symbol, start_date, end_date)
        if question:
            result = {**result, "question": question}
        return result

    def daily_position_review_skill(self, report_date: str | None = None, question: str | None = None) -> dict:
        if self.daily_position_review_agent is None:
            raise RuntimeError("DailyPositionReviewAgent is not configured")
        if not report_date:
            raise ValueError("report_date is required for daily_position_review_skill")
        result = self.daily_position_review_agent.generate_review(report_date)
        if question:
            result = {**result, "question": question}
        return result

    def risk_assessment_skill(self, question: str | None = None) -> dict:
        if self.risk_assessment_agent is None:
            raise RuntimeError("RiskAssessmentAgent is not configured")
        return self.risk_assessment_agent.analyze(question=question)

    def compact_skill_result(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        preferred = [
            "id",
            "result_id",
            "symbol",
            "report_date",
            "summary",
            "decision_summary",
            "action",
            "recommendation",
            "confidence",
            "overall_score",
            "score",
            "rating",
            "key_reasons",
            "major_risks",
            "key_risks",
            "review_warnings",
            "data_limitations",
            "position_advice",
            "execution_plan",
            "risk_level",
            "cards",
            "card_pack_summary",
        ]
        compact = {key: data[key] for key in preferred if key in data}
        if compact:
            return self._limit_json_size(compact)
        keys = list(data.keys())[:12]
        return self._limit_json_size({key: data[key] for key in keys})

    def _limit_json_size(self, data: Any, limit: int = 12000) -> Any:
        text = json.dumps(data, ensure_ascii=False, default=str)
        if len(text) <= limit:
            return data
        return {"truncated_json": text[:limit], "data_limitations": ["Skill result was compacted by Account Copilot."]}

    def _validate_arguments(self, input_schema: dict, arguments: dict) -> str | None:
        required = input_schema.get("required") or []
        for key in required:
            if key not in arguments or arguments.get(key) in {None, ""}:
                return f"Missing required skill argument: {key}"
        if input_schema.get("additionalProperties") is False:
            allowed = set((input_schema.get("properties") or {}).keys())
            extra = sorted(set(arguments.keys()) - allowed)
            if extra:
                return f"Unknown skill arguments: {', '.join(extra)}"
        for key, schema in (input_schema.get("properties") or {}).items():
            if key not in arguments or arguments.get(key) is None:
                continue
            expected = schema.get("type")
            if expected == "string" and not isinstance(arguments[key], str):
                return f"Skill argument must be a string: {key}"
            if expected == "object" and not isinstance(arguments[key], dict):
                return f"Skill argument must be an object: {key}"
        return None

    def _envelope(
        self,
        *,
        ok: bool,
        skill: str,
        arguments: dict,
        data: Any,
        limitations: list[str],
        metadata: dict,
        latency_ms: float,
    ) -> dict:
        return {
            "ok": ok,
            "skill": skill,
            "arguments": arguments or {},
            "data": data,
            "data_source": "ACCOUNT_COPILOT_SKILL",
            "data_limitations": limitations,
            "metadata": {
                "read_only": True,
                **metadata,
                "latency_ms": int((time.perf_counter() - latency_ms) * 1000),
            },
        }
