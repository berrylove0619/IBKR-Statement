from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.deps import (
    get_agent_task_repository,
    get_longbridge_external_data_client,
    get_trade_review_agent,
    get_trade_review_repository,
    require_authenticated_session,
)
from app.agents.trade_review_graph.graph import TRADE_REVIEW_GRAPH_EDGES, TRADE_REVIEW_GRAPH_NODES
from app.agents.versions import TRADE_REVIEW_GRAPH_VERSION
from app.core.auth import AuthSession
from app.schemas.agent_tasks import AgentTaskListResponse, AgentTaskResponse
from app.schemas.trade_review import (
    TradeReviewDetailResult,
    TradeReviewGenerateSymbolRequest,
    TradeReviewGenerateTradeRequest,
    TradeReviewHealthResponse,
    TradeReviewListResponse,
    TradeReviewMistakeSummaryResponse,
    TradeReviewResult,
)
from app.services.llm_service import LLMConfigError
from app.services.agent_task_repository import AgentTaskRepository
from app.services.agent_task_progress import AgentTaskProgressReporter
from app.services.longbridge_service import LongbridgeExternalDataClient
from app.services.trade_review_agent import TradeReviewAgent, TradeReviewAgentError
from app.services.trade_review_evidence import normalize_longbridge_symbol
from app.services.trade_review_repository import TradeReviewRepository

router = APIRouter(prefix="/agent/trade-review", tags=["trade-review-agent"])
AGENT_NAME = "trade_review"


def _public_review(document: dict, include_evidence: bool = False) -> TradeReviewResult | TradeReviewDetailResult:
    payload = {
        "id": document["id"],
        "review_type": document["review_type"],
        "symbol": document["symbol"],
        "trade_ids": document.get("trade_ids") or [],
        "start_date": document.get("start_date"),
        "end_date": document.get("end_date"),
        "overall_score": document["overall_score"],
        "rating": document["rating"],
        "score_detail": document["score_detail"],
        "summary": document["summary"],
        "strengths": document.get("strengths") or [],
        "weaknesses": document.get("weaknesses") or [],
        "mistake_tags": document.get("mistake_tags") or [],
        "improvement_suggestions": document.get("improvement_suggestions") or [],
        "data_limitations": document.get("data_limitations") or [],
        "evidence_used": document.get("evidence_used") or [],
        "run_trace": document.get("run_trace") or document.get("evidence_pack", {}).get("tool_trace") or [],
        "metadata": document.get("metadata") or {},
        "evidence_summary": document.get("evidence_summary") or {},
        "run_trace_summary": document.get("run_trace_summary") or {},
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
    }
    if include_evidence:
        payload["evidence_pack"] = document.get("evidence_pack")
        return TradeReviewDetailResult(**payload)
    return TradeReviewResult(**payload)


def _public_task(document: dict) -> AgentTaskResponse:
    return AgentTaskResponse(**document)


def _single_trade_task_metadata(agent: TradeReviewAgent, trade_id: str) -> tuple[str, dict]:
    try:
        trade_info = agent.evidence_builder.tool_get_single_trade(trade_id)
    except Exception:
        return f"{trade_id} 单笔交易复盘", {"trade_id": trade_id}

    symbol = str(trade_info.get("symbol") or trade_info.get("trade", {}).get("symbol") or "").strip()
    if not symbol:
        return f"{trade_id} 单笔交易复盘", {"trade_id": trade_id}
    return f"{symbol} {trade_id} 单笔交易复盘", {"trade_id": trade_id, "symbol": symbol}


def _run_review_task(task_id: str, task_repository: AgentTaskRepository, agent: TradeReviewAgent) -> None:
    task = task_repository.mark_running(task_id)
    if task is None:
        return
    payload = task.get("payload") or {}
    try:
        if task.get("task_type") == "symbol_level_review":
            document = agent.generate_symbol_review(
                symbol=str(payload.get("symbol") or ""),
                start_date=payload.get("start_date"),
                end_date=payload.get("end_date"),
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        elif task.get("task_type") == "single_trade_review":
            document = agent.generate_single_trade_review(
                trade_id=str(payload.get("trade_id") or ""),
                progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
            )
        else:
            raise TradeReviewAgentError("TASK_TYPE_INVALID", "Unsupported trade review task type")
        task_repository.sync_graph_from_run_trace(task_id, document.get("run_trace") or [], final_status="success")
        task_repository.mark_completed(task_id, result_id=document["id"])
    except (ValueError, LLMConfigError, TradeReviewAgentError) as exc:
        error_code = getattr(exc, "error_code", "TASK_FAILED")
        error_message = getattr(exc, "message", str(exc))
        task_repository.mark_graph_failed(task_id, error_message)
        task_repository.mark_failed(task_id, error_code=error_code, error_message=error_message)
    except Exception as exc:
        task_repository.mark_graph_failed(task_id, str(exc))
        task_repository.mark_failed(task_id, error_code="TASK_FAILED", error_message=str(exc))


@router.get("/health", response_model=TradeReviewHealthResponse)
def get_trade_review_health(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeReviewAgent = Depends(get_trade_review_agent),
    longbridge_client: LongbridgeExternalDataClient = Depends(get_longbridge_external_data_client),
) -> TradeReviewHealthResponse:
    longbridge_health = longbridge_client.health()
    from app.agents.versions import TRADE_REVIEW_AGENT_MODE_LANGGRAPH, TRADE_REVIEW_GRAPH_VERSION
    health = agent.health(longbridge_configured=bool(longbridge_health.get("configured")))
    health["agent_mode"] = TRADE_REVIEW_AGENT_MODE_LANGGRAPH
    health["graph_version"] = TRADE_REVIEW_GRAPH_VERSION
    return TradeReviewHealthResponse(**health)


@router.post("/symbol/{symbol}/generate", response_model=TradeReviewDetailResult)
def generate_symbol_review(
    symbol: str,
    payload: TradeReviewGenerateSymbolRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeReviewAgent = Depends(get_trade_review_agent),
) -> TradeReviewDetailResult:
    try:
        document = agent.generate_symbol_review(symbol=symbol, start_date=payload.start_date, end_date=payload.end_date)
        return _public_review(document, include_evidence=True)
    except (ValueError, LLMConfigError, TradeReviewAgentError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/symbol/{symbol}/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_symbol_review_task(
    symbol: str,
    payload: TradeReviewGenerateSymbolRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeReviewAgent = Depends(get_trade_review_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    normalized = normalize_longbridge_symbol(symbol)
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="symbol_level_review",
        label=f"{normalized} 标的级复盘",
        payload={
            "symbol": normalized,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "force_refresh": payload.force_refresh,
        },
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=TRADE_REVIEW_GRAPH_VERSION,
        nodes=TRADE_REVIEW_GRAPH_NODES,
        edges=TRADE_REVIEW_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_review_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.post("/trade/{trade_id}/generate", response_model=TradeReviewDetailResult)
def generate_single_trade_review(
    trade_id: str,
    _payload: TradeReviewGenerateTradeRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeReviewAgent = Depends(get_trade_review_agent),
) -> TradeReviewDetailResult:
    try:
        document = agent.generate_single_trade_review(trade_id=trade_id)
        return _public_review(document, include_evidence=True)
    except (ValueError, LLMConfigError, TradeReviewAgentError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/trade/{trade_id}/tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_trade_review_task(
    trade_id: str,
    payload: TradeReviewGenerateTradeRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent: TradeReviewAgent = Depends(get_trade_review_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    normalized_trade_id = trade_id.strip()
    label, task_payload = _single_trade_task_metadata(agent, normalized_trade_id)
    task_payload["force_refresh"] = payload.force_refresh
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="single_trade_review",
        label=label,
        payload=task_payload,
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=TRADE_REVIEW_GRAPH_VERSION,
        nodes=TRADE_REVIEW_GRAPH_NODES,
        edges=TRADE_REVIEW_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_review_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.get("/tasks", response_model=AgentTaskListResponse)
def list_trade_review_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskListResponse:
    return AgentTaskListResponse(items=[_public_task(item) for item in task_repository.list_tasks(agent=AGENT_NAME, limit=limit)])


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
def get_trade_review_task(
    task_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = task_repository.get_task(task_id)
    if task is None or task.get("agent") != AGENT_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
    return _public_task(task)


@router.get("/symbol/{symbol}", response_model=TradeReviewListResponse)
def list_symbol_reviews(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeReviewRepository = Depends(get_trade_review_repository),
) -> TradeReviewListResponse:
    normalized = normalize_longbridge_symbol(symbol)
    return TradeReviewListResponse(items=[_public_review(item) for item in repository.list_symbol_reviews(normalized, limit)])


@router.get("/recent", response_model=TradeReviewListResponse)
def list_recent_reviews(
    limit: int = Query(default=20, ge=1, le=100),
    review_type: str | None = Query(default=None),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeReviewRepository = Depends(get_trade_review_repository),
) -> TradeReviewListResponse:
    return TradeReviewListResponse(items=[_public_review(item) for item in repository.list_recent_reviews(limit, review_type)])


@router.get("/mistakes/summary", response_model=TradeReviewMistakeSummaryResponse)
def get_mistake_summary(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeReviewRepository = Depends(get_trade_review_repository),
) -> TradeReviewMistakeSummaryResponse:
    return TradeReviewMistakeSummaryResponse(items=repository.summarize_mistakes())


@router.get("/{review_id}", response_model=TradeReviewDetailResult)
def get_review_detail(
    review_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository: TradeReviewRepository = Depends(get_trade_review_repository),
) -> TradeReviewDetailResult:
    document = repository.get_review(review_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade review not found")
    return _public_review(document, include_evidence=True)
