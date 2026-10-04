"""databricks/streaming/batch.py: the pandas path the Spark `foreachBatch` wrappers call. No pyspark here --
these are plain-function tests per the handoff ("keep Spark glue thin"); they check that batching/chunking
the pipeline the way the streaming wrappers will gives identical results to running it in one shot."""
import numpy as np
import pandas as pd
import pytest

from databricks.features.baselines import BaselineConfig, add_baselines
from databricks.features.bronze_adapter import bronze_to_minute_frames
from databricks.features.minute_features import minute_features
from databricks.features.quality_policy import QualityPolicy
from databricks.features.state import build_gold
from databricks.features.synthetic import make_signals
from databricks.streaming.batch import (
    GOLD_COLUMNS, SILVER_FEATURE_COLUMNS, SilverStreamConfig, latest_processed_time, localize_utc_columns,
    localize_utc_scalar, process_gold_batch, process_silver_baseline_batch, process_silver_features_batch,
    safe_object_map,
)

BCFG = BaselineConfig(warmup_minutes=360, refresh_minutes=10)
MOCK_POLICY = QualityPolicy.for_source_kind("synthetic_fixture")


SIGNAL_UNITS = {"hr": "bpm", "eda": "microsiemens", "acc": "unverified"}


def to_bronze(hr: pd.DataFrame, eda: pd.DataFrame, acc: pd.DataFrame, *, run_id: str = "r1",
              participant_id: str = "p1", source_kind: str = "synthetic_fixture") -> pd.DataFrame:
    """Bronze-shaped rows matching the real 14-column contract (databricks.streaming.bronze_contract)."""
    parts = []
    for d, sig, keys in ((hr, "hr", ["value"]), (eda, "eda", ["value"]), (acc, "acc", ["x", "y", "z"])):
        if d.empty:
            continue
        n = len(d)
        p = d[["event_time"]].copy()
        p["schema_version"] = "1.0"
        p["run_id"] = run_id
        p["event_id"] = [f"{participant_id}-{sig}-{i:09d}" for i in range(n)]
        p["participant_id"] = participant_id
        p["source_kind"] = source_kind
        p["source_timestamp"] = p["event_time"]
        p["ingested_at"] = p["event_time"]
        p["signal"] = sig
        p["values"] = d[keys].to_dict("records")
        p["unit"] = SIGNAL_UNITS[sig]
        p["quality"] = "valid"
        p["source_file"] = f"{sig.upper()}_{participant_id}.csv"
        p["source_row"] = range(1, n + 1)
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def merge_baseline_update(all_feats: pd.DataFrame, baseline_update: pd.DataFrame) -> pd.DataFrame:
    """Apply a (possibly partial) baseline-pass result onto accumulated feature rows, the way a real MERGE
    `whenMatchedUpdate` would: only rows present in `baseline_update` get their baseline columns overwritten,
    everything else (already-baselined rows from an earlier batch) is left alone."""
    out = all_feats.set_index(["run_id", "participant_id", "window_start"])
    upd = baseline_update.set_index(["run_id", "participant_id", "window_start"])
    out.update(upd)
    return out.reset_index()


@pytest.fixture(scope="module")
def signals():
    return make_signals(days=3.0, episode_minutes=90)


def test_bronze_to_minute_frames_round_trips(signals):
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc)
    frames = bronze_to_minute_frames(bronze, MOCK_POLICY)
    assert len(frames["hr"]) == len(hr) and len(frames["eda"]) == len(eda) and len(frames["acc"]) == len(acc)
    assert np.allclose(frames["hr"]["value"].to_numpy(), hr["value"].to_numpy())
    assert set(frames["acc"].columns) == {"event_time", "x", "y", "z"}


def test_dropped_quality_excluded():
    hr = pd.DataFrame({"event_time": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z"]), "value": [70.0, 71.0]})
    bronze = to_bronze(hr, pd.DataFrame(columns=["event_time", "value"]), pd.DataFrame(columns=["event_time", "x", "y", "z"]))
    bronze.loc[1, "quality"] = "dropped"
    frames = bronze_to_minute_frames(bronze, MOCK_POLICY)
    assert len(frames["hr"]) == 1 and frames["hr"]["value"].iloc[0] == 70.0


def test_silver_feature_batch_matches_direct_pipeline(signals):
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc)
    direct = minute_features(hr, eda, acc, expected_hz=hz)
    cutoff = bronze["event_time"].max() - pd.Timedelta(minutes=2)
    direct = direct[direct["window_end"] <= cutoff].reset_index(drop=True)

    batched = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                             cfg=SilverStreamConfig(expected_hz=hz))
    cols = ["window_start", "window_end", "hr_mean_bpm", "eda_mean", "acc_dyn_mean_g", "stillness_ratio",
            "hr_coverage", "eda_coverage", "acc_coverage"]
    assert len(batched) == len(direct)
    for c in cols:
        if c in ("window_start", "window_end"):
            # compare as datetimes: pandas 3 may return ns on one side and us on the other, and
            # pd.to_numeric would turn those into integers 1000x apart
            assert (pd.to_datetime(batched[c], utc=True).to_numpy() == pd.to_datetime(direct[c], utc=True).to_numpy()).all()
            continue
        assert np.allclose(pd.to_numeric(batched[c], errors="coerce"), pd.to_numeric(direct[c], errors="coerce"), equal_nan=True)
    assert batched["run_id"].eq("r1").all() and batched["source_kind"].eq("synthetic_fixture").all()
    assert batched["hr_baseline_z"].isna().all()  # baseline pass hasn't run yet


def test_silver_feature_batch_respects_min_window_start(signals):
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc)
    full = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=SilverStreamConfig(expected_hz=hz))
    cut = full["window_start"].iloc[100]
    partial = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                            cfg=SilverStreamConfig(expected_hz=hz), min_window_start=cut)
    assert (partial["window_start"] >= cut).all()
    assert len(partial) == len(full) - 100


def test_baseline_batch_matches_add_baselines(signals):
    hr, eda, acc, hz = signals
    sil = minute_features(hr, eda, acc, expected_hz=hz)
    direct = add_baselines(sil, BCFG)
    feats = sil.copy()
    feats.insert(0, "run_id", "r1")
    feats.insert(1, "participant_id", "p1")
    baselined = process_silver_baseline_batch(feats, baseline_cfg=BCFG)
    assert np.allclose(baselined["hr_baseline_z"].to_numpy(dtype=float), direct["hr_baseline_z"].to_numpy(dtype=float), equal_nan=True)
    assert np.allclose(baselined["eda_baseline_z"].to_numpy(dtype=float), direct["eda_baseline_z"].to_numpy(dtype=float), equal_nan=True)


def test_baseline_batch_only_new_after(signals):
    hr, eda, acc, hz = signals
    sil = minute_features(hr, eda, acc, expected_hz=hz)
    feats = sil.copy()
    feats.insert(0, "run_id", "r1")
    feats.insert(1, "participant_id", "p1")
    cut = feats["window_start"].iloc[500]
    only_new = process_silver_baseline_batch(feats, baseline_cfg=BCFG, only_new_after=cut)
    assert (only_new["window_start"] > cut).all()
    assert len(only_new) == len(feats) - 501


def test_gold_batch_matches_direct_pipeline(signals):
    hr, eda, acc, hz = signals
    sil = minute_features(hr, eda, acc, expected_hz=hz)
    z = add_baselines(sil, BCFG)
    direct = build_gold(z, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    batched = process_gold_batch(z, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    assert len(batched) == len(direct)
    for c in ("heart_rate_bpm", "physiological_load", "activity_level", "estimated_rest_minutes", "recovery_score"):
        assert np.allclose(pd.to_numeric(batched[c], errors="coerce"), pd.to_numeric(direct[c], errors="coerce"), equal_nan=True)
    assert (batched["activity_confound"] == direct["activity_confound"]).all()


def test_gold_batch_only_new_after(signals):
    hr, eda, acc, hz = signals
    sil = minute_features(hr, eda, acc, expected_hz=hz)
    z = add_baselines(sil, BCFG)
    full = process_gold_batch(z, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    cut = full["window_end"].iloc[1000]
    only_new = process_gold_batch(z, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", only_new_after=cut)
    assert (only_new["window_end"] > cut).all()
    assert len(only_new) == len(full) - 1001
    assert latest_processed_time(only_new) == full["as_of"].iloc[-1]


def test_latest_processed_time_empty():
    assert latest_processed_time(pd.DataFrame()) is None
    assert latest_processed_time(None) is None


def test_end_to_end_chunked_streaming_matches_single_batch(signals):
    """Simulate two `foreachBatch` calls the way silver_stream.py/gold_stream.py make them (feature pass,
    baseline pass over everything persisted so far, then Gold over everything persisted so far) and check the
    result equals running the whole pipeline in one shot -- the "foreachBatch path == pandas path" check the
    handoff asks for."""
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc).sort_values("event_time").reset_index(drop=True)
    cfg = SilverStreamConfig(expected_hz=hz)

    one_shot_feats = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    one_shot_sil = merge_baseline_update(one_shot_feats, process_silver_baseline_batch(one_shot_feats, baseline_cfg=BCFG))
    one_shot_gold = process_gold_batch(one_shot_sil, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")

    mid_t = bronze["event_time"].iloc[len(bronze) // 2]
    chunk1 = bronze[bronze["event_time"] < mid_t]

    persisted = process_silver_features_batch(chunk1, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    sil1 = merge_baseline_update(persisted, process_silver_baseline_batch(persisted, baseline_cfg=BCFG))
    gold1 = process_gold_batch(sil1, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")

    new_feats = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                               cfg=cfg, min_window_start=persisted["window_start"].max() + pd.Timedelta(minutes=1))
    all_feats = pd.concat([sil1, new_feats], ignore_index=True)
    baseline2 = process_silver_baseline_batch(all_feats, baseline_cfg=BCFG, only_new_after=persisted["window_start"].max())
    final_sil = merge_baseline_update(all_feats, baseline2)
    last_as_of = gold1["as_of"].max() if len(gold1) else None
    gold2 = process_gold_batch(final_sil, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", only_new_after=last_as_of)
    combined_gold = pd.concat([gold1, gold2], ignore_index=True)

    assert len(combined_gold) == len(one_shot_gold)
    for c in ("heart_rate_bpm", "physiological_load", "activity_level", "estimated_rest_minutes"):
        assert np.allclose(pd.to_numeric(combined_gold[c], errors="coerce"), pd.to_numeric(one_shot_gold[c], errors="coerce"), equal_nan=True)


def test_localize_utc_columns_adds_tz_to_naive_timestamps():
    """Regression test for a real Spark-glue bug: `toPandas()` returns NAIVE timestamps when the session
    timezone is UTC, which then fail to compare against the tz-aware timestamps `minute_features` produces
    (`TypeError: Invalid comparison between dtype=datetime64[ns, UTC] and Timestamp`, seen against local
    Spark in scripts/local_spark_smoke.py)."""
    naive = pd.DataFrame({"window_start": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 00:01:00"]), "v": [1, 2]})
    assert naive["window_start"].dt.tz is None
    out = localize_utc_columns(naive, ["window_start"])
    assert str(out["window_start"].dt.tz) == "UTC"
    # the instant represented must be unchanged (tz_localize, not tz_convert from some other zone)
    assert out["window_start"].iloc[0] == pd.Timestamp("2026-01-01 00:00:00", tz="UTC")


def test_localize_utc_columns_is_idempotent_on_already_aware_columns():
    aware = pd.DataFrame({"window_start": pd.to_datetime(["2026-01-01T00:00:00Z"])})
    out = localize_utc_columns(aware, ["window_start"])
    assert out["window_start"].iloc[0] == aware["window_start"].iloc[0]


def test_localize_utc_columns_handles_missing_and_empty():
    df = pd.DataFrame({"other": [1, 2]})
    out = localize_utc_columns(df, ["window_start"])  # column absent -- no-op, no KeyError
    assert "window_start" not in out.columns
    empty = pd.DataFrame({"window_start": pd.to_datetime([])})
    out2 = localize_utc_columns(empty, ["window_start"])  # empty column -- no-op, no error
    assert out2.empty


def test_localize_utc_scalar_handles_none_and_naive_and_aware():
    assert localize_utc_scalar(None) is None
    assert localize_utc_scalar(pd.NaT) is None  # a one-row agg().toPandas() on an empty table gives NaT, not None
    import datetime
    naive = localize_utc_scalar(datetime.datetime(2026, 1, 1, 12, 0, 0))
    assert naive == pd.Timestamp("2026-01-01 12:00:00", tz="UTC")
    aware = localize_utc_scalar(pd.Timestamp("2026-01-01T12:00:00Z"))
    assert aware == pd.Timestamp("2026-01-01T12:00:00Z")


def test_silver_features_batch_with_naive_bronze_input_matches_aware_input(signals):
    """End-to-end regression: a bronze_rows frame with naive event_time (as it would arrive straight out of
    `batch_df.toPandas()` before the caller localizes it) must be rejected or handled the same way as one
    with tz-aware event_time, once localized -- this is the exact shape of the bug the Spark smoke test hit."""
    hr, eda, acc, hz = signals
    bronze_aware = to_bronze(hr, eda, acc)
    bronze_naive = bronze_aware.copy()
    bronze_naive["event_time"] = bronze_naive["event_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    bronze_naive = localize_utc_columns(bronze_naive, ["event_time"])

    cfg = SilverStreamConfig(expected_hz=hz)
    a = process_silver_features_batch(bronze_aware, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    b = process_silver_features_batch(bronze_naive, run_id="r1", participant_id="p1", source_kind="synthetic_fixture", cfg=cfg)
    pd.testing.assert_frame_equal(a, b)


def test_silver_feature_columns_constant_matches_actual_output(signals):
    """Guards silver_stream.py's explicit Spark schema (built from SILVER_FEATURE_COLUMNS, since an
    all-NULL column defeats pandas->Spark type inference) against drifting out of sync with what
    `process_silver_features_batch` actually returns."""
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc)
    out = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                        cfg=SilverStreamConfig(expected_hz=hz))
    assert list(out.columns) == SILVER_FEATURE_COLUMNS


def test_safe_object_map_preserves_int_and_none_dtype():
    """Regression test for a real bug hit converting Gold rows for Spark: `Series.map`/`.apply` re-infer the
    result dtype from the returned Python objects, so `[int, None, int]` silently collapses back to
    `float64` with the `None`s turned back into `NaN` -- undoing the exact NaN->None fix it was used for.
    `safe_object_map` must keep the real Python `int`/`None` objects."""
    s = pd.Series([491.0, None, 130.0], dtype=object)
    broken = s.map(lambda v: int(v) if v is not None else v)
    assert any(isinstance(v, float) and np.isnan(v) for v in broken)  # the bug, reproduced: None -> NaN

    fixed = safe_object_map(s, lambda v: int(v) if v is not None else v)
    assert fixed.tolist() == [491, None, 130]
    assert [type(v) for v in fixed] == [int, type(None), int]


def test_gold_columns_constant_matches_actual_output(signals):
    """Guards gold_stream.py's explicit Spark schema against drifting out of sync with `process_gold_batch`."""
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc)
    feats = process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                          cfg=SilverStreamConfig(expected_hz=hz))
    sil = merge_baseline_update(feats, process_silver_baseline_batch(feats, baseline_cfg=BCFG))
    out = process_gold_batch(sil, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    assert list(out.columns) == GOLD_COLUMNS


def test_silver_read_validates_against_bronze_contract(signals):
    """The Silver read (process_silver_features_batch, called from silver_stream.py's foreachBatch) must
    fail closed with a clear error if the Bronze rows it's handed don't match the real 14-column contract
    (databricks.streaming.bronze_contract) -- e.g. if a future Data A schema change silently drops a column
    this pipeline depends on, instead of a confusing KeyError three functions deeper."""
    hr, eda, acc, hz = signals
    bronze = to_bronze(hr, eda, acc).drop(columns=["unit"])
    with pytest.raises(ValueError, match="unit"):
        process_silver_features_batch(bronze, run_id="r1", participant_id="p1", source_kind="synthetic_fixture",
                                      cfg=SilverStreamConfig(expected_hz=hz))
