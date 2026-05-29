from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from collections.abc import Callable
from uuid import uuid4

from app.agents.account_copilot.approval import build_pending_approval
from app.agents.account_copilot import planner_prompts
from app.agents.account_copilot.planner_prompts import build_after_approval_final_messages, build_planner_messages
from app.agents.account_copilot.planner_schema import CopilotFinalAnswerAfterApproval, CopilotPlannerAction
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.agents.account_copilot.state import AccountCopilotState
from app.agents.account_copilot.subagent_registry import AccountCopilotSubAgentRegistry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output import StructuredOutputContract, StructuredOutputRuntime
from app.agents.structured_output.errors import LLM_CALL_FAILED, StructuredOutputError
from app.services.account_copilot.event_bus import AccountCopilotEventBus
from app.services.account_copilot.monitoring_service import AccountCopilotMonitoringService, provider_for_name
from app.services.llm_service import LLMConfigError, LLMService

FALLBACK_LLM_DISABLED = "Account Copilot 当前未启用 LLM，无法执行自主规划。"
FALLBACK_PARSE_FAILED = "Account Copilot 未能解析规划器输出，已安全停止本轮自主规划。"
FALLBACK_MAX_ROUNDS = "Account Copilot 已达到本轮最大工具调用轮数，已基于现有证据安全停止。"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotStructuredOutputError(Exception):
    def __init__(self, error_code: str, message: str, result_metadata: dict | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.result_metadata = result_metadata or {}


class AccountCopilotRuntime:
    def __init__(
        self,
        llm_service: LLMService,
        tool_registry: AccountCopilotToolRegistry,
        skill_registry: AccountCopilotSkillRegistry | None = None,
        subagent_registry: AccountCopilotSubAgentRegistry | None = None,
        subagent_service=None,
        event_bus: AccountCopilotEventBus | None = None,
        emit_terminal_events: bool = True,
        cancel_checker: Callable[[str], bool] | None = None,
        timeout_seconds: int | None = None,
        max_rounds: int = 8,
        max_observation_chars: int = 12000,
        max_tokens: int | None = None,
        monitoring_service: AccountCopilotMonitoringService | None = None,
        prompt_service=None,
    ) -> None:
        self.llm_service = llm_service
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry or AccountCopilotSkillRegistry()
        self.subagent_registry = subagent_registry or AccountCopilotSubAgentRegistry()
        self.subagent_service = subagent_service
        self.event_bus = event_bus
        self.emit_terminal_events = emit_terminal_events
        self.cancel_checker = cancel_checker
        self.timeout_seconds = timeout_seconds
        self.max_rounds = max_rounds
        self.max_observation_chars = max_observation_chars
        self.max_tokens = max_tokens
        self.monitoring_service = monitoring_service
        self.prompt_service = prompt_service

    def run(self, state: AccountCopilotState) -> AccountCopilotState:
        actions: list[dict] = []
        observations: list[dict] = []
        tool_calls: list[dict] = []
        skill_requests: list[dict] = []
        errors: list[dict] = []
        planner_output: dict = {}
        pending_approval = None
        final_answer = None
        metadata: dict = {"fallback_used": False}
        prompt_metadata: dict[str, dict] = {}
        started_monotonic = time.monotonic()
        consecutive_empty = 0
        self._publish(state, "run_started", {"user_message_id": state.get("user_message_id")})

        try:
            self.llm_service.health()
        except Exception:
            pass

        for round_index in range(1, self.max_rounds + 1):
            stop_reason = self._stop_reason(state, started_monotonic)
            if stop_reason == "cancelled":
                final_answer = "本轮分析已取消。"
                metadata.update({"cancelled": True, "fallback_used": True})
                self._publish(state, "run_cancelled", {"round": round_index})
                break
            if stop_reason == "timeout":
                final_answer = "本轮分析已达到最大执行时间，已安全停止。"
                metadata.update({"timeout": True, "fallback_used": True, "error_code": "RUN_TIMEOUT"})
                errors.append(self._error("RUN_TIMEOUT", "Run timed out", round_index))
                self._publish(state, "run_failed", {"round": round_index, "error_code": "RUN_TIMEOUT"})
                break
            try:
                self._publish(state, "planner_started", {"round": round_index})
                action, raw_planner = self._plan(state, actions, observations)
                if raw_planner.get("prompt_metadata"):
                    prompt_metadata["account_copilot_planner"] = raw_planner["prompt_metadata"]
                    metadata["prompt_metadata"] = prompt_metadata
            except LLMConfigError as exc:
                errors.append(self._error("LLM_NOT_CONFIGURED", str(exc), round_index))
                final_answer = FALLBACK_LLM_DISABLED
                metadata["fallback_used"] = True
                self._publish(state, "final_answer", {"content": final_answer, "fallback_used": True})
                self._publish(state, "run_failed", {"round": round_index, "error_code": "LLM_NOT_CONFIGURED", "message": str(exc)[:300]})
                break
            except AccountCopilotStructuredOutputError as exc:
                errors.append(self._error(exc.error_code, str(exc), round_index))
                final_answer = FALLBACK_PARSE_FAILED
                metadata["fallback_used"] = True
                metadata["structured_output"] = exc.result_metadata
                self._publish(state, "final_answer", {"content": final_answer, "fallback_used": True})
                self._publish(state, "run_failed", {"round": round_index, "error_code": exc.error_code, "message": str(exc)[:300]})
                break
            except Exception as exc:
                errors.append(self._error("PLANNER_FAILED", str(exc), round_index))
                final_answer = FALLBACK_PARSE_FAILED
                metadata["fallback_used"] = True
                self._publish(state, "final_answer", {"content": final_answer, "fallback_used": True})
                self._publish(state, "run_failed", {"round": round_index, "error_code": "PLANNER_FAILED", "message": str(exc)[:300]})
                break

            planner_output = raw_planner
            self._publish(
                state,
                "planner_finished",
                {
                    "round": round_index,
                    "action_type": action.action_type,
                    "thought_summary": action.thought_summary,
                    "evidence_sufficiency": action.evidence_sufficiency.model_dump(),
                    "tool_name": action.tool_name,
                    "skill_name": action.skill_name,
                    "subagent_name": action.subagent_name,
                    "repaired": raw_planner.get("repaired", False),
                    "latency_ms": raw_planner.get("latency_ms"),
                },
            )
            action_record = self._action_record(action, round_index)
            action_record["run_id"] = state.get("run_id")
            action_record["session_id"] = state.get("session_id")
            actions.append(action_record)
            self._publish(state, "action_selected", {"action": self._compact_action_event(action_record)})

            if action.action_type == "final_answer":
                final_answer = action.final_answer
                self._publish(state, "final_answer", {"content": final_answer})
                break

            if action.action_type == "request_skill_approval":
                spec = self.skill_registry.get(action.skill_name)
                if spec is None or not spec.read_only or not spec.approval_required:
                    observations.append(self._skill_error_observation(action_record, round_index, action, "SKILL_NOT_AVAILABLE"))
                    final_answer = "该 Skill 当前不可用或不允许执行，我不会绕过审批继续调用。"
                    metadata["fallback_used"] = True
                    break
                pending_approval = self._pending_approval(action, spec, state)
                skill_requests.append({**pending_approval, "action_id": action_record["id"], "round": round_index})
                final_answer = action.approval_message or f"我建议调用 {spec.display_name} Skill，需要你确认后才能继续。"
                metadata.update({"requires_approval": True, "approval_id": pending_approval["approval_id"]})
                self._publish(state, "skill_approval_requested", {"pending_approval": pending_approval})
                self._publish(state, "final_answer", {"content": final_answer})
                break

            if action.action_type == "delegate_to_subagent":
                subagent_name = action.subagent_name or ""
                subagent_args = action.subagent_arguments or {}
                args_preview = {k: str(v)[:120] for k, v in subagent_args.items()} if subagent_args else {}
                self._publish(state, "subagent_started", {
                    "round": round_index,
                    "subagent_name": subagent_name,
                    "arguments_preview": args_preview,
                })
                subagent_t0 = time.monotonic()
                observation = self._execute_subagent_action(action, action_record, round_index)
                subagent_latency_ms = int((time.monotonic() - subagent_t0) * 1000)
                obs_ok = bool(observation.get("ok", False))
                subagent_event_payload = {
                    "round": round_index,
                    "subagent_name": subagent_name,
                    "ok": obs_ok,
                    "latency_ms": subagent_latency_ms,
                    "data_summary": str(observation.get("data_summary") or "")[:500],
                    "data_limitations": list(observation.get("data_limitations") or []),
                }
                if obs_ok:
                    self._publish(state, "subagent_finished", subagent_event_payload)
                else:
                    subagent_event_payload["error_code"] = (observation.get("metadata") or {}).get("error_code", "SUBAGENT_FAILED")
                    self._publish(state, "subagent_failed", subagent_event_payload)
                observations.append(observation)
                self._publish(state, "observation_created", {"observation": self._compact_observation_event(observation)})
                if not observation.get("ok") or not observation.get("data"):
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0
                if consecutive_empty >= 3:
                    final_answer = "连续多轮工具调用未返回有效数据，基于已有证据回答。"
                    metadata["fallback_used"] = True
                    metadata["error_code"] = "CONSECUTIVE_EMPTY_RESULTS"
                    self._publish(state, "final_answer", {"content": final_answer, "fallback_used": True})
                    break
                continue

            stop_reason = self._stop_reason(state, started_monotonic)
            if stop_reason == "cancelled":
                final_answer = "本轮分析已取消。"
                metadata.update({"cancelled": True, "fallback_used": True})
                self._publish(state, "run_cancelled", {"round": round_index})
                break
            if stop_reason == "timeout":
                final_answer = "本轮分析已达到最大执行时间，已安全停止。"
                metadata.update({"timeout": True, "fallback_used": True, "error_code": "RUN_TIMEOUT"})
                errors.append(self._error("RUN_TIMEOUT", "Run timed out", round_index))
                self._publish(state, "run_failed", {"round": round_index, "error_code": "RUN_TIMEOUT"})
                break
            observation, tool_call = self._execute_tool_action(action, action_record, round_index)
            observations.append(observation)
            tool_calls.append(tool_call)
            self._publish(state, "observation_created", {"observation": self._compact_observation_event(observation)})
            if not observation.get("ok") or not observation.get("data"):
                consecutive_empty += 1
            else:
                consecutive_empty = 0
            if consecutive_empty >= 3:
                final_answer = "连续多轮工具调用未返回有效数据，基于已有证据回答。"
                metadata["fallback_used"] = True
                metadata["error_code"] = "CONSECUTIVE_EMPTY_RESULTS"
                self._publish(state, "final_answer", {"content": final_answer, "fallback_used": True})
                break

        if final_answer is None:
            final_answer = FALLBACK_MAX_ROUNDS
            metadata["fallback_used"] = True
            errors.append(self._error("MAX_ROUNDS_REACHED", "Max ReAct rounds reached", self.max_rounds))
            self._publish(state, "final_answer", {"content": final_answer})

        if self.emit_terminal_events and not metadata.get("requires_approval") and not metadata.get("cancelled") and not any(error.get("code") in {"LLM_NOT_CONFIGURED", "PLANNER_FAILED", "RUN_TIMEOUT"} for error in errors):
            self._publish(state, "run_completed", {"fallback_used": metadata.get("fallback_used", False), "requires_approval": False})

        return {
            **state,
            "planner_output": planner_output,
            "actions": actions,
            "observations": observations,
            "tool_calls": tool_calls,
            "skill_requests": skill_requests,
            "pending_approval": pending_approval,
            "memory_snapshot": self._memory_snapshot(state, observations),
            "final_answer": final_answer,
            "errors": errors,
            "metadata": metadata,
        }

    def compose_final_answer_after_approval(self, state: AccountCopilotState, skill_observation: dict) -> AccountCopilotState:
        observations = list(state.get("observations") or [])
        if skill_observation not in observations:
            observations.append(skill_observation)
        state = self._state_with_runtime_ids(state)
        messages = build_after_approval_final_messages(state, observations, skill_observation)
        context = self._after_approval_context(state, observations, skill_observation)
        contract = self._after_approval_final_contract()
        try:
            raw = self._chat_with_metric(
                state,
                messages,
                call_type="after_approval_final_answer",
                temperature=0.0,
                max_tokens=self.max_tokens,
                response_format=contract.response_format,
            )
        except Exception as exc:
            error = StructuredOutputError(LLM_CALL_FAILED, "After-approval final answer LLM call failed.", cause=exc)
            fallback_payload = self._after_approval_fallback(context, error, "")
            final_model = CopilotFinalAnswerAfterApproval.model_validate(fallback_payload)
            metadata = self._after_approval_metadata(
                state,
                structured_output={
                    "contract_name": contract.name,
                    "fallback_used": True,
                    "error_code": LLM_CALL_FAILED,
                    "error_message": str(exc)[:500],
                    "run_id_missing": not bool(state.get("run_id")),
                    "session_id_missing": not bool(state.get("session_id")),
                },
                fallback_used=True,
            )
            self._publish(state, "final_answer", {"content": final_model.final_answer, "fallback_used": True})
            return {
                **state,
                "observations": observations,
                "planner_output": {"after_approval": True, "structured_output": metadata["structured_output"]},
                "final_answer": final_model.final_answer,
                "metadata": metadata,
            }

        result = self._structured_output_runtime().parse_validate_repair(
            raw, contract, context=context,
            run_id=state.get("run_id") or state.get("id"),
            session_id=state.get("session_id"),
            task_id=state.get("task_id") or state.get("user_message_id"),
        )
        structured_metadata = dict(result.metadata)
        structured_metadata["errors"] = result.errors
        structured_metadata["trace"] = result.trace
        structured_metadata["initial_error_code"] = result.errors[0].get("error_code") if result.errors else None
        structured_metadata["run_id_missing"] = not bool(state.get("run_id"))
        structured_metadata["session_id_missing"] = not bool(state.get("session_id"))

        if result.ok and result.model is not None:
            final_model = result.model
        else:
            last_error = self._last_structured_error(result)
            fallback_payload = self._after_approval_fallback(context, last_error, raw)
            final_model = CopilotFinalAnswerAfterApproval.model_validate(fallback_payload)
            structured_metadata.update(
                {
                    "fallback_used": True,
                    "error_code": last_error.error_code,
                    "error_message": last_error.message,
                    "fallback_reason": f"{last_error.error_code}: {last_error.message}",
                }
            )

        self._publish(state, "final_answer", {"content": final_model.final_answer, "fallback_used": bool(structured_metadata.get("fallback_used"))})
        return {
            **state,
            "observations": observations,
            "planner_output": {
                "raw_action": self._safe_payload(result.payload or final_model.model_dump()),
                "after_approval": True,
                "structured_output": structured_metadata,
                "repaired": result.repaired,
                "fallback_used": bool(structured_metadata.get("fallback_used")),
            },
            "final_answer": final_model.final_answer,
            "metadata": self._after_approval_metadata(state, structured_output=structured_metadata, fallback_used=bool(structured_metadata.get("fallback_used"))),
        }

    def _plan(self, state: dict, actions: list[dict], observations: list[dict]) -> tuple[CopilotPlannerAction, dict]:
        system_prompt, prompt_metadata = resolve_runtime_prompt(
            self.prompt_service,
            "account_copilot_planner",
            planner_prompts.SYSTEM_PROMPT,
        )
        messages = build_planner_messages(
            state,
            self.tool_registry,
            actions,
            observations,
            self.skill_registry,
            self.subagent_registry,
            system_prompt=system_prompt,
        )
        started = time.perf_counter()
        raw = self._chat_with_metric(
            state,
            messages,
            call_type="planner",
            prompt_metadata=prompt_metadata,
            temperature=0.0,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        contract = self._planner_contract()
        result = self._structured_output_runtime().parse_validate_repair(
            raw,
            contract,
            context={"state": self._compact_planner_state(state), "prompt_metadata": prompt_metadata},
            run_id=state.get("run_id") or state.get("id"),
            session_id=state.get("session_id"),
            task_id=state.get("task_id") or state.get("user_message_id"),
        )
        raw_planner = {
            "raw_action": self._safe_payload(result.payload or {}),
            "latency_ms": latency_ms,
            "repaired": result.repaired,
            "prompt_metadata": prompt_metadata,
            "structured_output": {
                **result.metadata,
                "errors": result.errors,
                "trace": result.trace,
                "initial_error_code": result.errors[0].get("error_code") if result.errors else None,
            },
        }
        if result.ok and isinstance(result.model, CopilotPlannerAction):
            return result.model, raw_planner
        error_code = result.error_code or (result.errors[-1].get("error_code") if result.errors else "STRUCTURED_OUTPUT_FAILED")
        raise AccountCopilotStructuredOutputError(error_code, result.error_message or f"Planner structured output failed: {error_code}", raw_planner["structured_output"])

    def _structured_output_runtime(self) -> StructuredOutputRuntime:
        return StructuredOutputRuntime(
            self.llm_service,
            monitoring_service=self.monitoring_service,
            default_temperature=0.0,
            default_max_tokens=self.max_tokens,
        )

    def _planner_contract(self) -> StructuredOutputContract:
        return StructuredOutputContract(
            name="account_copilot_planner",
            agent_name="account_copilot",
            node_name="planner",
            output_model=CopilotPlannerAction,
            schema_hint=CopilotPlannerAction.model_json_schema(),
            examples=planner_prompts.PLANNER_ACTION_EXAMPLES,
            max_repair_attempts=1,
            repair_enabled=True,
            fallback_enabled=False,
        )

    def _after_approval_final_contract(self) -> StructuredOutputContract:
        return StructuredOutputContract(
            name="account_copilot_after_approval_final_answer",
            agent_name="account_copilot",
            node_name="after_approval_final_answer",
            output_model=CopilotFinalAnswerAfterApproval,
            schema_hint=CopilotFinalAnswerAfterApproval.model_json_schema(),
            examples=[planner_prompts.AFTER_APPROVAL_FINAL_EXAMPLE],
            max_repair_attempts=1,
            repair_enabled=True,
            fallback_enabled=False,
        )

    def _after_approval_context(self, state: dict, observations: list[dict], skill_observation: dict) -> dict:
        return {
            "user_input": state.get("user_input"),
            "observations": [self._compact_for_prompt(item) for item in observations[-8:]],
            "skill_observation": self._compact_for_prompt(skill_observation),
            "pending_approval": state.get("pending_approval") or {},
            "run_id": state.get("run_id"),
            "session_id": state.get("session_id"),
        }

    def _after_approval_fallback(self, context: dict | None, last_error: StructuredOutputError, raw_response: str) -> dict:
        value = context or {}
        skill_observation = value.get("skill_observation") if isinstance(value.get("skill_observation"), dict) else {}
        pending = value.get("pending_approval") if isinstance(value.get("pending_approval"), dict) else {}
        skill_name = str(pending.get("skill_name") or skill_observation.get("skill_name") or "")
        data = skill_observation.get("data_preview") if isinstance(skill_observation, dict) else {}
        limitations = list(skill_observation.get("data_limitations") or []) if isinstance(skill_observation, dict) else []
        if isinstance(data, dict):
            summary = self._readable_skill_summary(skill_name, data, limitations)
            confidence = str(data.get("confidence") or "medium")
            if confidence not in {"low", "medium", "high"}:
                confidence = "medium"
        else:
            summary = f"Skill 已执行，但最终回答格式化失败；以下是 Skill 结果摘要：{self._readable_value(data)}"
            confidence = "low"
        fallback_reason = self._friendly_structured_error(last_error.error_code)
        answer = f"{fallback_reason}。{summary}"
        data_limitations = [*limitations, "LLM 最终回答格式异常，已基于 Skill 结果生成保守摘要"]
        return {
            "final_answer": answer,
            "confidence": "low" if last_error.error_code == LLM_CALL_FAILED else ("medium" if confidence == "high" else confidence),
            "data_limitations": list(dict.fromkeys(str(item) for item in data_limitations if item)),
            "evidence_used": self._after_approval_evidence_used(skill_name, data),
        }

    def _readable_skill_summary(self, skill_name: str, data: dict, limitations: list[str]) -> str:
        summary = str(data.get("summary") or "").strip()
        risk_level = data.get("risk_level")
        key_risks = self._string_list(data.get("key_risks"))
        recommendations = self._string_list(data.get("recommendations"))
        watch_points = self._string_list(data.get("watch_points"))
        data_limitations = self._string_list(data.get("data_limitations")) + [str(item) for item in limitations if item]
        if skill_name == "risk_assessment_skill" or risk_level or key_risks:
            parts = ["Skill 已执行，以下是基于风险评估结果生成的保守摘要。"]
            if risk_level:
                parts.append(f"风险等级：{risk_level}。")
            if summary:
                parts.append(f"摘要：{summary}")
            if key_risks:
                parts.append(f"主要风险包括：{'、'.join(key_risks)}。")
            if watch_points:
                parts.append(f"后续观察点：{'、'.join(watch_points)}。")
            if recommendations:
                parts.append(f"可参考的风险管理动作：{'、'.join(recommendations)}。")
            if data_limitations:
                parts.append(f"数据限制：{'、'.join(data_limitations)}。")
            parts.append("以上用于风险识别和复盘，不构成确定性买卖建议。")
            return "".join(parts)
        if summary:
            return f"Skill 已执行，以下是 Skill 结果摘要：{summary}"
        return f"Skill 已执行，但最终回答格式化失败；以下是 Skill 结果摘要：{self._readable_value(data)}"

    def _readable_value(self, value) -> str:
        if isinstance(value, dict):
            important = []
            for key in ("summary", "risk_level", "confidence", "action", "recommendation"):
                if value.get(key):
                    important.append(f"{key}={value.get(key)}")
            for key in ("key_risks", "recommendations", "watch_points", "data_limitations"):
                items = self._string_list(value.get(key))
                if items:
                    important.append(f"{key}: {'、'.join(items[:5])}")
            if important:
                return "；".join(important)
            text = json.dumps(value, ensure_ascii=False, default=str)
            return text[:500]
        if isinstance(value, list):
            return "；".join(str(item) for item in value[:5])[:500]
        return str(value or "")[:500]

    def _string_list(self, value) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _after_approval_evidence_used(self, skill_name: str, data) -> list[str]:
        evidence = []
        if isinstance(data, dict):
            for key in ("evidence_used", "tools_used", "source_tools"):
                evidence.extend(self._string_list(data.get(key)))
        if skill_name:
            evidence.append(skill_name)
        return list(dict.fromkeys(evidence))

    def _friendly_structured_error(self, error_code: str) -> str:
        if error_code == LLM_CALL_FAILED:
            return "LLM 暂时不可用，已基于 Skill 结果生成保守摘要"
        if error_code == "LLM_JSON_PARSE_FAILED":
            return "模型输出格式异常，已基于 Skill 结果生成保守摘要"
        if error_code == "LLM_SCHEMA_INVALID":
            return "模型输出字段不完整，已基于 Skill 结果生成保守摘要"
        return "模型输出格式异常，已基于 Skill 结果生成保守摘要"

    def _last_structured_error(self, result) -> StructuredOutputError:
        last = result.errors[-1] if result.errors else {}
        return StructuredOutputError(
            str(last.get("error_code") or result.error_code or "STRUCTURED_OUTPUT_FAILED"),
            str(last.get("message") or result.error_message or "Structured output failed."),
            raw_response_preview=result.raw_response,
            validation_error=last.get("validation_error"),
        )

    def _after_approval_metadata(self, state: dict, *, structured_output: dict, fallback_used: bool) -> dict:
        return {
            **(state.get("metadata") or {}),
            "fallback_used": fallback_used,
            "structured_output": structured_output,
            "run_id_missing": not bool(state.get("run_id")),
            "session_id_missing": not bool(state.get("session_id")),
        }

    def _state_with_runtime_ids(self, state: dict) -> dict:
        if state.get("run_id") and state.get("session_id"):
            return dict(state)
        pending = state.get("pending_approval") if isinstance(state.get("pending_approval"), dict) else {}
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        return {
            **state,
            "run_id": state.get("run_id") or state.get("id") or pending.get("run_id") or metadata.get("run_id"),
            "session_id": state.get("session_id") or pending.get("session_id") or metadata.get("session_id"),
        }

    def _compact_planner_state(self, state: dict) -> dict:
        return {
            "session_id": state.get("session_id"),
            "run_id": state.get("run_id"),
            "user_input": state.get("user_input"),
            "message_count": len(state.get("messages") or []),
            "memory_keys": list((state.get("memory_snapshot") or {}).keys())[:10],
        }

    def _execute_tool_action(self, action: CopilotPlannerAction, action_record: dict, round_index: int) -> tuple[dict, dict]:
        tool_name = action.tool_name or ""
        tool_call_id = f"tool_{uuid4().hex[:12]}"
        started = time.perf_counter()
        ok = False
        result: dict
        spec = self.tool_registry.get(tool_name)
        if spec is None:
            result = self._tool_error(tool_name, action.tool_arguments, "TOOL_NOT_FOUND", "Tool is not registered")
        elif not spec.read_only or spec.handler is None:
            result = self._tool_error(tool_name, action.tool_arguments, "TOOL_NOT_ALLOWED", "Tool is not read-only or has no handler")
        else:
            try:
                self._publish(
                    {"run_id": action_record.get("run_id"), "session_id": action_record.get("session_id")},
                    "tool_started",
                    {"round": round_index, "tool_name": tool_name, "arguments_preview": self._preview(action.tool_arguments or {})},
                )
                result = spec.handler(**(action.tool_arguments or {}))
                ok = bool(result.get("ok", False)) if isinstance(result, dict) else True
            except Exception as exc:
                result = self._tool_error(tool_name, action.tool_arguments, "TOOL_EXECUTION_ERROR", str(exc))
        latency_ms = int((time.perf_counter() - started) * 1000)
        observation = self._observation_from_result(action_record, round_index, tool_name, action.tool_arguments, result)
        tool_call = {
            "id": tool_call_id,
            "round": round_index,
            "tool_name": tool_name,
            "arguments": action.tool_arguments or {},
            "ok": ok,
            "latency_ms": latency_ms,
        }
        self._publish(
            {"run_id": action_record.get("run_id"), "session_id": action_record.get("session_id")},
            "tool_finished" if tool_call["ok"] else "tool_failed",
            {
                "round": round_index,
                "tool_name": tool_name,
                "ok": tool_call["ok"],
                "latency_ms": latency_ms,
                "data_summary": observation.get("data_summary"),
                "data_limitations": observation.get("data_limitations") or [],
            },
        )
        self._record_tool_metric(action_record, tool_name, tool_call, result)
        return observation, tool_call

    def _record_tool_metric(self, action_record: dict, tool_name: str, tool_call: dict, result: dict) -> None:
        if self.monitoring_service is None:
            return
        metadata = result.get("metadata") if isinstance(result, dict) else {}
        self.monitoring_service.record_tool_call(
            run_id=action_record.get("run_id"),
            session_id=action_record.get("session_id"),
            agent_name="account_copilot",
            node_name="tool_action",
            tool_name=tool_name,
            ok=bool(tool_call.get("ok")),
            latency_ms=int(tool_call.get("latency_ms") or 0),
            error_code=(metadata or {}).get("error_code") if isinstance(metadata, dict) else None,
            error_message=(metadata or {}).get("message") if isinstance(metadata, dict) else None,
            source="runtime",
            metadata={"round": tool_call.get("round")},
        )

    def _chat_with_metric(self, state: dict, messages: list[dict], *, call_type: str, prompt_metadata: dict | None = None, **kwargs) -> str:
        started = time.perf_counter()
        provider_name, model = self._active_provider_info()
        try:
            if hasattr(self.llm_service, "chat_with_metadata"):
                result = self.llm_service.chat_with_metadata(
                    messages,
                    **kwargs,
                    call_type=call_type,
                    agent_name="account_copilot",
                    node_name="planner" if call_type == "planner" else call_type,
                    prompt_metadata=prompt_metadata,
                    run_id=state.get("run_id"),
                    session_id=state.get("session_id"),
                )
                raw = result.content or ""
            else:
                raw = self.llm_service.chat(messages, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._record_llm_metric(state, provider_name, model, call_type, True, latency_ms)
            return raw
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._record_llm_metric(
                state,
                provider_name,
                model,
                call_type,
                False,
                latency_ms,
                error_code=getattr(exc, "error_code", exc.__class__.__name__),
                error_message=str(exc),
            )
            raise

    def _record_llm_metric(
        self,
        state: dict,
        provider_name: str,
        model: str,
        call_type: str,
        ok: bool,
        latency_ms: int,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.monitoring_service is None:
            return
        self.monitoring_service.record_llm_call(
            run_id=state.get("run_id"),
            session_id=state.get("session_id"),
            agent_name="account_copilot",
            node_name="planner" if call_type == "planner" else call_type,
            provider=provider_for_name(provider_name),
            model=model,
            call_type=call_type,
            ok=ok,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            metadata={},
        )

    def _active_provider_info(self) -> tuple[str, str]:
        try:
            provider = self.llm_service.get_active_provider()
        except Exception:
            return "unknown", "unknown"
        if provider is None:
            return "unknown", "unknown"
        return provider.name or "unknown", provider.default_model or "unknown"

    def _observation_from_result(self, action_record: dict, round_index: int, tool_name: str, arguments: dict, result: dict) -> dict:
        data = result.get("data") if isinstance(result, dict) else result
        limitations = list(result.get("data_limitations") or []) if isinstance(result, dict) else []
        data, truncated = self._truncate_data(data)
        if truncated:
            limitations.append("Observation was truncated by Account Copilot runtime.")
        ok = bool(result.get("ok", False)) if isinstance(result, dict) else True
        return {
            "id": f"obs_{uuid4().hex[:12]}",
            "round": round_index,
            "action_id": action_record["id"],
            "tool_name": tool_name,
            "ok": ok,
            "arguments": arguments or {},
            "data": data,
            "data_summary": self._summary(data),
            "data_limitations": limitations,
            "created_at": utc_now_iso(),
        }

    def _action_record(self, action: CopilotPlannerAction, round_index: int) -> dict:
        return {
            "id": f"act_{uuid4().hex[:12]}",
            "run_id": None,
            "session_id": None,
            "round": round_index,
            "action_type": action.action_type,
            "tool_name": action.tool_name,
            "tool_arguments": action.tool_arguments or {},
            "skill_name": action.skill_name,
            "skill_arguments": action.skill_arguments or {},
            "subagent_name": action.subagent_name,
            "subagent_arguments": action.subagent_arguments or {},
            "thought_summary": action.thought_summary,
            "evidence_sufficiency": action.evidence_sufficiency.model_dump(),
            "created_at": utc_now_iso(),
        }

    def _compact_action_event(self, action: dict) -> dict:
        return {
            "id": action.get("id"),
            "round": action.get("round"),
            "action_type": action.get("action_type"),
            "tool_name": action.get("tool_name"),
            "skill_name": action.get("skill_name"),
            "subagent_name": action.get("subagent_name"),
            "thought_summary": action.get("thought_summary"),
            "evidence_sufficiency": action.get("evidence_sufficiency"),
        }

    def _compact_observation_event(self, observation: dict) -> dict:
        return {
            "id": observation.get("id"),
            "round": observation.get("round"),
            "observation_type": observation.get("observation_type"),
            "tool_name": observation.get("tool_name"),
            "skill_name": observation.get("skill_name"),
            "subagent_name": observation.get("subagent_name"),
            "ok": observation.get("ok"),
            "data_summary": observation.get("data_summary"),
            "data_limitations": observation.get("data_limitations") or [],
        }

    def _preview(self, value) -> dict:
        text = json.dumps(value or {}, ensure_ascii=False, default=str)
        if len(text) <= 800:
            return value or {}
        return {"truncated_json": text[:800]}

    def _publish(self, state: dict, event_type: str, payload: dict | None = None) -> None:
        if self.event_bus is None:
            return
        run_id = state.get("run_id")
        session_id = state.get("session_id")
        if not run_id or not session_id:
            return
        self.event_bus.publish(run_id, session_id, event_type, payload or {})

    def _pending_approval(self, action: CopilotPlannerAction, spec, state: dict) -> dict:
        return build_pending_approval(
            run_id=state["run_id"],
            session_id=state["session_id"],
            spec=spec,
            skill_arguments=action.skill_arguments or {},
            approval_message=action.approval_message or f"建议调用 {spec.display_name} Skill。是否继续？",
        )

    def _execute_subagent_action(self, action: CopilotPlannerAction, action_record: dict, round_index: int) -> dict:
        subagent_name = action.subagent_name or ""
        arguments = action.subagent_arguments or {}
        if self.subagent_service is None:
            result = self._subagent_error(subagent_name, arguments, "SUBAGENT_HANDLER_UNAVAILABLE", "SubAgent service is not configured")
        else:
            spec = self.subagent_registry.get(subagent_name)
            if spec is None:
                result = self._subagent_error(subagent_name, arguments, "SUBAGENT_UNKNOWN", "Requested SubAgent is not registered")
            else:
                result = self.subagent_service.execute(spec, arguments)
        return self._subagent_observation_from_result(action_record, round_index, subagent_name, arguments, result)

    def _subagent_observation_from_result(self, action_record: dict, round_index: int, subagent_name: str, arguments: dict, result: dict) -> dict:
        data = result.get("data") if isinstance(result, dict) else result
        limitations = list(result.get("data_limitations") or []) if isinstance(result, dict) else []
        data, truncated = self._truncate_data(data)
        if truncated:
            limitations.append("Observation was truncated by Account Copilot runtime.")
        return {
            "id": f"obs_{uuid4().hex[:12]}",
            "round": round_index,
            "action_id": action_record["id"],
            "observation_type": "subagent_result",
            "subagent_name": subagent_name,
            "ok": bool(result.get("ok", False)) if isinstance(result, dict) else True,
            "arguments": arguments or {},
            "data": data,
            "data_summary": self._summary(data),
            "data_limitations": limitations,
            "metadata": result.get("metadata") if isinstance(result, dict) else {},
            "created_at": utc_now_iso(),
        }

    def _skill_error_observation(self, action_record: dict, round_index: int, action: CopilotPlannerAction, error_code: str) -> dict:
        return {
            "id": f"obs_{uuid4().hex[:12]}",
            "round": round_index,
            "action_id": action_record["id"],
            "observation_type": "skill_request_error",
            "skill_name": action.skill_name,
            "ok": False,
            "arguments": action.skill_arguments or {},
            "data": {},
            "data_summary": error_code,
            "data_limitations": ["Requested Skill is not registered or not approval-required read-only."],
            "created_at": utc_now_iso(),
        }

    def skill_observation_from_result(self, action_id: str | None, skill_name: str, arguments: dict, result: dict) -> dict:
        data = result.get("data") if isinstance(result, dict) else result
        limitations = list(result.get("data_limitations") or []) if isinstance(result, dict) else []
        data, truncated = self._truncate_data(data)
        if truncated:
            limitations.append("Observation was truncated by Account Copilot runtime.")
        return {
            "id": f"obs_{uuid4().hex[:12]}",
            "round": None,
            "action_id": action_id,
            "observation_type": "skill_result",
            "skill_name": skill_name,
            "ok": bool(result.get("ok", False)) if isinstance(result, dict) else True,
            "arguments": arguments or {},
            "data": data,
            "data_summary": self._summary(data),
            "data_limitations": limitations,
            "created_at": utc_now_iso(),
        }

    def _tool_error(self, tool_name: str, arguments: dict, error_code: str, message: str) -> dict:
        return {
            "ok": False,
            "tool": tool_name,
            "arguments": arguments or {},
            "data": {},
            "data_source": "ACCOUNT_COPILOT_RUNTIME",
            "data_limitations": [message],
            "metadata": {"error_code": error_code, "message": message, "read_only": True},
        }

    def _subagent_error(self, subagent_name: str, arguments: dict, error_code: str, message: str) -> dict:
        return {
            "ok": False,
            "subagent": subagent_name,
            "arguments": arguments or {},
            "data": {},
            "data_source": "ACCOUNT_COPILOT_SUBAGENT",
            "data_limitations": [message],
            "metadata": {"error_code": error_code, "message": message, "read_only": True, "approval_required": False},
        }

    def _truncate_data(self, data):
        text = json.dumps(data, ensure_ascii=False, default=str)
        if len(text) <= self.max_observation_chars:
            return data, False
        return {"truncated_json": text[: self.max_observation_chars]}, True

    def _summary(self, data) -> str:
        if isinstance(data, dict):
            return f"object keys={list(data.keys())[:8]}"
        if isinstance(data, list):
            return f"list length={len(data)}"
        return str(data)[:160]

    def _safe_payload(self, payload: dict) -> dict:
        return {key: value for key, value in payload.items() if key not in {"reasoning", "thinking", "chain_of_thought"}}

    def _compact_for_prompt(self, observation: dict) -> dict:
        return {
            "id": observation.get("id"),
            "observation_type": observation.get("observation_type"),
            "tool_name": observation.get("tool_name"),
            "skill_name": observation.get("skill_name"),
            "subagent_name": observation.get("subagent_name"),
            "ok": observation.get("ok"),
            "summary": observation.get("data_summary"),
            "data_limitations": observation.get("data_limitations") or [],
            "data_preview": observation.get("data"),
        }

    def _memory_snapshot(self, state: dict, observations: list[dict]) -> dict:
        existing = dict(state.get("memory_snapshot") or {})
        return {
            **existing,
            "session_id": state.get("session_id"),
            "rolling_summary": state.get("rolling_summary") or "",
            "pinned_facts": state.get("pinned_facts") or {},
            "observation_count": len(observations),
            "retrieved_memory_count": len(state.get("retrieved_memories") or []),
            "non_compressible_constraint_count": len(state.get("non_compressible_constraints") or []),
        }

    def _error(self, code: str, message: str, round_index: int) -> dict:
        return {"code": code, "message": message[:500], "round": round_index, "created_at": utc_now_iso()}

    def _stop_reason(self, state: dict, started_monotonic: float) -> str | None:
        run_id = state.get("run_id")
        if run_id and self.cancel_checker is not None and self.cancel_checker(str(run_id)):
            return "cancelled"
        if self.timeout_seconds is not None and time.monotonic() - started_monotonic >= self.timeout_seconds:
            return "timeout"
        return None
