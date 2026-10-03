"""Agent tools (integrator task 9, HANDOFF 9.6). Spec: contracts/agent_tools.json. Local Python wrappers over backend
services (no MCP). Every result carries time ranges + evidence IDs so explanations can be checked.
The agent may only pass permitted reason codes; request_schedule_replan returns a proposal and never applies it."""
from __future__ import annotations

import json, pathlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

SPEC = json.loads((pathlib.Path(__file__).resolve().parents[1] / "contracts" / "agent_tools.json").read_text())
PERMITTED_REASONS = {"SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"}
MAX_HISTORY = timedelta(hours=6)
WINDOWS = {"last_20_min": 20, "last_60_min": 60, "last_120_min": 120}


def tool_names() -> list[str]:
    return [t["name"] for t in SPEC["tools"]]


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _dump(m) -> Any:
    return json.loads(m.model_dump_json())


class ToolError(Exception):
    pass


class ToolBox:
    """Executes tools against Services for one investigation. Keeps the proposal the scheduler returned."""

    def __init__(self, svc, state):
        self.svc, self.state = svc, state
        self.proposal = None
        self.calls: list[dict] = []

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None or name not in tool_names():
            raise ToolError(f"unknown tool {name}")
        try:
            out = fn(**(args or {}))
        except ToolError:
            raise
        except TypeError as e:
            raise ToolError(f"bad arguments for {name}: {e}")
        self.calls.append({"tool": name, "args": args, "result": out})
        return out

    # ---- tools ----
    def t_get_current_student_state(self, run_id: Optional[str] = None) -> dict:
        return _dump(self.state)

    def t_get_physiology_history(self, start: str, end: str, metrics: Optional[list[str]] = None) -> dict:
        s, e = _ts(start), min(_ts(end), self.state.as_of)
        if e - s > MAX_HISTORY:
            s = e - MAX_HISTORY  # bounded range
        keep = set(metrics or ["heart_rate_bpm", "physiological_load", "activity_level"])
        rows = self.svc.history(s, e)["windows"]
        return {"start": _iso(s), "end": _iso(e), "source_kind": self.state.source_kind,
                "windows": [{k: v for k, v in r.items() if k in keep | {"window_start", "window_end", "quality", "evidence_id"}}
                            for r in rows]}

    def t_compare_to_baseline(self, metric: str, window: str) -> dict:
        w = self.state.wearable
        base = {"metric": metric, "window": window, "baseline_id": w.baseline_id,
                "baseline_cutoff": _iso(w.baseline_cutoff) if w.baseline_cutoff else None,
                "note": "physiological_load is a baseline-relative heuristic (0 = at personal baseline, 1 = >= 3 robust SD above); not a diagnosis"}
        if window == "last_night":
            return {**base, **self.t_get_recent_rest(_iso(self.state.as_of))}
        if window not in WINDOWS:
            raise ToolError(f"window must be one of {sorted(WINDOWS) + ['last_night']}")
        end = self.state.as_of
        start = end - timedelta(minutes=WINDOWS[window])
        rows = [r for r in self.svc.history(start, end)["windows"] if r.get("quality") in ("valid", "sufficient")
                and _ts(r["window_end"]) > start]  # exactly N one-minute windows ending at as_of
        vals = [r.get(metric) for r in rows if r.get(metric) is not None]
        if metric not in ("physiological_load", "heart_rate_bpm", "activity_level"):
            raise ToolError("metric must be physiological_load, heart_rate_bpm or activity_level")
        out = {**base, "start": _iso(start), "end": _iso(end), "valid_minutes": len(vals),
               "window_minutes": WINDOWS[window],
               "evidence_ids": [r["evidence_id"] for r in rows if r.get("evidence_id")][-3:]}
        if not vals:
            return {**out, "mean": None, "missing_reason": "no valid minutes in window"}
        out.update(mean=round(sum(vals) / len(vals), 2), min=round(min(vals), 2), max=round(max(vals), 2))
        if metric == "physiological_load":
            out["threshold"] = 0.70
            out["minutes_at_or_above_threshold"] = sum(v >= 0.70 for v in vals)
        else:
            out["baseline_deviation"] = None
            out["missing_reason"] = "raw baseline statistics for this metric are not exposed by Gold; use physiological_load"
        return out

    def t_get_recent_rest(self, as_of: Optional[str] = None) -> dict:
        w = self.state.wearable
        q = w.quality
        lim = ["Estimated rest from low movement and compatible HR; not sleep staging or sleep quality.",
               "Inactivity may be quiet wakefulness or a removed device."]
        if w.estimated_rest_minutes is None:
            lim.append(f"Unknown: {q.missing_reasons.get('estimated_rest_minutes', 'insufficient overnight data')}")
        return {"as_of": _iso(self.state.as_of), "estimated_rest_minutes": w.estimated_rest_minutes,
                "target_rest_minutes": w.target_rest_minutes, "recovery_score": w.recovery_score,
                "overnight_coverage": q.overnight_coverage, "limitations": lim,
                "evidence_ids": [e for e in w.evidence_ids if e.startswith("rest-")]}

    def t_get_upcoming_deadlines(self, as_of: Optional[str] = None) -> dict:
        now = self.state.as_of
        cal = self.svc.calendar()
        hrs = lambda d: round((d - now).total_seconds() / 3600, 2)
        return {"as_of": _iso(now), "timezone": cal.timezone,
                "fixed_events": [{"event_id": e.event_id, "title": e.title, "kind": e.kind, "start": _iso(e.start),
                                  "end": _iso(e.end), "hours_until": hrs(e.start)}
                                 for e in sorted(cal.fixed_events, key=lambda e: e.start) if e.end > now],
                "task_deadlines": [{"task_id": t.task_id, "title": t.title, "deadline": _iso(t.deadline),
                                    "hours_until": hrs(t.deadline), "remaining_minutes": t.remaining_minutes}
                                   for t in sorted(cal.tasks, key=lambda t: t.deadline) if t.status != "done"]}

    def t_get_remaining_tasks(self) -> dict:
        cal = self.svc.calendar()
        return {"tasks_version": cal.tasks_version, "tasks": [_dump(t) for t in cal.tasks],
                "note": "progress comes only from explicit user input"}

    def t_request_schedule_replan(self, state_id: str, schedule_version: int, reason_codes: list[str]) -> dict:
        bad = set(reason_codes) - PERMITTED_REASONS
        if bad or not reason_codes:
            raise ToolError(f"reason_codes must be a non-empty subset of {sorted(PERMITTED_REASONS)}; got {sorted(bad)}")
        if state_id != self.state.state_id or schedule_version != self.svc.schedule().schedule_version:
            raise ToolError("STALE_VERSION: state_id or schedule_version does not match the current state")
        self.proposal = self.svc.request_proposal(sorted(set(reason_codes)), self.state)
        return summarize_proposal(self.proposal, self.svc.schedule())

    def t_get_schedule_change(self, decision_id: str) -> dict:
        d = self.svc.store.decision(decision_id)
        if d is None:
            raise ToolError("unknown decision")
        return {k: d[k] for k in ("decision_id", "state_id", "rule_version", "before_version", "after_version",
                                  "evidence_ids", "explanation", "explanation_kind", "proposal")}


def summarize_proposal(p, before) -> dict:
    """The diff the agent explains: old/new block times per change, unscheduled work, validation. Not applied."""
    old = {b.block_id: b for b in before.blocks}
    new = {b.block_id: b for b in p.blocks}
    span = lambda b: {"block_id": b.block_id, "task_id": b.task_id, "kind": b.kind, "start": _iso(b.start),
                      "end": _iso(b.end), "minutes": b.minutes}
    return {"proposal_id": p.proposal_id, "status": p.status, "applied": False,
            "validation_passed": p.validation.passed, "validation_checks": p.validation.checks,
            "changes": [{"action": c.action, "reason_code": c.reason_code,
                         "old_blocks": [span(old[i]) for i in c.old_block_ids if i in old],
                         "new_blocks": [span(new[i]) for i in c.new_block_ids if i in new]} for c in p.changes],
            "unscheduled_work": [{"task_id": u.task_id, "minutes": u.minutes, "deadline": _iso(u.deadline),
                                  "reason": u.reason} for u in p.unscheduled_work]}
