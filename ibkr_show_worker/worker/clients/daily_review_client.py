from __future__ import annotations

import logging

import requests

from worker.core.config import Settings

logger = logging.getLogger(__name__)


class DailyPositionReviewTrigger:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def trigger_latest(self) -> dict:
        base_url = self.settings.backend_base_url.rstrip("/")
        url = f"{base_url}/api/agent/daily-position-review/internal/latest/tasks"
        headers = {}
        if self.settings.daily_review_internal_token:
            headers["x-internal-token"] = self.settings.daily_review_internal_token
        response = requests.post(url, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        logger.info("daily position review task triggered: %s", payload)
        return payload


def trigger_latest_daily_position_review(settings: Settings) -> dict | None:
    try:
        return DailyPositionReviewTrigger(settings).trigger_latest()
    except requests.RequestException as exc:
        logger.warning("daily position review trigger skipped: %s", exc)
        return None
