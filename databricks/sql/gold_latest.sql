-- Latest Gold row for a run (backend polls this ~every 5 s). Parameter: :run_id
SELECT * FROM focusflow.main.gold_wearable_state
WHERE run_id = :run_id
ORDER BY as_of DESC
LIMIT 1;
