"""Generate four coherent SYNTHETIC scenarios under fixtures/scenarios/. Deterministic, no randomness.
Every payload is source_kind=synthetic_fixture. Do not present these as real wearable data.

Scenarios: normal (no trigger), trigger (feasible revision), missing_data (suppressed trigger),
infeasible (overloaded; partial proposal with unscheduled work).
Anchor: Mon 2026-10-12 23:20 ET == 2026-10-13T03:20:00Z (EDT, UTC-4). STAT exam Tue 09:00 ET.
"""
from __future__ import annotations

import json, pathlib, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from contracts.models import (AcademicState, CalendarBundle, FixedEvent, Interval, Quality, Schedule,
                              ScheduleBlock, ScheduleChange, ScheduleProposal, StudentState, Task,
                              Trigger, UnscheduledWork, WearableState)
from scheduler.validate import check_blocks

OUT = pathlib.Path(__file__).parent / "scenarios"
UTC = timezone.utc
AS_OF = datetime(2026, 10, 13, 3, 20, tzinfo=UTC)
RUN, PID, TZ = "fixture-run-001", "fixture-participant", "America/New_York"


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=UTC)


def iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def blk(bid, task, kind, s, e, locked=False):
    return ScheduleBlock(block_id=bid, task_id=task, kind=kind, start=s, end=e, locked=locked)


def calendar(extra_tasks=()) -> CalendarBundle:
    tasks = [
        Task(task_id="algorithms-review", title="Algorithms review", remaining_minutes=90, deadline=at(14, 19, 30), priority=6, splittable=True, minimum_block_minutes=30),
        Task(task_id="stat-exam-prep", title="STAT exam preparation", remaining_minutes=45, deadline=at(13, 12, 45), priority=9, splittable=False, minimum_block_minutes=45),
        Task(task_id="db-assignment-3", title="Databases assignment 3", remaining_minutes=120, deadline=at(15, 4, 0), priority=5, splittable=True, minimum_block_minutes=30),
        Task(task_id="writing-reflection", title="Writing reflection", remaining_minutes=60, deadline=at(15, 4, 0), priority=3, splittable=True, minimum_block_minutes=30),
        *extra_tasks,
    ]
    fixed = [
        FixedEvent(event_id="stat-exam", title="STAT exam", kind="exam", start=at(13, 13), end=at(13, 14)),
        FixedEvent(event_id="csc316-lecture", title="CSC 316 lecture", kind="class", start=at(13, 15, 45), end=at(13, 17)),
        FixedEvent(event_id="db-quiz", title="DB quiz", kind="quiz", start=at(14, 18), end=at(14, 18, 30)),
        FixedEvent(event_id="algorithms-midterm", title="Algorithms midterm", kind="exam", start=at(15, 14), end=at(15, 15, 15)),
    ]
    allowed = [Interval(start=at(d, 12), end=at(d + 1, 5)) for d in (12, 13, 14)]   # 08:00-01:00 ET
    sleep = [Interval(start=at(d, 5), end=at(d, 12)) for d in (13, 14, 15)]          # 01:00-08:00 ET
    return CalendarBundle(calendar_version=1, tasks_version=3, timezone=TZ, tasks=tasks, fixed_events=fixed,
                          allowed_study_intervals=allowed, protected_sleep_intervals=sleep)


def base_blocks(cal: CalendarBundle):
    b = [blk(f"fixed-{e.event_id}", None, "fixed", e.start, e.end, True) for e in cal.fixed_events]
    b += [blk(f"sleep-{i.start:%d}", None, "sleep_protected", i.start, i.end, True) for i in cal.protected_sleep_intervals]
    return b


def initial_study():
    return [
        blk("blk-stat-prep", "stat-exam-prep", "study", at(13, 12), at(13, 12, 45), True),
        blk("blk-alg-1", "algorithms-review", "study", at(13, 3, 30), at(13, 5)),
        blk("blk-db-1", "db-assignment-3", "study", at(13, 17, 30), at(13, 18, 30)),
        blk("blk-db-1b", "db-assignment-3", "study", at(13, 18, 45), at(13, 19, 45)),
        blk("blk-writing-1", "writing-reflection", "study", at(14, 12, 30), at(14, 13, 30)),
    ]


def diff(old, new):
    changes, n = [], 0
    oldmap, newmap = {}, {}
    for b in old:
        if b.kind == "study": oldmap.setdefault(b.task_id, []).append(b)
        elif b.kind == "sleep_extension": oldmap.setdefault("_sleep", []).append(b)
    for b in new:
        if b.kind == "study": newmap.setdefault(b.task_id, []).append(b)
        elif b.kind == "sleep_extension": newmap.setdefault("_sleep", []).append(b)
    for key in sorted(set(oldmap) | set(newmap)):
        o, nw = oldmap.get(key, []), newmap.get(key, [])
        sig = lambda bl: [(x.start, x.end) for x in bl]
        if sig(o) == sig(nw):
            continue
        n += 1
        if key == "_sleep":
            changes.append(ScheduleChange(change_id=f"chg-{n}", action="added", old_block_ids=[], new_block_ids=[x.block_id for x in nw], reason_code="PROTECT_REST"))
        else:
            action = "added" if not o else ("removed" if not nw else "moved")
            changes.append(ScheduleChange(change_id=f"chg-{n}", action=action, old_block_ids=[x.block_id for x in o], new_block_ids=[x.block_id for x in nw], reason_code="PROTECT_REST" if key == "algorithms-review" else "MAKE_ROOM"))
    return changes


# ---- wearable series (deterministic) ----
def load_at(scn: str, minute_offset: int) -> float | None:
    """minute_offset: minutes relative to AS_OF (negative = past)."""
    m = minute_offset
    if scn == "normal":
        return round(0.28 + 0.04 * ((m // 7) % 3), 2)
    if scn in ("trigger", "infeasible"):
        if m < -45:
            return round(0.40 + 0.004 * (m + 120), 2)   # 0.40 .. 0.70 climbing
        return round(min(0.86, 0.72 + 0.004 * (m + 45)), 2)  # >= 0.72 for the last 45 minutes
    if scn == "missing_data":
        return None if m > -40 else 0.5
    return None


def make_states(scn: str, cal: CalendarBundle):
    history, states = [], []
    loads = {}
    for m in range(-120, 1):
        t = AS_OF + timedelta(minutes=m)
        ld = load_at(scn, m)
        hr_ok = not (scn == "missing_data" and m > -40)
        loads[m] = ld
        hr = None if not hr_ok else round(60 + 35 * (ld or 0.3), 1)
        history.append({"window_start": iso(t - timedelta(minutes=1)), "window_end": iso(t), "heart_rate_bpm": hr,
                        "physiological_load": ld, "activity_level": 0.08 if scn != "normal" else 0.1,
                        "quality": "valid" if hr_ok else "unavailable", "evidence_id": f"window-{120 + m:04d}"})
    est_rest = {"normal": 460, "trigger": 210, "infeasible": 210, "missing_data": None}[scn]
    n = 0
    for m in range(-90, 1, 5):
        n += 1
        t = AS_OF + timedelta(minutes=m)
        hours = round((at(13, 13) - t).total_seconds() / 3600, 2)
        pressure = round(min(1.0, max(0.0, 1 - hours / 72)), 2)  # heuristic stand-in for fixtures only
        recent = [loads[k] for k in range(m - 19, m + 1)]
        valid = [v for v in recent if v is not None]
        sustained = len(valid) >= 15 and sum(v >= 0.70 for v in valid) >= 15
        rec = None if est_rest is None else round(est_rest / 480, 4)
        codes, supp = [], []
        if sustained: codes.append("SUSTAINED_LOAD")
        if rec is not None and rec < 0.50: codes.append("LIMITED_ESTIMATED_REST")
        if pressure >= 0.70: codes.append("HIGH_PRESSURE")
        fire = len(codes) == 3
        if scn == "missing_data" and len(valid) < 15: supp.append("INSUFFICIENT_DATA")
        cur = loads[m]
        reasons = {}
        if cur is None: reasons.update(physiological_load="hr_coverage_below_threshold", heart_rate_bpm="no_valid_hr_in_window")
        if est_rest is None: reasons.update(estimated_rest_minutes="overnight_coverage_below_minimum", recovery_score="estimated_rest_unavailable")
        status = "unavailable" if cur is None else "sufficient"
        w = WearableState(
            window_start=t - timedelta(minutes=1), window_end=t,
            heart_rate_bpm=None if cur is None else round(60 + 35 * cur, 1), physiological_load=cur,
            activity_level=0.08 if cur is not None else None,
            estimated_rest_minutes=est_rest, target_rest_minutes=480, recovery_score=rec,
            quality=Quality(status=status, hr_coverage=0.31 if cur is None else 0.98, eda_coverage=0.30 if cur is None else 0.96,
                            acc_coverage=0.99, overnight_coverage=0.2 if est_rest is None else 0.93, missing_reasons={**reasons, **({"activity_level": "acc_unavailable"} if cur is None else {})}),
            baseline_id="baseline-01", baseline_cutoff=datetime(2026, 10, 12, tzinfo=UTC),
            evidence_ids=[f"window-{120 + m:04d}"] + (["rest-0002"] if est_rest else []))
        rem = sum(t_.remaining_minutes for t_ in cal.tasks)
        states.append(StudentState(
            state_id=f"state-{n:04d}", run_id=RUN, participant_id=PID, as_of=t, scenario_timezone=TZ, source_kind="synthetic_fixture",
            wearable=w, academic=AcademicState(calendar_version=1, tasks_version=3, schedule_version=2, deadline_pressure=pressure,
                                               hours_until_next_exam=hours, remaining_work_minutes=rem, overdue_task_ids=[]),
            trigger=Trigger(replan_recommended=fire, reason_codes=codes if fire else [c for c in codes], suppressed_reason_codes=supp)))
    return states, history


def revised(cal, scn):
    base = base_blocks(cal)
    old = base + initial_study()
    ext = blk("blk-sleep-ext-1", None, "sleep_extension", at(13, 3, 30), at(13, 5), True)
    if scn == "trigger":
        study = [initial_study()[0], blk("blk-alg-2", "algorithms-review", "study", at(13, 14), at(13, 15)),
                 blk("blk-alg-3", "algorithms-review", "study", at(13, 17), at(13, 17, 30)),
                 initial_study()[2], initial_study()[3], initial_study()[4]]
        return old, base + study + [ext], {}
    # infeasible: thesis draft due Tue 16:00 ET cannot fit with protected sleep + exam day
    study = [initial_study()[0],
             blk("blk-thesis-1", "thesis-draft", "study", at(13, 14), at(13, 15, 30)),
             blk("blk-thesis-2", "thesis-draft", "study", at(13, 17), at(13, 18, 30)),
             blk("blk-thesis-3", "thesis-draft", "study", at(13, 18, 45), at(13, 19, 45)),
             blk("blk-alg-2", "algorithms-review", "study", at(14, 12), at(14, 13, 30)),
             blk("blk-db-2", "db-assignment-3", "study", at(14, 14), at(14, 15)),
             blk("blk-db-2b", "db-assignment-3", "study", at(14, 15, 15), at(14, 16, 15)),
             blk("blk-writing-2", "writing-reflection", "study", at(14, 16, 30), at(14, 17, 30))]
    return old, base + study + [ext], {"thesis-draft": 240}


def explanation(scn):
    if scn == "trigger":
        return {"text": "Fixture explanation. Over the last 20 minutes your estimated physiological load stayed high (above your own baseline), your estimated rest last night was about 3.5 of 8 target hours, and the STAT exam is under 10 hours away. I moved Algorithms review out of the 11:30 PM to 1:00 AM slot, protected that time for rest, and rescheduled it to 10:00 AM and 1:00 PM tomorrow, before its Wednesday deadline. Heuristic estimates from wearable signals; not a medical assessment.",
                "evidence_ids": ["window-0098", "window-0120", "rest-0002"], "synthetic": True}
    if scn == "infeasible":
        return {"text": "Fixture explanation. Not everything fits. Protecting rest and keeping exam hours leaves 240 minutes of the thesis draft unscheduled before its deadline. Options: ask for an extension, shorten scope, or trade rest time. Nothing was applied automatically.",
                "evidence_ids": ["window-0120", "rest-0002"], "synthetic": True}
    return None


def write(path: pathlib.Path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for scn in ("normal", "trigger", "missing_data", "infeasible"):
        d = OUT / scn
        d.mkdir(exist_ok=True)
        extra = [Task(task_id="thesis-draft", title="Thesis draft", remaining_minutes=480, deadline=at(13, 20), priority=9, splittable=True, minimum_block_minutes=30)] if scn == "infeasible" else []
        cal = calendar(extra)
        states, history = make_states(scn, cal)
        base = base_blocks(cal) + initial_study()
        if scn == "infeasible":
            base = [b for b in base]  # initial plan predates the thesis task; thesis appears as unscheduled in sched v2
        init_unsched = [UnscheduledWork(task_id="thesis-draft", minutes=480, deadline=at(13, 20), reason="NOT_YET_PLANNED")] if scn == "infeasible" else []
        sched = Schedule(schedule_version=2, blocks=base, unscheduled_work=init_unsched)
        proposal, expl = None, explanation(scn)
        if scn in ("trigger", "infeasible"):
            old, new, un = revised(cal, scn)
            uw = [UnscheduledWork(task_id=k, minutes=v, deadline=cal.tasks[-1].deadline, reason="INSUFFICIENT_CAPACITY_BEFORE_DEADLINE") for k, v in un.items()]
            rep = check_blocks(cal, new, un)
            proposal = ScheduleProposal(proposal_id=f"proposal-{scn}-001", based_on_state_id=states[-1].state_id, calendar_version=1, tasks_version=3,
                                        schedule_version=2, status="partial" if un else "feasible", blocks=new, changes=diff(old, new),
                                        unscheduled_work=uw, validation=rep)
            assert rep.passed, (scn, rep.messages)
        write(d / "calendar.json", json.loads(cal.model_dump_json()))
        write(d / "schedule.json", json.loads(sched.model_dump_json()))
        write(d / "states.json", [json.loads(s.model_dump_json()) for s in states])
        write(d / "history.json", history)
        write(d / "proposal.json", json.loads(proposal.model_dump_json()) if proposal else None)
        write(d / "explanation.json", expl)
        write(d / "meta.json", {"scenario": scn, "source_kind": "synthetic_fixture", "run_id": RUN, "participant_id": PID,
                                 "as_of": iso(AS_OF), "label": "SYNTHETIC FIXTURE - not real wearable data"})
    print("fixtures written to", OUT)


if __name__ == "__main__":
    build()
