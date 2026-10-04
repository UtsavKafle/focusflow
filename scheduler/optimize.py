"""Deterministic greedy scheduler (HANDOFF 9.5 / 10, integrator task 1). Owner: Integrator.
Pure function: never writes the calendar, never calls an LLM. Same inputs -> same proposal.

free = allowed study intervals - fixed events - protected sleep - locked blocks, never before `now`.
Tasks ranked by (deadline, -priority, task_id) and placed earliest-first; split only when `splittable`;
respects minimum_block_minutes, maximum_continuous_study_minutes and break_minutes.
Rest protection (reason codes SUSTAINED_LOAD / LIMITED_ESTIMATED_REST): add a `sleep_extension` block ending at the
next protected sleep start, extending toward target_sleep_minutes; no study is placed tonight before it, and
displaced study is re-placed. Leftover -> unscheduled_work (status partial). Always validated.
The greedy approach may miss a feasible arrangement: we say "no feasible plan found by this scheduler".
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from contracts.models import (CalendarBundle, Interval, Schedule, ScheduleBlock, ScheduleChange, ScheduleProposal,
                              StudentState, UnscheduledWork)
from scheduler.validate import validate_proposal

POLICY_VERSION = "sched-policy-1"
SLOT = 15  # placement granularity in minutes
REST_REASONS = {"SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST"}


def policy_for_reasons(reason_codes: Iterable[str]) -> dict:
    """Backend maps permitted reason codes to a versioned policy; the agent never supplies constraints."""
    codes = sorted(set(reason_codes))
    return {"policy_version": POLICY_VERSION, "reason_codes": codes, "protect_rest": bool(REST_REASONS & set(codes))}


def _ceil(t: datetime) -> datetime:
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    m = (t - epoch).total_seconds() / 60
    return epoch + timedelta(minutes=-(-m // SLOT) * SLOT)


def _mins(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def _ov(s, e, s2, e2) -> bool:
    return s < e2 and s2 < e


def _subtract(segs, busy):
    for bs, be in busy:
        nxt = []
        for s, e in segs:
            if not _ov(s, e, bs, be):
                nxt.append((s, e)); continue
            if s < bs: nxt.append((s, bs))
            if be < e: nxt.append((be, e))
        segs = nxt
    return sorted(segs)


def _run_minutes(study: list[ScheduleBlock], s: datetime, e: datetime, brk: int) -> int:
    """Minutes of continuous study if [s, e) is added: neighbours closer than `brk` minutes count as continuous."""
    gap = timedelta(minutes=brk)
    total, lo, hi = _mins(s, e), s, e
    for b in sorted(study, key=lambda b: b.end, reverse=True):
        if b.end <= lo and lo - b.end < gap:
            total += b.minutes; lo = b.start
    for b in sorted(study, key=lambda b: b.start):
        if b.start >= hi and b.start - hi < gap:
            total += b.minutes; hi = b.end
    return total


def _sleep_extension(now, cal: CalendarBundle, blocks: list[ScheduleBlock], ver: int) -> Optional[ScheduleBlock]:
    if any(p.start <= now < p.end for p in cal.protected_sleep_intervals):
        return None  # already in protected sleep
    nxt = sorted((p for p in cal.protected_sleep_intervals if p.start > now), key=lambda p: p.start)
    if not nxt:
        return None
    sleep = nxt[0]
    if any(b.kind == "sleep_extension" and b.end == sleep.start for b in blocks):
        return None  # tonight's sleep was already extended by an earlier revision
    want = max(0, cal.preferences.target_sleep_minutes - sleep.minutes)  # toward target, never below minimum
    start = max(_ceil(now), sleep.start - timedelta(minutes=want))
    for b in blocks:  # never overlap fixed or locked time
        if b.kind != "sleep_protected" and _ov(start, sleep.start, b.start, b.end):
            start = max(start, b.end)
    if _mins(start, sleep.start) < SLOT:
        return None
    return ScheduleBlock(block_id=f"blk-sleep-ext-v{ver}", kind="sleep_extension", start=start, end=sleep.start, locked=True)


def _diff(old: list[ScheduleBlock], new: list[ScheduleBlock], rest_task_ids: set[str]) -> list[ScheduleChange]:
    def group(bl):
        g: dict[str, list[ScheduleBlock]] = {}
        for b in bl:
            if b.kind == "study": g.setdefault(b.task_id, []).append(b)
            elif b.kind == "sleep_extension": g.setdefault("_sleep", []).append(b)
        return g
    o, n, out = group(old), group(new), []
    for key in sorted(set(o) | set(n)):
        ob = sorted(o.get(key, []), key=lambda b: b.start)
        nb = sorted(n.get(key, []), key=lambda b: b.start)
        if [(b.start, b.end) for b in ob] == [(b.start, b.end) for b in nb]:
            continue
        action = "added" if not ob else ("removed" if not nb else "moved")
        reason = ("PROTECT_REST" if key == "_sleep" or key in rest_task_ids else
                  "MEET_DEADLINE" if action == "added" else "MAKE_ROOM")
        out.append(ScheduleChange(change_id=f"chg-{len(out) + 1}", action=action, old_block_ids=[b.block_id for b in ob],
                                  new_block_ids=[b.block_id for b in nb], reason_code=reason))
    return out


def optimize_schedule(now: datetime, planning_horizon: Optional[Interval], calendar: CalendarBundle,
                      current_schedule: Schedule, student_state: Optional[StudentState],
                      policy: Optional[dict] = None) -> ScheduleProposal:
    cal, pol = calendar, policy or policy_for_reasons([])
    pref, ver = cal.preferences, current_schedule.schedule_version + 1
    tasks = {t.task_id: t for t in cal.tasks}
    future = [b for b in current_schedule.blocks if b.end > now]  # past blocks are history, not part of the diff

    # keep: every non-study block plus locked or in-progress study. Unlocked future study is re-placed.
    keep = [b for b in current_schedule.blocks if b.kind != "study"] + \
           [b for b in future if b.kind == "study" and (b.locked or b.start < now)]
    keep_ids = {b.block_id for b in keep}
    old_ids = {(b.task_id, b.start, b.end): b.block_id for b in future if b.kind == "study"}

    ext = _sleep_extension(now, cal, keep, ver) if pol.get("protect_rest") else None
    no_study_before = now
    rest_task_ids: set[str] = set()
    if ext:
        keep.append(ext)
        no_study_before = ext.end  # rest protection: no more study tonight
        rest_task_ids = {b.task_id for b in future if b.kind == "study" and b.block_id not in keep_ids
                         and _ov(b.start, b.end, now, ext.end)}

    h_end = planning_horizon.end if planning_horizon else max(a.end for a in cal.allowed_study_intervals)
    h_start = max(now, planning_horizon.start) if planning_horizon else now
    allowed = [(a.start, min(a.end, h_end)) for a in cal.allowed_study_intervals if a.start < h_end]
    hard_busy = [(f.start, f.end) for f in cal.fixed_events] + [(p.start, p.end) for p in cal.protected_sleep_intervals]
    hard_busy.append((min(a.start for a in cal.allowed_study_intervals), max(_ceil(h_start), no_study_before)))

    blocks = list(keep)
    unsched: list[UnscheduledWork] = []
    ranked = sorted((t for t in cal.tasks if t.status != "done" and t.remaining_minutes > 0),
                    key=lambda t: (t.deadline, -t.priority, t.task_id))
    movable = [b for b in future if b.kind == "study" and b.block_id not in keep_ids]
    for t in ranked:
        need = t.remaining_minutes - sum(b.minutes for b in blocks if b.kind == "study" and b.task_id == t.task_id)
        # stability: keep this task's existing blocks while still valid; only displaced study is re-placed
        kept = []
        for b in sorted((b for b in movable if b.task_id == t.task_id), key=lambda b: b.start):
            busy = hard_busy + [(x.start, x.end) for x in blocks + kept]
            if b.minutes <= need and b.end <= t.deadline and not any(_ov(b.start, b.end, s, e) for s, e in busy) \
                    and any(a.start <= b.start and b.end <= a.end for a in cal.allowed_study_intervals) \
                    and _run_minutes([x for x in blocks + kept if x.kind == "study"], b.start, b.end,
                                     pref.break_minutes) <= pref.maximum_continuous_study_minutes:
                kept.append(b); need -= b.minutes
        while kept and 0 < need < t.minimum_block_minutes:
            need += kept.pop().minutes  # never strand a too-short remainder
        blocks += kept
        if need > 0 and t.deadline > now and (t.splittable or need <= pref.maximum_continuous_study_minutes):
            while need > 0:
                spot = None
                segs = _subtract([(s, min(e, t.deadline)) for s, e in allowed if s < t.deadline],
                                 sorted(hard_busy + [(b.start, b.end) for b in blocks]))
                study = [b for b in blocks if b.kind == "study"]
                for fs, fe in segs:
                    s = _ceil(fs)
                    while spot is None and s < fe:
                        top = min(need, _mins(s, fe), pref.maximum_continuous_study_minutes)
                        lengths = ([need] if need <= top else []) if not t.splittable else \
                            sorted({top, *range(SLOT, top + 1, SLOT)}, reverse=True)
                        for L in lengths:
                            if L < min(t.minimum_block_minutes, need) or 0 < need - L < t.minimum_block_minutes:
                                continue  # too short, or would strand a too-short remainder
                            if _run_minutes(study, s, s + timedelta(minutes=L), pref.break_minutes) <= pref.maximum_continuous_study_minutes:
                                spot = (s, s + timedelta(minutes=L)); break
                        s += timedelta(minutes=SLOT)
                    if spot: break
                if not spot: break
                bid = old_ids.get((t.task_id, *spot)) or f"blk-{t.task_id}-v{ver}-{sum(b.task_id == t.task_id for b in blocks) + 1}"
                blocks.append(ScheduleBlock(block_id=bid, task_id=t.task_id, kind="study", start=spot[0], end=spot[1]))
                need -= _mins(*spot)
        if need > 0:
            reason = ("DEADLINE_PASSED" if t.deadline <= now else
                      "UNSPLITTABLE_EXCEEDS_MAX_CONTINUOUS" if not t.splittable and need > pref.maximum_continuous_study_minutes
                      else "INSUFFICIENT_CAPACITY_BEFORE_DEADLINE")
            unsched.append(UnscheduledWork(task_id=t.task_id, minutes=need, deadline=t.deadline, reason=reason))

    blocks.sort(key=lambda b: (b.start, b.end, b.block_id))
    placed_any = any(b.kind == "study" and not b.locked for b in blocks)
    status = "feasible" if not unsched else ("partial" if placed_any else "infeasible")
    sid = student_state.state_id if student_state else "manual"
    key = f"{sid}|{current_schedule.schedule_version}|{cal.calendar_version}|{cal.tasks_version}|{pol.get('reason_codes')}"
    proposal = ScheduleProposal(
        proposal_id=f"proposal-{hashlib.sha1(key.encode()).hexdigest()[:10]}", based_on_state_id=sid,
        calendar_version=cal.calendar_version, tasks_version=cal.tasks_version,
        schedule_version=current_schedule.schedule_version, status=status, blocks=blocks,
        changes=_diff(future, blocks, rest_task_ids), unscheduled_work=unsched,
        validation={"passed": False, "checks": {}})
    proposal.validation = validate_proposal(cal, proposal)
    if unsched:
        proposal.validation.messages.append("no feasible plan found by this scheduler for: " + ", ".join(u.task_id for u in unsched))
    return proposal
