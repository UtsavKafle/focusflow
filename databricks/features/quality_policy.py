"""Explicit, config-driven policy for turning Bronze-shaped rows into `minute_features` input.
HR and EDA: only `quality == "valid"` rows are used; flagged and dropped rows are excluded. We also re-apply
our own plausibility range (defense in depth) even though it agrees with Data A's stated 220 bpm HR rule.
Excluded rows lower coverage; they are never counted as zeros.

ACC: the 1/64 g unit scale is UNVERIFIED for the real dataset (see docs/data-provenance.md), so ACC
usability is controlled by `AccScaleAssumption` rather than treated as always-on:
  - "mock_assume_1_64g" (default for `synthetic_fixture` runs): the mock IS built at that scale by
    construction, so rows flagged ONLY for unverified units are used anyway. Rows flagged for any other
    reason are still excluded. Never silently exclude every flagged ACC row under this policy -- that would
    disable all ACC features for the mock, which is built to behave.
  - "exclude_until_verified" (default for `recorded_replay` runs): ALL ACC rows are excluded. The caller
    (see `databricks.features.bronze_adapter`, `databricks.features.run_local`) must null the ACC-derived
    Gold fields with an explicit reason (`ACC_UNVERIFIED_UNITS_REASON`) rather than silently trusting the
    scale or reporting the generic "no sensor data" reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

AccScaleAssumption = Literal["mock_assume_1_64g", "exclude_until_verified"]

ACC_UNVERIFIED_UNITS_REASON = "acc_units_unverified"

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
    """Bronze-shaped ACC rows -> rows usable under `policy`. Under "mock_assume_1_64g", a row flagged for any
    reason OTHER than unverified units is still excluded (it may be malformed, not just unit-ambiguous)."""
    if rows.empty or not acc_is_usable(policy):
        return rows.iloc[0:0]
    valid = rows["quality"] == "valid"
    flagged_units_only = (rows["quality"] == "flagged") & (rows["flag_reason"] == ACC_UNVERIFIED_UNITS_REASON)
    return rows[valid | flagged_units_only]
