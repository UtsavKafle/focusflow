"""Publish a five-minute synthetic prefix and generate a standalone Bronze notebook.

Local preparation is the default. --sdk uploads the same immutable batches to
the configured workspace; Spark execution is a separate, bounded notebook step.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapter import iter_events, iter_signal_chunks, resolve_signal_file
from .bronze_stream import event_schema, run_bronze, validate_marker
from .landing_writer import LandingWriter, SDKStore, identifier

ZONE = "America/New_York"
START = datetime(2020, 2, 13, 17, tzinfo=timezone.utc)
SCENARIO = datetime(2026, 10, 9, 16, tzinfo=timezone.utc)


def prepare(raw_directory, output, run_id, duration_minutes=5):
    """Prepare a bounded synthetic interval in immutable 100k-row batches."""
    if duration_minutes < 1 or duration_minutes > 84 * 60:
        raise ValueError("duration must be between 1 minute and the selected 84-hour segment")
    identifier(run_id)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    writer = LandingWriter(output / "landing")
    stamp = datetime.now(timezone.utc)
    files, markers = {}, []
    for signal in ("hr", "eda", "acc"):
        path = resolve_signal_file(raw_directory, signal)
        if path is None:
            raise ValueError(f"missing {signal} mock file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        count = flagged = dropped = 0
        batch_number = 0
        for df in iter_signal_chunks(path, signal, source_timezone=ZONE, chunksize=100_000):
            subset = df.loc[(df.source_timestamp >= START) &
                            (df.source_timestamp < START + timedelta(minutes=duration_minutes))].copy()
            subset.attrs = df.attrs.copy()
            events = list(iter_events(subset, signal, run_id, Path(raw_directory).name,
                source_start=START, scenario_start=SCENARIO, source_kind="synthetic_fixture",
                wall_time_shift_days=2430, mapping_timezone=ZONE,
                ingested_at=stamp, with_provenance=True))
            count += len(events)
            flagged += sum(e["quality"] == "flagged" for e in events)
            dropped += int(subset.quality.eq("dropped").sum())
            if events:
                markers.append(writer.publish(run_id, signal, batch_number, events))
                batch_number += 1
                print(f"PREPARED {signal} batch {batch_number}: {count} events", flush=True)
            if (df.source_timestamp >= START + timedelta(minutes=duration_minutes)).any():
                break
        if duration_minutes == 5 and count != {"hr": 300, "eda": 1200, "acc": 2400}[signal]:
            raise ValueError(f"unexpected five-minute {signal} prefix count: {count}")
        files[signal] = {"path": str(path), "sha256": digest.hexdigest(), "rows": count,
                         "flagged": flagged, "dropped": dropped}
    manifest = {"run_id": run_id, "source_kind": "synthetic_fixture", "timezone": ZONE,
        "wall_time_shift_days": 2430, "source_start": START.isoformat(),
        "scenario_start": SCENARIO.isoformat(), "duration_minutes": duration_minutes,
        "sampling_hz": {"hr": 1, "eda": 4, "acc": 8},
        "acc_unit_scale_g": 1 / 64, "acc_scale_status": "synthetic assumption; real units unverified",
        "acc_event_unit": "unverified", "expected_rows": sum(f["rows"] for f in files.values()), "files": files,
        "local_markers": markers}
    notebook = "# Databricks notebook source\nfrom __future__ import annotations\nimport re\nimport json\n"
    notebook += "\n\n".join(inspect.getsource(f) for f in
                            (identifier, validate_marker, event_schema, run_bronze))
    expected_rows = manifest["expected_rows"]
    bronze_timeout = 480 if duration_minutes > 5 else 300
    notebook += f'''\n\nrun_id = {run_id!r}
expected_counts = { {signal: meta["rows"] for signal, meta in files.items()}!r}
for attempt in range(2):
    run_bronze(spark, run_id, timeout_seconds={bronze_timeout})
    rows = spark.table("focusflow.main.bronze_wearable_events").where(f"run_id = '{{run_id}}'")
    assert rows.count() == {expected_rows}, "Unexpected Bronze count"
    assert rows.select("event_id").distinct().count() == {expected_rows}, "Duplicate event IDs"
    assert rows.where("source_kind != 'synthetic_fixture'").count() == 0
    assert rows.where("signal = 'acc' AND (unit != 'unverified' OR quality != 'flagged')").count() == 0
    assert rows.where("signal = 'hr' AND `values`['value'] > 220 AND quality != 'flagged'").count() == 0
    actual_counts = {{row.signal: row['count'] for row in rows.groupBy('signal').count().collect()}}
    assert actual_counts == expected_counts, "Signal counts disagree with publication manifest"
    print(json.dumps({{"attempt": attempt + 1, "run_id": run_id, "row_count": {expected_rows}}}))
display(rows.groupBy("signal", "quality", "unit").count())
'''
    (output / "bronze_smoke_notebook.py").write_text(notebook)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def publish(output, manifest):
    """Reuse prepared timestamps and IDs; retries compare bytes rather than overwrite."""
    from dotenv import load_dotenv
    load_dotenv(override=False)
    writer = LandingWriter("/Volumes/focusflow/main/landing", SDKStore())
    markers = []
    for marker in manifest["local_markers"]:
        if hashlib.sha256(Path(marker["path"]).read_bytes()).hexdigest() != marker["sha256"]:
            raise ValueError("prepared batch checksum changed; refusing publication")
        events = [json.loads(line) for line in Path(marker["path"]).read_text().splitlines()]
        batch_number = int(Path(marker["path"]).stem.removeprefix("batch-"))
        markers.append(writer.publish(manifest["run_id"], marker["signal"], batch_number, events))
        manifest["remote_markers"] = markers
        (Path(output) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"UPLOADED {len(markers)}/{len(manifest['local_markers'])} batches", flush=True)
    manifest["remote_markers"] = markers
    (Path(output) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def publication_complete(manifest):
    """A partial upload must never be reported or submitted as complete."""
    expected = {(m["signal"], Path(m["path"]).name, m["sha256"], m["row_count"])
                for m in manifest["local_markers"]}
    actual = {(m["signal"], Path(m["path"]).name, m["sha256"], m["row_count"])
              for m in manifest.get("remote_markers", [])}
    return bool(expected) and expected == actual and len(manifest.get("remote_markers", [])) == len(expected) and sum(m["row_count"] for m in
        manifest["local_markers"]) == manifest["expected_rows"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-directory", type=Path, default=Path("data/raw/001"))
    parser.add_argument("--output", type=Path, default=Path("data/derived/mock-smoke"))
    parser.add_argument("--run-id", default="mock-smoke-001")
    parser.add_argument("--duration-minutes", type=int, default=5, help="5040 selects 48 h history plus 36 h demo")
    parser.add_argument("--sdk", action="store_true")
    parser.add_argument("--submit", action="store_true", help="submit one bounded serverless Bronze verification job")
    parser.add_argument("--status", action="store_true", help="fetch the submitted job state and failure output")
    args = parser.parse_args()
    print(f"ASSUMPTION: naive timestamps interpreted as {ZONE}")
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("superseded_by"):
            parser.error(f"this run is superseded by {manifest['superseded_by']}; preserve its audit files")
        if manifest["run_id"] != args.run_id:
            parser.error("existing output belongs to a different run; choose another output directory")
        if manifest["duration_minutes"] != args.duration_minutes:
            parser.error("existing output has a different duration; choose another output directory")
    else:
        manifest = prepare(args.raw_directory, args.output, args.run_id, args.duration_minutes)
    if args.sdk and not args.status:
        manifest = publish(args.output, manifest)
    if args.submit or args.status:
        from dotenv import load_dotenv
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.workspace import ImportFormat, Language
        from databricks.sdk.service.jobs import NotebookTask, SubmitTask, PerformanceTarget
        load_dotenv(override=False)
        client = WorkspaceClient()
        if args.submit:
            if not publication_complete(manifest):
                parser.error("publish with --sdk before submitting Bronze verification")
            if "job_run_id" not in manifest:
                notebook_path = f"/Shared/FocusFlow/{identifier(manifest['run_id'])}"
                client.workspace.mkdirs("/Shared/FocusFlow")
                content = base64.b64encode((args.output / "bronze_smoke_notebook.py").read_bytes()).decode()
                client.workspace.import_(notebook_path, content=content, format=ImportFormat.SOURCE,
                                         language=Language.PYTHON, overwrite=False)
                response = client.jobs.submit(run_name=f"FocusFlow {manifest['run_id']}",
                    idempotency_token=manifest["run_id"], timeout_seconds=900,
                    performance_target=PerformanceTarget.STANDARD,
                    tasks=[SubmitTask(task_key="bronze_smoke", notebook_task=NotebookTask(notebook_path),
                        timeout_seconds=600, max_retries=0, retry_on_timeout=False,
                        disable_auto_optimization=True)]).response
                manifest["job_run_id"] = response.run_id
                manifest["notebook_path"] = notebook_path
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        if "job_run_id" in manifest:
            run = client.jobs.get_run(manifest["job_run_id"])
            state = run.state.as_dict() if run.state else {}
            manifest["job_state"] = state
            manifest["job_url"] = run.run_page_url
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            print(json.dumps({"job_run_id": manifest["job_run_id"], "url": run.run_page_url,
                              "state": state, "start_time": run.start_time,
                              "setup_duration": run.setup_duration,
                              "execution_duration": run.execution_duration}, indent=2))
            for task in run.tasks or []:
                print(json.dumps({"task": task.task_key, "run_id": task.run_id,
                                  "state": task.state.as_dict() if task.state else {},
                                  "setup_duration": task.setup_duration,
                                  "execution_duration": task.execution_duration}, indent=2))
                if task.state and task.state.result_state:
                    result = client.jobs.get_run_output(task.run_id)
                    print(json.dumps({"result": task.state.as_dict(), "error": result.error,
                                      "error_trace": result.error_trace}, indent=2))
    print(json.dumps({"run_id": manifest["run_id"], "rows": manifest["expected_rows"],
                      "published_to_databricks": publication_complete(manifest),
                      "bronze_verified": manifest.get("job_state", {}).get("result_state") == "SUCCESS",
                      "manifest": str(manifest_path)}, indent=2))
    if manifest.get("job_state", {}).get("result_state") in {"FAILED", "TIMEDOUT", "CANCELED"}:
        raise SystemExit("Bronze verification did not succeed; inspect job state and error output")


if __name__ == "__main__":
    main()
