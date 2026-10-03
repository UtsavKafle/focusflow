"""FocusFlow contracts v1.0 -- single source of truth (Pydantic v2).

Conventions (HANDOFF 9.1): RFC 3339 UTC, null-with-reason (never NaN), scores in [0,1],
half-open intervals, integer minutes for work. Change only via PR + contracts/CHANGELOG.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
SourceKind = Literal["recorded_replay", "synthetic_fixture", "synthetic_injection"]
Score = Optional[float]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware (UTC)")
    return v.astimezone(timezone.utc)


class Interval(_Base):
    """Half-open [start, end)."""
    start: datetime
    end: datetime

    _u = field_validator("start", "end")(_utc)

    @model_validator(mode="after")
    def _order(self):
        if not self.start < self.end:
            raise ValueError("interval start must precede end")
        return self

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


# ---------- 9.2 normalized event ----------
Signal = Literal["hr", "eda", "temp", "acc", "bvp", "ibi", "glucose"]
EventQuality = Literal["valid", "flagged", "dropped"]


class NormalizedEvent(_Base):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    run_id: str
    event_id: str
    participant_id: str
    source_kind: SourceKind
    source_timestamp: datetime
    event_time: datetime
    ingested_at: datetime
    signal: Signal
    values: dict[str, float]
    unit: str
    quality: EventQuality = "valid"

    _u = field_validator("source_timestamp", "event_time", "ingested_at")(_utc)

    @model_validator(mode="after")
    def _vals(self):
        need = {"acc": {"x", "y", "z"}}.get(self.signal, {"value"})
        if set(self.values) != need:
            raise ValueError(f"{self.signal} values must have keys {sorted(need)}")
        if any(isinstance(v, float) and (math.isnan(v) or math.isinf(v)) for v in self.values.values()):
            raise ValueError("NaN/inf not allowed; use quality=dropped")
        return self


# ---------- 9.3 state ----------
class Quality(_Base):
    status: Literal["sufficient", "limited", "unavailable"]
    hr_coverage: Optional[float] = Field(None, ge=0, le=1)
    eda_coverage: Optional[float] = Field(None, ge=0, le=1)
    acc_coverage: Optional[float] = Field(None, ge=0, le=1)
    overnight_coverage: Optional[float] = Field(None, ge=0, le=1)
    missing_reasons: dict[str, str] = Field(default_factory=dict)


class WearableState(_Base):
    window_start: datetime
    window_end: datetime
    heart_rate_bpm: Optional[float] = Field(None, ge=0)
    physiological_load: Score = Field(None, ge=0, le=1)
    activity_level: Score = Field(None, ge=0, le=1)
    estimated_rest_minutes: Optional[int] = Field(None, ge=0)
    target_rest_minutes: int = Field(480, gt=0)
    recovery_score: Score = Field(None, ge=0, le=1)
    quality: Quality
    baseline_id: Optional[str] = None
    baseline_cutoff: Optional[datetime] = None
    evidence_ids: list[str] = Field(default_factory=list)

    _u = field_validator("window_start", "window_end")(_utc)

    @model_validator(mode="after")
    def _null_needs_reason(self):
        for f in ("heart_rate_bpm", "physiological_load", "activity_level",
                  "estimated_rest_minutes", "recovery_score"):
            if getattr(self, f) is None and f not in self.quality.missing_reasons:
                raise ValueError(f"{f} is null but quality.missing_reasons has no entry for it")
        return self


class AcademicState(_Base):
    calendar_version: int
    tasks_version: int
    schedule_version: int
    deadline_pressure: Score = Field(None, ge=0, le=1)
    hours_until_next_exam: Optional[float] = None
    remaining_work_minutes: int = Field(0, ge=0)
    overdue_task_ids: list[str] = Field(default_factory=list)


ReasonCode = Literal["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"]


class Trigger(_Base):
    replan_recommended: bool
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    rule_version: str = "demo-rules-1"
    # PROPOSED ADDITION (see CHANGELOG): why a trigger was suppressed (cooldown, low quality...)
    suppressed_reason_codes: list[str] = Field(default_factory=list)


class StudentState(_Base):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    state_id: str
    run_id: str
    participant_id: str
    as_of: datetime
    scenario_timezone: str
    source_kind: SourceKind
    wearable: WearableState
    academic: AcademicState
    trigger: Trigger

    _u = field_validator("as_of")(_utc)


# ---------- 9.4 tasks / events / preferences ----------
class Task(_Base):
    task_id: str
    title: str
    remaining_minutes: int = Field(ge=0)
    deadline: datetime
    priority: int = Field(ge=1, le=10)
    splittable: bool = True
    minimum_block_minutes: int = Field(30, gt=0)
    status: Literal["todo", "in_progress", "done"] = "todo"

    _u = field_validator("deadline")(_utc)


class FixedEvent(Interval):
    event_id: str
    title: str
    kind: Literal["exam", "class", "quiz", "other"]


class Preferences(_Base):
    minimum_sleep_minutes: int = 420
    target_sleep_minutes: int = 480
    minimum_study_block_minutes: int = 30
    maximum_continuous_study_minutes: int = 90
    break_minutes: int = 15


class CalendarBundle(_Base):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    calendar_version: int
    tasks_version: int
    timezone: str
    tasks: list[Task]
    fixed_events: list[FixedEvent]
    allowed_study_intervals: list[Interval]
    protected_sleep_intervals: list[Interval]
    preferences: Preferences = Field(default_factory=Preferences)


# ---------- 9.5 scheduler ----------
BlockKind = Literal["study", "fixed", "sleep_protected", "sleep_extension", "break"]


class ScheduleBlock(Interval):
    block_id: str
    task_id: Optional[str] = None
    kind: BlockKind
    locked: bool = False


class ScheduleChange(_Base):
    change_id: str
    action: Literal["moved", "added", "removed", "shortened", "extended"]
    old_block_ids: list[str] = Field(default_factory=list)
    new_block_ids: list[str] = Field(default_factory=list)
    reason_code: str  # machine-readable, e.g. PROTECT_REST, MEET_DEADLINE


class UnscheduledWork(_Base):
    task_id: str
    minutes: int = Field(gt=0)
    deadline: datetime
    reason: str

    _u = field_validator("deadline")(_utc)


class ValidationReport(_Base):
    passed: bool
    checks: dict[str, bool]
    messages: list[str] = Field(default_factory=list)


class ScheduleProposal(_Base):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    proposal_id: str
    based_on_state_id: str
    calendar_version: int
    tasks_version: int
    schedule_version: int
    status: Literal["feasible", "partial", "infeasible"]
    blocks: list[ScheduleBlock]
    changes: list[ScheduleChange] = Field(default_factory=list)
    unscheduled_work: list[UnscheduledWork] = Field(default_factory=list)
    validation: ValidationReport

    @model_validator(mode="after")
    def _status_matches(self):
        if self.status == "feasible" and self.unscheduled_work:
            raise ValueError("feasible proposal cannot have unscheduled_work")
        if self.status != "feasible" and not self.unscheduled_work and self.status == "partial":
            raise ValueError("partial proposal must list unscheduled_work")
        return self


class Schedule(_Base):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    schedule_version: int
    blocks: list[ScheduleBlock]
    unscheduled_work: list[UnscheduledWork] = Field(default_factory=list)


# ---------- 9.6 agent tools / 9.7 API ----------
class ErrorBody(_Base):
    code: str
    message: str
    retryable: bool = False


class ReplanRequest(_Base):
    run_id: str
    state_id: str
    schedule_version: int
    calendar_version: int
    tasks_version: int
    reason_codes: list[ReasonCode] = Field(min_length=1)


class ReplanJob(_Base):
    job_id: str
    status: Literal["queued", "running", "ready", "failed", "applied"]
    proposal: Optional[ScheduleProposal] = None
    explanation: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    error: Optional[ErrorBody] = None


class ApplyRequest(_Base):
    expected_schedule_version: int


class ChatRequest(_Base):
    message: str
    decision_id: Optional[str] = None


class TaskProgressRequest(_Base):
    completed_minutes: int = Field(gt=0)
    expected_tasks_version: int


class ReplayStartRequest(_Base):
    scenario_id: str
    speed: float = Field(1.0, gt=0)
    bookmark: Optional[datetime] = None


class ReplayStatus(_Base):
    run_id: Optional[str]
    mode: Literal["live_databricks", "saved_replay", "synthetic_fixture"]
    state: Literal["idle", "running", "paused"]
    speed: float = 1.0
    published_time: Optional[datetime] = None
    processed_time: Optional[datetime] = None
    lag_seconds: Optional[float] = None


SSEType = Literal["state.updated", "replay.updated", "agent.started", "agent.tool_result",
                  "schedule.proposed", "schedule.applied", "agent.explanation", "pipeline.error"]


class SSEEvent(_Base):
    event_id: str
    sequence: int
    run_id: str
    event_time: datetime
    type: SSEType
    payload: dict[str, Any]
