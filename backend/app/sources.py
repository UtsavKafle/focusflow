"""Wearable data sources behind one interface (integrator task 5). The backend composes StudentState from these.
FixtureSource: SYNTHETIC fixture rows (no credentials needed). DatabricksSource lives in databricks_reader.py (task 6).
Rule: never serve rows later than the replay clock (no future leakage) and never mark stale data as fresh."""
from __future__ import annotations

import json, pathlib, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol

from contracts.models import ReplayStatus, StudentState, WearableState

from backend.app.trigger import MinuteLoad

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class WearableSnapshot:
    key: str                          # stable id of the underlying wearable row (state_id base)
    run_id: str
    participant_id: str
    as_of: datetime                   # replay clock
    source_kind: str
    wearable: WearableState
    activity_confound: bool = False
    stale: bool = False
    lag_seconds: Optional[float] = None
    extra_missing: dict = field(default_factory=dict)


class WearableSource(Protocol):
    mode: str     # live_databricks | saved_replay | synthetic_fixture
    label: str

    def latest(self) -> Optional[WearableSnapshot]: ...
    def history(self, start: Optional[datetime], end: Optional[datetime]) -> list[dict]: ...
    def minute_loads(self, end: datetime, minutes: int) -> list[MinuteLoad]: ...
    def status(self, run_id: Optional[str]) -> ReplayStatus: ...
    def start(self, speed: float, bookmark: Optional[datetime]) -> None: ...
    def pause(self) -> None: ...
    def reset(self) -> None: ...


class FixtureSource:
    """Replays fixtures/scenarios/<scenario>/states.json + history.json. One fixture state = 5 replay minutes."""
    mode = "synthetic_fixture"
    STEP_REPLAY_SECONDS = 300

    def __init__(self, scenario: str):
        d = FIX / scenario
        self.scenario = scenario
        self.meta = json.loads((d / "meta.json").read_text())
        self.label = self.meta["label"]
        self.states = [StudentState.model_validate(s) for s in json.loads((d / "states.json").read_text())]
        self.rows = json.loads((d / "history.json").read_text())
        self.reset()

    # ---- replay cursor (lazy: advances with wall time x speed while running) ----
    def reset(self) -> None:
        self.state, self.speed = "idle", 1.0
        self._base, self._t0 = len(self.states) - 1, None   # idle shows the full prepared window

    def _cursor(self) -> int:
        c = self._base
        if self.state == "running" and self._t0 is not None:
            c += int((time.monotonic() - self._t0) * self.speed / self.STEP_REPLAY_SECONDS)
        return min(c, len(self.states) - 1)

    def start(self, speed: float = 1.0, bookmark: Optional[datetime] = None) -> None:
        idx = 0
        if bookmark is not None:
            idx = max([i for i, s in enumerate(self.states) if s.as_of <= bookmark] or [0])
        self._base, self._t0, self.speed, self.state = idx, time.monotonic(), speed, "running"

    def pause(self) -> None:
        self._base, self._t0, self.state = self._cursor(), None, "paused"

    def advance(self, n: int = 1) -> int:
        self._base = min(len(self.states) - 1, self._cursor() + n)
        if self._t0 is not None:
            self._t0 = time.monotonic()
        return self._base

    # ---- reads ----
    def latest(self) -> Optional[WearableSnapshot]:
        s = self.states[self._cursor()]
        return WearableSnapshot(key=s.state_id, run_id=s.run_id, participant_id=s.participant_id, as_of=s.as_of,
                                source_kind=s.source_kind, wearable=s.wearable.model_copy(deep=True), lag_seconds=0.0)

    def _clock(self) -> datetime:
        return self.states[self._cursor()].as_of

    def history(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> list[dict]:
        clock = self._clock()
        end = min(end, clock) if end else clock
        return [r for r in self.rows if parse_ts(r["window_end"]) <= end and (start is None or parse_ts(r["window_end"]) >= start)]

    def minute_loads(self, end: datetime, minutes: int) -> list[MinuteLoad]:
        rows = self.history(end - timedelta(minutes=minutes), end)
        return [MinuteLoad(parse_ts(r["window_end"]), r["physiological_load"] if r["quality"] == "valid" else None) for r in rows]

    def status(self, run_id: Optional[str]) -> ReplayStatus:
        t = self._clock()
        return ReplayStatus(run_id=run_id, mode=self.mode, state=self.state, speed=self.speed,
                            published_time=t, processed_time=t, lag_seconds=0.0)
