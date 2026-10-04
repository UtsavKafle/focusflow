# Demo runbook (fallback ladder)

`GET /api/health` always shows the active `mode` and `label`. The UI must display it. Never present a lower rung as a higher one.

| Rung | Mode (`/api/health`) | How to run | Label to show |
|---|---|---|---|
| 1 | `live_databricks` | `.env`: `FOCUSFLOW_DATA_SOURCE=databricks`, `DATABRICKS_HOST/TOKEN/SQL_WAREHOUSE_ID`, optional `FOCUSFLOW_RUN_ID` | "Recorded wearable replay via Databricks" |
| 2 | `saved_replay` | same as 1 plus `FOCUSFLOW_REPLAY_MODE=saved` (Gold rows from saved derived results) | "Feature replay (saved derived results)" |
| 3 | `synthetic_fixture` | no `.env` needed: `FOCUSFLOW_DATA_SOURCE=fixture FOCUSFLOW_FIXTURE=trigger` | "SYNTHETIC FIXTURE - not real wearable data" |

Start: `uvicorn backend.app.main:app --port 8000`. Fresh clone (no credentials): `pip install -r requirements.txt && pytest -q && uvicorn backend.app.main:app`.

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
