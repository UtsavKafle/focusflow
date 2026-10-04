"""Unit tests for backend/app/trigger.py (integrator task 4): one test per rule branch."""
import json, pathlib
from datetime import datetime, timedelta

import pytest

from backend.app.trigger import MinuteLoad, TriggerContext, TriggerEngine, evaluate, sustained_load
from contracts.models import AcademicState, Schedule, StudentState

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
Z = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
ALL3 = ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"]


def base(scn="trigger"):
    rd = lambda f: json.loads((FIX / scn / f).read_text())
    st = StudentState.model_validate(rd("states.json")[-1])
    hist = [MinuteLoad(Z(h["window_end"]), h["physiological_load"] if h["quality"] == "valid" else None) for h in rd("history.json")]
    acad = AcademicState(calendar_version=1, tasks_version=3, schedule_version=2, deadline_pressure=0.9)
    return st, hist, acad, Schedule.model_validate(rd("schedule.json"))


def ev(st, hist, acad, sched, **ctx):
    return evaluate(st.as_of, st.wearable, hist, acad, sched, TriggerContext(**ctx))


def test_fires_when_all_conditions_hold():
    t = ev(*base())
    assert t.replan_recommended and t.reason_codes == ALL3 and t.suppressed_reason_codes == []
    assert t.rule_version == "demo-rules-2"


def test_normal_load_does_not_fire():
    t = ev(*base("normal"))
    assert not t.replan_recommended and "SUSTAINED_LOAD" not in t.reason_codes


def test_gap_resets_persistence_window():
    st, hist, acad, sched = base()
    gap_at = st.as_of - timedelta(minutes=5)
    hist = [MinuteLoad(h.window_end, None if h.window_end == gap_at else h.load) for h in hist]
    assert not sustained_load(hist, st.as_of)
    assert "SUSTAINED_LOAD" not in ev(st, hist, acad, sched).reason_codes


def test_needs_15_of_20_above_threshold():
    st, hist, acad, sched = base()
    last20 = {st.as_of - timedelta(minutes=i) for i in range(20)}
    low = sorted(last20)[:6]  # 6 low minutes -> only 14 high
    hist = [MinuteLoad(h.window_end, 0.5 if h.window_end in low else h.load) for h in hist]
    assert not sustained_load(hist, st.as_of)


def test_unknown_recovery_never_fires():
    st, hist, acad, sched = base("missing_data")
    t = ev(st, hist, acad, sched)
    assert not t.replan_recommended and "RECOVERY_UNKNOWN" in t.suppressed_reason_codes


def test_low_overnight_coverage_suppresses():
    st, hist, acad, sched = base()
    st.wearable.quality.overnight_coverage = 0.3
    t = ev(st, hist, acad, sched)
    assert not t.replan_recommended and "INSUFFICIENT_OVERNIGHT_EVIDENCE" in t.suppressed_reason_codes


def test_low_pressure_does_not_fire():
    st, hist, acad, sched = base()
    acad.deadline_pressure = 0.05  # below the 0.10 demo threshold
    t = ev(st, hist, acad, sched)
    assert not t.replan_recommended and "HIGH_PRESSURE" not in t.reason_codes


@pytest.mark.parametrize("mutate,code", [
    (lambda st, s, c: setattr(st.wearable, "baseline_id", None), "INSUFFICIENT_BASELINE"),
    (lambda st, s, c: setattr(st.wearable, "baseline_cutoff", st.as_of + timedelta(hours=1)), "INSUFFICIENT_BASELINE"),
    (lambda st, s, c: setattr(st.wearable.quality, "status", "limited"), "INSUFFICIENT_DATA"),
    (lambda st, s, c: c.update(activity_confound=True), "ACTIVITY_CONFOUND"),
    (lambda st, s, c: c.update(pending_decision=True), "PENDING_DECISION"),
    (lambda st, s, c: c.update(last_applied_at=st.as_of - timedelta(minutes=30)), "COOLDOWN"),
    (lambda st, s, c: setattr(s, "blocks", [b for b in s.blocks if b.kind != "study" or b.locked]), "NO_FLEXIBLE_BLOCK"),
])
def test_gates_suppress(mutate, code):
    st, hist, acad, sched = base()
    ctx = {}
    mutate(st, sched, ctx)
    t = ev(st, hist, acad, sched, **ctx)
    assert not t.replan_recommended and code in t.suppressed_reason_codes


def test_cooldown_expires_after_60_replay_minutes():
    st, hist, acad, sched = base()
    assert ev(st, hist, acad, sched, last_applied_at=st.as_of - timedelta(minutes=60)).replan_recommended


def test_hysteresis_rearms_below_reset_threshold():
    st, hist, acad, sched = base()
    eng = TriggerEngine()
    assert eng.evaluate(st.as_of, st.wearable, hist, acad, sched, TriggerContext()).replan_recommended
    eng.consume()
    t = eng.evaluate(st.as_of, st.wearable, hist, acad, sched, TriggerContext())
    assert not t.replan_recommended and "AWAITING_RESET" in t.suppressed_reason_codes
    eng.observe(0.50)  # load drops below 0.55 -> re-armed
    assert eng.evaluate(st.as_of, st.wearable, hist, acad, sched, TriggerContext()).replan_recommended
