-- Data B. Gold: one row per (run_id, participant_id, window_end). Nulls are real NULLs; each has a reason in quality_json.
CREATE TABLE IF NOT EXISTS focusflow.main.gold_wearable_state (
  run_id STRING NOT NULL, participant_id STRING NOT NULL, as_of TIMESTAMP NOT NULL,
  window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL,
  heart_rate_bpm DOUBLE, physiological_load DOUBLE, activity_level DOUBLE,
  estimated_rest_minutes INT, target_rest_minutes INT NOT NULL, recovery_score DOUBLE,
  quality_json STRING NOT NULL, baseline_id STRING, baseline_cutoff TIMESTAMP,
  evidence_ids ARRAY<STRING>, activity_confound BOOLEAN NOT NULL, source_kind STRING NOT NULL
) USING DELTA;
