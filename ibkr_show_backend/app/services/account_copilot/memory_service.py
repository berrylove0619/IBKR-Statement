from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.account_copilot.memory_manager import estimate_context_chars, extract_symbols, extract_topics
from app.agents.account_copilot.memory_prompts import build_memory_compression_messages
from app.agents.account_copilot.memory_schema import MemoryCompressionOutput
from app.services.account_copilot.memory_repository import AccountCopilotMemoryRepository
from app.services.account_copilot.repository import AccountCopilotRepository
from app.services.llm_service import LLMService


class AccountCopilotMemoryService:
    def __init__(
        self,
        repository: AccountCopilotRepository,
        memory_repository: AccountCopilotMemoryRepository,
        llm_service: LLMService,
        recent_message_count: int = 8,
        segment_message_count: int = 8,
        compression_message_threshold: int = 12,
        uncompressed_message_threshold: int = 10,
        max_context_chars: int = 40000,
    ) -> None:
        self.repository = repository
        self.memory_repository = memory_repository
        self.llm_service = llm_service
        self.recent_message_count = recent_message_count
        self.segment_message_count = segment_message_count
        self.compression_message_threshold = compression_message_threshold
        self.uncompressed_message_threshold = uncompressed_message_threshold
        self.max_context_chars = max_context_chars

    def load_context_for_run(self, session_id: str, user_input: str) -> dict:
        session = self.repository.get_session(session_id) or {}
        recent_messages = self.repository.list_messages(session_id, limit=1000)[-self.recent_message_count :]
        retrieved = self.retrieve_relevant_memories(session_id, user_input, limit=8)
        constraints = self._collect_constraints(session, retrieved)
        return {
            "rolling_summary": session.get("rolling_summary") or "",
            "pinned_facts": session.get("pinned_facts") or {},
            "non_compressible_constraints": constraints,
            "retrieved_memories": retrieved,
            "recent_messages": recent_messages,
            "memory_snapshot": {
                "memory_index": getattr(self.memory_repository.settings, "es_copilot_memory_index", ""),
                "retrieved_memory_count": len(retrieved),
                "recent_message_count": len(recent_messages),
                "rolling_summary_chars": len(session.get("rolling_summary") or ""),
                "compressed_until_message_id": session.get("compressed_until_message_id"),
                "context_layers": ["L0_messages", "L1_recent", "L2_summary", "L3_retrieved", "L4_constraints"],
            },
        }

    def maybe_update_after_run(self, session_id: str, run_id: str) -> dict:
        try:
            result = self.maybe_compress_session(session_id)
            return {"ok": True, **result, "run_id": run_id}
        except Exception as exc:
            return {"ok": False, "run_id": run_id, "error": str(exc)[:500]}

    def maybe_compress_session(self, session_id: str) -> dict:
        session = self.repository.get_session(session_id)
        if session is None:
            return {"compressed": False, "reason": "session_not_found"}
        messages = self.repository.list_messages(session_id, limit=1000)
        if not self._should_compress(session, messages):
            return {"compressed": False, "reason": "threshold_not_met"}
        segment = self._next_uncompressed_segment(session, messages)
        if not segment:
            return {"compressed": False, "reason": "no_segment"}
        memory = self.compress_message_segment(session_id, segment, self._runs_for_messages(segment), session.get("rolling_summary") or "")
        self.update_session_summary(session_id)
        return {"compressed": True, "memory_id": memory["id"], "message_end_id": memory.get("message_end_id")}

    def compress_message_segment(self, session_id: str, messages: list[dict], runs: list[dict], rolling_summary: str = "") -> dict:
        raw = self.llm_service.chat(
            build_memory_compression_messages(messages, runs, rolling_summary),
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        payload = self._parse_json(raw)
        output = MemoryCompressionOutput(**payload)
        source_run_ids = sorted({message.get("run_id") for message in messages if message.get("run_id")})
        source_message_ids = [message["id"] for message in messages if message.get("id")]
        return self.memory_repository.create_memory(
            session_id=session_id,
            memory_type="conversation_segment",
            payload={
                **output.model_dump(),
                "message_start_id": messages[0]["id"],
                "message_end_id": messages[-1]["id"],
                "message_count": len(messages),
                "message_range_created_at": {"start": messages[0].get("created_at"), "end": messages[-1].get("created_at")},
                "source_run_ids": source_run_ids,
                "source_message_ids": source_message_ids,
                "metadata": {"compression_model": "llm_service", "raw_message_count": len(messages)},
            },
        )

    def retrieve_relevant_memories(self, session_id: str, user_input: str, limit: int = 8) -> list[dict]:
        return self.memory_repository.retrieve_relevant(
            session_id,
            symbols=extract_symbols(user_input),
            topics=extract_topics(user_input),
            query=user_input,
            limit=limit,
        )

    def update_session_summary(self, session_id: str) -> dict | None:
        memories = self.memory_repository.list_memories(session_id, limit=100)
        if not memories:
            return self.repository.update_session_memory(session_id, rolling_summary="", compressed_until_message_id=None, pinned_facts={})
        chronological = sorted(memories, key=lambda item: item.get("message_range_created_at", {}).get("end") or item.get("created_at") or "")
        rolling_summary = "\n".join(f"- {memory.get('summary')}" for memory in chronological if memory.get("summary"))[:12000]
        last = chronological[-1]
        pinned_facts = self._build_pinned_facts(chronological)
        return self.repository.update_session_memory(
            session_id,
            rolling_summary=rolling_summary,
            compressed_until_message_id=last.get("message_end_id"),
            pinned_facts=pinned_facts,
        )

    def list_memories(self, session_id: str, limit: int = 20, memory_type: str | None = None) -> list[dict]:
        return self.memory_repository.list_memories(session_id=session_id, limit=limit, memory_type=memory_type)

    def rebuild_session_memory(self, session_id: str) -> dict:
        return self.maybe_compress_session(session_id)

    def _should_compress(self, session: dict, messages: list[dict]) -> bool:
        if not messages:
            return False
        uncompressed = self._uncompressed_messages(session, messages)
        old_enough = max(0, len(uncompressed) - self.recent_message_count)
        return (
            int(session.get("message_count") or len(messages)) >= self.compression_message_threshold and old_enough > 0
        ) or old_enough > self.uncompressed_message_threshold or estimate_context_chars(uncompressed) > self.max_context_chars

    def _next_uncompressed_segment(self, session: dict, messages: list[dict]) -> list[dict]:
        uncompressed = self._uncompressed_messages(session, messages)
        candidates = uncompressed[: max(0, len(uncompressed) - self.recent_message_count)]
        return candidates[: self.segment_message_count]

    def _uncompressed_messages(self, session: dict, messages: list[dict]) -> list[dict]:
        compressed_until = session.get("compressed_until_message_id")
        if not compressed_until:
            return messages
        for index, message in enumerate(messages):
            if message.get("id") == compressed_until:
                return messages[index + 1 :]
        return messages

    def _runs_for_messages(self, messages: list[dict]) -> list[dict]:
        runs = []
        seen = set()
        for message in messages:
            run_id = message.get("run_id")
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)
            run = self.repository.get_run(run_id)
            if run is not None:
                runs.append(run)
        return runs

    def _collect_constraints(self, session: dict, memories: list[dict]) -> list[str]:
        constraints = []
        for value in (session.get("pinned_facts") or {}).get("non_compressible_constraints", []):
            if value not in constraints:
                constraints.append(value)
        for memory in memories:
            for value in memory.get("non_compressible_constraints") or []:
                if value not in constraints:
                    constraints.append(value)
        return constraints

    def _build_pinned_facts(self, memories: list[dict]) -> dict[str, Any]:
        preferences = []
        constraints = [
            "涉及交易建议时必须说明风险",
            "不要把分析结果表述成确定性交易指令",
        ]
        for memory in memories:
            for value in memory.get("user_preferences") or []:
                if value not in preferences:
                    preferences.append(value)
            for value in memory.get("non_compressible_constraints") or []:
                if value not in constraints:
                    constraints.append(value)
        return {"user_preferences": preferences[-20:], "non_compressible_constraints": constraints[-20:]}

    def _parse_json(self, raw: str) -> dict:
        raw = str(raw or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Memory compression output is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Memory compression output must be a JSON object")
        try:
            MemoryCompressionOutput(**value)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return value
