from __future__ import annotations


class AccountCopilotSkillApprovalBroker:
    """Coordinates future user approval for skill execution requests."""

    def request_approval(self, *, run_id: str, skill_name: str, arguments: dict) -> dict:
        # TODO: Persist approval request and pause run in awaiting_approval state.
        return {
            "run_id": run_id,
            "skill_name": skill_name,
            "arguments": arguments,
            "status": "not_implemented",
        }
