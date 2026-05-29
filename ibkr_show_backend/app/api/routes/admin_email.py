import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.deps import (
    get_agent_task_repository,
    get_daily_account_snapshot_service,
    get_daily_position_review_agent,
    get_daily_position_review_repository,
    get_daily_position_review_service,
    get_email_service,
    require_admin_session,
)
from app.core.auth import AuthSession
from app.schemas.admin_email import (
    EmailSendLatestDailyReviewRequest,
    EmailSendLatestResponse,
    EmailSettingsMutationResponse,
    EmailSettingsResponse,
    EmailSettingsUpdateRequest,
    EmailTestRequest,
    EmailTestResponse,
)
from app.services.agent_task_repository import AgentTaskRepository
from app.services.daily_account_snapshot_service import DailyAccountSnapshotService
from app.services.daily_position_review_agent import DailyPositionReviewAgent
from app.services.daily_position_review_repository import DailyPositionReviewRepository
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.email_service import EmailConfigError, EmailSendError, EmailService

router = APIRouter(prefix="/admin/email", tags=["admin-email"])
AGENT_NAME = "daily_position_review"
logger = logging.getLogger(__name__)


def _handle_email_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _run_daily_review_email_task(
    task_id: str,
    task_repository: AgentTaskRepository,
    review_agent: DailyPositionReviewAgent,
    email_service: EmailService,
) -> None:
    task = task_repository.mark_running(task_id)
    if task is None:
        return
    payload = task.get("payload") or {}
    report_date = str(payload.get("report_date") or "")
    try:
        document = review_agent.generate_review(report_date)
        sent = email_service.send_daily_position_review(document)
        if not sent:
            task_repository.mark_failed(task_id, error_code="EMAIL_SEND_FAILED", error_message="Daily review email send returned false")
            return
        task_repository.mark_completed(task_id, result_id=document["id"])
        logger.info("Daily review email background task sent", extra={"task_id": task_id, "report_date": report_date})
    except Exception as exc:
        logger.exception("Daily review email background task failed", extra={"task_id": task_id, "report_date": report_date})
        task_repository.mark_failed(
            task_id,
            error_code=getattr(exc, "error_code", "TASK_FAILED"),
            error_message=getattr(exc, "message", str(exc)),
        )


@router.get("/settings", response_model=EmailSettingsResponse)
def get_email_settings(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: EmailService = Depends(get_email_service),
) -> EmailSettingsResponse:
    try:
        return service.get_settings()
    except EmailConfigError as exc:
        raise _handle_email_error(exc) from exc


@router.put("/settings", response_model=EmailSettingsMutationResponse)
def update_email_settings(
    payload: EmailSettingsUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: EmailService = Depends(get_email_service),
) -> EmailSettingsMutationResponse:
    try:
        settings = service.update_settings(payload)
        return EmailSettingsMutationResponse(settings=settings, message="邮件配置已保存")
    except EmailConfigError as exc:
        raise _handle_email_error(exc) from exc


@router.post("/test", response_model=EmailTestResponse)
def test_email_settings(
    payload: EmailTestRequest | None = None,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: EmailService = Depends(get_email_service),
) -> EmailTestResponse:
    try:
        return service.test_send(
            subject=payload.subject if payload else None,
            message=payload.message if payload else None,
        )
    except (EmailConfigError, EmailSendError) as exc:
        raise _handle_email_error(exc) from exc


@router.post("/send-latest-daily-review", response_model=EmailSendLatestResponse)
def send_latest_daily_review(
    background_tasks: BackgroundTasks,
    payload: EmailSendLatestDailyReviewRequest | None = None,
    _auth_session: AuthSession = Depends(require_admin_session),
    email_service: EmailService = Depends(get_email_service),
    review_service: DailyPositionReviewService = Depends(get_daily_position_review_service),
    review_repo: DailyPositionReviewRepository = Depends(get_daily_position_review_repository),
    review_agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> EmailSendLatestResponse:
    try:
        settings = email_service.store.read()
        if not settings.daily_review_email_enabled:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="每日复盘邮件未启用，请在邮件配置中启用后重试",
            )
        if not settings.daily_review_email_to:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="每日复盘邮件收件人未设置，请在邮件配置中设置收件人后重试",
            )

        report_dates = review_service.list_report_dates(limit=1)
        if not report_dates:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="未找到最近交易日，请先配置 IBKR 数据源",
            )

        force_refresh = payload.force_refresh if payload else False
        regenerate_if_legacy = payload.regenerate_if_legacy if payload else True

        report_date = report_dates[0]
        review_document = review_repo.get_review_by_date(report_date)

        needs_regeneration = False
        regeneration_reason = ""

        if not review_document:
            needs_regeneration = True
            regeneration_reason = "文档不存在"
        elif force_refresh:
            needs_regeneration = True
            regeneration_reason = "force_refresh=true"
        elif regenerate_if_legacy:
            agent_mode = review_document.get("agent_mode") or ""
            metadata = review_document.get("metadata") or {}
            metadata_agent_mode = metadata.get("agent_mode") if isinstance(metadata, dict) else ""
            evidence_card_summary = review_document.get("evidence_card_summary")
            subagent_trace = review_document.get("subagent_trace")

            is_legacy = (
                agent_mode != "daily_review_subagent_cards"
                and metadata_agent_mode != "daily_review_subagent_cards"
            )
            has_empty_evidence_card_summary = not evidence_card_summary or (
                isinstance(evidence_card_summary, dict) and len(evidence_card_summary) == 0
            )
            has_empty_subagent_trace = not subagent_trace or (
                isinstance(subagent_trace, dict) and len(subagent_trace) == 0
            )

            if is_legacy:
                needs_regeneration = True
                regeneration_reason = "旧模式文档，无 agent_mode 或 agent_mode != daily_review_subagent_cards"
            elif has_empty_evidence_card_summary:
                needs_regeneration = True
                regeneration_reason = "evidence_card_summary 为空，需要重新生成"
            elif has_empty_subagent_trace:
                needs_regeneration = True
                regeneration_reason = "subagent_trace 为空，需要重新生成"

        if needs_regeneration:
            task = task_repository.create_task(
                agent=AGENT_NAME,
                task_type="daily_position_review",
                label=f"{report_date} 每日持仓复盘邮件",
                payload={
                    "report_date": report_date,
                    "force_refresh": force_refresh,
                    "auto_email": True,
                    "request_source": "admin_email_send_latest_daily_review",
                    "regeneration_reason": regeneration_reason,
                },
            )
            background_tasks.add_task(_run_daily_review_email_task, task["id"], task_repository, review_agent, email_service)
            return EmailSendLatestResponse(
                success=True,
                sent=False,
                report_date=report_date,
                task_id=task["id"],
                status=task["status"],
                message=f"已启动后台任务：重新生成复盘文档（{regeneration_reason}）并发送邮件。任务完成后会自动发送。",
            )
        else:
            message = "直接发送已有子 Agent 文档"

        sent = email_service.send_daily_position_review(review_document)
        return EmailSendLatestResponse(
            success=sent,
            sent=sent,
            report_date=report_date,
            message=f"{message}成功" if sent else f"{message}失败",
        )
    except (EmailConfigError, EmailSendError) as exc:
        raise _handle_email_error(exc) from exc


@router.post("/send-latest-account-snapshot", response_model=EmailSendLatestResponse)
def send_latest_account_snapshot(
    _auth_session: AuthSession = Depends(require_admin_session),
    email_service: EmailService = Depends(get_email_service),
    review_service: DailyPositionReviewService = Depends(get_daily_position_review_service),
    snapshot_service: DailyAccountSnapshotService = Depends(get_daily_account_snapshot_service),
) -> EmailSendLatestResponse:
    try:
        settings = email_service.store.read()
        if not settings.daily_snapshot_email_enabled:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="账户快照邮件未启用，请在邮件配置中启用后重试",
            )
        if not settings.daily_snapshot_email_to:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="账户快照邮件收件人未设置，请在邮件配置中设置收件人后重试",
            )

        report_dates = review_service.list_report_dates(limit=1)
        if not report_dates:
            return EmailSendLatestResponse(
                success=False,
                sent=False,
                report_date=None,
                message="未找到最近交易日，请先配置 IBKR 数据源",
            )

        report_date = report_dates[0]
        snapshot = snapshot_service.build_snapshot(report_date)
        sent = email_service.send_daily_account_snapshot(snapshot)
        return EmailSendLatestResponse(
            success=sent,
            sent=sent,
            report_date=report_date,
            message="账户快照邮件发送成功" if sent else "账户快照邮件发送失败",
        )
    except (EmailConfigError, EmailSendError) as exc:
        raise _handle_email_error(exc) from exc
