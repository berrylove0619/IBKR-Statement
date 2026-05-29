from __future__ import annotations

from app.services.account_copilot.repository import AccountCopilotRepository


class AccountCopilotMessageService:
    def __init__(self, repository: AccountCopilotRepository) -> None:
        self.repository = repository

    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        return self.repository.create_message(
            session_id=session_id,
            role=role,
            content=content,
            run_id=run_id,
            metadata=metadata,
        )

    def list_messages(self, session_id: str, limit: int) -> list[dict]:
        return self.repository.list_messages(session_id=session_id, limit=limit)

    def update_message_run_id(self, message_id: str, run_id: str) -> dict | None:
        return self.repository.update_message_run_id(message_id=message_id, run_id=run_id)
