# 03 Handoff: Integrator (contracts, backend, scheduler, agent)

You are the coding agent for the Integrator. Read `00-common.md` first. You own `contracts/`, `backend/`, `scheduler/`, `agent/`, backend/scheduler/agent tests, and `docs/` except provenance. Everyone else depends on you not breaking the contract. You are the critical path.

**Mission:** a backend that composes `StudentState` from Gold plus academic state, a deterministic scheduler that returns validated proposals, and a tool-calling agent that investigates and explains. Fixtures first, Databricks second.

## Already done (M0)
Pydantic contracts, generated schemas, `API.md`, `agent_tools.json`, four fixtures, mock FastAPI (`backend/app/main.py`), `scheduler/validate.py`, tests (17 pass). Read `contracts/CHANGELOG.md` for decisions to confirm with the team.

## Mock data
Beyond the four scenario fixtures, `fixtures/mock_big_ideas/gold.csv` holds 3.5 days of realistic Gold rows (see `docs/mock-data.md`). Use it to build the Gold-to-`StudentState` path (`databricks.features.state.row_to_wearable_state`) and to run the trigger engine over the whole timeline: it must fire near the end (02-16 23:20 source time), not during the 02-14 exercise (activity confound) and not during warm-up, and must show unavailable windows during the planted gaps. Read with `dtype={"participant_id": str}`.

## Tasks in order
**M1 (to Sat 19:00): scheduler + real backend skeleton on fixtures**
1. `scheduler/optimize.py` per `docs/HANDOFF.md` section 10. Deterministic greedy: free intervals = allowed minus fixed minus protected sleep minus locked blocks; rank tasks by (deadline, -priority, task_id); place earliest-first; split only when `splittable`, respect `minimum_block_minutes`, `maximum_continuous_study_minutes` and breaks; never allocate before `now`. When reasons include rest protection (`SUSTAINED_LOAD`/`LIMITED_ESTIMATED_REST`), add a `sleep_extension` block ending at the next protected sleep start (extend toward `target_sleep_minutes`, never below minimum) and re-place displaced study. Leftover work -> `unscheduled_work`, status `partial`. Compute `changes` by diffing blocks. Always run `validate_proposal` on the result. Output must be deterministic.
   - **Golden tests:** `tests/test_scheduler_golden.py` regenerates proposals from `fixtures/scenarios/trigger` and `infeasible` calendars and asserts the same set of study minutes per task, status, validation pass, and sleep extension (exact block times may differ if your algorithm places differently, but the Tuesday story must hold: Algorithms leaves the 03:30Z to 05:00Z slot, rest is extended, deadline met). If your placement beats the fixture, regenerate the fixture and note it in CHANGELOG.
2. Persistence: SQLite (`backend/app/store.py`): tasks, calendar, schedules (versioned), proposals, decisions (state_id, tool results, rule_version, model id, before/after versions, evidence_ids, explanation). Reset keeps audit history.
3. Academic state: `deadline_pressure = clamp(sum((priority/10) * remaining_minutes / max(minutes_until_deadline, 30)), 0, 1)` over unfinished tasks, `hours_until_next_exam`, `remaining_work_minutes`, overdue flags, using the **replay clock**, never wall clock. Update fixtures to use the real formula if it disagrees, and note it.
4. Trigger engine `backend/app/trigger.py` (versioned config `demo-rules-1`): valid baseline and sufficient coverage; load >= 0.70 in at least 15 of the last 20 valid minutes (20 consecutive observed minutes, a gap resets); `recovery_score` < 0.50 with adequate overnight evidence (unknown recovery means no fire); pressure >= 0.70 and a future flexible block exists; no pending decision; >= 60 replay minutes since last applied revision; reset below load 0.55; suppress if `activity_confound`. Fill `reason_codes` and `suppressed_reason_codes`. Unit tests for each branch.
5. Swap the mock store for real state composition behind the same routes with `FOCUSFLOW_DATA_SOURCE=fixture` still working. Real SSE publisher (in-process queue). Replan jobs run in a background task; `POST /api/replan` returns 202 and a job id; apply checks versions and re-validates before commit.

**M2 (to Sun 00:00): Databricks reader**
6. `backend/app/databricks_reader.py` using `databricks-sql-connector` with `.env` creds: poll `gold_latest.sql` every ~5 s, parse into `WearableState` (JSON-decode `quality_json`), mark `source_kind`, handle "not ready" explicitly, never serve a stale row as fresh (compare `as_of` to replay clock and show lag). Keep warehouse usage cheap: one query per poll, bounded history ranges. Batch queries if the warehouse is cold.
7. Wire `simulator.replay.ReplayController` (Data A) into `/api/replay/*`. Until it lands, keep the mock.
8. Contract checks at the boundary: every Gold row goes through `WearableState.model_validate`; on failure emit `pipeline.error` SSE and keep last good state labeled stale.

**M3 (to Sun 05:00): agent**
9. `agent/agent.py`: provider adapter (`LLMProvider.chat(messages, tools) -> msg`) with implementations for the Databricks model endpoint (if confirmed; env `DATABRICKS_MODEL_ENDPOINT`) and a fallback API key provider. Tool implementations in `agent/tools.py` call backend services directly (local Python wrappers; no MCP needed). Tool-call cap (about 8) and a time cap. The agent may only pass permitted reason codes to `request_schedule_replan`. It never edits the schedule; the API applies it.
10. Explanation structure: Observation (features, window, baseline), Uncertainty (missing data, activity confound), Planning reason (deadline order, remaining work, movable blocks), Action/status (proposed/applied changes, unscheduled work). Every number must come from a tool result. Add an automated check that numbers and times in the explanation appear in tool outputs or the diff.
11. **Deterministic fallback explainer** (no LLM): built from the real evidence and diff, labeled "fallback explanation". Used when the model is unavailable, times out, or returns malformed output. Failed tool output must leave the schedule intact.
12. `GET /api/decisions/{id}` returns the saved decision so "Why did you move this?" retrieves history, not a fresh guess. `/api/chat` answers from saved decisions and tools.
13. Optional auto-apply setting for demo (valid in-app proposals only). Manual Apply remains default.

**M4 (to Sun 08:00): hardening**
14. Idempotency without keys: a second replan for the same `state_id` returns the existing job; apply is a one-time commit (409 on stale). Test reconnect/duplicate delivery.
15. Fallback ladder in the runbook (`docs/demo-runbook.md`): live Databricks -> saved-results replay -> fixture demo, each clearly labeled; a `/api/health` that shows which mode.
16. Fresh-clone test: a teammate can run fixture mode with no credentials.

## Definition of done
- Every applied plan passes overlap, deadline, duration, protected-time checks.
- The trigger-to-explanation path works on fixture AND on real Gold.
- Missing channels and warm-up show explicit unknowns.
- Explanation numbers match tool results and the diff (checked in tests).
- `pytest -q` green on every merge.

## Contract-change protocol
You are the gatekeeper. Edit `contracts/models.py` only when needed, regenerate schemas, add a CHANGELOG line, announce to the team, and keep fixtures validating. Tell the frontend agent when TS types need regenerating.

## Gotchas
- You will be pulled in 4 directions. Protect M1 (scheduler + trigger + store) first; it unblocks the agent and the UI.
- Keep the LLM out of constraints and arithmetic. It explains; Python decides.
- Do not claim a schedule change succeeded before commit.
