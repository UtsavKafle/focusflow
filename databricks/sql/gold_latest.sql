-- Latest Gold row for a run (backend polls this ~every 5 s). ${table} is substituted by the reader
-- (backend/app/databricks_reader.py's _latest_sql) with the actual catalog.schema.table name. Parameter:
-- :run_id. Columns match databricks_reader.py's COLS exactly (WS_FIELDS plus run_id/participant_id/as_of/
-- quality_json/activity_confound/source_kind) so the reader's row-to-dict mapping needs no changes here.
-- Replay clock: callers wanting a bounded "as of" read instead of the newest row may add
-- AND as_of <= :clock to this WHERE clause.
SELECT run_id, participant_id, as_of, window_start, window_end, heart_rate_bpm, physiological_load,
       activity_level, estimated_rest_minutes, target_rest_minutes, recovery_score, baseline_id,
       baseline_cutoff, evidence_ids, quality_json, activity_confound, source_kind
FROM ${table}
WHERE run_id = :run_id
ORDER BY window_end DESC
LIMIT 1;
