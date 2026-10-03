# databricks (Data A + Data B)
`ingestion/` landing + event-file writer, `streaming/` Bronze/Silver streams, `features/` baselines + Gold WearableState, `sql/` DDL and read queries the backend uses.
Output contract: Gold table rows serialize to `WearableState` in `contracts/models.py` (+ `source_kind`, `as_of`, `run_id`, `participant_id`).
Budget: smallest SQL warehouse, short auto-stop, bounded replay jobs. See `docs/HANDOFF.md` sections 6-8.
