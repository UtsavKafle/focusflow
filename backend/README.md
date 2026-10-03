# backend (Integrator)
`uvicorn backend.app.main:app --reload`. Fixture mode needs no credentials (`FOCUSFLOW_DATA_SOURCE=fixture`, `FOCUSFLOW_FIXTURE=normal|trigger|missing_data|infeasible`); `databricks` mode reads Gold (see `docs/demo-runbook.md`).
- `main.py` routes (contracts/API.md) -> `services.py` (compose StudentState, replan jobs, one-time apply with version checks + re-validation)
- `sources.py` FixtureSource (replay cursor, no future rows) | `databricks_reader.py` Gold poller (~5 s, contract check, stale labeling)
- `academic.py` pressure-v1 on the replay clock | `trigger.py` rules (`ACTIVE_RULES` = `demo-rules-2`) + hysteresis | `store.py` SQLite (reset keeps audit) | `events.py` SSE
- TODO (task 7): wire `simulator.replay.ReplayController` into `/api/replay/*` once Data A lands it.
