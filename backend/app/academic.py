"""Academic state (integrator task 3, HANDOFF 7.6). Uses the REPLAY clock (`as_of`), never wall-clock time.
Display heuristic, not a probability of missing a deadline:
    u_i = (priority_i / 10) * remaining_minutes_i / max(minutes_until_deadline_i, 30)
    deadline_pressure = clamp(sum(u_i), 0, 1)   over unfinished, not-yet-overdue tasks
Overdue tasks get a separate flag (overdue_task_ids) instead of entering the sum."""
from __future__ import annotations

from datetime import datetime

from contracts.models import AcademicState, CalendarBundle

PRESSURE_VERSION = "pressure-v1"


def compute_academic(cal: CalendarBundle, schedule_version: int, as_of: datetime) -> AcademicState:
    open_tasks = [t for t in cal.tasks if t.status != "done" and t.remaining_minutes > 0]
    overdue = sorted(t.task_id for t in open_tasks if t.deadline <= as_of)
    total = 0.0
    for t in open_tasks:
        if t.deadline <= as_of:
            continue
        minutes_left = (t.deadline - as_of).total_seconds() / 60
        total += (t.priority / 10) * t.remaining_minutes / max(minutes_left, 30)
    exams = sorted(e.start for e in cal.fixed_events if e.kind == "exam" and e.start > as_of)
    return AcademicState(
        calendar_version=cal.calendar_version, tasks_version=cal.tasks_version, schedule_version=schedule_version,
        deadline_pressure=round(min(1.0, max(0.0, total)), 4),
        hours_until_next_exam=round((exams[0] - as_of).total_seconds() / 3600, 2) if exams else None,
        remaining_work_minutes=sum(t.remaining_minutes for t in open_tasks),
        overdue_task_ids=overdue)
