"""Bounded Structured Streaming Bronze ingestion from committed landing batches.

Run on Databricks compute with this repository importable. No Spark dependency is
required for local adapter/replay tests. Uses availableNow, never an always-on job.
"""
from __future__ import annotations

import re

from .landing_writer import identifier


def validate_marker(marker: dict, run_id: str, landing_root: str) -> str:
    """Validate a commit reference before it can select files for Spark."""
    prefix = f"{landing_root.rstrip('/')}/{identifier(run_id)}/"
    signal = marker.get("signal")
    path = marker.get("path", "")
    count = marker.get("row_count")
    if (marker.get("run_id") != run_id or signal not in {"hr", "eda", "acc", "ibi", "temp"}
            or not isinstance(path, str) or not path.startswith(prefix + signal + "/")
            or not re.fullmatch(r"batch-\d{9}\.jsonl", path.removeprefix(prefix + signal + "/"))
            or not isinstance(count, int) or isinstance(count, bool) or count < 1
            or not re.fullmatch(r"[0-9a-f]{64}", marker.get("sha256") or "")):
        raise ValueError("invalid landing commit marker")
    return path


def event_schema():
    from pyspark.sql.types import (StructType, StructField, StringType, TimestampType,
                                  MapType, DoubleType, LongType)
    names = ("schema_version", "run_id", "event_id", "participant_id", "source_kind",
             "source_timestamp", "event_time", "ingested_at", "signal", "values", "unit",
             "quality", "source_file", "source_row")
    special = {"source_timestamp": TimestampType(), "event_time": TimestampType(),
               "ingested_at": TimestampType(), "values": MapType(StringType(), DoubleType(), False),
               "source_row": LongType()}
    return StructType([StructField(n, special.get(n, StringType()), False) for n in names])


def run_bronze(spark, run_id: str, *, landing_root="/Volumes/focusflow/main/landing",
               checkpoint_root="/Volumes/focusflow/main/checkpoints",
               table="focusflow.main.bronze_wearable_events", timeout_seconds=600):
    """Read ready markers, then validated final JSONL files; insert new IDs only.

    Table must already exist. Repeated microbatches/checkpoint recovery are
    idempotent via MERGE, including duplicate IDs arriving in later batches.
    """
    identifier(run_id)
    if not re.fullmatch(r"[A-Za-z_][\w]*\.[A-Za-z_][\w]*\.[A-Za-z_][\w]*", table):
        raise ValueError("table must be a safe catalog.schema.table identifier")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    from pyspark.sql.types import StructType, StructField, StringType, LongType
    from pyspark.sql import functions as F
    from delta.tables import DeltaTable
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    markers = (spark.readStream.schema(StructType([
        StructField("path", StringType()), StructField("sha256", StringType()),
        StructField("row_count", LongType()), StructField("run_id", StringType()),
        StructField("signal", StringType())])).option("recursiveFileLookup", "true")
        .option("pathGlobFilter", "*.ready.json").option("maxFilesPerTrigger", 100)
        .option("mode", "FAILFAST").json(f"{landing_root.rstrip('/')}/{run_id}"))

    def commit(batch, batch_id):
        rows = batch.collect()  # at most maxFilesPerTrigger small commit records
        if not rows:
            return
        session = batch.sparkSession
        paths = [validate_marker(row.asDict(), run_id, landing_root) for row in rows]
        # Verify complete-file fingerprints before parsing. Work is distributed;
        # only the small digest strings return to the driver.
        fingerprints = (session.read.format("binaryFile").load(paths)
            .select(F.sha2("content", 256).alias("sha256")).collect())
        if sorted(row.sha256 for row in fingerprints) != sorted(row.sha256 for row in rows):
            raise ValueError("landing file checksum does not match committed batch")
        events = session.read.schema(event_schema()).option("mode", "FAILFAST").json(paths)
        if events.count() != sum(row.row_count for row in rows):
            raise ValueError("landing row count does not match committed batch")
        required = ["schema_version", "run_id", "event_id", "participant_id", "source_kind", "source_timestamp",
                    "event_time", "ingested_at", "signal", "values", "unit", "quality", "source_file", "source_row"]
        invalid = F.lit(False)
        for column in required:
            invalid = invalid | F.col(column).isNull()
        invalid = invalid | (F.col("run_id") != run_id) | ~F.col("schema_version").eqNullSafe("1.0")
        expected = F.when(F.col("signal") == "acc", F.array(F.lit("x"), F.lit("y"), F.lit("z"))).otherwise(F.array(F.lit("value")))
        invalid = invalid | (F.sort_array(F.map_keys("values")) != expected)
        invalid = invalid | F.exists(F.map_values("values"), lambda v: v.isNull() | F.isnan(v) | (F.abs(v) == F.lit(float("inf"))))
        if events.filter(invalid).limit(1).count():
            raise ValueError("malformed Bronze event; refusing batch")
        # Insert only: an existing run/event is immutable audit data.
        source = events.dropDuplicates(["run_id", "event_id"])
        (DeltaTable.forName(session, table).alias("target").merge(source.alias("source"),
            "target.run_id = source.run_id AND target.event_id = source.event_id")
            .whenNotMatchedInsertAll().execute())

    query = (markers.writeStream.foreachBatch(commit)
        .option("checkpointLocation", f"{checkpoint_root.rstrip('/')}/{run_id}/bronze")
        .trigger(availableNow=True).start())
    try:
        if not query.awaitTermination(timeout_seconds):
            raise TimeoutError("Bronze availableNow run exceeded bounded timeout")
    finally:
        if query.isActive:
            query.stop()
    return query
