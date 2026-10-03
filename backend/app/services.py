"""Backend services (integrator task 5): compose StudentState, run replan jobs, apply proposals.
Routes (main.py) and agent tools (agent/tools.py) both call these directly. The LLM never edits the schedule:
only `apply()` commits, after version checks and re-validation."""
from __future__ import annotations

import json, threading, uuid
from datetime import datetime
from typing import Any, Callable, Optional

from contracts.models import (CalendarBundle, ErrorBody, ReplanJob, ReplanRequest, Schedule, ScheduleProposal,
                              StudentState)
from scheduler.optimize import optimize_schedule, policy_for_reasons
from scheduler.validate import validate_proposal

from backend.app.academic import compute_academic
from backend.app.events import EventBus
from backend.app.sources import FIX, WearableSnapshot, WearableSource
from backend.app.store import Store
from backend.app.trigger import ACTIVE_RULES, TriggerContext, TriggerEngine


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.body = status, ErrorBody(code=code, message=message, retryable=retryable)


class Services:
    def __init__(self, source: WearableSource, store: Store, scenario: str, data_source: str = "fixture",
                 investigator: Optional[Callable] = None, auto_apply: bool = False):
        self.source, self.store, self.scenario, self.data_source = source, store, scenario, data_source
        self.bus = EventBus()
        if hasattr(source, "on_error"):  # Databricks boundary failures -> SSE pipeline.error
            source.on_error = lambda code, msg: self.bus.emit(self.run_id, "pipeline.error", {"code": code, "message": msg})
        self.engine = TriggerEngine(ACTIVE_RULES)
        from agent.agent import run_investigation
        self.investigator = investigator or run_investigation
        self.auto_apply = auto_apply  # demo setting (task 13): valid in-app proposals only; manual Apply is default
        self.lock = threading.RLock()
        self._last_state_id: Optional[str] = None
        self._recommended_state_ids: set[str] = set()
        self.run_id = ""
        self.new_run()

    # ---------- runs ----------
    def new_run(self) -> str:
        """Fresh calendar + schedule from the scenario; prior proposals/decisions stay in the store (audit)."""
        d = FIX / self.scenario
        cal = CalendarBundle.model_validate_json((d / "calendar.json").read_text())
        sched = Schedule.model_validate_json((d / "schedule.json").read_text())
        self.run_id = f"{self.scenario}-run-{uuid.uuid4().hex[:6]}"
        self.store.start_run(self.run_id, self.scenario, cal, sched)
        self.engine = TriggerEngine(ACTIVE_RULES)
        self._last_state_id = None
        return self.run_id

    # ---------- state composition ----------
    def calendar(self) -> CalendarBundle:
        return self.store.calendar(self.run_id)

    def schedule(self) -> Schedule:
        return self.store.schedule(self.run_id)

    def snapshot(self) -> Optional[WearableSnapshot]:
        return self.source.latest()

    def compose(self) -> Optional[StudentState]:
        """StudentState = Gold/fixture WearableState + academic (replay clock) + trigger + versions."""
        snap = self.snapshot()
        if snap is None:
            return None
        cal, sched = self.calendar(), self.schedule()
        academic = compute_academic(cal, sched.schedule_version, snap.as_of)
        ctx = TriggerContext(pending_decision=bool(self.store.pending_jobs(self.run_id, self._versions())),
                             last_applied_at=self.store.last_applied_replay_time(self.run_id),
                             activity_confound=snap.activity_confound)
        loads = self.source.minute_loads(snap.as_of, ACTIVE_RULES["sustained_window_minutes"] + 5)
        trig = self.engine.evaluate(snap.as_of, snap.wearable, loads, academic, sched, ctx)
        if snap.stale:
            trig.replan_recommended = False
            trig.suppressed_reason_codes.append("STALE_STATE")
        state_id = f"{snap.key}.c{cal.calendar_version}t{cal.tasks_version}s{sched.schedule_version}"
        st = StudentState(state_id=state_id, run_id=self.run_id, participant_id=snap.participant_id, as_of=snap.as_of,
                          scenario_timezone=cal.timezone, source_kind=snap.source_kind, wearable=snap.wearable,
                          academic=academic, trigger=trig)
        if trig.replan_recommended:
            self._recommended_state_ids.add(state_id)
        if state_id != self._last_state_id:
            self._last_state_id = state_id
            self.bus.emit(self.run_id, "state.updated", {"state_id": state_id, "as_of": st.model_dump(mode="json")["as_of"],
                                                        "replan_recommended": trig.replan_recommended})
        return st

    def history(self, start: Optional[datetime], end: Optional[datetime]) -> dict:
        snap = self.snapshot()
        return {"schema_version": "1.0", "source_kind": snap.source_kind if snap else None,
                "windows": self.source.history(start, end)}

    # ---------- scheduler ----------
    def request_proposal(self, reason_codes: list[str], state: StudentState) -> ScheduleProposal:
        return optimize_schedule(state.as_of, None, self.calendar(), self.schedule(), state, policy_for_reasons(reason_codes))

    # ---------- replan jobs ----------
    def _versions(self) -> dict:
        cal, sched = self.calendar(), self.schedule()
        return {"calendar_version": cal.calendar_version, "tasks_version": cal.tasks_version,
                "schedule_version": sched.schedule_version}

    def create_job(self, req: ReplanRequest) -> tuple[ReplanJob, bool]:
        """Returns (job, created). 409 on stale versions; same state + versions -> existing job (idempotent)."""
        with self.lock:
            v = self._versions()
            if (req.calendar_version, req.tasks_version, req.schedule_version) != \
                    (v["calendar_version"], v["tasks_version"], v["schedule_version"]):
                raise ApiError(409, "STALE_VERSION", "input versions are stale; refetch state and schedule")
            existing = self.store.job_for_state(self.run_id, req.state_id, v)
            if existing:
                return existing, False
            job = ReplanJob(job_id=f"job-{uuid.uuid4().hex[:8]}", status="queued")
            self.store.save_job(self.run_id, req.state_id, v, job)
            if req.state_id in self._recommended_state_ids:
                self.engine.consume()  # hysteresis: this recommendation has been acted on
            self.bus.emit(self.run_id, "agent.started", {"job_id": job.job_id, "state_id": req.state_id})
            return job, True

    def run_job(self, job_id: str, req: ReplanRequest) -> None:
        """Background task. Failures leave the schedule untouched and mark the job failed."""
        v = self._versions()
        job = self.store.job(job_id)
        job.status = "running"
        self.store.save_job(self.run_id, req.state_id, v, job)
        try:
            state = self.compose()
            if state is None:
                raise ApiError(503, "STATE_NOT_READY", "no wearable state available yet", retryable=True)
            out = self.investigator(self, job_id, req, state)
            prop: Optional[ScheduleProposal] = out["proposal"]
            if prop is not None and not validate_proposal(self.calendar(), prop).passed:
                raise ApiError(422, "INVALID_PROPOSAL", "; ".join(validate_proposal(self.calendar(), prop).messages))
            if prop is not None and not prop.changes and not prop.unscheduled_work:
                prop = None  # ready + proposal null == "no change recommended" (CHANGELOG #6)
            job = ReplanJob(job_id=job_id, status="ready", proposal=prop, explanation=out["explanation"],
                            evidence_ids=out["evidence_ids"])
            self.store.save_decision(job_id, self.run_id, job_id, state.state_id, tool_results=out["tool_results"],
                                     rule_version=state.trigger.rule_version, model_id=out["model_id"],
                                     explanation_kind=out["explanation_kind"], before_version=v["schedule_version"],
                                     after_version=None, evidence_ids=out["evidence_ids"],
                                     explanation=out["explanation"] or "",
                                     proposal=prop.model_dump(mode="json") if prop else None)
            if prop:
                self.bus.emit(self.run_id, "schedule.proposed", {"job_id": job_id, "proposal_id": prop.proposal_id,
                                                                 "status": prop.status})
            if out["explanation"]:
                self.bus.emit(self.run_id, "agent.explanation", {"job_id": job_id, "text": out["explanation"],
                                                                 "kind": out["explanation_kind"]})
        except Exception as e:  # noqa: BLE001 - any failure must leave the schedule intact
            body = e.body if isinstance(e, ApiError) else ErrorBody(code="JOB_FAILED", message=str(e)[:300])
            job = ReplanJob(job_id=job_id, status="failed", error=body)
            self.bus.emit(self.run_id, "pipeline.error", {"job_id": job_id, "code": body.code, "message": body.message})
        self.store.save_job(self.run_id, req.state_id, v, job)
        if self.auto_apply and job.status == "ready" and job.proposal is not None and job.proposal.validation.passed:
            try:
                self.apply(job_id, v["schedule_version"])
            except ApiError as e:
                self.bus.emit(self.run_id, "pipeline.error", {"job_id": job_id, "code": e.body.code, "message": e.body.message})

    def apply(self, job_id: str, expected_schedule_version: int) -> Schedule:
        """One-time commit: checks versions, re-validates against the current calendar, then increments version."""
        with self.lock:
            job = self.store.job(job_id)
            if job is None:
                raise ApiError(404, "NOT_FOUND", "unknown job")
            if job.status == "applied":
                raise ApiError(409, "ALREADY_APPLIED", "this proposal was already applied")
            if job.status != "ready" or job.proposal is None:
                raise ApiError(422, "NOTHING_TO_APPLY", "job has no applicable proposal")
            cal, cur, p = self.calendar(), self.schedule(), job.proposal
            if expected_schedule_version != cur.schedule_version or p.schedule_version != cur.schedule_version \
                    or (p.calendar_version, p.tasks_version) != (cal.calendar_version, cal.tasks_version):
                raise ApiError(409, "STALE_VERSION", "schedule, calendar or tasks changed since proposal; replan")
            rep = validate_proposal(cal, p)
            if not rep.passed:
                raise ApiError(422, "INVALID_PROPOSAL", "; ".join(rep.messages))
            new = Schedule(schedule_version=cur.schedule_version + 1, blocks=p.blocks, unscheduled_work=p.unscheduled_work)
            self.store.save_schedule(self.run_id, new)
            job.status = "applied"
            self.store.save_job(self.run_id, p.based_on_state_id, {"calendar_version": p.calendar_version,
                                "tasks_version": p.tasks_version, "schedule_version": p.schedule_version}, job)
            snap = self.snapshot()
            self.store.mark_applied(job_id, new.schedule_version, snap.as_of if snap else datetime.now().astimezone())
            self.bus.emit(self.run_id, "schedule.applied", {"job_id": job_id, "schedule_version": new.schedule_version})
            return new

    def job(self, job_id: str) -> ReplanJob:
        j = self.store.job(job_id)
        if j is None:
            raise ApiError(404, "NOT_FOUND", "unknown job")
        return j

    def decision(self, decision_id: str) -> dict[str, Any]:
        d = self.store.decision(decision_id)
        if d is None:
            raise ApiError(404, "NOT_FOUND", "unknown decision")
        return d

    def progress(self, task_id: str, completed: int, expected_tasks_version: int) -> CalendarBundle:
        try:
            return self.store.record_progress(self.run_id, task_id, completed, expected_tasks_version)
        except ValueError:
            raise ApiError(409, "STALE_VERSION", "tasks changed; refetch")
        except KeyError:
            raise ApiError(404, "NOT_FOUND", "unknown task")


def dumps(m) -> Any:
    return json.loads(m.model_dump_json())
