"""Spark-free idempotency checks for databricks/streaming/batch.py, standing in for a real MERGE/retry on
Databricks (no local Spark session available -- see docs/decisions.md). `simulate_merge_replace` is the
pandas analog of `merge.merge_into`'s `whenMatchedUpdateAll().whenNotMatchedInsertAll()`: concat existing and
new rows, then keep the LAST row per key. That is exactly what a Delta MERGE on the same keys does, so if a
batch is replayed (e.g. Spark retries a micro-batch whose checkpoint commit didn't land), applying its
(deterministic) output twice must leave the table in the same state as applying it once."""
import numpy as np
import pandas as pd
import pytest

from databricks.features.baselines import BaselineConfig
from databricks.streaming.batch import (
    SilverStreamConfig, process_gold_batch, process_silver_baseline_batch, process_silver_features_batch,
)

from tests.test_streaming_batch import merge_baseline_update, to_bronze
from databricks.features.synthetic import make_signals

BCFG = BaselineConfig(warmup_minutes=360, refresh_minutes=10)


def simulate_merge_replace(existing: pd.DataFrame, updates: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Pandas analog of a Delta MERGE whenMatchedUpdateAll/whenNotMatchedInsertAll on `keys`."""
    if existing is None or existing.empty:
        return updates.reset_index(drop=True)
    if updates is None or updates.empty:
        return existing.reset_index(drop=True)
    combined = pd.concat([existing, updates], ignore_index=True)
    return combined.drop_duplicates(subset=keys, keep="last").sort_values(keys).reset_index(drop=True)


def assert_unique_keys(df: pd.DataFrame, keys: list[str]) -> None:
    assert not df.duplicated(subset=keys).any(), f"duplicate keys on {keys}"


@pytest.fixture(scope="module")
def signals():
    return make_signals(days=3.0, episode_minutes=90)


@pytest.fixture(scope="module")
def bronze(signals):
    hr, eda, acc, hz = signals
    return to_bronze(hr, eda, acc).sort_values("event_time").reset_index(drop=True), hz


def test_silver_features_batch_is_deterministic_with_unique_keys(bronze):
    rows, hz = bronze
    cfg = SilverStreamConfig(expected_hz=hz)
    a = process_silver_features_batch(rows, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    b = process_silver_features_batch(rows, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    assert_unique_keys(a, ["run_id", "participant_id", "window_start"])
    pd.testing.assert_frame_equal(a, b)


def test_gold_batch_is_deterministic_with_unique_keys(bronze):
    rows, hz = bronze
    cfg = SilverStreamConfig(expected_hz=hz)
    feats = process_silver_features_batch(rows, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    sil = merge_baseline_update(feats, process_silver_baseline_batch(feats, baseline_cfg=BCFG))
    a = process_gold_batch(sil, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    b = process_gold_batch(sil, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    assert_unique_keys(a, ["run_id", "participant_id", "window_end"])
    pd.testing.assert_frame_equal(a, b)


def test_merge_replace_is_idempotent_under_exact_replay(bronze):
    """MERGE-ing the exact same batch output twice (a replay of an unacknowledged micro-batch) must not
    duplicate rows or change any value."""
    rows, hz = bronze
    cfg = SilverStreamConfig(expected_hz=hz)
    keys = ["run_id", "participant_id", "window_start"]
    batch = process_silver_features_batch(rows, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)

    once = simulate_merge_replace(pd.DataFrame(), batch, keys)
    twice = simulate_merge_replace(once, batch, keys)  # replay the SAME batch again
    assert_unique_keys(twice, keys)
    assert len(twice) == len(once)
    pd.testing.assert_frame_equal(once, twice)


def test_retried_batch_with_overlapping_minutes_matches_clean_run(bronze):
    """Simulate silver_stream.py's two-batch, two-MERGE-pass flow, including a retry of the first batch
    (Spark redelivers the same rows after a transient failure) that OVERLAPS the data the second batch also
    covers once a bit of lookback is included -- then check the final table matches a single clean run."""
    rows, hz = bronze
    cfg = SilverStreamConfig(expected_hz=hz)
    keys = ["run_id", "participant_id", "window_start"]
    kwargs = dict(run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)

    mid_t = rows["event_time"].iloc[len(rows) // 2]
    chunk1 = rows[rows["event_time"] < mid_t]

    batch1 = process_silver_features_batch(chunk1, **kwargs)
    silver = simulate_merge_replace(pd.DataFrame(), batch1, keys)
    # retry: the same micro-batch is redelivered (e.g. the writeStream checkpoint commit failed after the
    # MERGE landed) -- overlapping entirely with what's already persisted.
    batch1_retry = process_silver_features_batch(chunk1, **kwargs)
    silver = simulate_merge_replace(silver, batch1_retry, keys)
    assert_unique_keys(silver, keys)
    assert len(silver) == len(batch1)

    baseline1 = process_silver_baseline_batch(silver, baseline_cfg=BCFG)
    silver = merge_baseline_update(silver, baseline1)

    # second batch sees all rows (plays the role of "new batch plus lookback"); min_window_start keeps it
    # from re-emitting rows batch1 already covered, so this batch's new rows overlap batch1's time range only
    # in the lookback portion, not in the emitted keys.
    batch2 = process_silver_features_batch(rows, min_window_start=silver["window_start"].max() + pd.Timedelta(minutes=1), **kwargs)
    silver = simulate_merge_replace(silver, batch2, keys)
    assert_unique_keys(silver, keys)

    baseline2 = process_silver_baseline_batch(silver, baseline_cfg=BCFG, only_new_after=batch1["window_start"].max())
    silver = merge_baseline_update(silver, baseline2)

    clean = process_silver_features_batch(rows, **kwargs)
    clean = merge_baseline_update(clean, process_silver_baseline_batch(clean, baseline_cfg=BCFG))

    assert len(silver) == len(clean)
    silver_sorted = silver.sort_values("window_start").reset_index(drop=True)
    clean_sorted = clean.sort_values("window_start").reset_index(drop=True)
    for c in ("hr_mean_bpm", "eda_mean", "acc_dyn_mean_g", "hr_baseline_z", "eda_baseline_z"):
        a = pd.to_numeric(silver_sorted[c], errors="coerce").to_numpy()
        b = pd.to_numeric(clean_sorted[c], errors="coerce").to_numpy()
        assert np.allclose(a, b, equal_nan=True), c
