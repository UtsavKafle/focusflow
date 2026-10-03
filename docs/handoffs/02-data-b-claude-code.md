# Data B: continuation handoff for Claude Code

**Paste this to Claude Code at the repo root:**
> Read AGENTS.md, docs/handoffs/00-common.md and docs/handoffs/02-data-b-claude-code.md. You are the Data B agent for FocusFlow (WolfHacks 2026, submission Sun Oct 4 11:00, feature freeze Sun 08:00). Run `pytest -q` first (expect everything green), then work through "Next tasks" in order. Stay inside the directories Data B owns. Ask me before changing anything in `contracts/`.

## Who and what
Data B owns Silver features, causal baselines, Gold `WearableState`, the Spark streaming wrappers, and Databricks spend tracking. Also owns: `databricks/streaming/`, `databricks/features/`, `databricks/sql/ddl_silver.sql`, `ddl_gold.sql`, `gold_*.sql`. Data A (a teammate) owns ingestion, Bronze and the replay controller. The Integrator owns contracts, backend, scheduler and agent. Spec: `docs/HANDOFF.md` sections 7.3 to 7.5 (and 7.7 for context). Role rules: `docs/handoffs/02-data-b.md`.

## State at handoff (all verified by `pytest -q`)
Built in pure pandas (no Spark), tested on SYNTHETIC data only. No real participant data has been used yet.
- `databricks/features/minute_features.py`: `minute_features(hr, eda, acc, expected_hz=, acc_unit_scale_g=1/64, still_thresh_g=0.05)`. Inputs are frames with `event_time` (UTC) and `value` (or `x,y,z`). Output: one row per half-open minute, full minute grid, gaps stay NaN with coverage 0. ACC is made causal by subtracting a trailing 10 s mean magnitude.
- `databricks/features/baselines.py`: `BaselineConfig`, `add_baselines`. Robust z `(v - median) / max(1.4826*MAD, eps)` from windows strictly before the baseline refresh (every 10 min). Warm-up 24 h of valid minutes gives NULL z with reason `baseline_warmup`. EDA uses `log1p`. Max history 4 days.
- `databricks/features/state.py`: `GoldConfig`, `build_gold`, `estimate_rest_nights`, `row_to_wearable_state`. Load = 0.5 clamp(HR z/3) + 0.5 clamp(EDA z/3). Activity = clamp(acc_dyn_mean_g / 0.25). `activity_confound` when activity >= 0.35. Rest = longest still stretch (stillness >= 0.9, HR z <= 0.5 or unchecked, bridging <= 5 min interruptions, sensor gaps break runs, minimum 30 min) in the last COMPLETED local 22:00 to 08:00 window; NULL with reason if overnight coverage < 0.7. Every null has a reason in `quality_json.missing_reasons`.
- `databricks/features/synthetic.py`: deterministic synthetic raw signals (never present as real).
- `databricks/features/run_local.py`: raw CSVs to `data/derived/<run>/silver.csv|gold.csv` plus a tuning summary.
- `databricks/sql/`: `ddl_silver.sql`, `ddl_gold.sql`, `gold_latest.sql`, `gold_history.sql`.
- `databricks/ingestion/quick_scan.py` (a scan script for the user to run on the raw dataset; Data A may replace it).
- Tests: `tests/test_features_pipeline.py` (11 tests: gaps are null not zero, warm-up, no future leakage, spike in the future does not change the past, confound, rest estimate, rest null on gappy night, Gold rows validate against `WearableState`, determinism).

## Mock data (use this now)
The real download is slow. `python fixtures/make_mock_big_ideas.py --out data/mock`, then `python -m databricks.features.run_local --participant 001 --raw data/mock --tz-assume America/New_York --acc-hz 8 --run-id mock-1`. Output must match `fixtures/mock_big_ideas/gold.csv` (pinned by `tests/test_mock_story.py`). Treat task 1 ("Real data pass") as: run on the mock now, run on real files when they arrive, and diff the two behaviors. Pass the true rates (`--acc-hz 32`) for real data. See `docs/mock-data.md`.

## File naming (seen on PhysioNet)
Participant folders hold `ACC_001.csv, BVP_001.csv, Dexcom_001.csv, EDA_001.csv, Food_Log_001.csv, HR_001.csv, IBI_001.csv, TEMP_001.csv`. Sizes for 001: ACC 838 MB, BVP 1.3 GB (skip), EDA 89 MB, TEMP 75 MB, HR 12 MB, IBI 10 MB. Put them in `data/raw/001/`.

## Known assumptions to verify (do not silently assume)
1. **ACC scale** 1/64 g per raw unit is the documented Empatica E4 scale. Unverified for this release. Check `docs/data-provenance.md` (Data A) or the PhysioNet page, and change `acc_unit_scale_g` plus the stillness threshold if needed.
2. **Timestamps**: `run_local.py` interprets naive timestamps in `--tz-assume` (default UTC) and prints a warning. Replace with whatever provenance documents. Dates in the dataset are shifted; time of day is preserved.
3. **Thresholds** (still ratio 0.9, activity 0.25 g, confound 0.35, HR compat z 0.5, overnight coverage 0.7, warm-up 24 h) are starters. Tune on the real participant using ONLY data before each decision time. Record the tuning window in `docs/decisions.md`.
4. **Night window** is local 22:00 to 08:00 America/New_York. Confirm it matches the scenario clock Data A uses.

## Next tasks, in order
1. **Real data pass (M1, was due Sat 19:00).** Get the chosen participant and demo segment from Data A (`docs/data-provenance.md`). Run `python -m databricks.features.run_local --participant <id> --raw data/raw --tz-assume <verified> --start ... --end ... --run-id local-1`. Inspect: coverage, load distribution, rest per night, how often `activity_confound` is true, share of minutes with load >= 0.70. Fix anything unrealistic (examples: ACC units, everything flagged as moving, no still nights). Add tests for each fix. Bound memory with `--start/--end` because ACC is 32 Hz.
2. **Pick demo moments.** Find ONE believable trigger-like stretch (load >= 0.70 in 15 of 20 valid minutes, low movement, rest < 240 min of 480) and one calm stretch, with at least 24 h of prior history. Write times to `docs/decisions.md`. Do not tune using future data. If the real data has no such stretch, say so and propose an honest alternative (synthetic injection labeled `synthetic_injection`, as described in `docs/HANDOFF.md`).
3. **Spark wrappers (M2, due Sun 00:00)** in `databricks/streaming/`. Recommended design (simple and robust):
   - `silver_stream.py`: `spark.readStream.table("focusflow.main.bronze_wearable_events")` filtered by `run_id`, with `.writeStream.foreachBatch(fn).option("checkpointLocation", f"/Volumes/focusflow/main/checkpoints/{run_id}/silver")`. Use `availableNow=True` in a loop if serverless disallows continuous triggers (log that in `docs/decisions.md`).
   - Inside `fn(batch_df, batch_id)`: determine finalized minutes = window_end <= max(event_time) - 2 minutes; load the needed bronze rows for those minutes plus a 10 s ACC lookback to pandas (single participant, small); call `minute_features`; MERGE into `silver_wearable_minute` on `(run_id, participant_id, window_start)` so retries are idempotent.
   - Baselines: load ALL Silver rows for the run from run start (<= ~15k rows), run `add_baselines`, write only the new rows. IMPORTANT: always recompute from the run's first minute, since warm-up counts and the 10-minute refresh grid depend on frame start.
   - `gold_stream.py`: same pattern, Silver to Gold. Run `build_gold` on all Silver for the run and MERGE only new `(run_id, participant_id, window_end)` rows. If that is too slow per batch, restrict to the last N hours plus the last two completed nights.
   - Write `source_kind` through (recorded_replay for real data).
   - Expose `latest_processed_time(run_id)` = max Gold `as_of` for the controller's `processed_time`.
   - A test that the pandas path and the foreachBatch path give identical Gold rows on the same small input (use a local Spark session if available, otherwise test `process_batch(pdf, ...)` as a plain function and keep Spark glue thin).
4. **Verify end to end** with the backend: `gold_latest.sql` returns a row, `row_to_wearable_state` validates it, nulls have reasons.
5. **Spend log.** At M2 and every few hours, check Databricks usage and append it to `docs/decisions.md`. Smallest SQL warehouse, 5 to 10 min auto-stop, no always-on streams. Under $8 remaining: tell the team to switch the demo to saved-results replay.
6. **M3.** Tune thresholds on the demo segment (see task 2). Add IBI/RMSSD only if all else is done (then weights 0.4/0.4/0.2 and add `rmssd_ms` to Silver; adding a Gold field needs Integrator approval).
7. **M4 (freeze Sun 08:00).** Export derived Gold for the demo segment for the saved-results fallback (coordinate with Data A): `data/derived/<run>/gold.csv` plus a Delta table if possible. Everything labeled FEATURE REPLAY in the UI.

## Definition of done
- Every Gold row validates against `WearableState`. No future leakage (tests). Gaps show as unavailable, never zero. Same input gives the same Gold.
- Silver and Gold tables populated from a real replayed segment, readable by the backend.
- `pytest -q` green at every push. Spend log current.

## Rules to keep
- Do NOT add `databricks/__init__.py`. `databricks/` is intentionally a namespace package so it cannot shadow the real `databricks` SDK and `databricks.sql` connector (`from databricks import sql` must keep working). Subfolders such as `databricks/features/` do have `__init__.py`.
- Honest labeling: scores are heuristics; no sleep staging; no stress diagnosis; "estimated rest" not "sleep quality"; one adult recording validates nothing.
- Never commit raw participant data (`data/raw/`, `data/derived/` are gitignored) or tokens.
- Do not edit `contracts/`, `backend/`, `frontend/`, `scheduler/`, `agent/`. Ask for contract changes through the human (Integrator owns them).
- Trigger rules live in the backend, not Gold. You only supply clean inputs and `activity_confound`.
- Branch `data-b/<topic>`, `git pull --rebase origin main` before pushing, merge to main at least every 2 hours.
- When blocked more than 20 minutes, tell the human and move to the next task.

## Reporting back
At each milestone, write 5 lines in `docs/decisions.md`: what changed, numbers that matter (coverage, share of load >= 0.70, rest by night), thresholds changed and why, open issues, credits left.
