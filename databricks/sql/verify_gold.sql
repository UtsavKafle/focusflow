-- Data B. Databricks SQL checks mirroring Task C's local pandas verification (docs/decisions.md), run
-- against the real gold_wearable_state table instead of a local CSV. Parameters: :run_id, :participant_id.
-- Paste one query at a time into a Databricks SQL editor/notebook (it will prompt for the widgets), or run
-- from a notebook with spark.sql(sql_text, args={"run_id": ..., "participant_id": ...}) per statement.
-- Expected values below are for the mock dataset (participant 001) over the full demo segment
-- (America/New_York 2020-02-13 12:00 to 2020-02-17 00:00, scenario-mapped with --shift-days 2430 to
-- 2026-10-09 12:00 to 2026-10-13 00:00); a real participant/segment will differ.

-- 1. No duplicate MERGE keys (idempotency sanity check -- should always return zero rows, any dataset).
SELECT run_id, participant_id, window_end, COUNT(*) AS n
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id
GROUP BY run_id, participant_id, window_end
HAVING COUNT(*) > 1;

-- 2. Row count and window_end range. Expected (mock, full segment): 5040 rows,
-- 2026-10-09T16:01:00Z to 2026-10-13T04:00:00Z.
SELECT COUNT(*) AS n_rows, MIN(window_end) AS first_window_end, MAX(window_end) AS last_window_end
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id;

-- 3. Rest minutes by night. Expected (mock): 474, 474, 130 for the three completed nights.
SELECT night_id, MIN(estimated_rest_minutes) AS estimated_rest_minutes
FROM (
  SELECT estimated_rest_minutes, filter(evidence_ids, x -> x LIKE 'rest-%')[0] AS night_id
  FROM focusflow.main.gold_wearable_state
  WHERE run_id = :run_id AND participant_id = :participant_id AND estimated_rest_minutes IS NOT NULL
)
GROUP BY night_id
ORDER BY night_id;

-- 4. Warm-up nulls near run start. Expected: physiological_load IS NULL with missing_reasons.physiological_load
-- = 'baseline_warmup' for roughly the first 24h of windows.
SELECT window_end, physiological_load,
       get_json_object(quality_json, '$.missing_reasons.physiological_load') AS load_null_reason
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id
ORDER BY window_end
LIMIT 5;

-- 5. Trigger-moment row. Expected (mock, decision 4): as_of = 2026-10-13T03:20:00Z, estimated_rest_minutes
-- = 130, recovery_score < 0.5, activity_confound = false, physiological_load >= 0.70.
SELECT as_of, physiological_load, activity_level, estimated_rest_minutes, recovery_score, activity_confound
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id AND as_of = TIMESTAMP '2026-10-13T03:20:00Z';

-- 6. Last 20 minutes of load. Expected: at least 15 of 20 rows with physiological_load >= 0.70.
SELECT COUNT(*) AS n, SUM(CASE WHEN physiological_load >= 0.70 THEN 1 ELSE 0 END) AS n_high_load
FROM (
  SELECT physiological_load
  FROM focusflow.main.gold_wearable_state
  WHERE run_id = :run_id AND participant_id = :participant_id
  ORDER BY window_end DESC
  LIMIT 20
);

-- 7. Quality status counts. Expected (mock, full segment): sufficient=3525, limited=1450, unavailable=65.
SELECT get_json_object(quality_json, '$.status') AS status, COUNT(*) AS n
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id
GROUP BY status
ORDER BY status;

-- 8. source_kind sanity (honest labeling): must never be 'recorded_replay' for a run built from the mock.
SELECT DISTINCT source_kind
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND participant_id = :participant_id;
