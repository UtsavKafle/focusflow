"""In-process SSE publisher (integrator task 5). Envelope = contracts.models.SSEEvent.
No replay cursor (CHANGELOG #2): clients dedupe by event_id and refetch /api/state + /api/schedule on reconnect."""
from __future__ import annotations

import itertools, threading, uuid
from datetime import datetime, timezone

from contracts.models import SSEEvent

RETAIN = 500


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self.events: list[SSEEvent] = []

    def emit(self, run_id: str, type_: str, payload: dict) -> SSEEvent:
        with self._lock:
            e = SSEEvent(event_id=f"evt-{uuid.uuid4().hex[:12]}", sequence=next(self._seq), run_id=run_id or "none",
                         event_time=datetime.now(timezone.utc), type=type_, payload=payload)
            self.events.append(e)
            del self.events[:-RETAIN]
            return e

    def since(self, sequence: int) -> list[SSEEvent]:
        with self._lock:
            return [e for e in self.events if e.sequence > sequence]

    def latest_sequence(self) -> int:
        with self._lock:
            return self.events[-1].sequence if self.events else 0
