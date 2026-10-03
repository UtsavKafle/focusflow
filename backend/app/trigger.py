"""Deterministic trigger rules (integrator task 4, HANDOFF 7.7). Thresholds live in versioned config, not LLM prose.
Fires only when SUSTAINED_LOAD + LIMITED_ESTIMATED_REST + HIGH_PRESSURE all hold and no gate suppresses it.
Unknown recovery never fires. Manual replanning still works regardless of the trigger."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from contracts.models import AcademicState, Schedule, Trigger, WearableState

DEMO_RULES_1 = {
    "rule_version": "demo-rules-1",
    "load_threshold": 0.70,
    "sustained_window_minutes": 20,      # must be 20 consecutive observed minutes; a gap resets
    "sustained_min_count": 15,           # >= 15 of those 20 at/above threshold
    "recovery_threshold": 0.50,
    "min_overnight_coverage": 0.60,      # "adequate overnight evidence" (assumption; tune on real data)
    "pressure_threshold": 0.70,
    "cooldown_replay_minutes": 60,
    "reset_load_threshold": 0.55,
}


@dataclass
class MinuteLoad:
    window_end: datetime
    load: Optional[float]  # None = not observed / invalid minute


@dataclass
class TriggerContext:
    pending_decision: bool = False
    last_applied_at: Optional[datetime] = None   # replay time of the last applied revision
    armed: bool = True                           # hysteresis: re-armed when load drops below reset threshold
    activity_confound: bool = False              # from Gold `activity_confound`


def sustained_load(history: list[MinuteLoad], as_of: datetime, cfg: dict = DEMO_RULES_1) -> bool:
    """Walk back from as_of over consecutive observed minutes; a missing/invalid minute ends the streak."""
    by_end = {h.window_end: h.load for h in history}
    streak, t = [], as_of
    while len(streak) < cfg["sustained_window_minutes"]:
        v = by_end.get(t)
        if v is None:
            return False
        streak.append(v)
        t -= timedelta(minutes=1)
    return sum(v >= cfg["load_threshold"] for v in streak) >= cfg["sustained_min_count"]


def evaluate(as_of: datetime, wearable: WearableState, history: list[MinuteLoad], academic: AcademicState,
             schedule: Schedule, ctx: TriggerContext, cfg: dict = DEMO_RULES_1) -> Trigger:
    codes, supp = [], []
    q = wearable.quality

    if sustained_load(history, as_of, cfg):
        codes.append("SUSTAINED_LOAD")
    if wearable.recovery_score is None:
        supp.append("RECOVERY_UNKNOWN")
    elif q.overnight_coverage is None or q.overnight_coverage < cfg["min_overnight_coverage"]:
        supp.append("INSUFFICIENT_OVERNIGHT_EVIDENCE")
    elif wearable.recovery_score < cfg["recovery_threshold"]:
        codes.append("LIMITED_ESTIMATED_REST")
    if academic.deadline_pressure is not None and academic.deadline_pressure >= cfg["pressure_threshold"]:
        codes.append("HIGH_PRESSURE")

    if not wearable.baseline_id or wearable.baseline_cutoff is None or wearable.baseline_cutoff > as_of:
        supp.append("INSUFFICIENT_BASELINE")
    if q.status != "sufficient":
        supp.append("INSUFFICIENT_DATA")
    if ctx.activity_confound:
        supp.append("ACTIVITY_CONFOUND")
    if not any(b.kind == "study" and not b.locked and b.start >= as_of for b in schedule.blocks):
        supp.append("NO_FLEXIBLE_BLOCK")
    if ctx.pending_decision:
        supp.append("PENDING_DECISION")
    if ctx.last_applied_at and as_of - ctx.last_applied_at < timedelta(minutes=cfg["cooldown_replay_minutes"]):
        supp.append("COOLDOWN")
    if not ctx.armed:
        supp.append("AWAITING_RESET")

    fire = len(codes) == 3 and not supp
    return Trigger(replan_recommended=fire, reason_codes=codes, rule_version=cfg["rule_version"],
                   suppressed_reason_codes=supp)


class TriggerEngine:
    """Holds hysteresis state per run. `consume()` when a replan is started from a recommendation."""

    def __init__(self, cfg: dict = DEMO_RULES_1):
        self.cfg, self.armed = cfg, True

    def observe(self, load: Optional[float]) -> None:
        if load is not None and load < self.cfg["reset_load_threshold"]:
            self.armed = True

    def consume(self) -> None:
        self.armed = False

    def evaluate(self, as_of, wearable, history, academic, schedule, ctx: TriggerContext) -> Trigger:
        self.observe(wearable.physiological_load)
        ctx.armed = self.armed
        return evaluate(as_of, wearable, history, academic, schedule, ctx, self.cfg)
