# Contracts changelog
## 1.0 (Sat 2026-10-03, M0)
Implemented from HANDOFF section 9. Deviations / additions the team should confirm:
1. **No idempotency keys** (hackathon-lean). Safety comes from version checks: `409 STALE_VERSION` on replan and apply.
2. **SSE has no replay cursor.** Client refetches `/api/state` + `/api/schedule` on reconnect. `sequence` and `event_id` kept for dedupe.
3. `Trigger.suppressed_reason_codes` (list[str], optional) added so the UI/agent can say *why* no trigger fired (e.g. `INSUFFICIENT_DATA`, `COOLDOWN`). PROPOSED.
4. `ReplanRequest` carries `calendar_version` and `tasks_version` as well as `schedule_version` (handoff only named schedule version).
5. Added `GET /api/calendar` (CalendarBundle) and `GET /api/decisions/{id}`. Added mock-only `POST /api/mock/advance` (not part of the real API).
6. `ReplanJob.status` in {queued, running, ready, failed, applied}. `ready` with `proposal: null` means "no change recommended".
7. Load uses HR + EDA only for MVP; `WearableState` has no RMSSD field yet (add as optional in 1.1 if IBI lands).
8. `ScheduleBlock.kind` in {study, fixed, sleep_protected, sleep_extension, break}. A sleep extension is a normal block, not a change to protected intervals.
9. Fixture pressure is a stand-in: `round(1 - hours_until_exam/72, 2)`. The real academic-pressure heuristic lives in the backend.
Rule: any change to `models.py` -> rerun `python contracts/generate_schemas.py` (a test fails if schemas are stale) and add a line here.
## 1.0 backend notes (Sat 2026-10-03, M1-M4 integrator). No models.py change; schemas unchanged.
10. **Pressure formula disagrees with fixtures.** Backend computes `pressure-v1` from HANDOFF 7.6 on the replay clock (overdue tasks are flagged, not summed). On the fixture calendar it gives ~0.12 (trigger/normal) and ~0.55 (infeasible), against fixture stand-in 0.87 and the 0.70 rule. Decision: keep the formula, leave fixture files unchanged for now; the trigger fixture therefore shows SUSTAINED_LOAD + LIMITED_ESTIMATED_REST but does not fire. TEAM TO DECIDE: heavier calendar, threshold, or formula.
11. `Trigger.suppressed_reason_codes` now used: INSUFFICIENT_BASELINE, INSUFFICIENT_DATA, ACTIVITY_CONFOUND, RECOVERY_UNKNOWN, INSUFFICIENT_OVERNIGHT_EVIDENCE, NO_FLEXIBLE_BLOCK, PENDING_DECISION, COOLDOWN, AWAITING_RESET, STALE_STATE.
12. `state_id` is composed: `<wearable row id>.c<calendar>t<tasks>s<schedule>` so a version change yields a new state. Same state + versions -> same replan job (idempotency without keys).
13. `decision_id == job_id`. `GET /api/decisions/{id}` returns the saved record (state_id, tool_results, rule_version, model_id, explanation_kind, before/after_version, evidence_ids, explanation, proposal).
14. New errors: `503 STATE_NOT_READY` on `/api/state`, `409 ALREADY_APPLIED` on a second apply. `/api/health` adds `data_source`, `run_id`. `/api/chat` adds `decision_id`, `kind` (saved | llm | fallback).
15. Scheduler golden: trigger reproduces the fixture's minutes and Tuesday story exactly (Algorithms 14:00-15:30Z instead of two blocks; same change set). Infeasible places 255 thesis minutes vs fixture 240 (better); fixture file not regenerated to avoid churning frontend data.
16. **Threshold change (team decision, resolves #10 for now):** active trigger rules are `demo-rules-2` = `demo-rules-1` with `pressure_threshold` 0.10 (was 0.70). The trigger fixture fires again (pressure 0.12). Side effect: HIGH_PRESSURE is true in all four fixtures, so load and rest decide. `demo-rules-1` kept in `backend/app/trigger.py`; switch via `ACTIVE_RULES`. Revisit with the real calendar.
17. `ReplayStatus.data_end_time` added (optional, defaults null): `live_databricks` mode's end-of-Gold-data timestamp for the run, so the UI can show "End of replay data" and stop a growing lag instead of the replay clock running past the last row forever. Additive, backward compatible; done directly rather than routed through the Integrator given the session's broader fix authorization -- flagging here for review.
