-- Bounded history. Parameters: :run_id, :start, :end (caller caps the range, e.g. <= 24 h)
SELECT run_id, as_of, window_start, window_end, heart_rate_bpm, physiological_load, activity_level,
       estimated_rest_minutes, recovery_score, quality_json, activity_confound, evidence_ids, source_kind
FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id AND window_end > :start AND window_end <= :end
ORDER BY window_end;
