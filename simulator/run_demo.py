"""Bounded raw-event replay. Requires explicit real source clock and scenario clock.

Local mode publishes JSONL/commit files but does not run Spark. SDK mode publishes
to Databricks volumes; run availableNow Bronze alongside/between publications.
"""
from __future__ import annotations

import argparse
import heapq
import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from databricks.ingestion.adapter import iter_events, iter_signal_chunks, resolve_signal_file, utc
from databricks.ingestion.landing_writer import LandingWriter, SDKStore
from .replay import ReplayController


def aware(value):
    try:
        return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def csv_source(raw_directory, source_start, source_end, scenario_start, *, source_timezone=None,
               acc_unit=None, ibi_unit=None, source_kind="recorded_replay", wall_time_shift_days=None):
    """Factory produces a fresh bounded-memory merged iterator for each reset.

    Every signal shares one mapping offset. Input files must be chronological;
    the controller rejects cross-chunk disorder instead of silently reordering.
    """
    directory = Path(raw_directory)
    paths = {s: resolve_signal_file(directory, s) for s in ("hr", "eda", "acc", "ibi", "temp")}
    for signal in ("hr", "eda", "acc"):
        if paths[signal] is None:
            raise ValueError(f"missing required file: {directory / (signal.upper() + '.csv')}")
    units = {"acc": acc_unit, "ibi": ibi_unit}

    def source(run_id, scenario_id):
        def per_signal(signal):
            path = paths[signal]
            for df in iter_signal_chunks(path, signal, source_timezone=source_timezone, verified_unit=units.get(signal)):
                keep = (df.source_timestamp >= source_start) & (df.source_timestamp < source_end)
                subset = df.loc[keep].copy()
                subset.attrs = df.attrs.copy()
                yield from iter_events(subset, signal, run_id, directory.name,
                    source_start=source_start, scenario_start=scenario_start,
                    source_kind=source_kind, with_provenance=True,
                    wall_time_shift_days=wall_time_shift_days,
                    mapping_timezone=source_timezone if wall_time_shift_days is not None else None)
        streams = [per_signal(s) for s in ("hr", "eda", "acc", "ibi", "temp") if paths[s] is not None]
        # Compare actual datetimes, preserving fractional seconds and UTC offsets.
        yield from heapq.merge(*streams, key=lambda e: aware(e["event_time"]))
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-directory", type=Path, required=True)
    parser.add_argument("--source-start", type=aware, required=True, help="beginning of baseline history, including offset")
    parser.add_argument("--scenario-start", type=aware, required=True, help="mapped beginning of baseline history")
    parser.add_argument("--source-timezone", "--tz-assume", help="explicit assumption for naive source CSV timestamps")
    parser.add_argument("--wall-time-shift-days", type=int,
                        help="shift local calendar days instead of using a constant UTC offset")
    parser.add_argument("--source-kind", choices=["recorded_replay", "synthetic_fixture", "synthetic_injection"],
                        default="recorded_replay", help="required synthetic label when inputs are mock data")
    parser.add_argument("--history-hours", type=int, default=48, choices=[24, 48])
    parser.add_argument("--demo-hours", type=int, default=12, choices=[12, 24, 36])
    parser.add_argument("--speed", type=int, default=300, choices=[1, 10, 60, 300])
    parser.add_argument("--landing-root", default="data/derived/landing")
    parser.add_argument("--sdk", action="store_true", help="publish through Databricks Files API")
    parser.add_argument("--acc-unit", choices=["g", "1/64g", "m/s2"])
    parser.add_argument("--ibi-unit", choices=["s", "ms"])
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--batch-size", type=int, default=100_000,
                        help="maximum due events per publication tick; larger batches reduce prefix upload requests")
    args = parser.parse_args()
    if args.wall_time_shift_days is not None and not args.source_timezone:
        parser.error("--wall-time-shift-days requires --source-timezone")
    if args.source_timezone:
        print(f"ASSUMPTION: naive timestamps interpreted as {args.source_timezone}")
    if args.timeout_seconds <= 0:
        parser.error("timeout must be positive")
    if args.batch_size < 1:
        parser.error("batch size must be positive")
    if args.sdk and not args.landing_root.startswith("/Volumes/"):
        parser.error("--sdk requires --landing-root /Volumes/focusflow/main/landing")
    if args.sdk:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    end = args.source_start + timedelta(hours=args.history_hours + args.demo_hours)
    source = csv_source(args.raw_directory, args.source_start, end, args.scenario_start,
                        source_timezone=args.source_timezone, acc_unit=args.acc_unit, ibi_unit=args.ibi_unit,
                        source_kind=args.source_kind, wall_time_shift_days=args.wall_time_shift_days)
    writer = LandingWriter(args.landing_root, SDKStore() if args.sdk else None)
    controller = ReplayController(source, writer, batch_size=args.batch_size)
    started = time.monotonic()
    try:
        controller.start(f"replay-{uuid.uuid4().hex}", "trigger", args.speed,
                         args.scenario_start + timedelta(hours=args.history_hours))
        while controller.status().state == "running":
            if time.monotonic() - started > args.timeout_seconds:
                raise TimeoutError("bounded replay stopped at configured timeout")
            time.sleep(0.1)
        if controller.last_error:
            raise controller.last_error
        status = controller.status().model_dump(mode="json")
        if not args.sdk:
            # ReplayStatus's frozen mode enum has no local raw-publication mode.
            # Do not label an offline publication as a live Databricks pipeline.
            status.pop("mode")
        print(json.dumps({"publication": "Databricks Files API" if args.sdk else "LOCAL RAW REPLAY; no Spark processing",
                          "source_kind": args.source_kind, "status": status}, indent=2))
    finally:
        controller.close()


if __name__ == "__main__":
    main()
