"""Inspect candidate CSVs without assuming their timezone or physical units.

Run: python -m databricks.ingestion.coverage_report --raw-root data/raw
Add --source-timezone ONLY after documenting the source-zone assumption.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import NOMINAL_HZ, SIGNALS, iter_signal_chunks, resolve_signal_file

BEGIN, END = "<!-- candidates:start -->", "<!-- candidates:end -->"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def overnight_coverage(times: pd.DatetimeIndex, nominal_hz: float | None) -> dict[str, float]:
    """Fraction of expected samples per minute, capped at one; ET 22:00–08:00.

    Uses unique valid timestamps. A minute's excess samples cannot cover a missing
    minute. Night denominators reflect daylight-saving transitions (9/10/11 h).
    IBI is event-based, so overnight completeness is not defined for it.
    """
    if times.empty or nominal_hz is None:
        return {}
    counts = pd.Series(1, index=times).resample("1min").sum()
    coverage = (counts / (nominal_hz * 60)).clip(upper=1)
    first, last = times.tz_convert("America/New_York")[[0, -1]]
    date, final = first.date() - timedelta(days=1), last.date()
    nights = {}
    while date <= final:
        start = pd.Timestamp(f"{date} 22:00", tz="America/New_York").tz_convert("UTC")
        end = pd.Timestamp(f"{date + timedelta(days=1)} 08:00", tz="America/New_York").tz_convert("UTC")
        if start <= times[-1] and end > times[0]:
            nights[str(date)] = round(float(coverage.loc[(coverage.index >= start) & (coverage.index < end)].sum())
                                     / ((end - start).total_seconds() / 60), 6)
        date += timedelta(days=1)
    return nights


def inspect_signal(path: Path, signal: str, source_timezone: str | None = None, *,
                   sampling_hz: float | None = None, verified_unit: str | None = None) -> dict:
    if sampling_hz is not None and (not np.isfinite(sampling_hz) or sampling_hz <= 0):
        raise ValueError("sampling_hz must be finite and positive")
    sample = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=3).to_dict("records")
    timezone_unresolved = False
    try:
        frames = iter_signal_chunks(path, signal, source_timezone=source_timezone, verified_unit=verified_unit)
        summary = _summarize(frames)
    except ValueError as exc:
        if "naive CSV timestamps" not in str(exc):
            raise
        # UTC here is only a surrogate for duration/ordering inspection. ET night
        # calculations and participant selection are withheld until zone supplied.
        timezone_unresolved = True
        summary = _summarize(iter_signal_chunks(path, signal, source_timezone="UTC", verified_unit=verified_unit))
    times = pd.DatetimeIndex(np.unique(summary.pop("times"))).tz_localize("UTC")
    usable = pd.DatetimeIndex(np.unique(summary.pop("usable_times"))).tz_localize("UTC")
    diffs = np.diff(times.asi8) / 1e9
    positive = diffs[diffs > 0]
    summary.update(file=str(path), bytes=path.stat().st_size, sha256=sha256(path), samples=sample,
                   timezone=("UNRESOLVED; UTC used only as an arithmetic surrogate" if timezone_unresolved
                             else (f"explicit assumption: {source_timezone}" if source_timezone else "CSV offsets")),
                   timezone_unresolved=timezone_unresolved,
                   unique_timestamps=len(times), duplicate_count=summary["timestamp_rows"] - len(times),
                   first_timestamp=str(times[0]) if len(times) else None,
                   last_timestamp=str(times[-1]) if len(times) else None,
                   observed_hz=round(1 / float(np.median(positive)), 6) if len(positive) else None,
                   coverage_expected_hz=sampling_hz if sampling_hz is not None else NOMINAL_HZ[signal],
                   gaps_over_60s=int((diffs > 60).sum()),
                   largest_gap_seconds=float(diffs.max()) if len(diffs) else None,
                   overnight_coverage={} if timezone_unresolved else overnight_coverage(
                       usable, sampling_hz if sampling_hz is not None else NOMINAL_HZ[signal]))
    return summary


def _summarize(frames):
    total = dropped = flagged = timestamp_rows = 0
    times, usable_times, reasons = [], [], {}
    for df in frames:
        total += len(df)
        dropped += int((df.quality == "dropped").sum())
        flagged += int((df.quality == "flagged").sum())
        timestamp_rows += int(df.source_timestamp.notna().sum())
        # Ordering/duplicates use all parseable timestamps; completeness excludes
        # malformed measurements, retaining finite unscaled ACC for inspection.
        times.append(df.loc[df.source_timestamp.notna(), "source_timestamp"].astype("int64").to_numpy())
        usable_times.append(df.loc[df.quality != "dropped", "source_timestamp"].astype("int64").to_numpy())
        for reason, count in df.quality_reason.value_counts().items():
            if reason:
                reasons[reason] = reasons.get(reason, 0) + int(count)
    return dict(rows=total, dropped_rows=dropped, flagged_rows=flagged,
                timestamp_rows=timestamp_rows, quality_reasons=reasons,
                times=np.concatenate(times) if times else np.array([], dtype="int64"),
                usable_times=np.concatenate(usable_times) if usable_times else np.array([], dtype="int64"))


def build_report(raw_root: Path, source_timezone: str | None = None, *, source_kind="recorded_replay",
                 sampling_hz: dict | None = None, verified_units: dict | None = None,
                 demo_hours: int = 24) -> dict:
    if source_kind not in {"recorded_replay", "synthetic_fixture", "synthetic_injection"}:
        raise ValueError("invalid source_kind")
    candidates = {}
    if raw_root.exists():
        for directory in sorted(p for p in raw_root.iterdir() if p.is_dir()):
            reports = {}
            for signal in SIGNALS:
                try:
                    path = resolve_signal_file(directory, signal)
                    if path:
                        reports[signal] = inspect_signal(path, signal, source_timezone,
                            sampling_hz=(sampling_hz or {}).get(signal),
                            verified_unit=(verified_units or {}).get(signal))
                except (ValueError, pd.errors.ParserError) as exc:
                    reports[signal] = {"error": str(exc)}
            if reports:
                candidates[directory.name] = reports
    ranked = []
    for participant, signals in candidates.items():
        required = [signals.get(s, {}) for s in ("hr", "eda", "acc")]
        if all(s.get("overnight_coverage") and not s.get("timezone_unresolved") for s in required):
            nights = set.intersection(*(set(s["overnight_coverage"]) for s in required))
            score = sum(min(s["overnight_coverage"][n] for s in required) for n in nights)
            start = max(pd.Timestamp(s["first_timestamp"]) for s in required)
            end = min(pd.Timestamp(s["last_timestamp"]) for s in required)
            if end - start >= pd.Timedelta(hours=60):
                ranked.append((score, participant, start, end))
    recommendation = None
    if ranked:
        score, participant, start, end = sorted(ranked, key=lambda r: (-r[0], r[1]))[0]
        recommendation = dict(participant=participant, common_start=str(start),
            baseline_history_start=str(start), demo_start=str(start + pd.Timedelta(hours=48)),
            demo_end=str(min(end + pd.Timedelta(seconds=1), start + pd.Timedelta(hours=48 + demo_hours))), score=round(score, 6),
            status="PROVISIONAL: inspect gaps and confirm timezone/units before selecting; no baseline quality claim")
    return {"dataset_version": "1.1.3" if source_kind == "recorded_replay" else None,
            "source_kind": source_kind, "candidates": candidates, "recommendation": recommendation}


def markdown(report: dict) -> str:
    lines = ["## Candidate inspection", "", f"Source kind: `{report.get('source_kind', 'recorded_replay')}`.", "",
             "Selection is provisional; timestamp assumptions and channel units are recorded below.", ""]
    if not report["candidates"]:
        lines += ["No participant CSVs found under the requested raw root. Checksums, coverage, participant",
                  "selection, and demo segment remain pending. Synthetic test samples are not dataset evidence.", ""]
    for participant, signals in report["candidates"].items():
        lines += [f"### Participant {participant}", ""]
        for signal, data in signals.items():
            lines += [f"#### {signal.upper()}", "", "```json", json.dumps(data, indent=2, allow_nan=False), "```", ""]
    lines += ["Recommendation: " + (json.dumps(report["recommendation"]) if report["recommendation"] else
              "pending; requires HR + EDA + ACC, explicit timestamp offsets/zone, and at least 48 h history + 12 h demo."), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--source-timezone")
    parser.add_argument("--source-kind", choices=["recorded_replay", "synthetic_fixture", "synthetic_injection"], default="recorded_replay")
    parser.add_argument("--acc-hz", type=float, help="explicit coverage denominator for a mock/downsampled ACC signal")
    parser.add_argument("--acc-unit", choices=["g", "1/64g", "m/s2"])
    parser.add_argument("--demo-hours", type=int, choices=[12, 24, 36], default=24)
    parser.add_argument("--output", type=Path, default=Path("docs/data-provenance.md"))
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    report = build_report(args.raw_root, args.source_timezone, source_kind=args.source_kind,
                          sampling_hz={"acc": args.acc_hz} if args.acc_hz is not None else None,
                          verified_units={"acc": args.acc_unit} if args.acc_unit else None,
                          demo_hours=args.demo_hours)
    rendered = markdown(report)
    print(rendered)
    original = args.output.read_text() if args.output.exists() else "# Data provenance\n"
    section = BEGIN + "\n" + rendered + "\n" + END
    if BEGIN in original and END in original:
        original = original[:original.index(BEGIN)] + section + original[original.index(END) + len(END):]
    else:
        original += "\n" + section + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(original)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
