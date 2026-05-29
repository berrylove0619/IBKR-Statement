from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_daily_account_snapshot_service, get_email_service, get_settings
from app.core.config import Settings
from app.services.daily_account_snapshot_service import DailyAccountSnapshotService
from app.services.email_service import EmailService

router = APIRouter(prefix="/account-snapshot-email", tags=["account-snapshot-email"])
logger = logging.getLogger(__name__)


def _require_internal_request(request: Request, settings: Settings) -> None:
    token = request.headers.get("x-internal-token", "")
    if settings.daily_review_internal_token:
        if token == settings.daily_review_internal_token:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token")

    client_host = request.client.host if request.client else ""
    if client_host in {"127.0.0.1", "::1", "localhost"}:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal endpoint is only available locally")


@router.post("/internal/latest")
def send_latest_daily_account_snapshot_email(
    request: Request,
    snapshot_service: DailyAccountSnapshotService = Depends(get_daily_account_snapshot_service),
    email_service: EmailService = Depends(get_email_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_internal_request(request, settings)

    latest_date = snapshot_service.daily_review_service.list_report_dates(limit=1)
    report_date = latest_date[0] if latest_date else None
    if not report_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No report date is available")

    try:
        snapshot = snapshot_service.build_snapshot(report_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        sent = email_service.send_daily_account_snapshot(snapshot)
    except Exception as exc:
        logger.exception("Daily account snapshot email send failed", extra={"report_date": report_date})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Email send failed: {exc}") from exc

    if sent:
        return {
            "success": True,
            "sent": True,
            "report_date": report_date,
            "message": "Daily account snapshot email sent",
        }
    return {
        "success": True,
        "sent": False,
        "report_date": report_date,
        "message": "Email is disabled",
    }
