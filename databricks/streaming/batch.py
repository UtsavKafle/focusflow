"""Pure-pandas batch logic shared by the Spark streaming wrappers (`silver_stream.py`, `gold_stream.py`).
No pyspark import here on purpose: this module is unit tested without a Spark session; the streaming files
are thin glue that call these functions from `foreachBatch`. Same feature math as `databricks.features`
(`minute_features`, `add_baselines`, `build_gold`) -- this module only adds batching/finalization/merge-payload
framing around it.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from databricks.features.baselines import BaselineConfig, add_baselines
from databricks.features.bronze_adapter import bronze_to_minute_frames
from databricks.features.minute_features import minute_features
from databricks.features.quality_policy import QualityPolicy
from databricks.features.state import GoldConfig, build_gold

BASELINE_COLUMNS = ["hr_baseline_z", "hr_z_reason", "eda_baseline_z", "eda_z_reason",
                    "baseline_id", "baseline_n_valid", "baseline_cutoff"]

# Single source of truth for the MERGE payload column sets, so the Spark-side explicit schemas in
# silver_stream.py/gold_stream.py (needed because pandas->Spark type inference fails on an all-NULL column,
# e.g. the baseline columns before the baseline pass runs) can be built from these and checked against the
# real output of the functions below, instead of drifting out of sync with `minute_features`/`build_gold`.
SILVER_FEATURE_COLUMNS = [
    "run_id", "participant_id", "window_start", "window_end",
    "hr_mean_bpm", "hr_min_bpm", "hr_max_bpm", "hr_std_bpm", "hr_coverage",
    "eda_mean", "eda_std", "eda_coverage",
    "acc_dyn_mean_g", "acc_dyn_std_g", "acc_dyn_max_g", "stillness_ratio", "acc_coverage",
    "eda_delta", *BASELINE_COLUMNS, "source_kind",
]
GOLD_COLUMNS = [
    "run_id", "participant_id", "as_of", "window_start", "window_end",
    "heart_rate_bpm", "physiological_load", "activity_level",
    "estimated_rest_minutes", "target_rest_minutes", "recovery_score",
    "quality_json", "baseline_id", "baseline_cutoff", "evidence_ids", "activity_confound", "source_kind",
]


def localize_utc_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Spark's `toPandas()` (and `Row` values from `.collect()`, see `localize_utc_scalar`) return NAIVE
    timestamps when the session timezone is UTC -- the setting this pipeline requires (see
    silver_stream.py/gold_stream.py's `SparkSession.builder`). This makes the given columns tz-aware UTC
    again, so they compare cleanly against the tz-aware timestamps `minute_features`/`add_baselines`/
    `build_gold` always produce. A column that is already tz-aware, or absent, or empty is left alone."""
    df = df.copy()
    for c in columns:
        if c in df.columns and len(df) and not isinstance(df[c].dtype, pd.DatetimeTZDtype):
            df[c] = pd.to_datetime(df[c]).dt.tz_localize("UTC")
    return df


def safe_object_map(series: pd.Series, fn) -> pd.Series:
    """Apply `fn` elementwise while forcing the result to stay `dtype=object`. Used by
    `streaming.merge.to_spark_df` to convert e.g. `float`/`None` cells to `int`/`None` before handing a
    nullable-integer column to Spark. `Series.map`/`.apply` would otherwise re-infer a dtype from the
    returned Python objects -- a `[int, None, int]` result silently collapses back to `float64` with the
    `None`s turned back into `NaN` (a real bug hit against local Spark: it quietly undoes the "turn NaN into
    a real SQL NULL" fix if routed through `.map`/`.apply` instead of this)."""
    return pd.Series([fn(v) for v in series], index=series.index, dtype=object)


def localize_utc_scalar(value) -> pd.Timestamp | None:
    """Same fix as `localize_utc_columns`, for a single scalar value pulled out of a one-row/one-column
    Spark DataFrame via `.toPandas()` (NOT `.collect()` -- see silver_stream.py/gold_stream.py's comments:
    `Row.collect()` was observed, against local Spark with Arrow disabled, to apply the driver JVM's
    default/system timezone to `TimestampType` values despite `spark.sql.session.timeZone=UTC`, while
    `.toPandas()` on the exact same query returns the correct UTC wall-clock value. Every caller in this
    codebase was moved off `.collect()` for timestamps for that reason; this function assumes its input is
    already correctly UTC (naive or aware) the way `.toPandas()` output is."""
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    return ts if ts.tzinfo is not None else ts.tz_localize("UTC")


@dataclass(frozen=True)
class SilverStreamConfig:
    lag_minutes: int = 2             # a minute is "finalized" once max(event_time) - lag_minutes >= window_end
    acc_lookback_seconds: int = 10   # caller must supply this much extra Bronze history for the ACC rolling mean
    expected_hz: dict | None = None
    acc_unit_scale_g: float = 1 / 64
    still_thresh_g: float = 0.05


def process_silver_features_batch(bronze_rows: pd.DataFrame, *, run_id: str, participant_id: str, source_kind: str,
                                  cfg: SilverStreamConfig = SilverStreamConfig(),
                                  policy: QualityPolicy | None = None,
                                  min_window_start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Bronze-shaped rows for one `foreachBatch` call (the new batch plus `cfg.acc_lookback_seconds` of prior
    history the caller loaded for the rolling ACC mean) -> finalized Silver feature rows, ready to MERGE into
    `silver_wearable_minute` on (run_id, participant_id, window_start). `databricks.features.quality_policy`
    (via `policy`, defaulting from `source_kind`) decides which rows `bronze_to_minute_frames` actually uses.
    Baseline columns are left NULL here; `process_silver_baseline_batch` fills them in a second pass once the
    row is persisted. A minute is finalized once `window_end <= max(event_time) - lag_minutes`: lookback rows
    loaded only to seed the rolling ACC mean are naturally excluded since they fall before `min_window_start`."""
    if bronze_rows is None or bronze_rows.empty:
        return pd.DataFrame()
    policy = policy or QualityPolicy.for_source_kind(source_kind)
    frames = bronze_to_minute_frames(bronze_rows, policy)
    max_t = pd.Timestamp(bronze_rows["event_time"].max())
    cutoff = max_t - pd.Timedelta(minutes=cfg.lag_minutes)
    sil = minute_features(frames["hr"], frames["eda"], frames["acc"], expected_hz=cfg.expected_hz,
                          acc_unit_scale_g=cfg.acc_unit_scale_g, still_thresh_g=cfg.still_thresh_g)
    if sil.empty:
        return sil
    sil = sil[sil["window_end"] <= cutoff]
    if min_window_start is not None:
        sil = sil[sil["window_start"] >= min_window_start]
    if sil.empty:
        return sil.reset_index(drop=True)
    sil = sil.reset_index(drop=True)
    sil.insert(0, "run_id", run_id)
    sil.insert(1, "participant_id", participant_id)
    for c in BASELINE_COLUMNS:
        sil[c] = None
    sil["source_kind"] = source_kind
    return sil


def process_silver_baseline_batch(all_silver_features: pd.DataFrame, *, baseline_cfg: BaselineConfig = BaselineConfig(),
                                  only_new_after: pd.Timestamp | None = None) -> pd.DataFrame:
    """ALL persisted Silver feature rows for a run (sorted by window_start, baseline columns ignored/overwritten)
    -> baseline columns for rows with `window_start > only_new_after`, ready to MERGE (update-only) into
    `silver_wearable_minute`. Always recomputed from the run's first minute: warm-up counts and the refresh
    grid depend on where the frame starts, so slicing the input would silently change past z-scores."""
    if all_silver_features is None or all_silver_features.empty:
        return pd.DataFrame(columns=["run_id", "participant_id", "window_start", *BASELINE_COLUMNS])
    s = all_silver_features.sort_values("window_start").reset_index(drop=True)
    z = add_baselines(s, baseline_cfg)
    out = z[["run_id", "participant_id", "window_start", *BASELINE_COLUMNS]]
    if only_new_after is not None:
        out = out[out["window_start"] > only_new_after]
    return out.reset_index(drop=True)


def process_gold_batch(silver_all: pd.DataFrame, *, run_id: str, participant_id: str, source_kind: str,
                       gold_cfg: GoldConfig = GoldConfig(), only_new_after: pd.Timestamp | None = None) -> pd.DataFrame:
    """ALL baselined Silver rows for a run -> Gold rows with `window_end > only_new_after`, ready to MERGE
    (insert-only in practice, since Gold rows never change once written) into `gold_wearable_state`. Rest
    estimation looks back across nights, so (like the baseline pass) this always runs on the full history."""
    if silver_all is None or silver_all.empty:
        return pd.DataFrame()
    s = silver_all.sort_values("window_start").reset_index(drop=True)
    g = build_gold(s, run_id=run_id, participant_id=participant_id, source_kind=source_kind, cfg=gold_cfg)
    if only_new_after is not None:
        g = g[g["window_end"] > only_new_after]
    return g.reset_index(drop=True)


def latest_processed_time(gold: pd.DataFrame) -> pd.Timestamp | None:
    """max Gold `as_of` for a run -- the controller's `processed_time`. Pure/pandas form; the Spark-backed
    version in `gold_stream.py` queries the table instead of requiring the caller to hold it in memory."""
    if gold is None or gold.empty:
        return None
    return pd.Timestamp(gold["as_of"].max())
