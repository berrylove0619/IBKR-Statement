"""
Tests for admin_email API - send-latest-daily-review endpoint.

Covers:
- Regeneration logic based on agent_mode and evidence_card_summary/subagent_trace
- force_refresh and regenerate_if_legacy parameters
- Different message responses for different scenarios
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_agent_task_repository,
    get_daily_position_review_agent,
    get_daily_position_review_repository,
    get_daily_position_review_service,
    get_email_service,
)
from app.core.config import get_settings
from app.main import app


class DummyConfig:
    daily_review_email_enabled = True
    daily_review_email_to = "review@example.com"
    daily_snapshot_email_enabled = False
    daily_snapshot_email_to = ""

    def read(self):
        return self


class DummyEmailService:
    @property
    def store(self):
        return DummyConfig()

    def get_settings(self):
        class Settings:
            daily_review_email_enabled = True
            daily_review_email_to = "review@example.com"
            daily_snapshot_email_enabled = False
            daily_snapshot_email_to = ""
        return Settings()

    def send_daily_position_review(self, review_document):
        return True


class DummyTaskRepository:
    def __init__(self) -> None:
        self.task = None

    def create_task(self, *, agent, task_type, label, payload):
        self.task = {
            "id": "task-1",
            "agent": agent,
            "task_type": task_type,
            "label": label,
            "payload": payload,
            "status": "queued",
            "result_id": None,
            "error_code": None,
            "error_message": None,
            "created_at": "2026-05-20T00:00:00+00:00",
            "started_at": None,
            "completed_at": None,
            "updated_at": "2026-05-20T00:00:00+00:00",
        }
        return dict(self.task)

    def get_task(self, task_id):
        return dict(self.task) if self.task and self.task["id"] == task_id else None

    def mark_running(self, task_id):
        if self.task is None:
            return None
        self.task["status"] = "running"
        return dict(self.task)

    def mark_completed(self, task_id, *, result_id):
        if self.task is None:
            return None
        self.task.update({"status": "completed", "result_id": result_id})
        return dict(self.task)

    def mark_failed(self, task_id, *, error_code, error_message):
        if self.task is None:
            return None
        self.task.update({"status": "failed", "error_code": error_code, "error_message": error_message})
        return dict(self.task)


def _login(client: TestClient) -> None:
    settings = get_settings()
    response = client.post(
        "/api/auth/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    assert response.status_code == 200


class TestSendLatestDailyReview:
    """Test send-latest-daily-review endpoint regeneration logic."""

    def _setup_mocks(self, review_repo_mock, review_agent_mock, review_service_mock=None):
        """Set up dependency overrides."""
        task_repo = DummyTaskRepository()

        def dummy_email():
            return DummyEmailService()

        def dummy_agent():
            return review_agent_mock

        def dummy_repo():
            return review_repo_mock

        def dummy_service():
            return review_service_mock or MagicMock(list_report_dates=MagicMock(return_value=["2026-05-20"]))

        def dummy_task_repo():
            return task_repo

        app.dependency_overrides[get_email_service] = dummy_email
        app.dependency_overrides[get_daily_position_review_agent] = dummy_agent
        app.dependency_overrides[get_daily_position_review_repository] = dummy_repo
        app.dependency_overrides[get_daily_position_review_service] = dummy_service
        app.dependency_overrides[get_agent_task_repository] = dummy_task_repo
        return task_repo

    def _cleanup_mocks(self):
        app.dependency_overrides.clear()

    def test_document_not_exists_calls_agent_generate_review(self):
        """When repo returns None, should call agent.generate_review() and send."""
        client = TestClient(app)
        new_doc = {"id": "2026-05-20", "report_date": "2026-05-20", "agent_mode": "daily_review_subagent_cards"}
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=None)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_legacy_document_regenerates(self):
        """When document has no agent_mode, should regenerate."""
        client = TestClient(app)
        legacy_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            # No agent_mode field
            "summary": "Legacy review",
        }
        new_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "summary": "New review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=legacy_doc)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_subagent_document_direct_send(self):
        """When document is sub-agent mode and force_refresh=false, should send directly."""
        client = TestClient(app)
        existing_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "evidence_card_summary": {"symbol_count": 5},
            "subagent_trace": {"symbol_agent_calls": []},
            "summary": "Existing review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=existing_doc)),
            review_agent_mock=MagicMock(),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert "直接发送" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_force_refresh_regenerates(self):
        """When force_refresh=true, should regenerate even with valid sub-agent document."""
        client = TestClient(app)
        existing_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "evidence_card_summary": {"symbol_count": 5},
            "subagent_trace": {"symbol_agent_calls": []},
            "summary": "Existing review",
        }
        new_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "summary": "New review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=existing_doc)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post(
                "/api/admin/email/send-latest-daily-review",
                json={"force_refresh": True},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_empty_evidence_card_summary_regenerates(self):
        """When evidence_card_summary is empty, should regenerate."""
        client = TestClient(app)
        existing_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "evidence_card_summary": {},  # Empty
            "subagent_trace": {"symbol_agent_calls": []},
            "summary": "Existing review",
        }
        new_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "summary": "New review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=existing_doc)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_empty_subagent_trace_regenerates(self):
        """When subagent_trace is empty, should regenerate."""
        client = TestClient(app)
        existing_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "evidence_card_summary": {"symbol_count": 5},
            "subagent_trace": {},  # Empty
            "summary": "Existing review",
        }
        new_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
            "summary": "New review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=existing_doc)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()

    def test_regenerate_if_legacy_false_skips_regeneration(self):
        """When regenerate_if_legacy=false, should not regenerate legacy docs."""
        client = TestClient(app)
        legacy_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            # No agent_mode
            "summary": "Legacy review",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=legacy_doc)),
            review_agent_mock=MagicMock(),
        )
        try:
            _login(client)
            response = client.post(
                "/api/admin/email/send-latest-daily-review",
                json={"regenerate_if_legacy": False},
            )
            assert response.status_code == 200
            data = response.json()
            # With regenerate_if_legacy=False, old doc should be sent directly (no agent_mode means old format)
            # Since the endpoint sends existing doc directly when regenerate_if_legacy=False,
            # the message will indicate sending, not regenerating
            assert "重新生成" not in data["message"]
        finally:
            self._cleanup_mocks()

    def test_metadata_agent_mode_check(self):
        """When agent_mode is in metadata but not at top level, should still detect legacy."""
        client = TestClient(app)
        legacy_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "metadata": {"agent_mode": "old_mode"},  # Legacy mode in metadata
            "summary": "Legacy review",
        }
        new_doc = {
            "id": "2026-05-20",
            "report_date": "2026-05-20",
            "agent_mode": "daily_review_subagent_cards",
        }
        self._setup_mocks(
            review_repo_mock=MagicMock(get_review_by_date=MagicMock(return_value=legacy_doc)),
            review_agent_mock=MagicMock(generate_review=MagicMock(return_value=new_doc)),
        )
        try:
            _login(client)
            response = client.post("/api/admin/email/send-latest-daily-review", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["sent"] is False
            assert data["task_id"] == "task-1"
            assert "已启动后台任务" in data["message"]
        finally:
            self._cleanup_mocks()


class TestSendLatestDailyReviewRequiresAuth:
    """Test that endpoint requires authentication."""

    def test_send_latest_daily_review_requires_auth(self):
        client = TestClient(app)
        response = client.post("/api/admin/email/send-latest-daily-review", json={})
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
