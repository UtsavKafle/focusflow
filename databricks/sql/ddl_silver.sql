-- Data B. Silver: one row per (run_id, participant_id, window_start). Half-open minute windows. Append-only Delta.
CREATE TABLE IF NOT EXISTS focusflow.main.silver_wearable_minute (
  run_id STRING NOT NULL, participant_id STRING NOT NULL,
  window_start TIMESTAMP NOT NULL, window_end TIMESTAMP NOT NULL,
  hr_mean_bpm DOUBLE, hr_min_bpm DOUBLE, hr_max_bpm DOUBLE, hr_std_bpm DOUBLE, hr_coverage DOUBLE,
  eda_mean DOUBLE, eda_std DOUBLE, eda_delta DOUBLE, eda_coverage DOUBLE,
  acc_dyn_mean_g DOUBLE, acc_dyn_std_g DOUBLE, acc_dyn_max_g DOUBLE, stillness_ratio DOUBLE, acc_coverage DOUBLE,
  hr_baseline_z DOUBLE, hr_z_reason STRING, eda_baseline_z DOUBLE, eda_z_reason STRING,
  baseline_id STRING, baseline_n_valid INT, baseline_cutoff TIMESTAMP, source_kind STRING NOT NULL
) USING DELTA;
