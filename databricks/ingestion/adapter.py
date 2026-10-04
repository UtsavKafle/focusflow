"""BIG IDEAs v1.1.3 CSV adapter. Raw values and physical data-row IDs are retained.

No scaling, interpolation, or downsampling is applied. A naive timestamp requires
an explicit source_timezone. Unverified ACC/IBI units remain flagged raw values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from contracts.models import NormalizedEvent

SIGNALS = {"hr": ("Value",), "eda": ("Value",), "acc": ("X", "Y", "Z"),
           "ibi": ("Value",), "temp": ("Value",)}
NOMINAL_HZ = {"hr": 1, "eda": 4, "acc": 32, "temp": 4, "ibi": None}
UNITS = {"hr": "bpm", "eda": "uS", "temp": "degC", "acc": "unverified", "ibi": "unverified"}
VERIFIABLE_UNITS = {"acc": {"g", "1/64g", "m/s2"}, "ibi": {"s", "ms"}}


def resolve_signal_file(directory: str | Path, signal: str) -> Path | None:
    """Accept release names and participant-suffixed mock names without renaming.

    Two possible files are ambiguous; never pick one silently.
    """
    directory = Path(directory)
    signal = signal.lower()
    if signal not in SIGNALS:
        raise ValueError(f"unsupported signal {signal!r}")
    found = [path for path in (directory / f"{signal.upper()}.csv",
                              directory / f"{signal.upper()}_{directory.name}.csv") if path.is_file()]
    if len(found) > 1:
        raise ValueError(f"ambiguous {signal} files: {[p.name for p in found]}")
    return found[0] if found else None


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def shift_local_days(timestamps: pd.Series, days: int, zone: str) -> pd.Series:
    """Shift calendar dates before re-localizing; never guess a DST offset."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError("wall-time shift must be an integer number of days")
    local = timestamps.dt.tz_convert(zone).dt.tz_localize(None)
    mapped = (local + pd.Timedelta(days=days)).dt.tz_localize(
        zone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    if (timestamps.notna() & mapped.isna()).any():
        raise ValueError("wall-time mapping creates an ambiguous or nonexistent local time")
    return mapped


def _timestamps(raw: pd.Series, source_timezone: str | None) -> pd.Series:
    text = raw.str.strip()
    # Numeric epochs are intentionally unsupported without a documented format.
    aware = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", case=False, regex=True)
    naive = ~aware & ~text.str.fullmatch(r"[\d.]+") & text.ne("")
    parsed = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns, UTC]")
    parsed.loc[aware] = pd.to_datetime(text[aware], format="mixed", errors="coerce", utc=True)
    local = pd.to_datetime(text[naive], format="mixed", errors="coerce")
    if local.notna().any() and source_timezone is None:
        raise ValueError("naive CSV timestamps: pass source_timezone explicitly; source zone is unverified")
    if source_timezone is not None:
        # Ambiguous/nonexistent local times cannot be silently assigned an offset.
        parsed.loc[naive] = local.dt.tz_localize(
            source_timezone, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return parsed


def parse_signal(path: str | Path, signal: str, *, source_timezone: str | None = None,
                 verified_unit: str | None = None) -> pd.DataFrame:
    """Return all physical data rows, including dropped rows and their reasons.

    source_row is one-based after the header and is assigned before filtering.
    Duplicate timestamps are flagged, not deduplicated: distinct measurements may
    share a timestamp. Consumers must exclude flagged rows from affected features.
    """
    signal = signal.lower()
    if signal not in SIGNALS:
        raise ValueError(f"unsupported signal {signal!r}; BVP is outside this ingestion scope")
    if verified_unit is not None and verified_unit not in VERIFIABLE_UNITS.get(signal, {UNITS[signal]}):
        raise ValueError(f"unsupported unit {verified_unit!r} for {signal}")
    path = Path(path)
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, skip_blank_lines=False)
    return _parse_frame(raw, path, signal, source_timezone, verified_unit, 0)


def _parse_frame(raw, path, signal, source_timezone, verified_unit, row_offset):
    raw.columns = raw.columns.str.strip()
    needed = {"Timestamp", *SIGNALS[signal]}
    if not needed.issubset(raw.columns):
        raise ValueError(f"{path.name}: missing columns {sorted(needed - set(raw.columns))}")
    raw = raw.reset_index(drop=True)
    df = pd.DataFrame({"source_row": np.arange(1, len(raw) + 1) + row_offset,
                       "source_file": str(path), "raw_timestamp": raw["Timestamp"]})
    df["source_timestamp"] = _timestamps(raw["Timestamp"], source_timezone)
    for column in SIGNALS[signal]:
        df[column.lower() if signal == "acc" else "value"] = pd.to_numeric(raw[column], errors="coerce")
    values = ["x", "y", "z"] if signal == "acc" else ["value"]
    invalid_time = df.source_timestamp.isna()
    invalid_value = ~np.isfinite(df[values]).all(axis=1)
    duplicate = df.source_timestamp.notna() & df.source_timestamp.duplicated(keep=False)
    backwards = df.source_timestamp.diff().dt.total_seconds().lt(0)
    negative = df["value"].lt(0) if signal in {"hr", "eda", "ibi"} else pd.Series(False, index=df.index)
    nonpositive = df["value"].le(0) if signal in {"hr", "ibi"} else pd.Series(False, index=df.index)
    # Engineering quality gate, not a clinical interpretation. Retain raw value.
    high_hr = df["value"].gt(220) if signal == "hr" else pd.Series(False, index=df.index)
    df["quality"] = "valid"
    df["quality_reason"] = ""
    for mask, reason in ((duplicate, "duplicate_timestamp"), (backwards, "out_of_order"),
                         (negative, "negative_measurement"), (nonpositive, "nonpositive_hr_or_ibi"),
                         (high_hr, "hr_above_engineering_range")):
        df.loc[mask, "quality"] = "flagged"
        df.loc[mask, "quality_reason"] += reason + ";"
    unit = verified_unit or UNITS[signal]
    if unit == "unverified":
        df["quality"] = "flagged"
        df["quality_reason"] += "unit_unverified;"
    for mask, reason in ((invalid_time, "invalid_or_ambiguous_timestamp"),
                         (invalid_value, "missing_or_nonfinite_measurement")):
        df.loc[mask, "quality"] = "dropped"
        df.loc[mask, "quality_reason"] += reason + ";"
    df.attrs.update(signal=signal, unit=unit, source_timezone=source_timezone,
                    total_rows=len(df), dropped_rows=int((df.quality == "dropped").sum()),
                    flagged_rows=int((df.quality == "flagged").sum()))
    return df


def iter_signal_chunks(path: str | Path, signal: str, *, source_timezone: str | None = None,
                       verified_unit: str | None = None, chunksize: int = 100_000) -> Iterator[pd.DataFrame]:
    """Bounded-memory CSV parsing for full-rate ACC. IDs span chunk boundaries.

    Chunk-local duplicate flags are supplemented by exact duplicate counts in the
    coverage report. Cross-chunk disorder and duplicate boundary rows are flagged.
    """
    signal = signal.lower()
    if signal not in SIGNALS:
        raise ValueError(f"unsupported signal {signal!r}")
    if verified_unit is not None and verified_unit not in VERIFIABLE_UNITS.get(signal, {UNITS[signal]}):
        raise ValueError(f"unsupported unit {verified_unit!r} for {signal}")
    if chunksize <= 0:
        raise ValueError("chunksize must be positive")
    offset, previous = 0, None
    for raw in pd.read_csv(path, dtype=str, keep_default_na=False, skip_blank_lines=False, chunksize=chunksize):
        df = _parse_frame(raw, Path(path), signal, source_timezone, verified_unit, offset)
        times = df.source_timestamp.dropna()
        if previous is not None and not times.empty and times.iloc[0] <= previous:
            first = times.index[0]
            if df.loc[first, "quality"] != "dropped":
                df.loc[first, "quality"] = "flagged"
                df.loc[first, "quality_reason"] += "cross_chunk_order_or_duplicate;"
        if not times.empty:
            previous = times.iloc[-1]
        offset += len(df)
        yield df


def iter_events(df: pd.DataFrame, signal: str, run_id: str, participant_id: str, *,
                source_start: datetime | None = None, scenario_start: datetime | None = None,
                ingested_at: datetime | None = None, source_kind: str = "recorded_replay",
                wall_time_shift_days: int | None = None, mapping_timezone: str | None = None,
                with_provenance: bool = False) -> Iterator[dict]:
    """Yield finite contract events in chronological order, omitting dropped rows.

    Mapping anchors must be provided together and shared across every signal.
    with_provenance adds the two Bronze-only fields, outside NormalizedEvent.
    """
    signal = signal.lower()
    if df.attrs.get("signal") != signal:
        raise ValueError("DataFrame signal does not match requested signal")
    if (source_start is None) != (scenario_start is None):
        raise ValueError("source_start and scenario_start must be supplied together")
    if (wall_time_shift_days is None) != (mapping_timezone is None):
        raise ValueError("wall_time_shift_days and mapping_timezone must be supplied together")
    if wall_time_shift_days is not None and source_start is not None:
        anchor = shift_local_days(pd.Series([pd.Timestamp(utc(source_start))]),
                                  wall_time_shift_days, mapping_timezone).iloc[0]
        if anchor != pd.Timestamp(utc(scenario_start)):
            raise ValueError("scenario_start disagrees with the local calendar-day mapping")
    offset = utc(scenario_start) - utc(source_start) if source_start is not None else None
    stamp = utc(ingested_at or datetime.now(timezone.utc))
    names = ["x", "y", "z"] if signal == "acc" else ["value"]
    clean = df.loc[df.quality != "dropped"].sort_values(["source_timestamp", "source_row"], kind="stable")
    clean = clean.copy()
    clean["event_time"] = (shift_local_days(clean.source_timestamp, wall_time_shift_days, mapping_timezone)
                           if wall_time_shift_days is not None else
                           clean.source_timestamp + offset if offset is not None else clean.source_timestamp)
    columns = ["source_row", "source_file", "source_timestamp", "event_time", "quality", *names]
    for row in clean[columns].itertuples(index=False, name=None):
        source_row, source_file, timestamp, mapped, quality, *measurements = row
        source = timestamp.to_pydatetime()
        event = NormalizedEvent(run_id=run_id,
            event_id=f"{participant_id}-{signal}-{source_row:09d}", participant_id=participant_id,
            source_kind=source_kind, source_timestamp=source,
            event_time=mapped.to_pydatetime(),
            ingested_at=stamp, signal=signal, values=dict(zip(names, measurements)),
            unit=df.attrs["unit"], quality=quality).model_dump(mode="json")
        if with_provenance:
            event.update(source_file=source_file, source_row=int(source_row))
        yield event


def to_events(df: pd.DataFrame, signal: str, run_id: str, participant_id: str, **kwargs) -> list[dict]:
    """Small-data convenience API. Use iter_events for large recordings."""
    return list(iter_events(df, signal, run_id, participant_id, **kwargs))
