"""Deterministic scheduler interface (HANDOFF 9.5). STUB: owner = Integrator.
Pure function: never writes calendar, never calls an LLM. Deterministic tie-breaking by (deadline, -priority, task_id)."""
from __future__ import annotations

from contracts.models import CalendarBundle, Schedule, ScheduleProposal, StudentState


def optimize_schedule(now, planning_horizon, calendar: CalendarBundle, current_schedule: Schedule,
                      student_state: StudentState, policy: dict) -> ScheduleProposal:
    """TODO(M1): greedy earliest-deadline-first with rest protection, then call scheduler.validate.validate_proposal.
    Until then the mock API serves the precomputed fixtures/scenarios/*/proposal.json."""
    raise NotImplementedError("see scheduler/README.md for the algorithm outline")
