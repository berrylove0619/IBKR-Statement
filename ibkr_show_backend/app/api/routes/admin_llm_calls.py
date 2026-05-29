from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_llm_call_metrics_service, require_admin_session
from app.core.auth import AuthSession
from app.services.llm_call_metrics_service import LLMCallMetricsService

router = APIRouter(prefix="/admin/llm-calls", tags=["admin-llm-calls"])


@router.get("")
def list_llm_calls(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    agent_name: str | None = None,
    prompt_key: str | None = None,
    model: str | None = None,
    ok: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _auth_session: AuthSession = Depends(require_admin_session),
    service: LLMCallMetricsService = Depends(get_llm_call_metrics_service),
) -> dict:
    return service.list_calls(
        hours=hours,
        agent_name=agent_name,
        prompt_key=prompt_key,
        model=model,
        ok=ok,
        limit=limit,
    )
