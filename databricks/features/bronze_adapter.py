"""Bronze-shaped rows (the real 14-column contract -- see `databricks.streaming.bronze_contract` and
databricks/sql/ddl_bronze.sql) -> the hr/eda/acc frames `minute_features` expects, after applying
`quality_policy`. There is NO `flag_reason`/`quality_reason` column: `quality` is the only status field,
and ACC usability is decided from `unit` (see quality_policy.py's docstring).

Also builds Bronze-shaped rows directly from the raw BIG IDEAs / mock CSVs, so Data B can exercise the
quality policy end to end without a live Bronze table -- point `raw_dir` at the real per-participant folder
later with no code change. `event_id`/`source_file`/`source_row` are filled for contract completeness, not
because downstream feature code reads them.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

from databricks.features.quality_policy import (
    ACC_UNVERIFIED_UNIT, EDA_PLAUSIBLE, HR_PLAUSIBLE, QualityPolicy, filter_acc, filter_hr_eda,
)

HR_UNIT, EDA_UNIT, ACC_UNIT_VERIFIED = "bpm", "microsiemens", "g"


def _flagger(n: int) -> pd.Series:
    return pd.Series("valid", index=range(n), dtype=object)


def _apply_flag(quality: pd.Series, mask: np.ndarray, q: str) -> None:
    """First flag wins (checked in priority order by the caller); leaves already-flagged/dropped rows alone."""
    apply = mask & (quality.to_numpy() == "valid")
    quality[apply] = q


def _localize_utc(ts: pd.Series, tz_assume: str, shift_days: int) -> pd.Series:
    """Naive local wall-clock timestamps -> UTC. `shift_days` is added to LOCAL wall time BEFORE localizing,
    so the time of day is preserved across the DST boundary (never add a fixed UTC offset)."""
    t = pd.to_datetime(ts, errors="coerce")
    if shift_days:
        t = t + pd.Timedelta(days=shift_days)
    t = t.dt.tz_localize(tz_assume) if t.dt.tz is None else t.dt.tz_convert(tz_assume)
    return t.dt.tz_convert("UTC")


def _contract_columns(df: pd.DataFrame, *, signal: str, participant_id: str, source_file: str,
                      event_time: pd.Series, values: pd.Series, quality: pd.Series, unit: str,
                      ingested_at: pd.Timestamp) -> pd.DataFrame:
    """Builds the 14-column contract shape, then OMITS nonfinite (`quality="dropped"`) rows entirely --
    matching Data A's verified Bronze exactly: nonfinite readings are omitted before publication, never
    written with `quality="dropped"` (see databricks/ingestion/DATA_B_HANDOFF.md: HR is 298,502 rows, not
    298,505 -- the 3 nonfinite readings are missing outright, not present-but-flagged). `source_row` is the
    1-based row number in the ORIGINAL source file (kept even for surviving rows, so it still means
    "position in the raw CSV", not "position in the published output")."""
    n = len(df)
    event_id = [f"{participant_id}-{signal}-{i:09d}" for i in range(n)]
    out = pd.DataFrame({
        "schema_version": "1.0", "event_id": event_id, "source_timestamp": event_time, "event_time": event_time,
        "ingested_at": ingested_at, "signal": signal, "values": values, "unit": unit,
        "quality": quality.to_numpy(), "source_file": source_file, "source_row": np.arange(1, n + 1),
    })
    return out[out["quality"] != "dropped"].reset_index(drop=True)


def hr_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0,
                     participant_id: str = "", ingested_at: pd.Timestamp | None = None) -> pd.DataFrame:
    path = pathlib.Path(path)
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    value = pd.to_numeric(df["Value"], errors="coerce")
    quality = _flagger(len(df))

    _apply_flag(quality, ~np.isfinite(value.to_numpy()), "dropped")
    _apply_flag(quality, (value == 0).to_numpy(), "flagged")
    _apply_flag(quality, (value > HR_PLAUSIBLE[1]).to_numpy(), "flagged")
    _apply_flag(quality, event_time.duplicated(keep=False).to_numpy(), "flagged")

    values = value.fillna(0.0).map(lambda v: {"value": float(v)})
    return _contract_columns(df, signal="hr", participant_id=participant_id, source_file=path.name,
                             event_time=event_time, values=values, quality=quality, unit=HR_UNIT,
                             ingested_at=ingested_at or pd.Timestamp.now(tz="UTC"))


def eda_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0,
                      participant_id: str = "", ingested_at: pd.Timestamp | None = None) -> pd.DataFrame:
    path = pathlib.Path(path)
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    value = pd.to_numeric(df["Value"], errors="coerce")
    quality = _flagger(len(df))

    _apply_flag(quality, ~np.isfinite(value.to_numpy()), "dropped")
    _apply_flag(quality, (value < 0).to_numpy(), "flagged")

    values = value.fillna(0.0).map(lambda v: {"value": float(v)})
    return _contract_columns(df, signal="eda", participant_id=participant_id, source_file=path.name,
                             event_time=event_time, values=values, quality=quality, unit=EDA_UNIT,
                             ingested_at=ingested_at or pd.Timestamp.now(tz="UTC"))


def acc_rows_from_raw(path: pathlib.Path, *, tz_assume: str, shift_days: int = 0,
                      participant_id: str = "", ingested_at: pd.Timestamp | None = None) -> pd.DataFrame:
    """Every row is `quality=flagged, unit="unverified"` (not malformed) -- the 1/64 g scale assumption
    applies to the whole stream, not individual samples. Matches Data A's verified Bronze exactly."""
    path = pathlib.Path(path)
    df = pd.read_csv(path)
    event_time = _localize_utc(df["Timestamp"], tz_assume, shift_days)
    x, y, z = (pd.to_numeric(df[c], errors="coerce") for c in ("X", "Y", "Z"))
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    values = [{"x": float(a), "y": float(b), "z": float(c)} for a, b, c in zip(x.fillna(0.0), y.fillna(0.0), z.fillna(0.0))]
    quality = pd.Series(np.where(finite, "flagged", "dropped"), dtype=object)

    return _contract_columns(df, signal="acc", participant_id=participant_id, source_file=path.name,
                             event_time=event_time, values=values, quality=quality, unit=ACC_UNVERIFIED_UNIT,
                             ingested_at=ingested_at or pd.Timestamp.now(tz="UTC"))


def bronze_rows_for_participant(raw_dir: pathlib.Path, participant_id: str, *, tz_assume: str, run_id: str,
                                source_kind: str = "recorded_replay", shift_days: int = 0) -> pd.DataFrame:
    """HR_<id>.csv, EDA_<id>.csv, ACC_<id>.csv under `raw_dir`/`participant_id` -> one combined Bronze-shaped
    frame matching the real 14-column contract (`databricks.streaming.bronze_contract.BRONZE_COLUMNS`),
    sorted by event_time."""
    d = pathlib.Path(raw_dir) / participant_id
    ingested_at = pd.Timestamp.now(tz="UTC")
    parts = [hr_rows_from_raw(d / f"HR_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days,
                              participant_id=participant_id, ingested_at=ingested_at),
             eda_rows_from_raw(d / f"EDA_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days,
                               participant_id=participant_id, ingested_at=ingested_at),
             acc_rows_from_raw(d / f"ACC_{participant_id}.csv", tz_assume=tz_assume, shift_days=shift_days,
                               participant_id=participant_id, ingested_at=ingested_at)]
    rows = pd.concat(parts, ignore_index=True).sort_values("event_time", kind="stable").reset_index(drop=True)
    rows.insert(0, "run_id", run_id)
    rows.insert(3, "participant_id", participant_id)
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
