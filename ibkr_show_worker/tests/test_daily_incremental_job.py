from dataclasses import dataclass
from pathlib import Path

from worker.jobs.daily_incremental_job import pull_daily_incremental


@dataclass
class DummySettings:
    flex_query_id_daily: str = "daily-query"


class StubESWriter:
    pass


class StubFlexClient:
    def download_flex_statement(self, query_id: str, save_path: Path) -> Path:
        assert query_id == "daily-query"
        return save_path


def test_pull_daily_incremental_triggers_snapshot_email_before_review(monkeypatch) -> None:
    snapshot_email_called = []

    def stub_snapshot_email(settings):
        snapshot_email_called.append(True)
        return {"success": True, "sent": True}

    def stub_review(settings):
        return {"id": "task-1", "status": "queued"}

    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.import_daily_snapshot_file",
        lambda es_writer, downloaded_file: {"account-index": {"upserted": 1}},
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_account_snapshot_email",
        stub_snapshot_email,
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_position_review",
        stub_review,
    )

    result = pull_daily_incremental(DummySettings(), StubESWriter(), StubFlexClient())

    assert result["account-index"]["upserted"] == 1
    assert result["daily_account_snapshot_email"]["success"] is True
    assert result["daily_position_review_task"]["id"] == "task-1"
    assert len(snapshot_email_called) == 1


def test_pull_daily_incremental_snapshot_email_failure_does_not_block_review(monkeypatch) -> None:
    def stub_snapshot_email(settings):
        return None

    def stub_review(settings):
        return {"id": "task-1", "status": "queued"}

    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.import_daily_snapshot_file",
        lambda es_writer, downloaded_file: {"account-index": {"upserted": 1}},
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_account_snapshot_email",
        stub_snapshot_email,
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_position_review",
        stub_review,
    )

    result = pull_daily_incremental(DummySettings(), StubESWriter(), StubFlexClient())

    assert result["account-index"]["upserted"] == 1
    assert "daily_account_snapshot_email" not in result
    assert result["daily_position_review_task"]["id"] == "task-1"


def test_pull_daily_incremental_review_network_failure_still_returns_import_result(monkeypatch) -> None:
    def stub_snapshot_email(settings):
        return {"success": True, "sent": True}

    def stub_review(settings):
        return None

    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.import_daily_snapshot_file",
        lambda es_writer, downloaded_file: {"account-index": {"upserted": 1}},
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_account_snapshot_email",
        stub_snapshot_email,
    )
    monkeypatch.setattr(
        "worker.jobs.daily_incremental_job.trigger_latest_daily_position_review",
        stub_review,
    )

    result = pull_daily_incremental(DummySettings(), StubESWriter(), StubFlexClient())

    assert result["account-index"]["upserted"] == 1
    assert result["daily_account_snapshot_email"]["success"] is True
    assert "daily_position_review_task" not in result
