from __future__ import annotations

from datetime import datetime, timezone

from app.agents.account_copilot.approval import compute_plan_hash
from app.agents.account_copilot.runtime import AccountCopilotRuntime
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.services.account_copilot.event_bus import AccountCopilotEventBus
from app.services.account_copilot.message_service import AccountCopilotMessageService
from app.services.account_copilot.monitoring_service import AccountCopilotMonitoringService
from app.services.account_copilot.run_service import AccountCopilotRunService
from app.services.account_copilot.session_service import AccountCopilotSessionService
from app.services.account_copilot.skill_service import AccountCopilotSkillService
from app.services.llm_service import LLMService

APPROVAL_REJECTED_MESSAGE = (
    "已取消调用该 Skill。由于该分析需要该 Skill 才能完整完成，我不会编造结论。"
    "你可以改问更具体的账户事实问题。"
)
APPROVAL_EXPIRED_MESSAGE = "该 Skill 审批已过期，请重新发起分析。"


class AccountCopilotApprovalError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountCopilotApprovalService:
    def __init__(
        self,
        run_service: AccountCopilotRunService,
        message_service: AccountCopilotMessageService,
        session_service: AccountCopilotSessionService,
        skill_registry: AccountCopilotSkillRegistry,
        skill_service: AccountCopilotSkillService,
        llm_service: LLMService,
        tool_registry: AccountCopilotToolRegistry,
        event_bus: AccountCopilotEventBus | None = None,
        monitoring_service: AccountCopilotMonitoringService | None = None,
    ) -> None:
        self.run_service = run_service
        self.message_service = message_service
        self.session_service = session_service
        self.skill_registry = skill_registry
        self.skill_service = skill_service
        self.llm_service = llm_service
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self.monitoring_service = monitoring_service

    def handle_approval(
        self,
        *,
        run_id: str,
        approval_id: str,
        approved: bool,
        plan_hash: str,
        comment: str | None = None,
    ) -> dict:
        run = self.run_service.get_run(run_id)
        if run is None:
            raise AccountCopilotApprovalError(404, "Account Copilot run not found")
        pending = dict(run.get("pending_approval") or {})
        self._validate_pending(run, pending, approval_id, plan_hash)
        if self._is_expired(pending):
            self._expire(run, pending)
            raise AccountCopilotApprovalError(400, "Approval has expired")

        if not approved:
            return self._reject(run, pending, comment)
        return self.approve_only(run, pending, comment)

    def approve_only(self, run: dict, pending: dict, comment: str | None) -> dict:
        now = utc_now_iso()
        pending.update({"status": "approved", "approved_at": now, "updated_at": now, "comment": comment})
        self.run_service.update_run_fields(run["id"], {"status": "running", "pending_approval": pending})
        self._publish(run, "skill_approval_approved", {"pending_approval": pending})
        updated_run = self.run_service.get_run(run["id"]) or run
        return {"run": updated_run, "assistant_message": None}

    def execute_approved_skill(self, run_id: str, approval_id: str) -> None:
        try:
            run = self.run_service.get_run(run_id)
            if run is None:
                return
            pending = dict(run.get("pending_approval") or {})
            if pending.get("approval_id") != approval_id:
                return
            if pending.get("status") != "approved":
                return
            pending["execution_status"] = "running"
            pending["updated_at"] = utc_now_iso()
            self.run_service.update_run_fields(run_id, {"pending_approval": pending})
            self._do_execute_skill(run, pending)
        except Exception as exc:
            try:
                self._handle_execution_failure(run_id, str(exc)[:500])
            except Exception:
                pass

    def _do_execute_skill(self, run: dict, pending: dict) -> None:
        spec = self.skill_registry.get(pending.get("skill_name"))
        if spec is None:
            result = {
                "ok": False,
                "skill": pending.get("skill_name"),
                "arguments": pending.get("skill_arguments") or {},
                "data": {},
                "data_source": "ACCOUNT_COPILOT_SKILL",
                "data_limitations": ["Skill is not registered."],
                "metadata": {"read_only": True, "error_code": "SKILL_NOT_FOUND", "approval_id": pending["approval_id"]},
            }
        else:
            self._publish(run, "skill_started", {"skill_name": spec.name, "arguments_preview": pending.get("skill_arguments") or {}})
            result = self.skill_service.execute(spec, pending.get("skill_arguments") or {}, pending)
        self._publish(
            run,
            "skill_finished" if result.get("ok") else "skill_failed",
            {
                "skill_name": pending.get("skill_name"),
                "ok": bool(result.get("ok")),
                "data_summary": self._summary(result.get("data")),
                "data_limitations": result.get("data_limitations") or [],
            },
        )

        action_id = self._approval_action_id(run, pending["approval_id"])
        runtime = AccountCopilotRuntime(
            llm_service=self.llm_service,
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            event_bus=self.event_bus,
            monitoring_service=self.monitoring_service,
        )
        observation = runtime.skill_observation_from_result(
            action_id,
            pending.get("skill_name") or "",
            pending.get("skill_arguments") or {},
            result,
        )
        self._publish(run, "observation_created", {"observation": runtime._compact_observation_event(observation)})
        pending.update(
            {
                "status": "executed" if result.get("ok") else "failed",
                "executed_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
                "result_observation_id": observation["id"],
            }
        )
        state = {
            **run,
            "pending_approval": pending,
            "observations": [*(run.get("observations") or []), observation],
            "messages": self.message_service.list_messages(run["session_id"], limit=20),
        }
        composed = runtime.compose_final_answer_after_approval(state, observation)
        final_answer = composed.get("final_answer") or "Skill 已执行，但无法生成最终回答。"
        assistant_message = self.message_service.create_message(
            session_id=run["session_id"],
            role="assistant",
            content=final_answer,
            run_id=run["id"],
            metadata={"approval_id": pending["approval_id"], "approval_status": pending["status"]},
        )
        payload = {
            "planner_output": composed.get("planner_output") or run.get("planner_output") or {},
            "actions": run.get("actions") or [],
            "observations": composed.get("observations") or state["observations"],
            "tool_calls": run.get("tool_calls") or [],
            "skill_requests": self._updated_skill_requests(run, pending, pending["status"]),
            "pending_approval": pending,
            "memory_snapshot": run.get("memory_snapshot") or {},
            "metadata": {**(run.get("metadata") or {}), **(composed.get("metadata") or {}), "approval_executed": True},
        }
        saved = self.run_service.mark_run_completed(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=final_answer,
            payload=payload,
        )
        self._publish(run, "run_completed", {"approval_status": pending["status"]})
        self.session_service.touch_after_messages(run["session_id"], message_count=1, last_message_at=assistant_message["created_at"])

    def _handle_execution_failure(self, run_id: str, error_message: str) -> None:
        run = self.run_service.get_run(run_id)
        if run is None:
            return
        pending = dict(run.get("pending_approval") or {})
        pending["status"] = "failed"
        pending["updated_at"] = utc_now_iso()
        fallback_answer = "Skill 执行失败，无法生成最终回答。"
        assistant_message = self.message_service.create_message(
            session_id=run["session_id"],
            role="assistant",
            content=fallback_answer,
            run_id=run["id"],
            metadata={"approval_id": pending.get("approval_id"), "approval_status": "failed", "error_message": error_message},
        )
        self.run_service.mark_run_failed(run_id, "SKILL_EXECUTION_ERROR", error_message)
        self.run_service.update_run_fields(run_id, {"pending_approval": pending})
        self._publish(run, "skill_failed", {"skill_name": pending.get("skill_name"), "ok": False, "error_message": error_message})
        self._publish(run, "run_failed", {"error_code": "SKILL_EXECUTION_ERROR"})
        self.session_service.touch_after_messages(run["session_id"], message_count=1, last_message_at=assistant_message["created_at"])

    def _validate_pending(self, run: dict, pending: dict, approval_id: str, plan_hash: str) -> None:
        if run.get("status") == "cancelled":
            raise AccountCopilotApprovalError(400, "Run has been cancelled")
        if run.get("status") != "awaiting_approval":
            raise AccountCopilotApprovalError(400, "Run is not awaiting approval")
        if not pending:
            raise AccountCopilotApprovalError(400, "Run has no pending approval")
        if pending.get("status") != "pending":
            raise AccountCopilotApprovalError(400, "Approval is not pending")
        if pending.get("approval_id") != approval_id:
            raise AccountCopilotApprovalError(400, "Approval id does not match")
        expected = compute_plan_hash(
            run["id"],
            pending["approval_id"],
            pending["skill_name"],
            pending.get("skill_arguments") or {},
        )
        if pending.get("plan_hash") != expected or plan_hash != expected:
            raise AccountCopilotApprovalError(400, "Approval plan hash does not match")

    def _expire(self, run: dict, pending: dict) -> dict | None:
        now = utc_now_iso()
        pending.update({"status": "expired", "updated_at": now})
        assistant_message = self.message_service.create_message(
            session_id=run["session_id"],
            role="assistant",
            content=APPROVAL_EXPIRED_MESSAGE,
            run_id=run["id"],
            metadata={"approval_id": pending.get("approval_id"), "approval_status": "expired"},
        )
        saved = self.run_service.mark_run_completed(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=APPROVAL_EXPIRED_MESSAGE,
            payload={
                "pending_approval": pending,
                "skill_requests": self._updated_skill_requests(run, pending, "expired"),
                "metadata": {**(run.get("metadata") or {}), "approval_expired": True},
            },
        )
        self._publish(run, "skill_approval_rejected", {"pending_approval": pending, "reason": "expired"})
        self._publish(run, "run_completed", {"approval_status": "expired"})
        self.session_service.touch_after_messages(run["session_id"], message_count=1, last_message_at=assistant_message["created_at"])
        return saved

    def _is_expired(self, pending: dict) -> bool:
        raw = pending.get("expires_at")
        if not raw:
            return False
        try:
            expires_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return expires_at <= datetime.now(timezone.utc)
        except ValueError:
            return False

    def _reject(self, run: dict, pending: dict, comment: str | None) -> dict:
        now = utc_now_iso()
        pending.update({"status": "rejected", "rejected_at": now, "updated_at": now, "comment": comment})
        self._publish(run, "skill_approval_rejected", {"pending_approval": pending})
        assistant_message = self.message_service.create_message(
            session_id=run["session_id"],
            role="assistant",
            content=APPROVAL_REJECTED_MESSAGE,
            run_id=run["id"],
            metadata={"approval_id": pending["approval_id"], "approval_status": "rejected"},
        )
        payload = {
            "pending_approval": pending,
            "skill_requests": self._updated_skill_requests(run, pending, "rejected"),
            "metadata": {**(run.get("metadata") or {}), "approval_rejected": True},
        }
        saved = self.run_service.mark_run_completed(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=APPROVAL_REJECTED_MESSAGE,
            payload=payload,
        )
        self._publish(run, "final_answer", {"content": APPROVAL_REJECTED_MESSAGE})
        self._publish(run, "run_completed", {"approval_status": "rejected"})
        self.session_service.touch_after_messages(run["session_id"], message_count=1, last_message_at=assistant_message["created_at"])
        return {"run": saved, "assistant_message": assistant_message}

    def _approve_and_execute(self, run: dict, pending: dict, comment: str | None) -> dict:
        now = utc_now_iso()
        pending.update({"status": "approved", "approved_at": now, "updated_at": now, "comment": comment})
        self.run_service.update_run_fields(run["id"], {"status": "running", "pending_approval": pending})
        self._publish(run, "skill_approval_approved", {"pending_approval": pending})

        spec = self.skill_registry.get(pending.get("skill_name"))
        if spec is None:
            result = {
                "ok": False,
                "skill": pending.get("skill_name"),
                "arguments": pending.get("skill_arguments") or {},
                "data": {},
                "data_source": "ACCOUNT_COPILOT_SKILL",
                "data_limitations": ["Skill is not registered."],
                "metadata": {"read_only": True, "error_code": "SKILL_NOT_FOUND", "approval_id": pending["approval_id"]},
            }
        else:
            self._publish(run, "skill_started", {"skill_name": spec.name, "arguments_preview": pending.get("skill_arguments") or {}})
            result = self.skill_service.execute(spec, pending.get("skill_arguments") or {}, pending)
        self._publish(
            run,
            "skill_finished" if result.get("ok") else "skill_failed",
            {
                "skill_name": pending.get("skill_name"),
                "ok": bool(result.get("ok")),
                "data_summary": self._summary(result.get("data")),
                "data_limitations": result.get("data_limitations") or [],
            },
        )

        action_id = self._approval_action_id(run, pending["approval_id"])
        runtime = AccountCopilotRuntime(
            llm_service=self.llm_service,
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            event_bus=self.event_bus,
            monitoring_service=self.monitoring_service,
        )
        observation = runtime.skill_observation_from_result(
            action_id,
            pending.get("skill_name") or "",
            pending.get("skill_arguments") or {},
            result,
        )
        self._publish(run, "observation_created", {"observation": runtime._compact_observation_event(observation)})
        pending.update(
            {
                "status": "executed" if result.get("ok") else "failed",
                "executed_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
                "result_observation_id": observation["id"],
            }
        )
        state = {
            **run,
            "pending_approval": pending,
            "observations": [*(run.get("observations") or []), observation],
            "messages": self.message_service.list_messages(run["session_id"], limit=20),
        }
        composed = runtime.compose_final_answer_after_approval(state, observation)
        final_answer = composed.get("final_answer") or "Skill 已执行，但无法生成最终回答。"
        assistant_message = self.message_service.create_message(
            session_id=run["session_id"],
            role="assistant",
            content=final_answer,
            run_id=run["id"],
            metadata={"approval_id": pending["approval_id"], "approval_status": pending["status"]},
        )
        payload = {
            "planner_output": composed.get("planner_output") or run.get("planner_output") or {},
            "actions": run.get("actions") or [],
            "observations": composed.get("observations") or state["observations"],
            "tool_calls": run.get("tool_calls") or [],
            "skill_requests": self._updated_skill_requests(run, pending, pending["status"]),
            "pending_approval": pending,
            "memory_snapshot": run.get("memory_snapshot") or {},
            "metadata": {**(run.get("metadata") or {}), **(composed.get("metadata") or {}), "approval_executed": True},
        }
        saved = self.run_service.mark_run_completed(
            run_id=run["id"],
            assistant_message_id=assistant_message["id"],
            final_answer=final_answer,
            payload=payload,
        )
        self._publish(run, "run_completed", {"approval_status": pending["status"]})
        self.session_service.touch_after_messages(run["session_id"], message_count=1, last_message_at=assistant_message["created_at"])
        return {"run": saved, "assistant_message": assistant_message}

    def _updated_skill_requests(self, run: dict, pending: dict, status: str) -> list[dict]:
        updated = []
        matched = False
        for request in run.get("skill_requests") or []:
            item = dict(request)
            if item.get("approval_id") == pending.get("approval_id"):
                item.update(pending)
                item["status"] = status
                matched = True
            updated.append(item)
        if not matched:
            updated.append({**pending, "status": status})
        return updated

    def _approval_action_id(self, run: dict, approval_id: str) -> str | None:
        for request in run.get("skill_requests") or []:
            if request.get("approval_id") == approval_id:
                return request.get("action_id")
        return None

    def _publish(self, run: dict, event_type: str, payload: dict) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(run["id"], run["session_id"], event_type, payload)

    def _summary(self, data) -> str:
        if isinstance(data, dict):
            return f"object keys={list(data.keys())[:8]}"
        if isinstance(data, list):
            return f"list length={len(data)}"
        return str(data or "")[:160]
