"""Golden tests for scheduler/optimize.py against fixtures/scenarios (integrator task 1)."""
import json, pathlib
from datetime import datetime, timezone

from contracts.models import CalendarBundle, Schedule, ScheduleProposal, StudentState, Task
from scheduler.optimize import optimize_schedule, policy_for_reasons
from scheduler.validate import validate_proposal

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
REST = ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"]
Z = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(s):
    rd = lambda f: json.loads((FIX / s / f).read_text())
    cal, sched = CalendarBundle.model_validate(rd("calendar.json")), Schedule.model_validate(rd("schedule.json"))
    st = StudentState.model_validate(rd("states.json")[-1])
    fx = ScheduleProposal.model_validate(rd("proposal.json")) if rd("proposal.json") else None
    return cal, sched, st, fx


def minutes(p):
    out = {}
    for b in p.blocks:
        if b.kind == "study": out[b.task_id] = out.get(b.task_id, 0) + b.minutes
    return out


def run(s, codes=REST, **kw):
    cal, sched, st, fx = load(s)
    cal = cal.model_copy(update=kw) if kw else cal
    return cal, st, fx, optimize_schedule(st.as_of, None, cal, sched, st, policy_for_reasons(codes))


def test_trigger_tuesday_story():
    cal, st, fx, p = run("trigger")
    assert p.status == fx.status == "feasible"
    assert p.validation.passed and validate_proposal(cal, p).passed
    assert minutes(p) == minutes(fx)
    alg = [b for b in p.blocks if b.task_id == "algorithms-review"]
    assert sum(b.minutes for b in alg) == 90
    assert all(not (b.start < Z("2026-10-13T05:00:00Z") and Z("2026-10-13T03:30:00Z") < b.end) for b in alg)
    assert all(b.end <= Z("2026-10-14T19:30:00Z") for b in alg)
    ext = [b for b in p.blocks if b.kind == "sleep_extension"]
    assert len(ext) == 1 and ext[0].end == Z("2026-10-13T05:00:00Z")
    assert {(c.action, c.reason_code) for c in p.changes} == {("added", "PROTECT_REST"), ("moved", "PROTECT_REST")}
    stat = next(b for b in p.blocks if b.task_id == "stat-exam-prep")
    assert (stat.block_id, stat.start) == ("blk-stat-prep", Z("2026-10-13T12:00:00Z"))  # STAT prep unchanged


def test_infeasible_partial_with_shortfall():
    cal, st, fx, p = run("infeasible")
    assert p.status == fx.status == "partial" and p.validation.passed
    assert [u.task_id for u in p.unscheduled_work] == ["thesis-draft"]
    got, want = minutes(p), minutes(fx)
    assert {k: v for k, v in got.items() if k != "thesis-draft"} == {k: v for k, v in want.items() if k != "thesis-draft"}
    assert got["thesis-draft"] >= want["thesis-draft"]  # placement at least as good as the hand-made fixture
    assert got["thesis-draft"] + p.unscheduled_work[0].minutes == 480


def test_no_rest_reason_means_no_change():
    cal, st, fx, p = run("normal", codes=["HIGH_PRESSURE"])
    assert p.status == "feasible" and p.validation.passed and p.changes == []
    assert not any(b.kind == "sleep_extension" for b in p.blocks)


def test_deterministic():
    assert run("trigger")[3] == run("trigger")[3]
    assert run("infeasible")[3] == run("infeasible")[3]


def test_never_before_now():
    cal, sched, st, _ = load("normal")
    now = datetime(2026, 10, 13, 17, 40, tzinfo=timezone.utc)
    cal = cal.model_copy(update={"tasks": [t for t in cal.tasks if t.task_id != "stat-exam-prep"]})
    sched = sched.model_copy(update={"blocks": [b for b in sched.blocks if b.task_id != "stat-exam-prep"]})
    p = optimize_schedule(now, None, cal, sched, st, policy_for_reasons(["HIGH_PRESSURE"]))
    assert p.validation.passed
    old_ids = {b.block_id for b in sched.blocks}
    assert all(b.start >= now for b in p.blocks if b.kind == "study" and b.block_id not in old_ids)
    assert any(b.block_id == "blk-db-1" for b in p.blocks)  # in-progress block (17:30-18:30) kept stable


def test_unsplittable_too_long_is_reported():
    cal, sched, st, _ = load("normal")
    big = Task(task_id="big", title="Big", remaining_minutes=120, deadline=Z("2026-10-15T04:00:00Z"), priority=5, splittable=False)
    cal = cal.model_copy(update={"tasks": cal.tasks + [big]})
    p = optimize_schedule(st.as_of, None, cal, sched, st, policy_for_reasons(["HIGH_PRESSURE"]))
    assert p.status == "partial" and p.validation.passed
    assert [(u.task_id, u.reason) for u in p.unscheduled_work] == [("big", "UNSPLITTABLE_EXCEEDS_MAX_CONTINUOUS")]
