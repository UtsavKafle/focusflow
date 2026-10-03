# 02 Handoff: Data B (Silver features, baselines, Gold WearableState)

You are the coding agent for Data B. Read `00-common.md` first. You own `databricks/streaming/`, `databricks/features/`, `databricks/sql/ddl_silver.sql`, `databricks/sql/ddl_gold.sql`, `databricks/sql/gold_*.sql`. You also watch Databricks spend.

**Mission:** turn Bronze events into one-minute Silver features, causal personal baselines, and Gold `WearableState` rows that exactly match the contract, with explicit unknowns and quality. The backend reads Gold every ~5 s.

## Mock data first
The real download is slow. Generate the mock (`python fixtures/make_mock_big_ideas.py --out data/mock`) and run `python -m databricks.features.run_local --participant 001 --raw data/mock --tz-assume America/New_York --acc-hz 8 --run-id mock-1`. Your Silver/Gold should match `fixtures/mock_big_ideas/*.csv` (rest 474, 474, 130 minutes; confound during the 02-14 exercise; load >= 0.70 in the last 20 minutes). Build the Spark wrappers and idempotency tests against it. Details: `docs/mock-data.md`.

## Inputs
- Bronze table `bronze_wearable_events` (Data A). Until it exists, develop against `NormalizedEvent`-shaped test data you generate from the real CSVs, or from a synthetic stub.
- Contract: `WearableState`, `Quality` in `contracts/models.py`. Target behavior examples: `fixtures/scenarios/*/states.json` (e.g. `missing_data` shows nulls with `missing_reasons`).
- Definitions: `docs/HANDOFF.md` sections 7.3 to 7.5, 7.7.

## Build features as pure functions first (testable without Spark)
Create `databricks/features/` as plain Python/pandas modules, then wrap in Spark:
1. `minute_features.py`: from events to one row per half-open minute `[window_start, window_end)`: `hr_mean_bpm, hr_min, hr_max, hr_std, hr_coverage`, `eda_mean, eda_std, eda_delta, eda_coverage`, `acc_dyn_mean, acc_dyn_std, acc_dyn_max, stillness_ratio, acc_coverage` (use dynamic magnitude: remove gravity/static offset via trailing causal mean or magnitude variation, not raw magnitude), optional `temp_mean`. Coverage = fraction of expected samples present. Missing is null, never zero.
2. `baselines.py`: causal robust z: `(value - median) / max(1.4826 * MAD, epsilon)` using only data strictly before the current time. First 24 to 48 usable recorded hours = warm-up: output null z with reason `baseline_warmup` and suppress physiology-driven triggers. Store transform, epsilon, valid count, `baseline_id`, `baseline_cutoff`. Consider a log transform for EDA and document it. If you claim "evening baseline", compute an actual earlier-evening one; otherwise call it "recent baseline".
3. `state.py` (Gold rules):
   - `component(z) = clamp(z/3, 0, 1)`; `physiological_load = 0.5*comp(HR z) + 0.5*comp(EDA z)` for the MVP (RMSSD later, then 0.4/0.4/0.2). Require usable HR and EDA coverage, else null with reason.
   - `activity_level` from ACC (normalized 0 to 1, documented). `activity_confound = activity_level above threshold`; when true the backend suppresses the exam-load trigger.
   - Rest estimate: longest sustained low-movement stretch in the scenario's overnight window with compatible HR pattern. Separate observed stillness from sensor gaps. `estimated_rest_minutes` null with reason `overnight_coverage_below_minimum` if coverage is poor. `target_rest_minutes = 480`, `recovery_score = clamp(est/target, 0, 1)` or null. No sleep staging, no efficiency.
   - `quality`: `status` in sufficient/limited/unavailable, per-signal coverage, `missing_reasons` for EVERY null field (the Pydantic model rejects a null without a reason).
   - `evidence_ids`: IDs of minute windows and rest interval used (`window-0042`, `rest-0002` style, must be resolvable via Silver/Gold).
4. Tests in `tests/` named `test_features_*.py` (you may add files with that prefix): z-scores never use future data, coverage nulls, confound flag, rest estimate on a synthetic night, and a Gold-row -> `WearableState.model_validate` round trip.

## Spark layer
5. `databricks/sql/ddl_silver.sql`, `ddl_gold.sql` per `00-common.md`.
6. `databricks/streaming/silver_stream.py`: watermarked 1-minute windowed aggregation, 2-minute lateness allowance, append output, unique checkpoint per run and query. Finalized windows lag event time; expose "latest fully processed time" for the controller's `processed_time`.
7. `databricks/streaming/gold_stream.py`: Silver -> Gold. If you use `foreachBatch`, make writes idempotent (MERGE on `(run_id, participant_id, window_end)`) and order explicitly. Baselines need history: read prior Silver rows for the run.
8. Gold read query for the backend: `databricks/sql/gold_latest.sql` (latest row per run) and `gold_history.sql` (range query, bounded). Keep them parameterized and cheap.
9. If serverless rejects the trigger mode, use `availableNow` batches in a loop and document it in `docs/decisions.md`.

## Milestones
- M1 (Sat 19:00): features 1 to 3 working locally on real HR/EDA/ACC for the chosen participant (get the chosen ID and segment from Data A), tests green.
- M2 (Sun 00:00): Silver and Gold tables populated from a real replayed segment; backend can `SELECT` the latest Gold row and validate it. Credits check.
- M3 (Sun 05:00): tuned thresholds so the demo segment produces ONE believable trigger moment and a calm moment; rest estimate or honest unknown; IBI/RMSSD only if everything else is done.
- M4: freeze. Export derived Gold for the saved-results fallback (coordinate with Data A).

## Definition of done
- Every Gold row validates against `WearableState` (with the quality + missing reasons rule).
- No future leakage (test). Warm-up behavior visible. Gaps show as unavailable, never zero.
- Same input replayed twice gives the same Gold (determinism test).
- Spend log in `docs/decisions.md`: credits at M2 and at each check.

## Gotchas
- Trigger rule logic (15 of last 20 valid minutes at load >= 0.70, recovery < 0.50, pressure, cooldown) lives in the backend (Integrator), not Gold. You only supply the inputs, clean.
- Do not tune thresholds to make a pretty demo by peeking at the future. Document the tuning window.
