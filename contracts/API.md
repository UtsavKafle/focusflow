# HTTP + SSE API v1.0 (all JSON; times RFC 3339 UTC; models in `contracts/models.py`)
Mock implementation: `backend/app/main.py`. Errors: `{code, message, retryable}`; `409` stale version, `422` invalid payload, `404` unknown id.

| Method + path | Request | Response |
|---|---|---|
| GET `/api/health` | | `{ok, mode, scenario, label}` |
| GET `/api/state?run_id=` | | `StudentState` |
| GET `/api/history?run_id=&start=&end=` | | `{schema_version, source_kind, windows:[{window_start, window_end, heart_rate_bpm, physiological_load, activity_level, quality, evidence_id}]}` |
| GET `/api/calendar` | | `CalendarBundle` |
| GET `/api/schedule` | | `Schedule` |
| POST `/api/replan` | `ReplanRequest` | `202 {job_id}`; `409` if any version is stale |
| GET `/api/replans/{job_id}` | | `ReplanJob` (poll; or follow SSE) |
| POST `/api/replans/{job_id}/apply` | `ApplyRequest` | new `Schedule`; `409` if schedule version changed |
| GET `/api/decisions/{id}` | | saved proposal + explanation |
| POST `/api/chat` | `ChatRequest` | `{answer, evidence_ids}` |
| POST `/api/tasks/{task_id}/progress` | `TaskProgressRequest` | updated `CalendarBundle` |
| POST `/api/replay/start` | `ReplayStartRequest` | `{run_id}` |
| POST `/api/replay/pause` / `/reset` | | `ReplayStatus` |
| GET `/api/replay/status` | | `ReplayStatus` |
| GET `/api/events` | | SSE; envelope `SSEEvent`; types: state.updated, replay.updated, agent.started, agent.tool_result, schedule.proposed, schedule.applied, agent.explanation, pipeline.error |
| POST `/api/mock/advance?n=` | | MOCK ONLY: step fixture cursor |

Every payload with sensor-derived data includes `source_kind`; the UI must display it (and the mode: live_databricks / saved_replay / synthetic_fixture).
Agent tools: `contracts/agent_tools.json`. Scheduler: `scheduler/optimize.py`; validator: `scheduler/validate.py`.
