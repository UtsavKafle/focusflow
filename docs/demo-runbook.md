# Demo runbook (fallback ladder)

`GET /api/health` always shows the active `mode` and `label`. The UI must display it. Never present a lower rung as a higher one.

| Rung | Mode (`/api/health`) | How to run | Label to show |
|---|---|---|---|
| 1 | `live_databricks` | `.env`: `FOCUSFLOW_DATA_SOURCE=databricks`, `DATABRICKS_HOST/TOKEN/SQL_WAREHOUSE_ID`, optional `FOCUSFLOW_RUN_ID` | "Recorded wearable replay via Databricks" |
| 2 | `saved_replay` | `FOCUSFLOW_DATA_SOURCE=databricks FOCUSFLOW_REPLAY_MODE=saved FOCUSFLOW_RUN_ID=<run_id>`; no Databricks credentials. Reads `data/derived/<run_id>/feature_replay/gold.csv` (Data B: `python -m databricks.features.export_gold_fixture --run-id <run_id>`) with the same `as_of <= clock` replay as rung 1. Timestamps must be in scenario (2026) time or the calendar trigger never fires | "Feature replay (saved derived results)"; synthetic files: "SYNTHETIC feature replay (saved derived results) - not real wearable data" |
| 3 | `synthetic_fixture` | no `.env` needed: `FOCUSFLOW_DATA_SOURCE=fixture FOCUSFLOW_FIXTURE=trigger` | "SYNTHETIC FIXTURE - not real wearable data" |

Start: `uvicorn backend.app.main:app --port 8000`. Fresh clone (no credentials): `pip install -r requirements.txt && pytest -q && uvicorn backend.app.main:app`.

## Replay clock for rung 1 (live_databricks)
Without a replay controller (`FOCUSFLOW_REPLAY_RAW_DIR` unset, the normal case for the demo), `DatabricksSource`
runs its own local clock from a bookmark. If no bookmark is ever configured, `clock()` stays `None` and
every poll reads the newest Gold row -- for a finite replayed run that row never changes, so the UI cards
(heart rate, load, rest, `as_of`) look frozen even though `/api/state` keeps returning 200. The backend now
defaults to 24h after the run's earliest Gold row (past `baseline_warmup`) if nothing else is configured,
and the frontend's "Play from start" button sends the first prepared bookmark
(`frontend/src/demoBookmarks.ts`, "Evening start") instead of no bookmark at all -- so in normal use this
default rarely even triggers.

To pin an explicit default instead (lands on the "Evening start" bookmark, `2026-10-13T01:50:00Z`, for
`mock-demo-002`), set in `.env`:
```
FOCUSFLOW_REPLAY_SCENARIO_START=2026-10-12T21:50:00-04:00
FOCUSFLOW_REPLAY_HISTORY_HOURS=0
```
(`FOCUSFLOW_REPLAY_HISTORY_HOURS` defaults to 48 if unset; `SCENARIO_START` converted to UTC plus `HISTORY_HOURS`
is the resulting bookmark.) An explicit `bookmark` passed to `POST /api/replay/start`, or one of the
DemoPanel's prepared bookmark buttons, always overrides both of these.

## Before presenting
- Warm the SQL warehouse; check `/api/state` returns 200 (503 `STATE_NOT_READY` means no Gold row yet).
- If remaining Databricks credits < $8, drop to rung 2 or 3.
- Agent: no key -> deterministic explanation labeled "Fallback explanation". `DATABRICKS_MODEL_ENDPOINT` or `LLM_API_KEY` enables the model; any failure falls back automatically.
- Pause the replay (`POST /api/replay/pause`) during the explanation so the decision does not go stale.

## Switching mid-demo
- Gold contract violation or query failure: SSE `pipeline.error`, last good state kept and labeled stale (trigger suppressed with `STALE_STATE`). Switch rungs if it persists.
- Reset: `POST /api/replay/reset` starts a new run; earlier decisions remain retrievable at `/api/decisions/{id}`.

## Trigger rules
Active rules: `demo-rules-2` (pressure threshold 0.10; `demo-rules-1` used 0.70). The pressure-v1 formula gives ~0.12 on the demo calendar, so the trigger fixture fires. HIGH_PRESSURE is on in every fixture; load and rest decide. If asked: the threshold is a demo heuristic, not a calibrated cut-off. See `contracts/CHANGELOG.md` #16.
