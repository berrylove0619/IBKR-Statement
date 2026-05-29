from __future__ import annotations

from app.agents.account_copilot.approval import compute_plan_hash
from app.agents.account_copilot.demo_fixtures import DEMO_MEMORY, DEMO_RUN_EVENTS
from app.services.account_copilot.event_bus import AccountCopilotEventBus
from app.services.account_copilot.memory_repository import AccountCopilotMemoryRepository
from app.services.account_copilot.repository import AccountCopilotRepository


class AccountCopilotDemoService:
    def __init__(
        self,
        repository: AccountCopilotRepository,
        memory_repository: AccountCopilotMemoryRepository,
        event_bus: AccountCopilotEventBus,
    ) -> None:
        self.repository = repository
        self.memory_repository = memory_repository
        self.event_bus = event_bus

    def seed(self) -> dict:
        session = self.repository.create_session("Account Copilot Demo")
        session_id = session["id"]
        risk_run, risk_messages = self._completed_risk_run(session_id)
        longbridge_run, longbridge_messages = self._completed_longbridge_run(session_id)
        approval_run, approval_messages = self._awaiting_approval_run(session_id)
        memory = self.memory_repository.create_memory(
            session_id=session_id,
            memory_type="conversation_segment",
            payload={
                **DEMO_MEMORY,
                "message_start_id": risk_messages[0]["id"],
                "message_end_id": longbridge_messages[-1]["id"],
                "message_count": 4,
                "message_range_created_at": {"start": risk_messages[0]["created_at"], "end": longbridge_messages[-1]["created_at"]},
                "source_run_ids": [risk_run["id"], longbridge_run["id"]],
                "source_message_ids": [message["id"] for message in [*risk_messages, *longbridge_messages]],
                "metadata": {"demo": True},
            },
        )
        self.repository.update_session_memory(
            session_id,
            rolling_summary=f"- {memory['summary']}",
            compressed_until_message_id=longbridge_messages[-1]["id"],
            pinned_facts={"non_compressible_constraints": DEMO_MEMORY["non_compressible_constraints"], "user_preferences": DEMO_MEMORY["user_preferences"]},
        )
        self.repository.touch_session(session_id, message_count_delta=6, last_message_at=approval_messages[-1]["created_at"])
        session = self.repository.get_session(session_id) or session
        return {
            "session": session,
            "messages": [*risk_messages, *longbridge_messages, *approval_messages],
            "runs": [risk_run, longbridge_run, approval_run],
            "memories": [memory],
        }

    def _completed_risk_run(self, session_id: str) -> tuple[dict, list[dict]]:
        user = self.repository.create_message(session_id, "user", "我现在账户风险高不高？")
        run = self.repository.create_run(session_id, user["id"], user["content"])
        user = self.repository.update_message_run_id(user["id"], run["id"]) or user
        assistant = self.repository.create_message(
            session_id,
            "assistant",
            "Demo：当前账户风险中等偏高，主要来自半导体仓位集中。建议继续查看最大持仓和现金比例，不要把这当成确定性交易指令。",
            run_id=run["id"],
        )
        payload = {
            "planner_output": {"raw_action": {"action_type": "final_answer"}, "latency_ms": 120, "repaired": False},
            "actions": [
                {"id": "act_demo_risk_1", "round": 1, "action_type": "call_tool", "tool_name": "ibkr_get_risk_snapshot", "thought_summary": "先读取账户风险快照。"},
                {"id": "act_demo_risk_2", "round": 2, "action_type": "final_answer", "thought_summary": "已有风险证据，可以回答。"},
            ],
            "observations": [
                {
                    "id": "obs_demo_risk",
                    "round": 1,
                    "action_id": "act_demo_risk_1",
                    "tool_name": "ibkr_get_risk_snapshot",
                    "ok": True,
                    "data": {"largest_position_pct": 0.28, "top_3_position_pct": 0.61, "cash_pct": 0.18},
                    "data_summary": "账户集中度偏高，现金比例中等。",
                    "data_limitations": ["Demo mock data."],
                }
            ],
            "tool_calls": [{"id": "tool_demo_risk", "round": 1, "tool_name": "ibkr_get_risk_snapshot", "arguments": {}, "ok": True, "latency_ms": 31}],
            "memory_snapshot": {"retrieved_memory_count": 0, "recent_message_count": 0, "context_layers": ["L1_recent", "L2_summary"]},
            "metadata": {"demo": True, "fallback_used": False},
        }
        run = self.repository.mark_run_completed(run["id"], assistant["id"], assistant["content"], payload) or run
        self._publish_events(run, "risk")
        return run, [user, assistant]

    def _completed_longbridge_run(self, session_id: str) -> tuple[dict, list[dict]]:
        user = self.repository.create_message(session_id, "user", "AMD 最近为什么涨跌，市场上有什么公开信息？")
        run = self.repository.create_run(session_id, user["id"], user["content"])
        user = self.repository.update_message_run_id(user["id"], run["id"]) or user
        assistant = self.repository.create_message(
            session_id,
            "assistant",
            "Demo：AMD 近期波动与 AI 需求预期、同业估值变化和公开新闻催化有关。长桥工具通过 meta tools 渐进式披露，没有暴露账户或交易工具。",
            run_id=run["id"],
        )
        tool_calls = [
            {"id": "tool_demo_lb_1", "round": 1, "tool_name": "longbridge_list_public_tools", "arguments": {"query": "AMD news"}, "ok": True, "latency_ms": 25},
            {"id": "tool_demo_lb_2", "round": 2, "tool_name": "longbridge_get_public_tool_schema", "arguments": {"tool_name": "quote"}, "ok": True, "latency_ms": 22},
            {"id": "tool_demo_lb_3", "round": 3, "tool_name": "longbridge_call_public_tool", "arguments": {"tool_name": "quote", "arguments": {"symbol": "AMD.US"}}, "ok": True, "latency_ms": 36},
        ]
        payload = {
            "planner_output": {"raw_action": {"action_type": "final_answer"}, "latency_ms": 160, "repaired": False},
            "actions": [
                {"id": "act_demo_lb_1", "round": 1, "action_type": "call_tool", "tool_name": "longbridge_list_public_tools", "thought_summary": "先发现可用公开市场工具。"},
                {"id": "act_demo_lb_2", "round": 2, "action_type": "call_tool", "tool_name": "longbridge_get_public_tool_schema", "thought_summary": "获取公开行情工具 schema。"},
                {"id": "act_demo_lb_3", "round": 3, "action_type": "call_tool", "tool_name": "longbridge_call_public_tool", "thought_summary": "调用确认过的公开市场工具。"},
                {"id": "act_demo_lb_4", "round": 4, "action_type": "final_answer", "thought_summary": "公开信息足够，生成回答。"},
            ],
            "observations": [
                {"id": "obs_demo_lb", "round": 3, "tool_name": "longbridge_call_public_tool", "ok": True, "data_summary": "AMD public market demo", "data_limitations": ["Demo mock data."]}
            ],
            "tool_calls": tool_calls,
            "memory_snapshot": {"retrieved_memory_count": 1, "recent_message_count": 2},
            "metadata": {"demo": True, "fallback_used": False},
        }
        run = self.repository.mark_run_completed(run["id"], assistant["id"], assistant["content"], payload) or run
        self._publish_events(run, "longbridge")
        return run, [user, assistant]

    def _awaiting_approval_run(self, session_id: str) -> tuple[dict, list[dict]]:
        user = self.repository.create_message(session_id, "user", "MU 现在适合建仓吗？")
        run = self.repository.create_run(session_id, user["id"], user["content"])
        user = self.repository.update_message_run_id(user["id"], run["id"]) or user
        pending = {
            "approval_id": "approval_demo_mu",
            "run_id": run["id"],
            "session_id": session_id,
            "skill_name": "trade_decision_entry_skill",
            "skill_display_name": "交易决策-建仓分析",
            "skill_arguments": {"symbol": "MU.US", "question": "MU 现在适合建仓吗？"},
            "approval_message": "Demo：建议调用【交易决策-建仓分析】Skill。它会读取账户事实和公开市场数据，是否继续？",
            "plan_hash": "",
            "status": "pending",
            "data_access": ["IBKR account facts", "Longbridge public market data"],
        }
        pending["plan_hash"] = compute_plan_hash(run["id"], pending["approval_id"], pending["skill_name"], pending["skill_arguments"])
        assistant = self.repository.create_message(session_id, "assistant", pending["approval_message"], run_id=run["id"], metadata={"approval_id": pending["approval_id"]})
        payload = {
            "planner_output": {"raw_action": {"action_type": "request_skill_approval", "skill_name": pending["skill_name"]}, "latency_ms": 110, "repaired": False},
            "actions": [{"id": "act_demo_skill", "round": 1, "action_type": "request_skill_approval", "skill_name": pending["skill_name"], "skill_arguments": pending["skill_arguments"], "thought_summary": "建仓分析需要高阶 Skill，先请求审批。"}],
            "skill_requests": [{**pending, "action_id": "act_demo_skill", "round": 1}],
            "pending_approval": pending,
            "memory_snapshot": {"retrieved_memory_count": 1, "recent_message_count": 4},
            "metadata": {"demo": True, "requires_approval": True, "approval_id": pending["approval_id"]},
        }
        run = self.repository.mark_run_awaiting_approval(run["id"], assistant["id"], assistant["content"], pending, payload) or run
        self._publish_events(run, "approval")
        self.event_bus.publish(run["id"], session_id, "skill_approval_requested", {"pending_approval": pending})
        return run, [user, assistant]

    def _publish_events(self, run: dict, fixture_name: str) -> None:
        for event_type, payload in DEMO_RUN_EVENTS.get(fixture_name, []):
            self.event_bus.publish(run["id"], run["session_id"], event_type, payload)
