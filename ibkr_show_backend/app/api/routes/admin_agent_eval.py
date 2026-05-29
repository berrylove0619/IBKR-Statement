from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_agent_eval_service, require_admin_session
from app.core.auth import AuthSession
from app.services.agent_eval_service import AgentEvalService

router = APIRouter(prefix="/admin/agent-eval", tags=["admin-agent-eval"])


class EvalRunRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list)
    agent_name: str | None = None
    replay_ids: list[str] = Field(default_factory=list)
    mode: str = "static"
    name: str | None = None


@router.get("/cases")
def list_eval_cases(
    agent_name: str | None = None,
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return {"items": service.list_cases(agent_name=agent_name, source=source, limit=limit)}


@router.get("/cases/{case_id}")
def get_eval_case(
    case_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    case = service.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return case


@router.post("/cases/seed")
def seed_eval_cases(
    force: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.seed_builtin_cases(force=force)


@router.post("/cases/from-replay/{replay_id}")
def create_eval_case_from_replay(
    replay_id: str,
    save: bool = False,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    case = service.build_case_from_replay(replay_id, save=save)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay snapshot not found")
    return case


@router.post("/runs")
def run_eval(
    payload: EvalRunRequest,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.run_eval(
        case_ids=payload.case_ids,
        agent_name=payload.agent_name,
        replay_ids=payload.replay_ids,
        mode=payload.mode,
        name=payload.name,
    )


@router.get("/runs")
def list_eval_runs(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    agent_name: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    return service.list_eval_runs(hours=hours, agent_name=agent_name, limit=limit)


@router.get("/runs/{eval_run_id}")
def get_eval_run(
    eval_run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentEvalService = Depends(get_agent_eval_service),
) -> dict:
    run = service.get_eval_run(eval_run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found")
    return run
