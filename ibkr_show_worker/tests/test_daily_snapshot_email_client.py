import pytest
from unittest.mock import patch, MagicMock

from worker.clients.daily_snapshot_email_client import DailySnapshotEmailTrigger, trigger_latest_daily_account_snapshot_email


class DummySettings:
    backend_base_url: str = "http://localhost:8000"
    daily_review_internal_token: str = "test-token"


def test_trigger_latest_returns_json_on_success() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"success": True, "sent": True, "report_date": "2026-05-19"}
    mock_response.raise_for_status = MagicMock()

    with patch("worker.clients.daily_snapshot_email_client.requests.post") as mock_post:
        mock_post.return_value = mock_response

        settings = DummySettings()
        trigger = DailySnapshotEmailTrigger(settings)
        result = trigger.trigger_latest()

        assert result == {"success": True, "sent": True, "report_date": "2026-05-19"}
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8000/api/account-snapshot-email/internal/latest"
        assert call_args[1]["headers"]["x-internal-token"] == "test-token"


def test_trigger_latest_returns_none_on_request_failure() -> None:
    import requests as req

    with patch("worker.clients.daily_snapshot_email_client.requests.post") as mock_post:
        mock_post.side_effect = req.RequestException("Connection refused")

        settings = DummySettings()
        result = trigger_latest_daily_account_snapshot_email(settings)

        assert result is None


def test_trigger_latest_daily_account_snapshot_email_returns_none_on_failure() -> None:
    import requests as req

    with patch("worker.clients.daily_snapshot_email_client.requests.post") as mock_post:
        mock_post.side_effect = req.RequestException("Timeout")

        settings = DummySettings()
        result = trigger_latest_daily_account_snapshot_email(settings)

        assert result is None
