from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_agent_run_trace_service, require_admin_session
from app.core.auth import AuthSession
from app.services.agent_run_trace_service import AgentRunTraceService

router = APIRouter(prefix="/admin/agent-runs", tags=["admin-agent-runs"])


@router.get("")
def list_agent_runs(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    agent_name: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentRunTraceService = Depends(get_agent_run_trace_service),
) -> dict:
    return service.list_traces(hours=hours, agent_name=agent_name, final_status=final_status, limit=limit)


@router.get("/{run_id}")
def get_agent_run(
    run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentRunTraceService = Depends(get_agent_run_trace_service),
) -> dict:
    trace = service.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run trace not found")
    return trace
