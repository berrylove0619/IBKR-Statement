from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.deps import (
    get_admin_ibkr_service,
    get_agent_task_repository,
    get_daily_position_review_agent,
    get_daily_position_review_service,
    get_email_service,
    require_admin_session,
)
from app.core.auth import AuthSession
from app.schemas.admin_ibkr import (
    IBKRFlexSettingsMutationResponse,
    IBKRFlexSettingsResponse,
    IBKRFlexSettingsUpdateRequest,
    IBKRFlexTestResponse,
    IBKRImportResponse,
)
from app.services.admin_ibkr_service import AdminIBKRError, AdminIBKRService
from app.services.agent_task_repository import AgentTaskRepository
from app.services.daily_position_review_agent import DailyPositionReviewAgent
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.email_service import EmailService
from app.api.routes.daily_position_review import _public_task, _start_daily_review_task

router = APIRouter(prefix="/admin/ibkr", tags=["admin-ibkr"])


def _handle_admin_ibkr_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/settings", response_model=IBKRFlexSettingsResponse)
def get_ibkr_settings(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminIBKRService = Depends(get_admin_ibkr_service),
) -> IBKRFlexSettingsResponse:
    try:
        return service.get_settings()
    except AdminIBKRError as exc:
        raise _handle_admin_ibkr_error(exc) from exc


@router.put("/settings", response_model=IBKRFlexSettingsMutationResponse)
def update_ibkr_settings(
    payload: IBKRFlexSettingsUpdateRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminIBKRService = Depends(get_admin_ibkr_service),
) -> IBKRFlexSettingsMutationResponse:
    try:
        settings = service.update_settings(payload)
        return IBKRFlexSettingsMutationResponse(settings=settings, message="IBKR 配置已保存")
    except AdminIBKRError as exc:
        raise _handle_admin_ibkr_error(exc) from exc


@router.post("/test", response_model=IBKRFlexTestResponse)
def test_ibkr_connection(
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminIBKRService = Depends(get_admin_ibkr_service),
) -> IBKRFlexTestResponse:
    try:
        return service.test_connection()
    except AdminIBKRError as exc:
        raise _handle_admin_ibkr_error(exc) from exc


@router.post("/pull-daily", response_model=IBKRImportResponse)
def pull_daily_from_ibkr(
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminIBKRService = Depends(get_admin_ibkr_service),
    daily_review_service: DailyPositionReviewService = Depends(get_daily_position_review_service),
    daily_review_agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    email_service: EmailService = Depends(get_email_service),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> IBKRImportResponse:
    try:
        response = service.pull_daily_from_ibkr()
        latest_date = next(iter(daily_review_service.list_report_dates(limit=1)), "")
        if latest_date:
            task = _start_daily_review_task(
                report_date=latest_date,
                force_refresh=True,
                background_tasks=background_tasks,
                agent=daily_review_agent,
                email_service=email_service,
                task_repository=task_repository,
                auto_email=False,
            )
            response.result["daily_position_review_task"] = _public_task(task).model_dump()
            response.message = f"{response.message}，已启动每日持仓复盘"
        return response
    except AdminIBKRError as exc:
        raise _handle_admin_ibkr_error(exc) from exc


@router.post("/import-history", response_model=IBKRImportResponse)
async def import_ibkr_history(
    request: Request,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AdminIBKRService = Depends(get_admin_ibkr_service),
) -> IBKRImportResponse:
    filename = unquote(request.headers.get("x-filename", "history.csv"))
    content = await request.body()
    try:
        return service.import_history_csv(filename=filename, content=content)
    except AdminIBKRError as exc:
        raise _handle_admin_ibkr_error(exc) from exc
