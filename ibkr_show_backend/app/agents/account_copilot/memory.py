from __future__ import annotations


class AccountCopilotMemoryManager:
    """Builds and updates memory snapshots for Account Copilot runs."""

    def build_snapshot(self, *, session: dict, messages: list[dict]) -> dict:
        # TODO: Add rolling-summary and compression-aware memory selection.
        return {
            "session_id": session.get("id"),
            "rolling_summary": session.get("rolling_summary") or "",
            "compressed_until_message_id": session.get("compressed_until_message_id"),
            "pinned_facts": session.get("pinned_facts") or {},
            "message_count": len(messages),
        }
