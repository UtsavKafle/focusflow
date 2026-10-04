-- Bounded "as of" Gold read for feature replay (saved-results fallback). Separate from gold_latest.sql
-- on purpose: databricks_reader.py's _latest_sql() reads gold_latest.sql from disk and executes it
-- verbatim with whatever is in `params` (today only :run_id) -- an unconditional :clock clause there
-- would break every poll call, since :clock is never bound. This file adds :clock as its own query;
-- the Integrator must pass {"run_id": ..., "clock": ...} in params when wiring up a bounded read that
-- uses this file instead of gold_latest.sql. ${table} is substituted the same way gold_latest.sql's is.
-- Columns/ordering match gold_latest.sql exactly.
SELECT run_id, participant_id, as_of, window_start, window_end, heart_rate_bpm, physiological_load,
       activity_level, estimated_rest_minutes, target_rest_minutes, recovery_score, baseline_id,
       baseline_cutoff, evidence_ids, quality_json, activity_confound, source_kind
FROM ${table}
WHERE run_id = :run_id
  AND as_of <= :clock
ORDER BY window_end DESC
LIMIT 1;
