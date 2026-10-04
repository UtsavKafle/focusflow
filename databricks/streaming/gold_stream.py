"""Spark Structured Streaming wrapper: Silver -> Gold. Thin glue only -- feature math lives in
`databricks.features.state.build_gold`, batching/framing in `databricks.streaming.batch`, both pure pandas
and unit tested without Spark. This file needs a Databricks runtime (pyspark + delta-spark) and is NOT
imported by the test suite.

Each micro-batch reloads ALL Silver rows for the run (rest estimation looks back across nights, so this
always runs on full history -- restrict with `--history-hours` if a run gets too large for one batch) and
MERGEs only the Gold rows after the last written `as_of` into `gold_wearable_state`.

Run:
  python -m databricks.streaming.gold_stream --run-id <id> --participant <id> --catalog focusflow --schema main \
      --checkpoint-root /Volumes/focusflow/main/checkpoints [--available-now]
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import replace

import pandas as pd

try:
    from pyspark.sql import DataFrame, SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql.types import (
        ArrayType, BooleanType, DoubleType, IntegerType, StringType, StructField, StructType, TimestampType,
    )
except ImportError as exc:  # pragma: no cover - requires a Databricks runtime
    raise ImportError("databricks.streaming.gold_stream requires pyspark (run on a Databricks cluster)") from exc

from databricks.features.quality_policy import ACC_UNVERIFIED_UNITS_REASON, QualityPolicy, acc_is_usable
from databricks.features.state import GoldConfig
from databricks.streaming.batch import GOLD_COLUMNS, localize_utc_columns, localize_utc_scalar, process_gold_batch
from databricks.streaming.merge import merge_into, to_spark_df

SILVER_TABLE = "{catalog}.{schema}.silver_wearable_minute"
GOLD_TABLE = "{catalog}.{schema}.gold_wearable_state"
GOLD_KEYS = ["run_id", "participant_id", "window_end"]

# Built from GOLD_COLUMNS (batch.py's single source of truth) -- see silver_stream.py for why an explicit
# schema is needed at all (pandas->Spark type inference fails on an all-NULL column).
_COLUMN_TYPES = {
    "run_id": StringType(), "participant_id": StringType(), "as_of": TimestampType(),
    "window_start": TimestampType(), "window_end": TimestampType(),
    "heart_rate_bpm": DoubleType(), "physiological_load": DoubleType(), "activity_level": DoubleType(),
    "estimated_rest_minutes": IntegerType(), "target_rest_minutes": IntegerType(), "recovery_score": DoubleType(),
    "quality_json": StringType(), "baseline_id": StringType(), "baseline_cutoff": TimestampType(),
    "evidence_ids": ArrayType(StringType()), "activity_confound": BooleanType(), "source_kind": StringType(),
}
_NOT_NULL = {"run_id", "participant_id", "as_of", "window_start", "window_end", "target_rest_minutes",
            "quality_json", "activity_confound", "source_kind"}
GOLD_SCHEMA = StructType([StructField(c, _COLUMN_TYPES[c], c not in _NOT_NULL) for c in GOLD_COLUMNS])


def make_foreach_batch(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str,
                        source_kind: str, history_hours: float | None = None, gold_cfg: GoldConfig = GoldConfig()):
    silver_table = SILVER_TABLE.format(catalog=catalog, schema=schema)
    gold_table = GOLD_TABLE.format(catalog=catalog, schema=schema)
    if not acc_is_usable(QualityPolicy.for_source_kind(source_kind)) and gold_cfg.acc_unavailable_reason == "acc_unavailable":
        gold_cfg = replace(gold_cfg, acc_unavailable_reason=ACC_UNVERIFIED_UNITS_REASON)

    def fn(batch_df: DataFrame, batch_id: int) -> None:
        if batch_df.isEmpty():
            return
        silver_q = (
            spark.read.table(silver_table)
            .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
        )
        # .toPandas(), not .collect(), for every timestamp scalar below: see localize_utc_scalar's docstring
        # -- .collect() was observed to mis-apply the driver's local system timezone to TimestampType values
        # against local Spark, while .toPandas() on the same query is correct.
        if history_hours is not None:
            # must filter by run/participant too -- otherwise the cutoff could come from an unrelated run
            cutoff = silver_q.agg(F.max("window_start").alias("m")).toPandas()["m"].iloc[0]
            cutoff = localize_utc_scalar(cutoff)
            if cutoff is not None:
                silver_q = silver_q.filter(F.col("window_start") >= cutoff - pd.Timedelta(hours=history_hours))
        silver_all = localize_utc_columns(silver_q.toPandas(), ["window_start", "window_end", "baseline_cutoff"])

        existing_max_as_of = (
            spark.read.table(gold_table)
            .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
            .agg(F.max("as_of").alias("m")).toPandas()["m"].iloc[0]
        )
        only_new_after = localize_utc_scalar(existing_max_as_of)

        gold_rows = process_gold_batch(silver_all, run_id=run_id, participant_id=participant_id,
                                       source_kind=source_kind, gold_cfg=gold_cfg, only_new_after=only_new_after)
        if not gold_rows.empty:
            merge_into(spark, to_spark_df(spark, gold_rows, GOLD_SCHEMA), gold_table, keys=GOLD_KEYS)

    return fn


def start(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str, source_kind: str,
          checkpoint_root: str, available_now: bool = False, history_hours: float | None = None,
          gold_cfg: GoldConfig = GoldConfig()):
    silver_table = SILVER_TABLE.format(catalog=catalog, schema=schema)
    # silver_stream.py's baseline pass legitimately UPDATEs existing Silver rows (fills in baseline columns
    # once they're persisted) -- a Delta streaming source rejects update/delete commits by default
    # (DELTA_SOURCE_TABLE_IGNORE_CHANGES). skipChangeCommits is correct here, not a workaround: this stream's
    # foreachBatch (above) always reloads ALL Silver fresh via spark.read.table, so the readStream's diff is
    # only used as a "something changed, run a batch" signal -- it never reads the batch_df's own rows.
    stream = (
        spark.readStream.option("skipChangeCommits", "true").table(silver_table)
        .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
    )
    writer = stream.writeStream.foreachBatch(
        make_foreach_batch(spark, catalog=catalog, schema=schema, run_id=run_id, participant_id=participant_id,
                           source_kind=source_kind, history_hours=history_hours, gold_cfg=gold_cfg)
    ).option("checkpointLocation", f"{checkpoint_root}/{run_id}/gold")
    if available_now:
        return writer.trigger(availableNow=True).start()
    return writer.start()


def query_latest_processed_time(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str):
    """max Gold `as_of` for a run -- the controller's `processed_time`. None if no Gold rows exist yet.
    .toPandas(), not .collect(): see localize_utc_scalar's docstring."""
    gold_table = GOLD_TABLE.format(catalog=catalog, schema=schema)
    value = (
        spark.read.table(gold_table)
        .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
        .agg(F.max("as_of").alias("m")).toPandas()["m"].iloc[0]
    )
    return localize_utc_scalar(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--participant", required=True)
    ap.add_argument("--catalog", default=os.environ.get("DATABRICKS_CATALOG", "focusflow"))
    ap.add_argument("--schema", default=os.environ.get("DATABRICKS_SCHEMA", "main"))
    ap.add_argument("--checkpoint-root", default=os.environ.get("DATABRICKS_VOLUME_PATH", "/Volumes/focusflow/main/checkpoints"))
    ap.add_argument("--source-kind", default="recorded_replay")
    ap.add_argument("--history-hours", type=float, default=None, help="restrict Gold recompute to the last N hours, for runs too large for one batch")
    ap.add_argument("--available-now", action="store_true")
    a = ap.parse_args()
    spark = SparkSession.builder.getOrCreate()
    q = start(spark, catalog=a.catalog, schema=a.schema, run_id=a.run_id, participant_id=a.participant,
              source_kind=a.source_kind, checkpoint_root=a.checkpoint_root, available_now=a.available_now,
              history_hours=a.history_hours)
    if a.available_now:
        q.awaitTermination()
    else:
        while q.isActive:
            time.sleep(5)


if __name__ == "__main__":
    main()
