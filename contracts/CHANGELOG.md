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
