from pathlib import Path
import tempfile

from worker.clients.es_client import ElasticsearchWriter
from worker.clients.flex_client import FlexClient
from worker.clients.daily_review_client import trigger_latest_daily_position_review
from worker.clients.daily_snapshot_email_client import trigger_latest_daily_account_snapshot_email
from worker.core.config import Settings, get_settings
from worker.jobs.import_daily_snapshot import import_daily_snapshot_file


def pull_daily_incremental(
    settings: Settings,
    es_writer: ElasticsearchWriter,
    flex_client: FlexClient,
) -> dict:
    with tempfile.NamedTemporaryFile(prefix="ibkr_daily_", suffix=".csv", delete=False) as temp_file:
        downloaded_path = Path(temp_file.name)

    downloaded_file = flex_client.download_flex_statement(
        query_id=settings.flex_query_id_daily,
        save_path=downloaded_path,
    )
    result = import_daily_snapshot_file(es_writer, downloaded_file)

    snapshot_email_result = trigger_latest_daily_account_snapshot_email(settings)
    if snapshot_email_result is not None:
        result["daily_account_snapshot_email"] = snapshot_email_result

    review_task = trigger_latest_daily_position_review(settings)
    if review_task is not None:
        result["daily_position_review_task"] = review_task

    return result


def run_daily_incremental_job() -> dict:
    settings = get_settings()
    es_writer = ElasticsearchWriter(settings)
    flex_client = FlexClient(settings)
    return pull_daily_incremental(settings=settings, es_writer=es_writer, flex_client=flex_client)
