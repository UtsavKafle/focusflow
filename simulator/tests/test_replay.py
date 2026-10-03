import json
from datetime import datetime, timedelta, timezone

import pytest

from contracts.models import NormalizedEvent, ReplayStatus
from databricks.ingestion.landing_writer import LandingWriter, LocalStore
from simulator.replay import ReplayController
from simulator.run_demo import csv_source

BASE = datetime(2026, 10, 13, 0, tzinfo=timezone.utc)


class Clock:
    now = 0
    def __call__(self):
        return self.now


def source_at(offsets):
    def source(run_id, scenario_id):
        for n, seconds in enumerate(offsets):
            yield {**NormalizedEvent(run_id=run_id, event_id=f"001-hr-{n+1:09d}", participant_id="001",
                source_kind="recorded_replay", source_timestamp=BASE + timedelta(seconds=seconds),
                event_time=BASE + timedelta(seconds=seconds), ingested_at=BASE,
                signal="hr", values={"value": 70}, unit="bpm").model_dump(mode="json"),
                "source_file": "HR.csv", "source_row": n+1}
    return source


def test_speed_pause_resume_and_processed_time_are_contract_safe(tmp_path):
    clock = Clock()
    controller = ReplayController(source_at([0, 10, 20]), LandingWriter(tmp_path),
        monotonic=clock, background=False, processed_time=lambda run: BASE)
    assert controller.start("r", "trigger", 10, None) == "r"
    assert controller.tick() == 1
    clock.now = 1
    assert controller.tick() == 1
    controller.pause()
    clock.now = 100
    assert controller.tick() == 0
    assert controller.status().state == "paused"
    controller.start("r", "trigger", 10, None)
    clock.now = 101
    assert controller.tick() == 1
    status = controller.status()
    assert isinstance(status, ReplayStatus) and status.state == "idle"
    assert status.published_time == BASE + timedelta(seconds=20)
    assert status.lag_seconds == 20


def test_reset_preserves_old_files_and_changes_run_and_checkpoint(tmp_path):
    controller = ReplayController(source_at([0, 10]), LandingWriter(tmp_path), background=False)
    controller.start("old", "trigger", 1, None)
    controller.tick()
    old_files = list((tmp_path / "old").rglob("*.jsonl"))
    contents = [p.read_bytes() for p in old_files]
    new_run = controller.reset()
    assert new_run != "old" and controller.checkpoint_path == f"{new_run}/bronze"
    controller.tick()
    assert [p.read_bytes() for p in old_files] == contents
    assert list((tmp_path / new_run).rglob("*.ready.json"))
    assert controller.status().processed_time is None


def test_bookmark_bulk_prefix_is_real_then_pacing_resumes(tmp_path):
    clock = Clock()
    bookmark = BASE + timedelta(hours=24)
    controller = ReplayController(source_at([0, 3600, 86400, 86410]), LandingWriter(tmp_path),
                                  background=False, monotonic=clock, batch_size=2)
    controller.start("run", "trigger", 10, bookmark)
    assert controller.tick() == 2
    assert controller.tick() == 1
    assert controller.published_time == bookmark
    assert controller.tick() == 0
    clock.now = 1
    assert controller.tick() == 1
    rows = [json.loads(line) for path in (tmp_path / "run/hr").glob("*.jsonl")
            for line in path.read_text().splitlines()]
    assert len(rows) == 4 and min(r["source_timestamp"] for r in rows) == "2026-10-13T00:00:00Z"


def test_bookmark_insufficient_history_is_rejected(tmp_path):
    controller = ReplayController(source_at([0, 10]), LandingWriter(tmp_path), background=False)
    with pytest.raises(ValueError, match="24 hours"):
        controller.start("run", "trigger", 1, BASE + timedelta(hours=2))
    assert controller.status().run_id is None


def test_unsorted_source_fails_without_silent_reordering(tmp_path):
    controller = ReplayController(source_at([0, 10, 5]), LandingWriter(tmp_path), background=False)
    controller.start("run", "trigger", 300, None)
    controller.tick()
    controller._started -= 1
    with pytest.raises(ValueError, match="chronological"):
        controller.tick()


def test_failed_batch_retry_retains_ingestion_timestamp_and_ids(tmp_path):
    class FlakyStore(LocalStore):
        failed = False
        def put_immutable(self, path, data):
            if path.endswith(".ready.json") and not self.failed:
                self.failed = True
                raise OSError("transient upload failure")
            super().put_immutable(path, data)
    wall = [BASE]
    writer = LandingWriter(tmp_path, FlakyStore())
    controller = ReplayController(source_at([0]), writer, background=False, wall_clock=lambda: wall[0])
    controller.start("run", "trigger", 1, None)
    with pytest.raises(OSError):
        controller.tick()
    assert controller.published_time is None
    wall[0] += timedelta(hours=1)
    assert controller.tick() == 1
    row = json.loads((tmp_path / "run/hr/batch-000000000.jsonl").read_text())
    assert row["ingested_at"] == BASE.isoformat().replace("+00:00", "Z")


def test_speed_changes_preserve_elapsed_replay_time(tmp_path):
    clock = Clock()
    controller = ReplayController(source_at([0, 20, 30]), LandingWriter(tmp_path), background=False, monotonic=clock)
    controller.start("run", "trigger", 10, None)
    controller.tick()
    clock.now = 1
    controller.set_speed(1)
    clock.now = 11
    assert controller.tick() == 1
    assert controller.published_time == BASE + timedelta(seconds=20)


@pytest.mark.parametrize("speed", [0, -1, 2, float("nan"), float("inf")])
def test_invalid_speed_rejected(tmp_path, speed):
    controller = ReplayController(source_at([0]), LandingWriter(tmp_path), background=False)
    with pytest.raises(ValueError, match="speeds"):
        controller.start("run", "trigger", speed, None)


def test_multisignal_csv_replay_shares_clock_and_preserves_quality(tmp_path):
    import pandas as pd
    raw = tmp_path / "001"
    raw.mkdir()
    offsets = [i * 4800 for i in range(20)]  # sparse synthetic sample; no coverage claim
    for signal in ("hr", "eda", "acc"):
        data = {"Timestamp": [(BASE + timedelta(seconds=n)).isoformat() for n in offsets]}
        data.update({"X": [64]*20, "Y": [-32]*20, "Z": [0]*20} if signal == "acc" else {"Value": [70]*20})
        pd.DataFrame(data).to_csv(raw / f"{signal.upper()}.csv", index=False)
    mapped = BASE + timedelta(days=7)
    source = csv_source(raw, BASE, BASE + timedelta(hours=26), mapped, source_kind="synthetic_fixture")
    clock = Clock()
    controller = ReplayController(source, LandingWriter(tmp_path / "landing"), monotonic=clock,
                                  background=False, batch_size=7)
    controller.start("run", "trigger", 300, mapped + timedelta(hours=24))
    for _ in range(20):
        controller.tick()
    clock.now = 100
    for _ in range(20):
        controller.tick()
    assert controller.status().state == "idle"
    rows = [json.loads(line) for path in (tmp_path / "landing/run").glob("*/batch-*.jsonl")
            for line in path.read_text().splitlines()]
    assert len(rows) == 60
    for row in rows:
        event = NormalizedEvent.model_validate({k: v for k, v in row.items() if k not in {"source_file", "source_row"}})
        assert event.event_time - event.source_timestamp == timedelta(days=7)
        assert event.source_kind == "synthetic_fixture"
        assert event.quality == ("flagged" if event.signal == "acc" else "valid")


def test_previously_used_run_cannot_overwrite_old_audit(tmp_path):
    controller = ReplayController(source_at([0, 10]), LandingWriter(tmp_path), background=False)
    controller.start("first", "trigger", 1)
    controller.pause()
    controller.start("second", "trigger", 1)
    controller.pause()
    with pytest.raises(ValueError, match="already been used"):
        controller.start("first", "trigger", 1)
