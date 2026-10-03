"""Boundary tests use 20-row synthetic samples, never participant recordings."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from contracts.models import NormalizedEvent
from databricks.ingestion.adapter import iter_signal_chunks, parse_signal, to_events, resolve_signal_file
from databricks.ingestion.coverage_report import build_report, inspect_signal, overnight_coverage
from databricks.ingestion.landing_writer import LandingWriter, LocalStore
from databricks.ingestion.bronze_stream import validate_marker

BASE = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)


def test_mock_calendar_mapping_preserves_wall_time_and_source(tmp_path):
    path = tmp_path / "HR.csv"
    path.write_text("Timestamp,Value\n2020-02-13 12:00:00.000000,70\n2020-03-10 12:00:00.125000,71\n")
    df = parse_signal(path, "hr", source_timezone="America/New_York")
    events = to_events(df, "hr", "mock", "001", source_kind="synthetic_fixture",
        wall_time_shift_days=2430, mapping_timezone="America/New_York")
    assert events[0]["source_timestamp"] == "2020-02-13T17:00:00Z"
    assert events[0]["event_time"] == "2026-10-09T16:00:00Z"
    assert events[1]["event_time"] == "2026-11-04T17:00:00.125000Z"
    first, second = [NormalizedEvent.model_validate(e) for e in events]
    assert first.event_time - first.source_timestamp != second.event_time - second.source_timestamp
    with pytest.raises(ValueError, match="disagrees"):
        to_events(df, "hr", "mock", "001", source_start=first.source_timestamp,
                  scenario_start=first.event_time + timedelta(hours=1),
                  wall_time_shift_days=2430, mapping_timezone="America/New_York")


def test_mapping_rejects_ambiguous_destination(tmp_path):
    path = tmp_path / "HR.csv"
    path.write_text("Timestamp,Value\n2026-10-31 01:30:00,70\n")
    df = parse_signal(path, "hr", source_timezone="America/New_York")
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        to_events(df, "hr", "mock", "001", wall_time_shift_days=1,
                  mapping_timezone="America/New_York")


def test_participant_suffixed_files_require_unambiguous_selection(tmp_path):
    participant = tmp_path / "001"
    participant.mkdir()
    suffixed = participant / "HR_001.csv"
    suffixed.touch()
    assert resolve_signal_file(participant, "hr") == suffixed
    assert resolve_signal_file(participant, "eda") is None
    (participant / "HR.csv").touch()
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_signal_file(participant, "hr")


@pytest.fixture
def sample_csv(tmp_path):
    def make(signal="hr", *, naive=False, bad=False):
        columns = ["Timestamp", "X", "Y", "Z"] if signal == "acc" else ["Timestamp", "Value"]
        rows = []
        for n in range(20):
            when = BASE + timedelta(seconds=n)
            stamp = when.replace(tzinfo=None).isoformat() if naive else when.isoformat()
            rows.append([stamp, 64, -32, 0] if signal == "acc" else [stamp, 70 + n])
        if bad:
            rows[3][0] = "broken"
            rows[5][-1] = "NaN"
            rows[8][-1] = "inf"
            rows[10][0] = rows[9][0]
            rows[12][-1] = -2
        path = tmp_path / f"{signal.upper()}.csv"
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
        return path
    return make


def test_twenty_row_finite_events_and_stable_source_ids(sample_csv):
    df = parse_signal(sample_csv(bad=True), "hr")
    assert df.attrs["total_rows"] == 20
    assert df.attrs["dropped_rows"] == 3
    events = to_events(df, "hr", "run", "001", ingested_at=BASE)
    assert len(events) == 17
    assert "001-hr-000000004" not in {e["event_id"] for e in events}
    assert events[0]["event_id"] == "001-hr-000000001"
    assert any(e["quality"] == "flagged" and e["values"]["value"] == -2 for e in events)
    for e in events:
        NormalizedEvent.model_validate(e)
        json.dumps(e, allow_nan=False)
    assert events == to_events(df, "hr", "run", "001", ingested_at=BASE)


def test_naive_zone_must_be_supplied_and_mapping_is_shared(sample_csv):
    path = sample_csv(naive=True)
    with pytest.raises(ValueError, match="source_timezone"):
        parse_signal(path, "hr")
    df = parse_signal(path, "hr", source_timezone="America/New_York")
    assert df.source_timestamp.iloc[0] == pd.Timestamp(BASE + timedelta(hours=4))
    mapped = to_events(df, "hr", "run", "001", source_start=BASE, scenario_start=BASE + timedelta(days=4))
    first = NormalizedEvent.model_validate(mapped[0])
    assert first.event_time - first.source_timestamp == timedelta(days=4)
    with pytest.raises(ValueError, match="together"):
        to_events(df, "hr", "run", "001", source_start=BASE)


def test_acc_raw_vectors_flagged_until_units_verified(sample_csv):
    path = sample_csv("acc")
    df = parse_signal(path, "acc")
    events = to_events(df, "acc", "run", "001")
    assert len(events) == 20
    assert events[0]["values"] == {"x": 64, "y": -32, "z": 0}
    assert events[0]["quality"] == "flagged" and events[0]["unit"] == "unverified"
    verified = parse_signal(path, "acc", verified_unit="1/64g")
    assert verified.quality.eq("valid").all()
    assert verified.attrs["unit"] == "1/64g"
    with pytest.raises(ValueError, match="unsupported unit"):
        parse_signal(path, "acc", verified_unit="guess")


def test_ibi_remains_unscaled(sample_csv):
    path = sample_csv("ibi")
    df = parse_signal(path, "ibi")
    assert df.attrs["unit"] == "unverified"
    assert df.quality.eq("flagged").all()
    df = parse_signal(path, "ibi", verified_unit="ms")
    assert to_events(df, "ibi", "r", "001")[0]["values"]["value"] == 70


def test_high_hr_is_flagged_and_retained(tmp_path):
    path = tmp_path / "HR.csv"
    path.write_text("Timestamp,Value\n2020-02-13T17:00:00Z,255\n2020-02-13T17:00:01Z,220\n")
    df = parse_signal(path, "hr")
    assert df.iloc[0].quality == "flagged"
    assert "hr_above_engineering_range" in df.iloc[0].quality_reason
    assert df.iloc[1].quality == "valid"
    assert to_events(df, "hr", "run", "001")[0]["values"]["value"] == 255


def test_chunk_ids_are_physical_rows(sample_csv):
    chunks = list(iter_signal_chunks(sample_csv(bad=True), "hr", chunksize=5))
    assert len(chunks) == 4
    events = [e for df in chunks for e in to_events(df, "hr", "r", "001")]
    ids = {e["event_id"] for e in events}
    assert len(ids) == 17 and "001-hr-000000020" in ids
    assert [r for df in chunks for r in df.source_row] == list(range(1, 21))


def test_ambiguous_dst_is_dropped_without_fabricated_offset(tmp_path):
    path = tmp_path / "HR.csv"
    path.write_text("Timestamp,Value\n2026-11-01 01:30:00,70\n2026-03-08 02:30:00,80\n")
    df = parse_signal(path, "hr", source_timezone="America/New_York")
    assert df.quality.eq("dropped").all()
    assert to_events(df, "hr", "run", "001") == []


def test_coverage_flags_unresolved_timezone_and_counts_real_bad_rows(sample_csv):
    path = sample_csv(naive=True, bad=True)
    report = inspect_signal(path, "hr")
    assert report["rows"] == 20 and report["dropped_rows"] == 3
    assert report["duplicate_count"] == 1 and report["observed_hz"] == 1
    assert report["timezone_unresolved"]
    assert report["overnight_coverage"] == {}
    assert len(report["sha256"]) == 64
    assert report["samples"][0]["Timestamp"] == BASE.replace(tzinfo=None).isoformat()


def test_mock_coverage_uses_explicit_eight_hz_and_synthetic_label(tmp_path):
    directory = tmp_path / "001"
    directory.mkdir()
    times = pd.date_range("2026-10-12T02:00:00Z", periods=480, freq="125ms")
    path = directory / "ACC_001.csv"
    pd.DataFrame({"Timestamp": times.astype(str), "X": 0, "Y": 0, "Z": 64}).to_csv(path, index=False)
    default = inspect_signal(path, "acc")
    report = build_report(tmp_path, source_kind="synthetic_fixture", sampling_hz={"acc": 8})
    mock = report["candidates"]["001"]["acc"]
    assert mock["observed_hz"] == 8 and mock["coverage_expected_hz"] == 8
    assert mock["overnight_coverage"]["2026-10-11"] == round(1 / 600, 6)
    assert default["overnight_coverage"]["2026-10-11"] == round(0.25 / 600, 6)
    assert report["dataset_version"] is None and report["source_kind"] == "synthetic_fixture"
    assert mock["flagged_rows"] == 480


def test_coverage_excludes_nonfinite_values(sample_csv):
    report = inspect_signal(sample_csv(bad=True), "hr")
    coverage = report["overnight_coverage"]["2026-10-11"]
    assert coverage == round(16 / 36000, 6)  # 17 finite rows, one duplicate time


def test_missing_data_produces_honest_pending_report(tmp_path):
    report = build_report(tmp_path / "missing")
    assert report["candidates"] == {} and report["recommendation"] is None


def test_night_denominator_tracks_dst():
    times = pd.date_range("2026-11-01T02:00:00Z", "2026-11-01T12:59:59Z", freq="s")
    assert overnight_coverage(times, 1)["2026-10-31"] == 1


def test_writer_publishes_marker_last_and_retry_is_immutable(sample_csv, tmp_path):
    class RecordingStore(LocalStore):
        def __init__(self):
            self.paths = []
        def put_immutable(self, path, data):
            self.paths.append(path)
            super().put_immutable(path, data)
    store = RecordingStore()
    writer = LandingWriter(tmp_path / "landing", store)
    rows = to_events(parse_signal(sample_csv(), "hr"), "hr", "run", "001", with_provenance=True, ingested_at=BASE)
    marker = writer.publish("run", "hr", 0, rows)
    assert store.paths[-1].endswith(".ready.json")
    path = tmp_path / "landing/run/hr/batch-000000000.jsonl"
    assert len(path.read_text().splitlines()) == 20
    assert json.loads(path.with_suffix(".ready.json").read_text()) == marker
    assert writer.publish("run", "hr", 0, rows) == marker
    changed = [{**rows[0], "values": {"value": 100}}, *rows[1:]]
    with pytest.raises(FileExistsError):
        writer.publish("run", "hr", 0, changed)
    assert json.loads(path.read_text().splitlines()[0])["values"]["value"] == 70


def test_failed_final_write_does_not_publish_commit_marker(sample_csv, tmp_path):
    class FailedStore(LocalStore):
        def put_immutable(self, path, data):
            if "/.staging/" not in path:
                raise OSError("simulated interrupted upload")
            super().put_immutable(path, data)
    rows = to_events(parse_signal(sample_csv(), "hr"), "hr", "run", "001", with_provenance=True)
    with pytest.raises(OSError):
        LandingWriter(tmp_path, FailedStore()).publish("run", "hr", 0, rows)
    assert not list(tmp_path.rglob("*.ready.json"))


@pytest.mark.parametrize("run_id", ["../escape", "/absolute", "a/b", ""])
def test_writer_rejects_path_traversal(tmp_path, run_id):
    with pytest.raises(ValueError):
        LandingWriter(tmp_path).publish(run_id, "hr", 0, [{}])


@pytest.mark.parametrize("field,value", [
    ("run_id", "other"), ("path", "/landing/run/hr/../../other.jsonl"),
    ("sha256", "bad"), ("row_count", 0), ("row_count", True), ("signal", "bvp")])
def test_bronze_commit_rejects_bad_references(field, value):
    marker = {"path": "/landing/run/hr/batch-000000000.jsonl", "sha256": "a"*64,
              "row_count": 20, "run_id": "run", "signal": "hr"}
    assert validate_marker(marker, "run", "/landing") == marker["path"]
    marker[field] = value
    with pytest.raises(ValueError, match="commit marker"):
        validate_marker(marker, "run", "/landing")
