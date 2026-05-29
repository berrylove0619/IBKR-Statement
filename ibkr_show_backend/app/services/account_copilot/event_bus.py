from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections import defaultdict
from collections.abc import AsyncGenerator

from app.services.account_copilot.event_repository import AccountCopilotEventRepository
from app.services.account_copilot.event_sanitizer import sanitize_event_payload

TERMINAL_EVENTS = {"run_completed", "run_failed", "run_cancelled"}


class AccountCopilotEventBus:
    def __init__(self, repository: AccountCopilotEventRepository, max_payload_chars: int = 6000) -> None:
        self.repository = repository
        self.max_payload_chars = max_payload_chars
        self._lock = threading.Lock()
        self._seq_by_run: dict[str, int] = {}
        self._subscribers: dict[str, list[queue.Queue[dict]]] = defaultdict(list)

    def publish(self, run_id: str, session_id: str, event_type: str, payload: dict | None = None) -> dict:
        safe_payload = sanitize_event_payload(event_type, payload or {}, self.max_payload_chars)
        with self._lock:
            seq = self._seq_by_run.get(run_id)
            if seq is None:
                try:
                    seq = self.repository.next_seq(run_id)
                except Exception:
                    seq = 1
            self._seq_by_run[run_id] = seq + 1
            try:
                event = self.repository.create_event(run_id, session_id, event_type, safe_payload, seq=seq)
            except Exception:
                event = {
                    "id": f"evt_memory_{seq}",
                    "run_id": run_id,
                    "session_id": session_id,
                    "event_type": event_type,
                    "seq": seq,
                    "created_at": "",
                    "payload": safe_payload,
                }
            subscribers = list(self._subscribers.get(run_id, []))
        for subscriber in subscribers:
            subscriber.put(event)
        return event

    async def subscribe(self, run_id: str, after_seq: int = 0, heartbeat_seconds: int = 15) -> AsyncGenerator[dict, None]:
        for event in self.repository.list_events(run_id, after_seq=after_seq, limit=200):
            yield event
            if event.get("event_type") in TERMINAL_EVENTS:
                return

        subscriber: queue.Queue[dict] = queue.Queue()
        with self._lock:
            self._subscribers[run_id].append(subscriber)
        try:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, heartbeat_seconds)
                except queue.Empty:
                    event = {
                        "id": "heartbeat",
                        "run_id": run_id,
                        "session_id": "",
                        "event_type": "heartbeat",
                        "seq": after_seq,
                        "created_at": "",
                        "payload": {},
                    }
                yield event
                if event.get("event_type") in TERMINAL_EVENTS:
                    return
        finally:
            with self._lock:
                subscribers = self._subscribers.get(run_id, [])
                if subscriber in subscribers:
                    subscribers.remove(subscriber)
                if not subscribers and run_id in self._subscribers:
                    self._subscribers.pop(run_id, None)


def format_sse(event: dict) -> str:
    event_type = str(event.get("event_type") or "message")
    seq = str(event.get("seq") or 0)
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: {event_type}\nid: {seq}\ndata: {data}\n\n"
