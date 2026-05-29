from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_agent_replay_service, require_admin_session
from app.core.auth import AuthSession
from app.services.agent_replay_service import AgentReplayService

router = APIRouter(prefix="/admin/agent-replays", tags=["admin-agent-replays"])


@router.get("")
def list_agent_replays(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    agent_name: str | None = None,
    final_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentReplayService = Depends(get_agent_replay_service),
) -> dict:
    return service.list_snapshots(hours=hours, agent_name=agent_name, final_status=final_status, limit=limit)


@router.get("/by-run/{run_id}")
def get_agent_replay_by_run(
    run_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentReplayService = Depends(get_agent_replay_service),
) -> dict:
    snapshot = service.get_by_run_id(run_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent replay snapshot not found")
    return snapshot


@router.get("/{replay_id}")
def get_agent_replay(
    replay_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentReplayService = Depends(get_agent_replay_service),
) -> dict:
    snapshot = service.get_snapshot(replay_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent replay snapshot not found")
    return snapshot


@router.get("/{replay_id}/export")
def export_agent_replay(
    replay_id: str,
    _auth_session: AuthSession = Depends(require_admin_session),
    service: AgentReplayService = Depends(get_agent_replay_service),
) -> dict:
    package = service.export_replay_package(replay_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent replay snapshot not found")
    return package
