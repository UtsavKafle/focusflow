"""Canonical Bronze schema for `focusflow.main.bronze_wearable_events` -- source of truth:
databricks/sql/ddl_bronze.sql and databricks/ingestion/DATA_B_HANDOFF.md (Data A's verified run). No
pyspark import: usable standalone from `databricks.streaming.batch` and the test suite, and from the Spark
glue (`silver_stream.py`) without adding a dependency.

There is NO `flag_reason`/`quality_reason` column on the real table -- that string lives only in Data A's
local ingestion adapter, never written to Bronze. `quality` is the sole status field; ACC usability is
decided from `unit` instead (see `databricks.features.quality_policy`).
"""
from __future__ import annotations

import pandas as pd

BRONZE_COLUMNS = [
    "schema_version", "run_id", "event_id", "participant_id", "source_kind",
    "source_timestamp", "event_time", "ingested_at", "signal", "values",
    "unit", "quality", "source_file", "source_row",
]

ALLOWED_SOURCE_KIND = {"recorded_replay", "synthetic_fixture", "synthetic_injection"}
ALLOWED_SIGNAL = {"hr", "eda", "acc", "ibi", "temp"}
ALLOWED_QUALITY = {"valid", "flagged", "dropped"}


def validate_bronze_columns(df: pd.DataFrame, *, context: str = "Bronze rows") -> None:
    """Fail closed: raise a clear `ValueError` if any of the 14 required Bronze columns is missing. Does
    NOT validate row-level values (that's `validate_bronze_values`) -- a schema check must not depend on
    the batch actually containing, say, a `dropped` row to pass."""
    missing = [c for c in BRONZE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{context}: missing required Bronze column(s) {missing}. Expected all of {BRONZE_COLUMNS} "
            f"(databricks/sql/ddl_bronze.sql). Got: {list(df.columns)}"
        )


def validate_bronze_values(df: pd.DataFrame, *, context: str = "Bronze rows") -> None:
    """Fail closed on out-of-contract VALUES in `source_kind`/`signal`/`quality` (the DDL's CHECK
    constraints). Calls `validate_bronze_columns` first, since checking values in a missing column would
    raise a confusing KeyError instead."""
    validate_bronze_columns(df, context=context)
    checks = [("source_kind", ALLOWED_SOURCE_KIND), ("signal", ALLOWED_SIGNAL), ("quality", ALLOWED_QUALITY)]
    for col, allowed in checks:
        bad = set(df[col].dropna().unique()) - allowed
        if bad:
            raise ValueError(f"{context}: column '{col}' has value(s) outside {allowed}: {sorted(bad)}")
