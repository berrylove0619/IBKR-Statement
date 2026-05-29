from __future__ import annotations

from app.services.account_copilot.repository import AccountCopilotRepository


class AccountCopilotRunService:
    def __init__(self, repository: AccountCopilotRepository) -> None:
        self.repository = repository

    def create_run(self, session_id: str, user_message_id: str, user_input: str) -> dict:
        return self.repository.create_run(
            session_id=session_id,
            user_message_id=user_message_id,
            user_input=user_input,
        )

    def mark_run_running(self, run_id: str) -> dict | None:
        return self.repository.mark_run_running(run_id)

    def mark_run_completed(
        self,
        run_id: str,
        assistant_message_id: str,
        final_answer: str,
        payload: dict | None = None,
    ) -> dict | None:
        return self.repository.mark_run_completed(
            run_id=run_id,
            assistant_message_id=assistant_message_id,
            final_answer=final_answer,
            payload=payload,
        )

    def mark_run_awaiting_approval(
        self,
        run_id: str,
        assistant_message_id: str,
        final_answer: str,
        pending_approval: dict,
        payload: dict | None = None,
    ) -> dict | None:
        return self.repository.mark_run_awaiting_approval(
            run_id=run_id,
            assistant_message_id=assistant_message_id,
            final_answer=final_answer,
            pending_approval=pending_approval,
            payload=payload,
        )

    def mark_run_failed(self, run_id: str, error_code: str, error_message: str) -> dict | None:
        return self.repository.mark_run_failed(
            run_id=run_id,
            error_code=error_code,
            error_message=error_message,
        )

    def mark_run_cancelled(self, run_id: str, reason: str | None = None) -> dict | None:
        return self.repository.mark_run_cancelled(run_id, reason)

    def get_run(self, run_id: str) -> dict | None:
        return self.repository.get_run(run_id)

    def update_run_fields(self, run_id: str, payload: dict) -> dict | None:
        return self.repository.update_run_fields(run_id, payload)

    def find_active_run_by_session(self, session_id: str) -> dict | None:
        return self.repository.find_active_run_by_session(session_id)
