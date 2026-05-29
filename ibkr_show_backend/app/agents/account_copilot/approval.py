from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.agents.account_copilot.skill_registry import AccountCopilotSkillSpec


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: dict) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def compute_plan_hash(run_id: str, approval_id: str, skill_name: str, skill_arguments: dict) -> str:
    material = f"{skill_name}|{canonical_json(skill_arguments)}|{run_id}|{approval_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_pending_approval(
    *,
    run_id: str,
    session_id: str,
    spec: AccountCopilotSkillSpec,
    skill_arguments: dict,
    approval_message: str,
    ttl_minutes: int = 30,
) -> dict:
    now = datetime.now(timezone.utc)
    approval_id = f"approval_{uuid4().hex[:12]}"
    plan_hash = compute_plan_hash(run_id, approval_id, spec.name, skill_arguments)
    return {
        "approval_id": approval_id,
        "run_id": run_id,
        "session_id": session_id,
        "skill_name": spec.name,
        "skill_display_name": spec.display_name,
        "skill_arguments": skill_arguments or {},
        "approval_message": approval_message,
        "plan_hash": plan_hash,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        "approved_at": None,
        "rejected_at": None,
        "executed_at": None,
        "result_observation_id": None,
        "data_access": list(spec.data_access or []),
    }
