"""API routes for risk assessment agent."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.deps import (
    get_agent_task_repository,
    get_risk_assessment_agent,
    get_risk_assessment_repository,
    require_authenticated_session,
)
from app.agents.risk_assessment_graph.graph import RISK_ASSESSMENT_GRAPH_EDGES, RISK_ASSESSMENT_GRAPH_NODES
from app.agents.versions import RISK_ASSESSMENT_GRAPH_VERSION
from app.core.auth import AuthSession
from app.schemas.agent_tasks import AgentTaskListResponse, AgentTaskResponse
from app.schemas.risk_assessment import (
    RiskAssessmentAnalyzeRequest,
    RiskAssessmentHealthResponse,
    RiskAssessmentListResponse,
    RiskAssessmentResult,
)
from app.services.agent_task_progress import AgentTaskProgressReporter
from app.services.agent_task_repository import AgentTaskRepository

router = APIRouter(prefix="/agent/risk-assessment", tags=["risk-assessment-agent"])
AGENT_NAME = "risk_assessment"


def _public_result(document: dict) -> RiskAssessmentResult:
    return RiskAssessmentResult(
        id=document.get("id", ""),
        assessment_type=document.get("assessment_type", "portfolio_risk"),
        overall_risk_score=document.get("overall_risk_score", 0),
        risk_level=document.get("risk_level", "medium"),
        risk_summary=document.get("risk_summary", ""),
        score_detail=document.get("score_detail") or {},
        key_risks=document.get("key_risks") or [],
        suggested_actions=document.get("suggested_actions") or [],
        concentration_warnings=document.get("concentration_warnings") or [],
        event_warnings=document.get("event_warnings") or [],
        stress_test_summary=document.get("stress_test_summary") or {},
        data_limitations=document.get("data_limitations") or [],
        evidence_used=document.get("evidence_used") or [],
        confidence=document.get("confidence", "low"),
        card_pack=document.get("card_pack") or {},
        run_trace=document.get("run_trace") or [],
        run_trace_summary=document.get("run_trace_summary") or {},
        metadata=document.get("metadata") or {},
        fallback_used=document.get("fallback_used", False),
        fallback_reason=document.get("fallback_reason"),
        created_at=document.get("created_at", ""),
        updated_at=document.get("updated_at", ""),
    )


def _public_task(document: dict) -> AgentTaskResponse:
    return AgentTaskResponse(**document)


def _run_risk_assessment_task(task_id: str, task_repository: AgentTaskRepository, agent) -> None:
    task = task_repository.mark_running(task_id)
    if task is None:
        return
    payload = task.get("payload") or {}
    try:
        document = agent.analyze(
            question=payload.get("question"),
            progress_reporter=AgentTaskProgressReporter(task_repository, task_id),
        )
        if document.get("fallback_used"):
            task_repository.sync_graph_from_run_trace(task_id, document.get("run_trace") or [], final_status="failed")
            task_repository.mark_failed(
                task_id,
                error_code="GRAPH_FAILED",
                error_message=str(document.get("fallback_reason") or "risk assessment graph failed")[:500],
            )
            return
        task_repository.sync_graph_from_run_trace(task_id, document.get("run_trace") or [], final_status="success")
        task_repository.mark_completed(task_id, result_id=document["id"])
    except Exception as exc:
        task_repository.mark_graph_failed(task_id, str(exc))
        task_repository.mark_failed(task_id, error_code="TASK_FAILED", error_message=str(exc))


@router.get("/health", response_model=RiskAssessmentHealthResponse)
def get_risk_assessment_health(
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent=Depends(get_risk_assessment_agent),
) -> RiskAssessmentHealthResponse:
    try:
        return RiskAssessmentHealthResponse(**agent.health())
    except Exception as exc:
        from app.agents.versions import RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH, RISK_ASSESSMENT_GRAPH_VERSION
        return RiskAssessmentHealthResponse(
            enabled=False,
            llm_configured=False,
            account_data_source="IBKR_ONLY",
            public_market_data_source="unavailable",
            agent_mode=RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
            graph_version=RISK_ASSESSMENT_GRAPH_VERSION,
            message=f"risk assessment health degraded: {str(exc)[:200]}",
        )


@router.post(
    "/tasks",
    response_model=RiskAssessmentResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="同步执行组合风险评估",
    description="同步调用 LangGraph 风险评估 Agent，返回完整评估结果。请求会阻塞直到所有节点（账户快照、集中度、行业主题、相关性、财报日历、压力测试、综合评分、持久化）全部完成后才返回。如需后台异步执行，可搭配 /tasks 后台任务版本。",
)
def run_risk_assessment(
    payload: RiskAssessmentAnalyzeRequest,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent=Depends(get_risk_assessment_agent),
) -> RiskAssessmentResult:
    try:
        document = agent.analyze(question=payload.question)
        return _public_result(document)
    except Exception as exc:
        from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner
        runner = RiskAssessmentGraphRunner.__new__(RiskAssessmentGraphRunner)
        runner.deps = type("Deps", (), {"repository": None})()
        document = runner._build_fallback(payload.question, f"route_fallback: {str(exc)[:180]}", persist=False)
        return _public_result(document)


@router.post("/background-tasks", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
def start_risk_assessment_task(
    payload: RiskAssessmentAnalyzeRequest,
    background_tasks: BackgroundTasks,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    agent=Depends(get_risk_assessment_agent),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = task_repository.create_task(
        agent=AGENT_NAME,
        task_type="portfolio_risk_assessment",
        label="组合风险评估",
        payload={"question": payload.question},
    )
    task_repository.init_graph_progress(
        task["id"],
        graph_version=RISK_ASSESSMENT_GRAPH_VERSION,
        nodes=RISK_ASSESSMENT_GRAPH_NODES,
        edges=RISK_ASSESSMENT_GRAPH_EDGES,
    )
    task = task_repository.get_task(task["id"]) or task
    background_tasks.add_task(_run_risk_assessment_task, task["id"], task_repository, agent)
    return _public_task(task)


@router.get("/background-tasks", response_model=AgentTaskListResponse)
def list_risk_assessment_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskListResponse:
    return AgentTaskListResponse(items=[_public_task(item) for item in task_repository.list_tasks(agent=AGENT_NAME, limit=limit)])


@router.get("/background-tasks/{task_id}", response_model=AgentTaskResponse)
def get_risk_assessment_task(
    task_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> AgentTaskResponse:
    task = task_repository.get_task(task_id)
    if task is None or task.get("agent") != AGENT_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent task not found")
    return _public_task(task)


@router.get("/recent", response_model=RiskAssessmentListResponse)
def list_recent_assessments(
    limit: int = Query(default=20, ge=1, le=100),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository=Depends(get_risk_assessment_repository),
) -> RiskAssessmentListResponse:
    return RiskAssessmentListResponse(items=[_public_result(item) for item in repository.list_recent(limit)])


@router.get("/{assessment_id}", response_model=RiskAssessmentResult)
def get_assessment_detail(
    assessment_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    repository=Depends(get_risk_assessment_repository),
) -> RiskAssessmentResult:
    document = repository.get_assessment(assessment_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk assessment not found")
    return _public_result(document)
