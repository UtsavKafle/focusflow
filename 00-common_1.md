# 00 Common rules (everyone, every agent)

**Product:** FocusFlow. One BIG IDEAs wearable recording is replayed through Databricks Structured Streaming. A synthetic exam-week calendar is overlaid. A tool-calling agent asks a deterministic scheduler for a validated schedule revision and explains the evidence. Track: Applied AI / Databricks.

**Clock:** Submission Sun Oct 4 at 11:00. Demo about 12:30. Feature freeze Sun 08:00. Rehearse and record 08:00 to 10:30. Do not start new features after freeze.

## Milestones (all times ET)
| ID | Deadline | Everyone's goal |
|---|---|---|
| M0 | Sat 14:30 | DONE: repo, contracts v1.0, four fixtures, mock API, validator, tests |
| M1 | Sat 19:00 | Fixture loop works end to end (UI shows mock state, scheduler reproduces fixture proposals, data team has adapters + local features on real files) |
| M2 | Sun 00:00 | One real replay segment goes source -> Bronze -> Silver -> Gold -> API -> UI. SPEND GATE: stop and review Databricks credits |
| M3 | Sun 05:00 | Agent uses real tools against real Gold state; apply flow works; history ("why did this change") works |
| M4 | Sun 08:00 | Hardening, fallbacks, labels. FEATURE FREEZE |

## Roles and owned directories
| Role | Owns | Does not touch |
|---|---|---|
| Data A (ingestion + replay) | `databricks/ingestion/`, `databricks/sql/ddl_*.sql`, `simulator/`, `docs/data-provenance.md` | contracts, backend, frontend |
| Data B (features + state) | `databricks/streaming/`, `databricks/features/`, `databricks/sql/gold_*.sql` | contracts, backend, frontend |
| Integrator | `contracts/`, `backend/`, `scheduler/`, `agent/`, `tests/` (backend/scheduler/agent), `docs/` except provenance | `databricks/`, `frontend/` |
| Frontend (part-time) | `frontend/` | everything else |

## Git
- Branch per person: `data-a/...`, `data-b/...`, `integrator/...`, `frontend/...`. Small PRs or direct pushes to your branch, merge to `main` at least every 2 hours so nobody drifts.
- `git pull --rebase origin main` before pushing. Never force-push `main`.
- CI is just `pytest -q`. Do not merge red.
- Commit messages: imperative, one line. No secrets, no raw participant files (`data/raw/` is gitignored).

## Contracts are frozen unless the Integrator agrees
`contracts/models.py` is the source of truth. Need a change? Message the Integrator with the exact field and why. They edit models, regenerate schemas (`python contracts/generate_schemas.py`), add a line to `contracts/CHANGELOG.md`, and push. Meanwhile code against the current contract.

## Data table contract between the data team and the backend
Catalog/schema: `focusflow.main` (from `.env`). Tables (append-only, Delta):
- `bronze_wearable_events`: one row per `NormalizedEvent` (fields exactly as in `contracts/models.py`, `values` as MAP<STRING,DOUBLE>, plus `source_file` and `source_row`). Dedupe key `(run_id, event_id)`.
- `silver_wearable_minute`: one row per `(run_id, participant_id, window_start)`. Half-open one-minute windows. Per-signal stats and coverage, `stillness_ratio`, `hr_baseline_z`, `eda_baseline_z`.
- `gold_wearable_state`: one row per `(run_id, participant_id, window_end)`. Columns: `run_id, participant_id, as_of, window_start, window_end, heart_rate_bpm, physiological_load, activity_level, estimated_rest_minutes, target_rest_minutes, recovery_score, quality_json (STRING JSON matching Quality), baseline_id, baseline_cutoff, evidence_ids ARRAY<STRING>, activity_confound BOOLEAN, source_kind`. Nulls are real NULLs and every null has an entry in `quality_json.missing_reasons`. The backend turns a Gold row into `WearableState`, then composes `StudentState` (adds academic state, versions, trigger).
- Data A owns DDL for Bronze. Data B owns DDL for Silver and Gold. DDL lives in `databricks/sql/`.

## Honest labeling (judges will check)
- Scores are engineering heuristics, not diagnoses or probabilities. No sleep staging. No stress diagnosis. "Estimated rest", not "sleep quality".
- Every screen and payload carries `source_kind`. Modes: live Databricks replay, saved derived-results replay (call it "feature replay"), synthetic fixture. Never show a fixture as a live run.
- Null means unknown. Never NaN, never fake zero, never a stale value marked fresh.
- One adult recording does not validate anything. Say so in the demo.

## Budget ($30 Databricks credits)
Smallest SQL warehouse, auto-stop 5 to 10 minutes. Bounded replay jobs (no leaving streams running overnight). Fixtures for anything that is not data work. One person (Data B) checks usage at M2 and every few hours. If remaining credits are under $8, switch the demo to saved-results replay.

## Always
- Fixture mode must work without Databricks credentials: `FOCUSFLOW_DATA_SOURCE=fixture`.
- Tests for anything on a boundary (schemas, SQL row -> contract, scheduler constraints).
- When blocked more than 20 minutes, tell your human and pick the next unblocked task. Do not stall.
- Finish by writing 5 lines in `docs/decisions.md` for anything you decided that others depend on.
