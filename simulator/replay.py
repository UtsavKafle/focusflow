"""Bounded, importable replay with injectable event source, writer, and clocks.

Event sources must yield chronological mapped NormalizedEvents + Bronze provenance.
Bookmark prefixes are published in bounded batches before paced publication begins.
No baseline is synthesized. Processed time is supplied externally from Gold.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from contracts.models import ReplayStatus
from databricks.ingestion.adapter import utc
from databricks.ingestion.landing_writer import LandingWriter, identifier

SPEEDS = {1, 10, 60, 300}


def timestamp(value) -> datetime:
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value)


class ReplayController:
    def __init__(self, event_source: Callable[[str, str], Iterable[dict]], writer: LandingWriter, *,
                 processed_time: Callable[[str], datetime | None] | None = None,
                 monotonic=time.monotonic, wall_clock=None, background=True, batch_size=5000,
                 minimum_history_hours=24):
        if batch_size < 1 or minimum_history_hours < 24:
            raise ValueError("positive batch_size and at least 24 h bookmark history required")
        self.event_source, self.writer = event_source, writer
        self.processed_reader = processed_time or (lambda run: None)
        self.monotonic = monotonic
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.background, self.batch_size = background, batch_size
        self.minimum_history_hours = minimum_history_hours
        self._lock = threading.RLock()
        self._worker = None
        self._wake = threading.Event()
        self._closed = False
        self.run_id = None
        self.scenario_id = None
        self.speed = 1.0
        self.state = "idle"
        self.published_time = None
        self.last_error = None
        self._pending = []
        self._used_runs = set()

    @property
    def checkpoint_path(self):
        return f"{self.run_id}/bronze" if self.run_id else None

    def start(self, run_id: str, scenario_id: str, speed: float,
              bookmark: datetime | None = None) -> str:
        identifier(run_id)
        identifier(scenario_id)
        if speed not in SPEEDS:
            raise ValueError("supported speeds: 1, 10, 60, 300")
        with self._lock:
            if self._closed:
                raise RuntimeError("controller is closed")
            if self.run_id == run_id:
                if self.state != "paused" or scenario_id != self.scenario_id or bookmark != self._bookmark:
                    raise ValueError("existing run may only resume from pause with the same scenario/bookmark")
                self.speed = float(speed)
                self._started = self.monotonic()
                self.state = "running"
                self.last_error = None
            else:
                if run_id in self._used_runs:
                    raise ValueError("run_id has already been used; start a new audit run")
                if self.state == "running":
                    raise ValueError("pause the active run before starting another")
                events = iter(self.event_source(run_id, scenario_id))
                first = next(events, None)
                if first is None:
                    raise ValueError("event source is empty")
                base = timestamp(first["event_time"])
                bookmark = utc(bookmark) if bookmark else None
                if bookmark and bookmark - base < timedelta(hours=self.minimum_history_hours):
                    raise ValueError("bookmark requires a real prefix of at least 24 hours")
                self.run_id, self.scenario_id, self.speed = run_id, scenario_id, float(speed)
                self._used_runs.add(run_id)
                self._events, self._next, self._previous = events, first, None
                self._base, self._bookmark = base, bookmark
                self._warming = bookmark is not None
                self._elapsed = 0.0
                self._started = self.monotonic()
                self._batch_numbers = defaultdict(int)
                self._pending = []
                self.published_time = None
                self.last_error = None
                self.state = "running"
            self._ensure_worker()
            self._wake.set()
            return run_id

    def _ensure_worker(self):
        if self.background and (self._worker is None or not self._worker.is_alive()):
            self._worker = threading.Thread(target=self._run, daemon=True, name="focusflow-replay")
            self._worker.start()

    def _run(self):
        while not self._closed:
            self._wake.wait(0.1)
            self._wake.clear()
            try:
                self.tick()
            except Exception as exc:
                with self._lock:
                    self.last_error = exc
                    self._pause_locked()

    def _pause_locked(self):
        if self.state == "running":
            if not self._warming:
                self._elapsed += (self.monotonic() - self._started) * self.speed
            self.state = "paused"

    def pause(self) -> None:
        with self._lock:
            self._pause_locked()

    def set_speed(self, speed: float) -> None:
        if speed not in SPEEDS:
            raise ValueError("supported speeds: 1, 10, 60, 300")
        with self._lock:
            if self.state == "running" and not self._warming:
                self._elapsed += (self.monotonic() - self._started) * self.speed
                self._started = self.monotonic()
            self.speed = float(speed)

    def reset(self) -> str:
        with self._lock:
            if self.scenario_id is None:
                raise ValueError("cannot reset before a run is configured")
            self._pause_locked()
            return self.start(f"replay-{uuid.uuid4().hex}", self.scenario_id, self.speed, self._bookmark)

    def tick(self) -> int:
        """Publish at most batch_size due events; deterministic under fake clocks."""
        with self._lock:
            if self.state != "running":
                return 0
            origin = self._bookmark if self._bookmark else self._base
            due = self._bookmark if self._warming else origin + timedelta(
                seconds=self._elapsed + (self.monotonic() - self._started) * self.speed)
            if not self._pending:
                while self._next is not None and len(self._pending) < self.batch_size:
                    event_time = timestamp(self._next["event_time"])
                    if self._previous is not None and event_time < self._previous:
                        raise ValueError("event source must be chronological across all signals/chunks")
                    if event_time > due:
                        break
                    row = dict(self._next)
                    row["ingested_at"] = utc(self.wall_clock()).isoformat()
                    self._pending.append(row)
                    self._previous = event_time
                    self._next = next(self._events, None)
            if self._pending:
                grouped = defaultdict(list)
                for row in self._pending:
                    grouped[row["signal"]].append(row)
                # On failure retain the exact pending rows/ingestion times/numbers.
                # Previously completed signal files match byte-for-byte on retry.
                for signal, rows in grouped.items():
                    self.writer.publish(self.run_id, signal, self._batch_numbers[signal], rows)
                for signal in grouped:
                    self._batch_numbers[signal] += 1
                count = len(self._pending)
                self.published_time = timestamp(self._pending[-1]["event_time"])
                self._pending = []
            else:
                count = 0
            if self._warming and (self._next is None or timestamp(self._next["event_time"]) > self._bookmark):
                if self._next is None:
                    raise ValueError("bookmark is at/after recording end; no demo events remain")
                self._warming = False
                self._elapsed = 0.0
                self._started = self.monotonic()
            if self._next is None:
                self.state = "idle"
            return count

    def status(self) -> ReplayStatus:
        with self._lock:
            processed = self.processed_reader(self.run_id) if self.run_id else None
            processed = utc(processed) if processed else None
            lag = max(0.0, (self.published_time - processed).total_seconds()) if processed and self.published_time else None
            return ReplayStatus(run_id=self.run_id, mode="live_databricks", state=self.state,
                                speed=self.speed, published_time=self.published_time,
                                processed_time=processed, lag_seconds=lag)

    def close(self):
        with self._lock:
            self._pause_locked()
            self._closed = True
        self._wake.set()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(timeout=5)
