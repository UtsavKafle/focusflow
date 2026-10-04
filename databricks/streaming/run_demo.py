"""Notebook-friendly Databricks job: create the Silver/Gold tables if missing, run the Silver then Gold
streams for one run to catch up, then print a verification summary. Paste into a Databricks notebook cell,
or run as a Job/Task:
  python databricks/streaming/run_demo.py --run-id mock-demo-002 --participant 001
Needs a Databricks runtime (pyspark + delta-spark); NOT imported or run by the test suite. See
`databricks.streaming.batch` for the Spark-free, unit-tested core this calls under the hood, and
`tests/test_streaming_idempotency.py` for a Spark-free idempotency check of the same batch functions.
See docs/databricks-runbook.md for how to actually run this.

Trigger mode defaults to availableNow: each of `silver_stream.start`/`gold_stream.start` processes every
batch currently available then stops on its own (Spark's availableNow trigger already loops internally
until caught up) -- pass --continuous for an always-on stream instead, for a live Databricks replay.

Checkpoints: /Volumes/<catalog>/<schema>/checkpoints/<run_id>/{silver,gold}. To start a run over, pass a
NEW --run-id -- checkpoints and MERGE keys are both keyed by run_id, so nothing needs to be deleted.
"""
from __future__ import annotations

import argparse
import os
import pathlib

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
except ImportError as exc:  # pragma: no cover - requires a Databricks runtime
    raise ImportError("databricks.streaming.run_demo requires pyspark (run on a Databricks cluster)") from exc

from databricks.streaming import gold_stream, silver_stream

SQL_DIR = pathlib.Path(__file__).resolve().parents[1] / "sql"


def _strip_line_comments(sql_text: str) -> str:
    """Drop whole-line `-- ...` comments before splitting on `;` -- a comment can itself contain a semicolon
    (e.g. ddl_gold.sql's header), which would otherwise split the DDL mid-comment and leave a dangling
    statement with nothing but prose after it."""
    return "\n".join(line for line in sql_text.splitlines() if not line.strip().startswith("--"))


def ensure_tables(spark: SparkSession, *, catalog: str, schema: str) -> None:
    """Create silver_wearable_minute / gold_wearable_state from the checked-in DDL if they don't exist yet.
    Bronze is Data A's table and is NOT created here -- this job assumes it already exists and has rows for
    the run."""
    for name in ("ddl_silver.sql", "ddl_gold.sql"):
        ddl = (SQL_DIR / name).read_text().replace("focusflow.main", f"{catalog}.{schema}")
        for stmt in _strip_line_comments(ddl).split(";"):
            if stmt.strip():
                spark.sql(stmt)


def summarize(spark: SparkSession, *, catalog: str, schema: str, run_id: str, participant_id: str) -> None:
    gold_table = f"{catalog}.{schema}.gold_wearable_state"
    silver_table = f"{catalog}.{schema}.silver_wearable_minute"
    g = spark.read.table(gold_table).filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))
    s = spark.read.table(silver_table).filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant_id))

    print(f"-- run {run_id} / participant {participant_id} --")
    print("silver rows:", s.count(), "gold rows:", g.count())
    # .toPandas(), not .collect(): see batch.localize_utc_scalar's docstring -- .collect() was observed to
    # mis-apply the driver's local system timezone to TimestampType values against local Spark.
    bounds = g.agg(F.min("window_end").alias("lo"), F.max("window_end").alias("hi")).toPandas().iloc[0]
    print("gold window_end range:", bounds["lo"], "to", bounds["hi"])

    status_counts = (g.select(F.get_json_object("quality_json", "$.status").alias("status"))
                       .groupBy("status").count().collect())
    print("quality status counts:", {r["status"]: r["count"] for r in status_counts})

    null_reasons = (g.select(F.get_json_object("quality_json", "$.missing_reasons.physiological_load").alias("r"))
                      .filter(F.col("r").isNotNull()).groupBy("r").count().collect())
    print("physiological_load null reasons:", {r["r"]: r["count"] for r in null_reasons})

    nights = (g.filter(F.col("estimated_rest_minutes").isNotNull())
                .select(F.element_at(F.filter("evidence_ids", lambda x: x.startswith("rest-")), 1).alias("night_id"),
                        "estimated_rest_minutes")
                .groupBy("night_id").agg(F.min("estimated_rest_minutes").alias("estimated_rest_minutes"))
                .orderBy("night_id").collect())
    print("rest by night:", [(r["night_id"], r["estimated_rest_minutes"]) for r in nights])

    kinds = [r["source_kind"] for r in g.select("source_kind").distinct().collect()]
    print("source_kind(s) present:", kinds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="mock-demo-002")
    ap.add_argument("--participant", default="001")
    ap.add_argument("--catalog", default=os.environ.get("DATABRICKS_CATALOG", "focusflow"))
    ap.add_argument("--schema", default=os.environ.get("DATABRICKS_SCHEMA", "main"))
    ap.add_argument("--source-kind", default="synthetic_fixture",
                    choices=["recorded_replay", "synthetic_fixture", "synthetic_injection"])
    ap.add_argument("--checkpoint-root", default=None, help="default /Volumes/<catalog>/<schema>/checkpoints")
    ap.add_argument("--continuous", action="store_true", help="run an always-on stream instead of one availableNow catch-up pass")
    a = ap.parse_args()
    checkpoint_root = a.checkpoint_root or f"/Volumes/{a.catalog}/{a.schema}/checkpoints"
    available_now = not a.continuous

    spark = SparkSession.builder.getOrCreate()
    ensure_tables(spark, catalog=a.catalog, schema=a.schema)

    print(f"-- silver_stream: run_id={a.run_id} participant={a.participant} available_now={available_now} --")
    silver_q = silver_stream.start(spark, catalog=a.catalog, schema=a.schema, run_id=a.run_id,
                                   participant_id=a.participant, source_kind=a.source_kind,
                                   checkpoint_root=checkpoint_root, available_now=available_now)
    silver_q.awaitTermination()

    print(f"-- gold_stream: run_id={a.run_id} participant={a.participant} available_now={available_now} --")
    gold_q = gold_stream.start(spark, catalog=a.catalog, schema=a.schema, run_id=a.run_id,
                               participant_id=a.participant, source_kind=a.source_kind,
                               checkpoint_root=checkpoint_root, available_now=available_now)
    gold_q.awaitTermination()

    summarize(spark, catalog=a.catalog, schema=a.schema, run_id=a.run_id, participant_id=a.participant)


if __name__ == "__main__":
    main()
