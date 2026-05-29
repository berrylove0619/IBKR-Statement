import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.api.deps import (
    get_agent_task_repository,
    get_daily_position_review_agent,
    get_daily_position_review_repository,
    get_daily_position_review_service,
    get_email_service,
    get_longbridge_external_data_client,
    require_authenticated_session,
)
from app.agents.daily_position_review_graph.graph import DAILY_POSITION_REVIEW_GRAPH_EDGES, DAILY_POSITION_REVIEW_GRAPH_NODES
from app.agents.versions import DAILY_POSITION_REVIEW_GRAPH_VERSION
from app.core.auth import AuthSession
from app.core.config import Settings, get_settings
from app.schemas.agent_tasks import AgentTaskListResponse, AgentTaskResponse
from app.schemas.daily_position_review import (
    DailyPositionReviewContextResponse,
    DailyPositionReviewDateListResponse,
    DailyPositionReviewGenerateRequest,
    DailyPositionReviewHealthResponse,
    DailyPositionReviewListResponse,
    DailyPositionReviewOverviewResponse,
    DailyPositionReviewPositionsResponse,
    DailyPositionReviewRankingsResponse,
    DailyPositionReviewResult,
    DailyPositionReviewRiskResponse,
)
from app.services.agent_task_repository import AgentTaskRepository
from app.services.agent_task_progress import AgentTaskProgressReporter
from app.services.daily_position_review_agent import DailyPositionReviewAgent, DailyPositionReviewAgentError
from app.services.daily_position_review_repository import DailyPositionReviewRepository
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.email_service import EmailService
from app.services.llm_service import LLMClientError, LLMConfigError
from app.services.longbridge_service import LongbridgeExternalDataClient

router = APIRouter(prefix="/agent/daily-position-review", tags=["daily-position-review"])
AGENT_NAME = "daily_position_review"
logger = logging.getLogger(__name__)


def _public_task(document: dict) -> AgentTaskResponse:
    return AgentTaskResponse(**document)


def _public_review(document: dict) -> DailyPositionReviewResult:
    return DailyPositionReviewResult(
        id=document["id"],
        report_date=document["report_date"],
        review_type=document.get("review_type") or "daily_position_review",
        summary=document["summary"],
        account_conclusion=document["account_conclusion"],
        attribution_summary=document["attribution_summary"],
        major_contributors_analysis=document.get("major_contributors_analysis") or [],
        major_drags_analysis=document.get("major_drags_analysis") or [],
        focus_symbol_analyses=document.get("focus_symbol_analyses") or [],
        market_context=document.get("market_context") or "",
        risk_analysis=document.get("risk_analysis") or "",
        tomorrow_watchlist=document.get("tomorrow_watchlist") or [],
        operation_observation=document.get("operation_observation") or "",
        data_limitations=document.get("data_limitations") or [],
        evidence_used=document.get("evidence_used") or [],
        data_source_summary=document.get("data_source_summary") or {},
        deterministic_context=document.get("deterministic_context") or {},
        run_trace=document.get("run_trace") or [],
        metadata=document.get("metadata") or {},
        evidence_summary=document.get("evidence_summary") or {},
        run_trace_summary=document.get("run_trace_summary") or {},
        subagent_card_pack=document.get("subagent_card_pack") or {},
        subagent_trace=document.get("subagent_trace") or {},
        evidence_card_summary=document.get("evidence_card_summary") or {},
        graph_node_traces=document.get("graph_node_traces") or [],
        graph_version=document.get("graph_version") or (document.get("metadata") or {}).get("graph_version"),
        fallback_used=document.get("fallback_used", False),
        fallback_reason=document.get("fallback_reason"),
        status=document.get("status"),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )


def _run_daily_review_task(
    task_id: str,
    task_repository: AgentTaskRepository,
    agent: DailyPositionReviewAgent,
    email_service: EmailService,
) -> None:
    task = task_repository.mark_running(task_id)
    if task is None:
        return
    payload = task.get("payload") or {}
    try:
        if task.get("task_type") != "daily_position_review":
            raise DailyPositionReviewAgentError("TASK_TYPE_INVALID", "Unsupported daily position review task type")
        report_date = str(payload.get("report_date") or "")
        try:
            document = agent.generate_review(
                report_date=report_date,
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        except TypeError as exc:
            if "progress_reporter" not in str(exc):
                raise
            document = agent.generate_review(report_date=report_date)
        if document.get("fallback_used") or document.get("status") in {"failed", "completed_with_fallback"}:
            _sync_graph_from_document(task_repository, task_id, document, final_status="failed")
            task_repository.mark_failed(
                task_id,
                error_code="GRAPH_FAILED",
                error_message=str(document.get("fallback_reason") or "daily review graph failed")[:500],
            )
            return
        _sync_graph_from_document(task_repository, task_id, document, final_status="success")
        task_repository.mark_completed(task_id, result_id=document["id"])
        if bool(payload.get("auto_email")):
            try:
                sent = email_service.send_daily_position_review(document)
                if sent:
                    logger.info("Daily position review email sent", extra={"task_id": task_id, "report_date": document.get("report_date")})
                else:
                    logger.info("Daily position review email skipped because email is disabled", extra={"task_id": task_id})
            except Exception:
                logger.exception("Daily position review email send failed", extra={"task_id": task_id, "report_date": document.get("report_date")})
    except LLMClientError as exc:
        _mark_graph_failed(task_repository, task_id, exc.message)
        task_repository.mark_failed(task_id, error_code=exc.error_code, error_message=exc.message)
    except (ValueError, LLMConfigError, DailyPositionReviewAgentError) as exc:
        error_code = getattr(exc, "error_code", "TASK_FAILED")
        error_message = getattr(exc, "message", str(exc))
        _mark_graph_failed(task_repository, task_id, error_message)
        task_repository.mark_failed(task_id, error_code=error_code, error_message=error_message)
    except Exception as exc:
        _mark_graph_failed(task_repository, task_id, str(exc))
        task_repository.mark_failed(task_id, error_code="TASK_FAILED", error_message=str(exc))


def _sync_graph_from_document(task_repository: AgentTaskRepository, task_id: str, document: dict, *, final_status: str) -> None:
    if hasattr(task_repository, "sync_graph_from_run_trace"):
        task_repository.sync_graph_from_run_trace(task_id, document.get("run_trace") or [], final_status=final_status)


def _mark_graph_failed(task_repository: AgentTaskRepository, task_id: str, error_message: str) -> None:
    if hasattr(task_repository, "mark_graph_failed"):
        task_repository.mark_graph_failed(task_id, error_message)


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


def _start_daily_review_task(
    *,
    report_date: str,
    force_refresh: bool,
    background_tasks: BackgroundTasks,
    agent: DailyPositionReviewAgent,
    email_service: EmailService,
    task_repository: AgentTaskRepository,
    auto_email: bool = False,
) -> dict:
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="daily_position_review",
        label=f"{report_date} 每日持仓复盘",
        payload={"report_date": report_date, "force_refresh": force_refresh, "auto_email": auto_email},
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=DAILY_POSITION_REVIEW_GRAPH_VERSION,
        nodes=DAILY_POSITION_REVIEW_GRAPH_NODES,
        edges=DAILY_POSITION_REVIEW_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_daily_review_task, task["id"], task_repository, agent, email_service)
    return task


@router.get("/health", response_model=DailyPositionReviewHealthResponse)
def get_daily_position_review_health(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    longbridge_client: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> DailyPositionReviewHealthResponse:
    return DailyPositionReviewHealthResponse(**agent.health(longbridge_configured=bool(longbridge_client.health().get("configured"))))


@router.get("/dates", response_model=DailyPositionReviewDateListResponse)
def list_daily_position_review_dates(
    limit: int = Query(default=60, ge=1, le=500),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewDateListResponse:
    return DailyPositionReviewDateListResponse(items=service.list_report_dates(limit=limit))


@router.get("/recent", response_model=DailyPositionReviewListResponse)
def list_recent_daily_position_reviews(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: DailyPositionReviewRepository = Depends(get_daily_position_review_repository),
) -> DailyPositionReviewListResponse:
    return DailyPositionReviewListResponse(items=[_public_review(item) for item in repository.list_reviews(limit=limit)])


@router.get("/tasks", response_model=AgentTaskListResponse)
def list_daily_position_review_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskListResponse:
    return AgentTaskListResponse(items=[_public_task(item) for item in task_repository.list_tasks(agent=AGENT_NAME, limit=limit)])


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
def get_daily_position_review_task(
    task_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = task_repository.get_task(task_id)
    if task is None or task.get("agent") != AGENT_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
    return _public_task(task)


@router.post("/internal/latest/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_latest_daily_position_review_internal_task(
    request: Request,
    background_tasks: BackgroundTasks,
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
    agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    email_service: EmailService = Depends(get_email_service),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
    settings: Settings = Depends(get_settings),
) -> AgentTaskResponse:
    _require_internal_request(request, settings)
    latest_date = next(iter(service.list_report_dates(limit=1)), "")
    if not latest_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No report date is available")
    task = _start_daily_review_task(
        report_date=latest_date,
        force_refresh=True,
        auto_email=True,
        background_tasks=background_tasks,
        agent=agent,
        email_service=email_service,
        task_repository=task_repository,
    )
    return _public_task(task)


@router.get("/{report_date}/context", response_model=DailyPositionReviewContextResponse)
def get_daily_position_review_context(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewContextResponse:
    try:
        context = service.build_review_context(
            report_date, include_public_context=False, include_benchmarks=False,
        )
        public_context = {key: value for key, value in context.items() if key != "symbol_public_context"}
        return DailyPositionReviewContextResponse(**public_context)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{report_date}/overview", response_model=DailyPositionReviewOverviewResponse)
def get_daily_position_review_overview(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewOverviewResponse:
    try:
        return DailyPositionReviewOverviewResponse(**service.get_overview(report_date))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{report_date}/positions", response_model=DailyPositionReviewPositionsResponse)
def get_daily_position_review_positions(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewPositionsResponse:
    try:
        return DailyPositionReviewPositionsResponse(report_date=report_date, items=service.get_positions(report_date))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{report_date}/rankings", response_model=DailyPositionReviewRankingsResponse)
def get_daily_position_review_rankings(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewRankingsResponse:
    try:
        return DailyPositionReviewRankingsResponse(report_date=report_date, **service.get_rankings(report_date))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{report_date}/risk", response_model=DailyPositionReviewRiskResponse)
def get_daily_position_review_risk(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    service: DailyPositionReviewService = Depends(get_daily_position_review_service),
) -> DailyPositionReviewRiskResponse:
    try:
        return DailyPositionReviewRiskResponse(report_date=report_date, **service.get_risk(report_date))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{report_date}/generate", response_model=DailyPositionReviewResult)
def generate_daily_position_review(
    report_date: str,
    _payload: DailyPositionReviewGenerateRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
) -> DailyPositionReviewResult:
    try:
        return _public_review(agent.generate_review(report_date=report_date))
    except LLMClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error_code": exc.error_code, "message": exc.message}) from exc
    except (ValueError, LLMConfigError, DailyPositionReviewAgentError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{report_date}/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_daily_position_review_task(
    report_date: str,
    payload: DailyPositionReviewGenerateRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    email_service: EmailService = Depends(get_email_service),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = _start_daily_review_task(
        report_date=report_date,
        force_refresh=payload.force_refresh,
        auto_email=False,
        background_tasks=background_tasks,
        agent=agent,
        email_service=email_service,
        task_repository=task_repository,
    )
    return _public_task(task)


@router.post("/{report_date}/regenerate", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def regenerate_daily_position_review(
    report_date: str,
    payload: DailyPositionReviewGenerateRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: DailyPositionReviewAgent = Depends(get_daily_position_review_agent),
    email_service: EmailService = Depends(get_email_service),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    payload.force_refresh = True
    return start_daily_position_review_task(report_date, payload, background_tasks, _auth_session, agent, email_service, task_repository)


@router.get("/{report_date}", response_model=DailyPositionReviewResult)
def get_daily_position_review(
    report_date: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: DailyPositionReviewRepository = Depends(get_daily_position_review_repository),
) -> DailyPositionReviewResult:
    document = repository.get_review_by_date(report_date)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily position review not found")
    return _public_review(document)
