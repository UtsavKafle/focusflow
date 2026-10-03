# backend (Integrator)
`uvicorn backend.app.main:app --reload`. Today: fixture mock (`FOCUSFLOW_FIXTURE=normal|trigger|missing_data|infeasible`). Next: Databricks SQL reader behind the same routes, SQLite for tasks/schedule/decisions, real SSE publisher, replan job runner calling `agent/`.
