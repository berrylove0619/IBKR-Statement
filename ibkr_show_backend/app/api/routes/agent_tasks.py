from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_task_repository, require_authenticated_session
from app.core.auth import AuthSession
from app.services.agent_task_repository import AgentTaskRepository

router = APIRouter(prefix="/agent/tasks", tags=["agent-tasks"])


@router.get("/{task_id}/graph")
def get_agent_task_graph(
    task_id: str,
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> dict:
    task = task_repository.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "updated_seq": task.get("updated_seq") or 0,
        "graph_snapshot": task.get("graph_snapshot"),
        "graph_progress_summary": task.get("graph_progress_summary") or {},
    }


@router.get("/{task_id}/events")
async def stream_agent_task_graph_events(
    task_id: str,
    after_seq: int = Query(default=0, ge=0),
    _auth_session: AuthSession = Depends(require_authenticated_session),
    task_repository: AgentTaskRepository = Depends(get_agent_task_repository),
) -> StreamingResponse:
    if task_repository.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Agent task not found")

    async def event_generator():
        last_seq = after_seq
        idle_ticks = 0
        while True:
            task = task_repository.get_task(task_id)
            if task is None:
                yield _sse("error", {"message": "Agent task not found", "seq": last_seq})
                break
            events = task_repository.list_graph_events(task_id, after_seq=last_seq)
            if events:
                idle_ticks = 0
                for event in events:
                    last_seq = max(last_seq, int(event.get("seq") or last_seq))
                    yield _sse("graph_event", event)
            else:
                idle_ticks += 1
                yield ": heartbeat\n\n"
            if task.get("status") in {"completed", "failed"} and idle_ticks >= 2:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
