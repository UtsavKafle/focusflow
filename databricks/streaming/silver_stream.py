"""Spark Structured Streaming wrapper: Bronze -> Silver. Thin glue only -- all feature math lives in
`databricks.features.minute_features` and the batching/framing in `databricks.streaming.batch`, both pure
pandas and unit tested without Spark. This file needs a Databricks runtime (pyspark + delta-spark) and is
NOT imported by the test suite.

Each micro-batch does two MERGE passes into `silver_wearable_minute`:
  1. feature pass: compute finalized minute features for the new Bronze rows (plus a short lookback for the
     rolling ACC mean), MERGE insert-or-update on (run_id, participant_id, window_start).
  2. baseline pass: reload ALL persisted feature rows for the run, recompute `add_baselines` from the run's
     first minute (required -- warm-up and the refresh grid depend on where the frame starts), MERGE-update
     only the new rows' baseline columns.

Run:
  python -m databricks.streaming.silver_stream --run-id <id> --participant <id> --catalog focusflow --schema main \
      --checkpoint-root /Volumes/focusflow/main/checkpoints [--available-now]
If the workspace disallows a continuous streaming trigger, pass --available-now and loop this process
externally (log that choice in docs/decisions.md).
"""
from __future__ import annotations

import argparse
import os
import time

import pandas as pd

try:
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import DoubleType, IntegerType, StringType, StructField, StructType, TimestampType
except ImportError as exc:  # pragma: no cover - requires a Databricks runtime
    raise ImportError("databricks.streaming.silver_stream requires pyspark (run on a Databricks cluster)") from exc

from databricks.streaming.batch import (
    BASELINE_COLUMNS, SILVER_FEATURE_COLUMNS, SilverStreamConfig, localize_utc_columns, localize_utc_scalar,
    process_silver_baseline_batch, process_silver_features_batch,
)
from databricks.streaming.merge import merge_into, merge_update_only, to_spark_df

BRONZE_TABLE = "{catalog}.{schema}.bronze_wearable_events"
SILVER_TABLE = "{catalog}.{schema}.silver_wearable_minute"
SILVER_KEYS = ["run_id", "participant_id", "window_start"]

# Spark types for each column `batch.py` can produce, keyed by name so the schemas below are built FROM
# SILVER_FEATURE_COLUMNS/BASELINE_COLUMNS (the single source of truth in batch.py) instead of a second,
# independently-maintained column list that could silently drift out of sync with it.
_COLUMN_TYPES = {
    "run_id": StringType(), "participant_id": StringType(),
    "window_start": TimestampType(), "window_end": TimestampType(),
    "hr_mean_bpm": DoubleType(), "hr_min_bpm": DoubleType(), "hr_max_bpm": DoubleType(), "hr_std_bpm": DoubleType(),
    "hr_coverage": DoubleType(), "eda_mean": DoubleType(), "eda_std": DoubleType(), "eda_coverage": DoubleType(),
    "acc_dyn_mean_g": DoubleType(), "acc_dyn_std_g": DoubleType(), "acc_dyn_max_g": DoubleType(),
    "stillness_ratio": DoubleType(), "acc_coverage": DoubleType(), "eda_delta": DoubleType(),
    "hr_baseline_z": DoubleType(), "hr_z_reason": StringType(), "eda_baseline_z": DoubleType(), "eda_z_reason": StringType(),
    "baseline_id": StringType(), "baseline_n_valid": IntegerType(), "baseline_cutoff": TimestampType(),
    "source_kind": StringType(),
}
_NOT_NULL = {"run_id", "participant_id", "window_start", "window_end", "source_kind"}

# Explicit schemas for the MERGE payloads -- matches ddl_silver.sql's columns (any order: MERGE matches by
# name, and `to_spark_df` reorders to this before conversion). An explicit schema is required here: the
# feature pass's baseline columns are all NULL (the baseline pass hasn't run yet), and pandas->Spark type
# inference cannot determine a type from an all-None column.
SILVER_FEATURE_SCHEMA = StructType([StructField(c, _COLUMN_TYPES[c], c not in _NOT_NULL) for c in SILVER_FEATURE_COLUMNS])
BASELINE_UPDATE_SCHEMA = StructType([
    StructField(c, _COLUMN_TYPES[c], c not in _NOT_NULL) for c in ["run_id", "participant_id", "window_start", *BASELINE_COLUMNS]
])


def make_foreach_batch(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str,
                        source_kind: str, cfg: SilverStreamConfig = SilverStreamConfig()):
    bronze_table = BRONZE_TABLE.format(catalog=catalog, schema=schema)
    silver_table = SILVER_TABLE.format(catalog=catalog, schema=schema)

    def fn(batch_df: DataFrame, batch_id: int) -> None:
        if batch_df.isEmpty():
            return
        batch_pdf = localize_utc_columns(batch_df.toPandas(), ["event_time"])
        min_t = pd.Timestamp(batch_pdf["event_time"].min())
        # Must cover at least `lag_minutes` PLUS one full window (1 minute), not just the ACC rolling-mean
        # buffer: the previous batch's cutoff is `max_event_time - lag_minutes`, and it finalizes windows
        # with window_end <= cutoff -- so the first PENDING (unfinalized) window's own window_START can be
        # up to `lag_minutes + 1 minute` before that batch's max event time (the extra minute is the pending
        # window's own duration). Those pending minutes' Bronze rows live entirely in the previous batch,
        # before this batch's min event time; without reloading them here too, `combined` never contains
        # their data once the cutoff finally passes them, and they're silently finalized with PARTIAL
        # coverage instead of correctly delayed (caught empirically against local Spark: a 1-minute-short
        # margin gave 2/3 or 1/6 coverage, not 0, so this is easy to miss without comparing against the
        # pandas baseline -- scripts/local_spark_smoke.py).
        lookback_start = min_t - pd.Timedelta(minutes=cfg.lag_minutes + 1) - pd.Timedelta(seconds=cfg.acc_lookback_seconds)
        lookback_pdf = localize_utc_columns((
            spark.read.table(bronze_table)
            .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
            .filter((F.col("event_time") >= lookback_start) & (F.col("event_time") < min_t))
            .toPandas()
        ), ["event_time"])
        combined = pd.concat([lookback_pdf, batch_pdf], ignore_index=True) if not lookback_pdf.empty else batch_pdf

        # .toPandas(), not .collect(): see localize_utc_scalar's docstring -- .collect() was observed to
        # mis-apply the driver's local system timezone to TimestampType values against local Spark.
        existing = (
            spark.read.table(silver_table)
            .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
            .agg(F.max("window_start").alias("m")).toPandas()["m"].iloc[0]
        )
        existing = localize_utc_scalar(existing)
        min_window_start = existing + pd.Timedelta(minutes=1) if existing is not None else None

        feature_rows = process_silver_features_batch(
            combined, run_id=run_id, participant_id=participant_id, source_kind=source_kind, cfg=cfg,
            min_window_start=min_window_start)
        if not feature_rows.empty:
            merge_into(spark, to_spark_df(spark, feature_rows, SILVER_FEATURE_SCHEMA), silver_table, keys=SILVER_KEYS)

        all_features = localize_utc_columns((
            spark.read.table(silver_table)
            .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
            .toPandas()
        ), ["window_start", "window_end", "baseline_cutoff"])
        last_baselined = all_features.loc[all_features["hr_baseline_z"].notna() | (all_features["hr_z_reason"].notna()), "window_start"]
        only_new_after = pd.Timestamp(last_baselined.max()) if len(last_baselined) else None
        baseline_rows = process_silver_baseline_batch(all_features, only_new_after=only_new_after)
        if not baseline_rows.empty:
            merge_update_only(spark, to_spark_df(spark, baseline_rows, BASELINE_UPDATE_SCHEMA), silver_table,
                              keys=SILVER_KEYS, set_columns=BASELINE_COLUMNS)

    return fn


def start(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str, source_kind: str,
          checkpoint_root: str, available_now: bool = False, cfg: SilverStreamConfig = SilverStreamConfig()):
    bronze_table = BRONZE_TABLE.format(catalog=catalog, schema=schema)
    stream = (
        spark.readStream.table(bronze_table)
        .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
    )
    writer = stream.writeStream.foreachBatch(
        make_foreach_batch(spark, catalog=catalog, schema=schema, run_id=run_id, participant_id=participant_id,
                           source_kind=source_kind, cfg=cfg)
    ).option("checkpointLocation", f"{checkpoint_root}/{run_id}/silver")
    if available_now:
        return writer.trigger(availableNow=True).start()
    return writer.start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--participant", required=True)
    ap.add_argument("--catalog", default=os.environ.get("DATABRICKS_CATALOG", "focusflow"))
    ap.add_argument("--schema", default=os.environ.get("DATABRICKS_SCHEMA", "main"))
    ap.add_argument("--checkpoint-root", default=os.environ.get("DATABRICKS_VOLUME_PATH", "/Volumes/focusflow/main/checkpoints"))
    ap.add_argument("--source-kind", default="recorded_replay")
    ap.add_argument("--available-now", action="store_true", help="run one availableNow batch and exit, instead of a continuous trigger")
    a = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()
    q = start(spark, catalog=a.catalog, schema=a.schema, run_id=a.run_id, participant_id=a.participant,
              source_kind=a.source_kind, checkpoint_root=a.checkpoint_root, available_now=a.available_now)
    if a.available_now:
        q.awaitTermination()
    else:
        while q.isActive:
            time.sleep(5)


if __name__ == "__main__":
    main()
