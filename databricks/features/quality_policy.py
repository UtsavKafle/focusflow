"""Explicit, config-driven policy for turning Bronze-shaped rows into `minute_features` input.
Bronze schema (source of truth: databricks/sql/ddl_bronze.sql, databricks/ingestion/DATA_B_HANDOFF.md):
14 columns, `quality` in {valid, flagged, dropped}, NO `flag_reason`/`quality_reason` column (that is the
real ingestion adapter's own LOCAL debug column, never written to Bronze). ACC usability is therefore
decided from `unit`, not a reason string.

HR and EDA: only `quality == "valid"` rows are used; flagged and dropped rows are excluded. We also re-apply
our own plausibility range (defense in depth) even though it agrees with Data A's stated 220 bpm HR rule.
Excluded rows lower coverage; they are never counted as zeros.

ACC: the 1/64 g unit scale is UNVERIFIED for the real dataset, so ACC usability is controlled by
`AccScaleAssumption` rather than treated as always-on:
  - "mock_assume_1_64g" (default for `synthetic_fixture` runs): the mock IS built at that scale by
    construction, so rows with `unit == "unverified"` (quality `valid` or `flagged`, not `dropped`) and
    finite x/y/z are used anyway. Never silently exclude every ACC row under this policy -- that would
    disable all ACC features for the mock, which is built to behave.
  - "exclude_until_verified" (default for `recorded_replay` runs): rows with `unit == "unverified"` are
    excluded (today, that is ALL real ACC rows too). The caller (see `databricks.features.bronze_adapter`,
    `databricks.features.run_local`) must null the ACC-derived Gold fields with an explicit reason
    (`ACC_UNVERIFIED_UNITS_REASON`, a Gold-side `missing_reasons` string -- unrelated to Bronze's `unit`
    column) rather than silently trusting the scale or reporting the generic "no sensor data" reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

AccScaleAssumption = Literal["mock_assume_1_64g", "exclude_until_verified"]

ACC_UNVERIFIED_UNIT = "unverified"          # Bronze `unit` column's sentinel value for unverified-scale ACC
ACC_UNVERIFIED_UNITS_REASON = "acc_units_unverified"   # Gold-side missing_reasons string (see state.py)

HR_PLAUSIBLE = (30.0, 220.0)   # bpm; agrees with Data A's stated engineering upper bound
EDA_PLAUSIBLE = (0.0, 100.0)   # microsiemens


@dataclass(frozen=True)
class QualityPolicy:
    acc_scale_assumption: AccScaleAssumption = "exclude_until_verified"

    @classmethod
    def for_source_kind(cls, source_kind: str) -> "QualityPolicy":
        return cls(acc_scale_assumption="mock_assume_1_64g" if source_kind == "synthetic_fixture" else "exclude_until_verified")


def acc_is_usable(policy: QualityPolicy) -> bool:
    return policy.acc_scale_assumption == "mock_assume_1_64g"


def filter_hr_eda(rows: pd.DataFrame, *, plausible: tuple[float, float]) -> pd.DataFrame:
    """Bronze-shaped rows (columns: quality, values={'value': ...}) for one signal -> valid, in-range rows.
    Flagged and dropped rows are excluded outright; valid rows outside the plausible range are excluded too
    (never coerced to the range boundary, never treated as zero -- just absent, so coverage reflects it)."""
    if rows.empty:
        return rows
    v = rows[rows["quality"] == "valid"]
    if v.empty:
        return v
    val = v["values"].map(lambda d: d.get("value"))
    return v[pd.to_numeric(val, errors="coerce").between(*plausible)]


def filter_acc(rows: pd.DataFrame, *, policy: QualityPolicy) -> pd.DataFrame:
    """Bronze-shaped ACC rows (columns: quality, unit, values={'x','y','z'}) -> rows usable under `policy`.
    `dropped` rows are never used under either policy. Finite x/y/z is checked as defense in depth even
    though `unit == "unverified"` rows are expected to be malformed only in units, not values."""
    if rows.empty:
        return rows
    not_dropped = rows[rows["quality"] != "dropped"]
    if not_dropped.empty:
        return not_dropped
    unverified = not_dropped["unit"] == ACC_UNVERIFIED_UNIT
    usable = not_dropped[unverified] if acc_is_usable(policy) else not_dropped[~unverified]
    if usable.empty:
        return usable
    xyz = usable["values"].map(lambda d: (d.get("x"), d.get("y"), d.get("z")))
    finite = xyz.map(lambda t: all(v is not None and np.isfinite(v) for v in t))
    return usable[finite]
