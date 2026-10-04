"""Thin Delta MERGE helper shared by the streaming wrappers. Requires a Databricks/Delta-enabled Spark
session -- not imported by the test suite (see `databricks.streaming.batch` for the unit-tested logic).

Uses plain SQL `MERGE INTO` via a temp view rather than the `delta.tables.DeltaTable` Python API.
`DeltaTable.forName` turned out not to accept a 3-part `catalog.schema.table` name against a local
`spark_catalog`-backed Delta table (`ParseException` at the second dot -- it resolves names through
Spark's legacy 2-part `TableIdentifier`, not full multipart catalog resolution), even though `spark.sql`/
`spark.read.table` handle the exact same 3-part name fine. Plain SQL sidesteps that entirely and is the same
syntax Unity Catalog expects, so this one code path covers both `spark_catalog.smoke.*` (this file's local
smoke test) and `focusflow.main.*` (Databricks) without a special case."""
from __future__ import annotations

import uuid

import pandas as pd

try:
    from pyspark.sql.types import IntegerType, TimestampType
except ImportError as exc:  # pragma: no cover - requires a Databricks runtime
    raise ImportError("databricks.streaming.merge requires pyspark (run on a Databricks cluster)") from exc

from databricks.streaming.batch import safe_object_map


def to_spark_df(spark, pdf: pd.DataFrame, schema):
    """pandas -> Spark DataFrame for a MERGE payload, using an EXPLICIT schema. Four real bugs this avoids:
    1. Without an explicit schema, `createDataFrame` infers types by sampling values; a column that is all
       `None` in this batch (e.g. the baseline columns on a fresh Silver feature row, before the baseline
       pass has run) makes inference fail outright (`CANNOT_DETERMINE_TYPE`).
    2. `DataFrame.where(pd.notnull(df), None)` below turns pandas NaN/NaT into real Python `None` before
       conversion. Without it, a `DoubleType` column receives Spark's floating-point NaN, which is a VALUE
       distinct from SQL NULL (survives `IS NOT NULL`, compares weirdly) -- not the "no data" NULL every
       other part of this pipeline (and the `Quality.missing_reasons` contract) relies on.
    3. With an explicit schema and Arrow disabled, Spark's row conversion checks `type(obj) is
       datetime.datetime` for `TimestampType` columns -- `pandas.Timestamp`, though a `datetime.datetime`
       subclass, fails that exact-type check (`CANNOT_ACCEPT_OBJECT_IN_TYPE`). `.to_pydatetime()` converts
       each Timestamp cell to a plain (and, since these are tz-aware UTC, still correctly-instanted) Python
       datetime first.
    4. A nullable integer column (e.g. `estimated_rest_minutes`) is `float64` in pandas because of the NaNs
       (there's no native nullable int dtype pandas uses by default here), so a present value arrives as
       Python `float` (`297.0`), which `IntegerType` rejects (`CANNOT_ACCEPT_OBJECT_IN_TYPE`). Cast those
       cells to `int` explicitly, via `batch.safe_object_map` and NOT `Series.map`/`.apply` (see its
       docstring: pandas would otherwise re-infer the result dtype and silently undo step 2's NaN->None fix).
    Columns are selected and reordered to match `schema` by name, so the caller doesn't need to match
    `batch.py`'s internal column order."""
    cols = [f.name for f in schema.fields]
    safe = pdf[cols].astype(object).where(pd.notnull(pdf[cols]), None)
    for field in schema.fields:
        if isinstance(field.dataType, TimestampType):
            safe[field.name] = safe_object_map(safe[field.name], lambda v: v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)
        elif isinstance(field.dataType, IntegerType):
            safe[field.name] = safe_object_map(safe[field.name], lambda v: int(v) if v is not None else v)
    return spark.createDataFrame(safe, schema=schema)


def merge_into(spark, updates, table: str, keys: list[str]) -> None:
    """Upsert `updates` (a Spark DataFrame) into `table` matched on `keys`. Idempotent: re-running the same
    batch (e.g. after a Structured Streaming retry) overwrites the same rows instead of duplicating them."""
    if updates is None or updates.isEmpty():
        return
    view = f"_merge_updates_{uuid.uuid4().hex}"
    updates.createOrReplaceTempView(view)
    cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    spark.sql(f"MERGE INTO {table} AS t USING {view} AS s ON {cond} "
             f"WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")
    spark.catalog.dropTempView(view)


def merge_update_only(spark, updates, table: str, keys: list[str], set_columns: list[str]) -> None:
    """Like `merge_into`, but only ever UPDATEs the given columns on existing rows (never inserts). Used for
    the baseline backfill pass, which must not create new Silver rows -- only fill in z-scores on rows the
    feature pass already wrote."""
    if updates is None or updates.isEmpty():
        return
    view = f"_merge_updates_{uuid.uuid4().hex}"
    updates.createOrReplaceTempView(view)
    cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    set_clause = ", ".join(f"t.{c} = s.{c}" for c in set_columns)
    spark.sql(f"MERGE INTO {table} AS t USING {view} AS s ON {cond} WHEN MATCHED THEN UPDATE SET {set_clause}")
    spark.catalog.dropTempView(view)
