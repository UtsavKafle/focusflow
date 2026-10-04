"""Bronze-shaped rows (NormalizedEvent fields plus `flag_reason`) -> the hr/eda/acc frames `minute_features`
expects, after applying `quality_policy`.

Also builds Bronze-shaped rows directly from the raw BIG IDEAs / mock CSVs, so Data B can exercise the
quality policy end to end before Data A's real adapter and Bronze table are available -- point `raw_dir` at
the real per-participant folder later with no code change.

The exact `flag_reason` strings below are DATA B'S OWN, inferred from the published mock quality counts
(see docs/decisions.md): they are a stand-in pending confirmation from Data A's adapter / column names in
docs/data-provenance.md. Only `hr_above_engineering_range` is confirmed verbatim by Data A.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

from databricks.features.quality_policy import (
    ACC_UNVERIFIED_UNITS_REASON, EDA_PLAUSIBLE, HR_PLAUSIBLE, QualityPolicy, filter_acc, filter_hr_eda,
)

HR_NONFINITE_REASON = "nonfinite"
HR_ZERO_REASON = "hr_zero_reading"
HR_ABOVE_RANGE_REASON = "hr_above_engineering_range"
HR_DUPLICATE_REASON = "duplicate_timestamp"
EDA_NEGATIVE_REASON = "eda_negative"


def _flagger(n: int):
    quality = pd.Series("valid", index=range(n), dtype=object)
    reason = pd.Series(None, index=range(n), dtype=object)

    def flag(mask: np.ndarray, q: str, r: str) -> None:
        apply = mask & reason.isna().to_numpy()
        quality[apply] = q
        reason[apply] = r

    return quality, reason, flag


def _localize_utc(ts: pd.Series, tz_assume: str, shift_days: int) -> pd.Series:
    """Naive local wall-clock timestamps -> UTC. `shift_days` is added to LOCAL wall time BEFORE localizing,
    so the time of day is preserved across the DST boundary (never add a fixed UTC offset)."""
    t = pd.to_datetime(ts, errors="coerce")
    if shift_days:
        t = t + pd.Timedelta(days=shift_days)
    t = t.dt.tz_localize(tz_assume) if t.dt.tz is None else t.dt.tz_convert(tz_assume)
    return t.dt.tz_convert("UTC")


def hr_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0) -> pd.DataFrame:
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    value = pd.to_numeric(df["Value"], errors="coerce")
    quality, reason, flag = _flagger(len(df))

    flag(~np.isfinite(value.to_numpy()), "dropped", HR_NONFINITE_REASON)
    flag((value == 0).to_numpy(), "flagged", HR_ZERO_REASON)
    flag((value > HR_PLAUSIBLE[1]).to_numpy(), "flagged", HR_ABOVE_RANGE_REASON)
    flag(event_time.duplicated(keep=False).to_numpy(), "flagged", HR_DUPLICATE_REASON)

    return pd.DataFrame({"event_time": event_time, "signal": "hr", "values": value.fillna(0.0).map(lambda v: {"value": float(v)}),
                         "quality": quality.to_numpy(), "flag_reason": reason.to_numpy()})


def eda_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0) -> pd.DataFrame:
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    value = pd.to_numeric(df["Value"], errors="coerce")
    quality, reason, flag = _flagger(len(df))

    flag(~np.isfinite(value.to_numpy()), "dropped", HR_NONFINITE_REASON)
    flag((value < 0).to_numpy(), "flagged", EDA_NEGATIVE_REASON)

    return pd.DataFrame({"event_time": event_time, "signal": "eda", "values": value.fillna(0.0).map(lambda v: {"value": float(v)}),
                         "quality": quality.to_numpy(), "flag_reason": reason.to_numpy()})


def acc_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0) -> pd.DataFrame:
    """Every row is flagged `acc_units_unverified` (not malformed) -- the 1/64 g scale assumption applies to
    the whole stream, not individual samples."""
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    x, y, z = (pd.to_numeric(df[c], errors="coerce") for c in ("X", "Y", "Z"))
    values = [{"x": float(a), "y": float(b), "z": float(c)} for a, b, c in zip(x.fillna(0.0), y.fillna(0.0), z.fillna(0.0))]
    quality = np.where(np.isfinite(x) & np.isfinite(y) & np.isfinite(z), "flagged", "dropped")
    reason = np.where(quality == "flagged", ACC_UNVERIFIED_UNITS_REASON, HR_NONFINITE_REASON)
    return pd.DataFrame({"event_time": event_time, "signal": "acc", "values": values, "quality": quality, "flag_reason": reason})


def bronze_rows_for_participant(raw_dir: pathlib.Path, participant_id: str, *, tz_assume: str, run_id: str,
                                source_kind: str = "recorded_replay", shift_days: int = 0) -> pd.DataFrame:
    """HR_<id>.csv, EDA_<id>.csv, ACC_<id>.csv under `raw_dir`/`participant_id` -> one combined Bronze-shaped
    frame (columns: run_id, participant_id, source_kind, event_time, signal, values, quality, flag_reason),
    sorted by event_time."""
    d = pathlib.Path(raw_dir) / participant_id
    parts = [hr_rows_from_raw(d / f"HR_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days),
             eda_rows_from_raw(d / f"EDA_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days),
             acc_rows_from_raw(d / f"ACC_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days)]
    rows = pd.concat(parts, ignore_index=True).sort_values("event_time", kind="stable").reset_index(drop=True)
    rows.insert(0, "run_id", run_id)
    rows.insert(1, "participant_id", participant_id)
    rows["source_kind"] = source_kind
    return rows


def bronze_to_minute_frames(bronze_rows: pd.DataFrame, policy: QualityPolicy) -> dict[str, pd.DataFrame]:
    """Bronze-shaped rows (any source: raw-CSV adapter above, or a real Bronze table read) -> the hr/eda/acc
    frames `minute_features` expects, after applying `quality_policy`."""
    empty = {"hr": pd.DataFrame(columns=["event_time", "value"]), "eda": pd.DataFrame(columns=["event_time", "value"]),
             "acc": pd.DataFrame(columns=["event_time", "x", "y", "z"])}
    if bronze_rows is None or bronze_rows.empty:
        return empty

    def extract(rows: pd.DataFrame, keys: list[str], empty_key: str) -> pd.DataFrame:
        if rows.empty:
            return empty[empty_key]
        vals = pd.DataFrame(list(rows["values"]), index=rows.index)
        return pd.concat([rows[["event_time"]], vals[keys]], axis=1).reset_index(drop=True)

    hr = filter_hr_eda(bronze_rows[bronze_rows["signal"] == "hr"], plausible=HR_PLAUSIBLE)
    eda = filter_hr_eda(bronze_rows[bronze_rows["signal"] == "eda"], plausible=EDA_PLAUSIBLE)
    acc = filter_acc(bronze_rows[bronze_rows["signal"] == "acc"], policy=policy)
    return {"hr": extract(hr, ["value"], "hr"), "eda": extract(eda, ["value"], "eda"), "acc": extract(acc, ["x", "y", "z"], "acc")}
