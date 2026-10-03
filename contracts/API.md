# HTTP + SSE API v1.0 (all JSON; times RFC 3339 UTC; models in `contracts/models.py`)
Implementation: `backend/app/main.py` (fixture mode needs no credentials). Errors: `{code, message, retryable}`; `409` stale version, `422` invalid payload, `404` unknown id.

| Method + path | Request | Response |
|---|---|---|
| GET `/api/health` | | `{ok, mode, data_source, scenario, label, run_id}` |
| GET `/api/state?run_id=` | | `StudentState`; `503 STATE_NOT_READY` before the first wearable row |
| GET `/api/history?run_id=&start=&end=` | | `{schema_version, source_kind, windows:[{window_start, window_end, heart_rate_bpm, physiological_load, activity_level, quality, evidence_id}]}` |
| GET `/api/calendar` | | `CalendarBundle` |
| GET `/api/schedule` | | `Schedule` |
| POST `/api/replan` | `ReplanRequest` | `202 {job_id}`; `409` if any version is stale |
| GET `/api/replans/{job_id}` | | `ReplanJob` (poll; or follow SSE) |
| POST `/api/replans/{job_id}/apply` | `ApplyRequest` | new `Schedule`; `409 STALE_VERSION` if versions changed, `409 ALREADY_APPLIED` on repeat |
| GET `/api/decisions/{id}` | | saved decision (id == job_id): state_id, tool_results, rule_version, model_id, explanation_kind, before/after_version, evidence_ids, explanation, proposal |
| POST `/api/chat` | `ChatRequest` | `{answer, evidence_ids, decision_id, kind}` (answers from saved decisions) |
| POST `/api/tasks/{task_id}/progress` | `TaskProgressRequest` | updated `CalendarBundle` |
| POST `/api/replay/start` | `ReplayStartRequest` | `{run_id}` |
| POST `/api/replay/pause` / `/reset` | | `ReplayStatus` |
| GET `/api/replay/status` | | `ReplayStatus` |
| GET `/api/events` | | SSE; envelope `SSEEvent`; types: state.updated, replay.updated, agent.started, agent.tool_result, schedule.proposed, schedule.applied, agent.explanation, pipeline.error |
| POST `/api/mock/advance?n=` | | FIXTURE MODE ONLY: step the replay cursor |

Every payload with sensor-derived data includes `source_kind`; the UI must display it (and the mode: live_databricks / saved_replay / synthetic_fixture).
Agent tools: `contracts/agent_tools.json`. Scheduler: `scheduler/optimize.py`; validator: `scheduler/validate.py`.
