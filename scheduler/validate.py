"""Independent validator for ScheduleProposals (pure Python). Used by fixtures, tests and the backend
before any apply. The scheduler itself should call this on its own output (belt and braces)."""
from __future__ import annotations

from contracts.models import CalendarBundle, ScheduleBlock, ScheduleProposal, ValidationReport


def _overlap(a: ScheduleBlock, b: ScheduleBlock) -> bool:
    return a.start < b.end and b.start < a.end


def check_blocks(cal: CalendarBundle, blocks: list[ScheduleBlock], unscheduled: dict[str, int] | None = None) -> ValidationReport:
    unscheduled = unscheduled or {}
    msgs: list[str] = []
    study = [b for b in blocks if b.kind == "study"]
    nonstudy = [b for b in blocks if b.kind != "study"]
    checks: dict[str, bool] = {}

    # no overlaps among any blocks, and with fixed events / protected sleep
    ordered = sorted(blocks, key=lambda b: (b.start, b.end, b.block_id))
    ok = True
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b.start >= a.end:
                break
            ok = False
            msgs.append(f"overlap: {a.block_id} and {b.block_id}")
    for s in study:
        for fe in cal.fixed_events:
            if s.start < fe.end and fe.start < s.end:
                ok = False
                msgs.append(f"{s.block_id} overlaps fixed event {fe.event_id}")
        for ps in cal.protected_sleep_intervals:
            if s.start < ps.end and ps.start < s.end:
                ok = False
                msgs.append(f"{s.block_id} overlaps protected sleep")
    checks["no_overlap"] = ok

    # inside allowed study intervals
    ok = True
    for s in study:
        if not any(a.start <= s.start and s.end <= a.end for a in cal.allowed_study_intervals):
            ok = False
            msgs.append(f"{s.block_id} outside allowed study intervals")
    checks["within_allowed_intervals"] = ok

    # deadlines and minute accounting
    tasks = {t.task_id: t for t in cal.tasks}
    ok_dl, ok_min, ok_blk, ok_max = True, True, True, True
    pm = cal.preferences
    for tid, t in tasks.items():
        if t.status == "done" or t.remaining_minutes == 0:
            continue
        mine = [b for b in study if b.task_id == tid]
        got = sum(b.minutes for b in mine)
        if got + unscheduled.get(tid, 0) != t.remaining_minutes:
            ok_min = False
            msgs.append(f"{tid}: scheduled {got} + unscheduled {unscheduled.get(tid, 0)} != remaining {t.remaining_minutes}")
        for b in mine:
            if b.end > t.deadline:
                ok_dl = False
                msgs.append(f"{b.block_id} ends after deadline of {tid}")
            if b.minutes < min(t.minimum_block_minutes, t.remaining_minutes):
                ok_blk = False
                msgs.append(f"{b.block_id} shorter than minimum block")
            if b.minutes > pm.maximum_continuous_study_minutes:
                ok_max = False
                msgs.append(f"{b.block_id} exceeds max continuous study")
            if not t.splittable and len(mine) > 1:
                ok_blk = False
                msgs.append(f"{tid} is not splittable")
    unknown = [b.block_id for b in study if b.task_id not in tasks]
    if unknown:
        ok_min = False
        msgs.append(f"study blocks with unknown task: {unknown}")
    checks.update(deadlines_met=ok_dl, minutes_conserved=ok_min, min_block_size=ok_blk, max_continuous=ok_max)

    # sleep: every protected interval must remain fully free of study (checked above); report extension
    checks["protected_sleep_respected"] = all(
        not any(s.start < ps.end and ps.start < s.end for s in study) for ps in cal.protected_sleep_intervals)
    return ValidationReport(passed=all(checks.values()), checks=checks, messages=msgs)


def validate_proposal(cal: CalendarBundle, p: ScheduleProposal) -> ValidationReport:
    return check_blocks(cal, p.blocks, {u.task_id: u.minutes for u in p.unscheduled_work})
