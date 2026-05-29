from __future__ import annotations

import json

MEMORY_COMPRESSION_SYSTEM_PROMPT = """
You compress Account Copilot conversation history into structured memory.
Preserve useful history, user preferences, open questions, and compact tool/skill facts.
Do not invent account facts. IBKR tools are the source of truth for current account facts.
Do not save hidden chain-of-thought. Keep only concise summaries and facts.
Return strict JSON with exactly the requested schema. Use empty strings or arrays when absent.
""".strip()

MEMORY_COMPRESSION_SCHEMA_HINT = {
    "summary": "string",
    "symbols": ["AMD"],
    "topics": ["risk", "trade_decision"],
    "user_intent": "string",
    "important_facts": ["string"],
    "user_preferences": ["string"],
    "open_questions": ["string"],
    "tool_facts": [{"tool": "name", "symbol": "optional", "fact_summary": "string", "source_run_id": "optional"}],
    "skill_facts": [{"skill": "name", "symbol": "optional", "result_summary": "string", "source_run_id": "optional"}],
    "non_compressible_constraints": ["string"],
}


def build_memory_compression_messages(messages: list[dict], runs: list[dict], rolling_summary: str = "") -> list[dict[str, str]]:
    payload = {
        "existing_rolling_summary": rolling_summary,
        "messages": [_message_item(item) for item in messages],
        "run_summaries": [_run_item(item) for item in runs],
        "schema": MEMORY_COMPRESSION_SCHEMA_HINT,
    }
    return [
        {"role": "system", "content": MEMORY_COMPRESSION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Compress this Account Copilot history segment into structured memory. Return only JSON.\n\n"
            + json.dumps(payload, ensure_ascii=False, default=str),
        },
    ]


def _message_item(message: dict) -> dict:
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "content": str(message.get("content") or "")[:4000],
        "created_at": message.get("created_at"),
        "run_id": message.get("run_id"),
    }


def _run_item(run: dict) -> dict:
    return {
        "id": run.get("id"),
        "status": run.get("status"),
        "final_answer": str(run.get("final_answer") or "")[:2000],
        "actions": [_compact_action(item) for item in (run.get("actions") or [])[-6:]],
        "observations": [_compact_observation(item) for item in (run.get("observations") or [])[-6:]],
        "skill_requests": [
            {
                "skill_name": item.get("skill_name"),
                "status": item.get("status"),
                "skill_arguments": item.get("skill_arguments") or {},
            }
            for item in (run.get("skill_requests") or [])[-4:]
        ],
    }


def _compact_action(action: dict) -> dict:
    return {
        "action_type": action.get("action_type"),
        "tool_name": action.get("tool_name"),
        "skill_name": action.get("skill_name"),
        "thought_summary": action.get("thought_summary"),
    }


def _compact_observation(observation: dict) -> dict:
    return {
        "observation_type": observation.get("observation_type"),
        "tool_name": observation.get("tool_name"),
        "skill_name": observation.get("skill_name"),
        "ok": observation.get("ok"),
        "summary": observation.get("data_summary"),
        "data_limitations": observation.get("data_limitations") or [],
    }
