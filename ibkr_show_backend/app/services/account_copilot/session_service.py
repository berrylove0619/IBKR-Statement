from __future__ import annotations

from app.services.account_copilot.repository import AccountCopilotRepository


class AccountCopilotSessionService:
    def __init__(self, repository: AccountCopilotRepository) -> None:
        self.repository = repository

    def create_session(self, title: str | None = None) -> dict:
        return self.repository.create_session(title=title)

    def get_session(self, session_id: str) -> dict | None:
        return self.repository.get_session(session_id)

    def list_sessions(self, limit: int) -> list[dict]:
        return self.repository.list_sessions(limit=limit)

    def update_session(self, session_id: str, payload: dict) -> dict | None:
        return self.repository.update_session(session_id, payload)

    def update_session_memory(
        self,
        session_id: str,
        *,
        rolling_summary: str | None = None,
        compressed_until_message_id: str | None = None,
        pinned_facts: dict | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        return self.repository.update_session_memory(
            session_id,
            rolling_summary=rolling_summary,
            compressed_until_message_id=compressed_until_message_id,
            pinned_facts=pinned_facts,
            metadata=metadata,
        )

    def touch_after_messages(self, session_id: str, *, message_count: int, last_message_at: str) -> dict | None:
        return self.repository.touch_session(
            session_id,
            message_count_delta=message_count,
            last_message_at=last_message_at,
        )
