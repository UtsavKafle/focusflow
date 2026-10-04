"""Local Spark + Delta smoke test for the Data B streaming glue (no Databricks needed).

It builds a local Bronze Delta table from the mock BIG IDEAs data (same Bronze-shaped rows as
databricks/features/bronze_adapter.py), appends it in time chunks, and after EACH chunk runs
silver_stream then gold_stream with the availableNow trigger. That exercises the incremental path (checkpoints,
foreachBatch, MERGE) the way a live replay would. At the end it compares Gold with the expected pandas
output in fixtures/mock_big_ideas/gold.csv, then re-runs everything under a new checkpoint to check that
MERGE is idempotent (row counts must not change).

Needs: Java 17, `pip install -r requirements-spark.txt`, mock data in data/mock/001 (see docs/mock-data.md).
Run from the repo root:
  export SPARK_LOCAL_IP=127.0.0.1
  python scripts/local_spark_smoke.py                      # full 84 h segment, 4 chunks (several minutes)
  python scripts/local_spark_smoke.py --acc-stride 8       # faster: keep every 8th ACC row
Writes only under ./.smoke/ (git-ignored). Uses catalog `spark_catalog`, schema `smoke`.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, MapType, StringType, StructField, StructType, TimestampType

from databricks.features.bronze_adapter import bronze_rows_for_participant
from databricks.streaming import gold_stream, silver_stream
from databricks.streaming.batch import SilverStreamConfig
from databricks.streaming.run_demo import ensure_tables, summarize

CATALOG, SCHEMA = "spark_catalog", "smoke"
BRONZE = f"{CATALOG}.{SCHEMA}.bronze_wearable_events"
BRONZE_SCHEMA = StructType([
    StructField("run_id", StringType(), False), StructField("participant_id", StringType(), False),
    StructField("source_kind", StringType(), False), StructField("event_time", TimestampType(), False),
    StructField("signal", StringType(), False), StructField("values", MapType(StringType(), DoubleType()), False),
    StructField("quality", StringType(), False), StructField("flag_reason", StringType(), True),
])


def local_to_utc(ts: str, tz: str, shift_days: int) -> pd.Timestamp:
    t = pd.Timestamp(ts) + pd.Timedelta(days=shift_days)
    return t.tz_localize(tz).tz_convert("UTC")


def make_spark(work: pathlib.Path) -> SparkSession:
    b = (SparkSession.builder.master("local[4]").appName("focusflow-smoke")
         .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
         .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
         .config("spark.sql.warehouse.dir", str(work / "warehouse"))
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.driver.memory", "4g").config("spark.ui.enabled", "false")
         .config("spark.sql.shuffle.partitions", "4")
         .config("spark.sql.execution.arrow.pyspark.enabled", "false"))
    return configure_spark_with_delta_pip(b).getOrCreate()


def pass_once(spark, run_id, participant, source_kind, checkpoint_root, label, cfg):
    print(f"\n=== {label}: silver ===", flush=True)
    silver_stream.start(spark, catalog=CATALOG, schema=SCHEMA, run_id=run_id, participant_id=participant,
                        source_kind=source_kind, checkpoint_root=checkpoint_root, available_now=True,
                        cfg=cfg).awaitTermination()
    print(f"=== {label}: gold ===", flush=True)
    gold_stream.start(spark, catalog=CATALOG, schema=SCHEMA, run_id=run_id, participant_id=participant,
                      source_kind=source_kind, checkpoint_root=checkpoint_root, available_now=True).awaitTermination()
    s = spark.read.table(f"{CATALOG}.{SCHEMA}.silver_wearable_minute").count()
    g = spark.read.table(f"{CATALOG}.{SCHEMA}.gold_wearable_state").count()
    print(f"[{label}] silver rows={s} gold rows={g}", flush=True)
    return s, g


def compare_to_expected(spark, run_id, participant, expected_csv, acc_stride, lag_minutes):
    got = (spark.read.table(f"{CATALOG}.{SCHEMA}.gold_wearable_state")
           .filter((F.col("run_id") == run_id) & (F.col("participant_id") == participant))
           .orderBy("window_end").toPandas())
    exp = pd.read_csv(expected_csv).sort_values("window_end").reset_index(drop=True)
    print(f"\n=== compare to {expected_csv} ===")
    print(f"rows: got={len(got)} expected={len(exp)}")
    # The streaming path's finalization lag means the FINAL `lag_minutes` or so windows of this FINITE
    # replay can never gather enough "future" data to be legitimately finalized (no chunk ever arrives after
    # the segment ends to confirm them) -- this is correct streaming behavior, not a bug. The pandas
    # baseline (run_local.py) has no such lag (it processes the whole file in one shot), so it has no
    # trailing gap. Comparing the overlapping prefix both runs produced is the honest comparison; anything
    # beyond a `lag_minutes`-ish shortfall would be a real bug.
    tail_short = len(exp) - len(got)
    if tail_short == 0:
        ok = True
    elif 0 < tail_short <= lag_minutes + 1:
        print(f"  {tail_short} fewer rows than expected -- within the {lag_minutes}-minute finalization lag's "
             f"unavoidable tail on a finite replay; comparing the {min(len(got), len(exp))} rows both have.")
        ok = True
    else:
        print(f"  UNEXPECTED row count difference ({tail_short}), beyond the finalization-lag tail -- real bug.")
        ok = False
    n = min(len(got), len(exp))
    got, exp = got.iloc[:n], exp.iloc[:n]
    # --acc-stride subsamples the raw ACC signal itself (not just its labeled rate), so ACC-derived fields
    # are only STATISTICALLY similar to the full-density fixture, never bit-exact; skip them under stride and
    # rely on the full (--acc-stride 1) run to validate those. HR/EDA-derived fields are untouched by the
    # stride and must still match exactly.
    skip_cols = {"activity_level", "estimated_rest_minutes", "recovery_score"} if acc_stride > 1 else set()
    for col in ["heart_rate_bpm", "physiological_load", "activity_level", "estimated_rest_minutes", "recovery_score"]:
        if col in skip_cols:
            print(f"  {col}: SKIP (--acc-stride {acc_stride} subsamples ACC; not expected to match bit-for-bit)")
            continue
        a = pd.to_numeric(got[col], errors="coerce").to_numpy() if col in got else None
        b = pd.to_numeric(exp[col], errors="coerce").to_numpy()
        if a is None or len(a) != len(b):
            print(f"  {col}: SKIP (missing or length mismatch)"); ok = False; continue
        both_nan = np.isnan(a) & np.isnan(b)
        close = np.isclose(a, b, atol=1e-3, equal_nan=False) | both_nan
        bad = int((~close).sum())
        print(f"  {col}: mismatches={bad}/{len(a)}")
        ok &= bad == 0
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "mock"))
    ap.add_argument("--participant", default="001")
    ap.add_argument("--run-id", default="smoke-001")
    ap.add_argument("--source-kind", default="synthetic_fixture")
    ap.add_argument("--shift-days", type=int, default=2430)
    ap.add_argument("--tz-assume", default="America/New_York")
    ap.add_argument("--history-start", default="2020-02-13 12:00:00")
    ap.add_argument("--segment-end", default="2020-02-17 00:00:00")
    ap.add_argument("--chunks", type=int, default=4)
    ap.add_argument("--acc-hz", type=float, default=8.0, help="actual ACC rate the mock data was generated at")
    ap.add_argument("--acc-stride", type=int, default=1, help="keep every Nth ACC row (speed); changes ACC coverage")
    ap.add_argument("--expected", default=str(ROOT / "fixtures" / "mock_big_ideas" / "gold.csv"))
    ap.add_argument("--keep", action="store_true", help="keep ./.smoke from a previous run instead of wiping it")
    a = ap.parse_args()

    work = ROOT / ".smoke"
    if work.exists() and not a.keep:
        shutil.rmtree(work)
    work.mkdir(exist_ok=True)
    ckpt = str(work / "checkpoints")

    print("loading mock data into Bronze-shaped rows ...", flush=True)
    rows = bronze_rows_for_participant(pathlib.Path(a.raw), a.participant, tz_assume=a.tz_assume, run_id=a.run_id,
                                       source_kind=a.source_kind, shift_days=a.shift_days)
    st = local_to_utc(a.history_start, a.tz_assume, a.shift_days)
    en = local_to_utc(a.segment_end, a.tz_assume, a.shift_days)
    rows = rows[(rows["event_time"] >= st) & (rows["event_time"] < en)]
    if a.acc_stride > 1:
        acc = rows["signal"] == "acc"
        keep = ~acc | (rows.groupby("signal").cumcount() % a.acc_stride == 0)
        rows = rows[keep]
    rows = rows.sort_values("event_time", kind="stable").reset_index(drop=True)
    # Keep event_time tz-AWARE (UTC) all the way to createDataFrame below. A NAIVE python datetime fed into
    # createDataFrame's TimestampType, with Arrow disabled, is silently interpreted using the driver's
    # LOCAL SYSTEM timezone rather than spark.sql.session.timeZone -- verified directly: a naive
    # 2026-10-09T16:00:00 round-trips as 20:00:00 UTC on this machine (EDT, UTC-4). An aware datetime
    # (tzinfo=UTC) round-trips correctly regardless of the driver's local timezone.
    rows["event_time"] = rows["event_time"].dt.tz_convert("UTC")
    print(f"bronze rows: {len(rows):,} ({rows['signal'].value_counts().to_dict()}) window [{st}, {en})", flush=True)

    # The mock is generated at --acc-hz (8, not the real dataset's 32), and --acc-stride further thins it;
    # minute_features' default expected_hz (32) would otherwise read every mock minute as having ~1/4 (or,
    # under stride, far less) of the ACC coverage it actually has -- wrongly tanking activity_level/rest
    # availability regardless of stride, not just when striding.
    effective_acc_hz = a.acc_hz / a.acc_stride
    cfg = SilverStreamConfig(expected_hz={"hr": 1.0, "eda": 4.0, "acc": effective_acc_hz})
    print(f"expected_hz: hr=1.0 eda=4.0 acc={effective_acc_hz} (acc-hz {a.acc_hz} / acc-stride {a.acc_stride})", flush=True)

    spark = make_spark(work)
    spark.sparkContext.setLogLevel("ERROR")
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {SCHEMA}")
    spark.sql(f"DROP TABLE IF EXISTS {BRONZE}")
    spark.createDataFrame([], BRONZE_SCHEMA).write.format("delta").saveAsTable(BRONZE)
    ensure_tables(spark, catalog=CATALOG, schema=SCHEMA)

    bounds = np.linspace(0, len(rows), a.chunks + 1).astype(int)
    for i in range(a.chunks):
        chunk = rows.iloc[bounds[i]:bounds[i + 1]]
        if chunk.empty:
            continue
        recs = list(zip(chunk["run_id"], chunk["participant_id"], chunk["source_kind"],
                        chunk["event_time"].dt.to_pydatetime(), chunk["signal"], chunk["values"],
                        chunk["quality"], chunk["flag_reason"].where(chunk["flag_reason"].notna(), None)))
        spark.createDataFrame(recs, BRONZE_SCHEMA).write.format("delta").mode("append").saveAsTable(BRONZE)
        print(f"\n--- appended chunk {i + 1}/{a.chunks}: {len(chunk):,} rows, up to {chunk['event_time'].max()} UTC ---", flush=True)
        pass_once(spark, a.run_id, a.participant, a.source_kind, ckpt, f"chunk {i + 1}", cfg)

    summarize(spark, catalog=CATALOG, schema=SCHEMA, run_id=a.run_id, participant_id=a.participant)
    ok = compare_to_expected(spark, a.run_id, a.participant, a.expected, a.acc_stride, cfg.lag_minutes)

    print("\n=== idempotency: rerun with a fresh checkpoint (same Bronze, MERGE keys already present) ===")
    s0 = spark.read.table(f"{CATALOG}.{SCHEMA}.silver_wearable_minute").count()
    g0 = spark.read.table(f"{CATALOG}.{SCHEMA}.gold_wearable_state").count()
    s1, g1 = pass_once(spark, a.run_id, a.participant, a.source_kind, str(work / "checkpoints_rerun"), "rerun", cfg)
    idem = (s0, g0) == (s1, g1)
    print(f"idempotent: {idem} (silver {s0}->{s1}, gold {g0}->{g1})")

    print("\nRESULT:", "PASS" if ok and idem else "CHECK OUTPUT ABOVE")
    return 0 if ok and idem else 1


if __name__ == "__main__":
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    raise SystemExit(main())
