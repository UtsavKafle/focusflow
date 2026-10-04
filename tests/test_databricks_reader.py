"""Gold row -> WearableState boundary (integrator tasks 6 + 8), using a fake SQL connection (no credentials)."""
import json
from datetime import datetime, timezone

import pytest

from backend.app.databricks_reader import DatabricksSource, parse_gold_row
from backend.app.services import Services
from backend.app.store import Store

T = lambda h, m: datetime(2026, 10, 13, h, m, tzinfo=timezone.utc)


def gold_row(minute=20, **over):
    q = {"status": "sufficient", "hr_coverage": 0.98, "eda_coverage": 0.96, "acc_coverage": 0.99,
         "overnight_coverage": 0.93, "missing_reasons": {}}
    r = dict(run_id="run-1", participant_id="001", as_of=T(3, minute), window_start=T(3, minute - 1), window_end=T(3, minute),
             heart_rate_bpm=91.0, physiological_load=0.81, activity_level=0.08, estimated_rest_minutes=210,
             target_rest_minutes=480, recovery_score=0.4375, quality_json=json.dumps(q), baseline_id="baseline-01",
             baseline_cutoff=T(0, 0), evidence_ids=["window-0042"], activity_confound=False, source_kind="recorded_replay")
    r.update(over)
    return r


class FakeConn:
    def __init__(self, rows): self.rows = rows
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params): self.description = [(k,) for k in (self.rows[0] if self.rows else {})]
    def fetchall(self): return [tuple(r.values()) for r in self.rows]


def src(rows):
    s = DatabricksSource(lambda: FakeConn(rows), "focusflow.main.gold_wearable_state")
    s.errors = []
    s.on_error = lambda c, m: s.errors.append(c)
    return s


def test_parse_gold_row():
    ws, ex = parse_gold_row(gold_row())
    assert ws.physiological_load == 0.81 and ws.quality.status == "sufficient"
    assert ex["participant_id"] == "001" and ex["source_kind"] == "recorded_replay" and not ex["activity_confound"]


def test_null_without_reason_is_rejected():
    with pytest.raises(Exception):
        parse_gold_row(gold_row(physiological_load=None))


def test_not_ready_then_ready():
    assert src([]).latest() is None
    snap = src([gold_row()]).latest()
    assert snap.source_kind == "recorded_replay" and snap.key == "run-1:20261013T0320" and not snap.stale


def test_bad_row_keeps_last_good_marked_stale():
    s = src([gold_row()])
    assert s.latest().wearable.physiological_load == 0.81
    s._conn.rows = [gold_row(minute=21, physiological_load=float("nan"))]
    s.poll()
    snap = s.latest()
    assert snap.stale and snap.wearable.window_end == T(3, 20) and s.errors == ["GOLD_CONTRACT_VIOLATION"]


def test_stale_state_suppresses_trigger_and_emits_error():
    s = src([gold_row()])
    svc = Services(s, Store(), "trigger", data_source="databricks")
    svc.compose()
    s._conn.rows = [gold_row(minute=21, quality_json=None)]
    s.poll()
    st = svc.compose()
    assert st.source_kind == "recorded_replay" and "STALE_STATE" in st.trigger.suppressed_reason_codes
    assert any(e.type == "pipeline.error" for e in svc.bus.events)


# ---- task 7: Data A's ReplayController behind /api/replay/* (fake clock, in-memory writer, no credentials) ----
from datetime import timedelta

from fastapi.testclient import TestClient

from backend.app.main import create_app
from contracts.models import NormalizedEvent
from simulator.replay import ReplayController

RB = datetime(2026, 10, 12, 4, tzinfo=timezone.utc)  # replay base; bookmark RB + 24 h = 2026-10-13T04:00Z


class Clock:
    now = 0.0
    def __call__(self): return self.now


class MemWriter:
    def __init__(self): self.batches = []
    def publish(self, run_id, signal, n, rows): self.batches.append((run_id, signal, n, len(rows)))


def hr_source(offsets_s):
    def source(run_id, scenario_id):
        for n, sec in enumerate(offsets_s):
            t = RB + timedelta(seconds=sec)
            yield {**NormalizedEvent(run_id=run_id, event_id=f"001-hr-{n + 1:09d}", participant_id="001",
                                     source_kind="synthetic_fixture", source_timestamp=t, event_time=t, ingested_at=t,
                                     signal="hr", values={"value": 70}, unit="bpm").model_dump(mode="json"),
                   "source_file": "HR_001.csv", "source_row": n + 1}
    return source


def replay_src(offsets_s=(0, 86340, 86460)):
    clock, writer = Clock(), MemWriter()
    ctrl = ReplayController(hr_source(offsets_s), writer, monotonic=clock, background=False)
    s = DatabricksSource(lambda: FakeConn([]), "focusflow.main.gold_wearable_state", replay=ctrl,
                         default_bookmark=RB + timedelta(hours=24))
    return s, ctrl, clock, writer


def test_replay_start_publishes_history_and_reader_follows_run():
    s, ctrl, clock, writer = replay_src()
    s.start(60)
    assert s.state == "running" and s.run_id == ctrl.run_id and s.run_id.startswith("replay-")
    ctrl.tick()  # warm-up: history up to the bookmark is published before paced replay
    assert writer.batches == [(s.run_id, "hr", 0, 2)]
    st = s.status(None)
    assert st.mode == "live_databricks" and st.published_time == RB + timedelta(seconds=86340)
    assert st.processed_time is None and st.lag_seconds is None  # no Gold yet: unknown, not zero
    s._conn = FakeConn([gold_row(run_id=s.run_id)])
    s.poll()
    st = s.status(None)
    assert st.processed_time == T(3, 20) and st.lag_seconds == 39 * 60  # published 03:59Z vs Gold as_of 03:20Z


def test_replay_speed_pause_resume_keep_run_and_reset_makes_new_run():
    s, ctrl, clock, _ = replay_src()
    s.start(60)
    run = s.run_id
    s.start(300)  # running + same bookmark -> speed change only
    assert s.speed == 300 and s.run_id == run
    s.pause()
    assert s.state == "paused"
    s.start(10)  # resume same run
    assert s.state == "running" and s.run_id == run and s.speed == 10
    s._good = object()
    s.reset()
    assert s.run_id != run and s.run_id == ctrl.run_id and s._good is None  # old run's Gold never shown as new


def test_old_run_gold_is_not_processed_time_for_new_run():
    s, ctrl, _, _ = replay_src()
    s.start(60)
    s._conn = FakeConn([gold_row(run_id="some-older-run")])
    s.poll()
    assert s.status(None).processed_time is None


def test_replay_route_rejects_unsupported_speed_with_422():
    app = create_app("trigger", "fixture")
    svc = app.state.svc
    s, _, _, _ = replay_src()
    svc.source, svc.data_source = s, "databricks"
    c = TestClient(app)
    r = c.post("/api/replay/start", json={"scenario_id": "trigger", "speed": 7})
    assert r.status_code == 422 and r.json()["code"] == "REPLAY_REJECTED"
    assert c.post("/api/replay/start", json={"scenario_id": "trigger", "speed": 60}).status_code == 200
    assert c.get("/api/replay/status").json()["state"] == "running"


def test_reader_without_controller_keeps_local_replay_state():
    s = src([])
    s.start(5.0)
    assert s.state == "running" and s.speed == 5.0 and s.replay is None
    s.pause()
    assert s.state == "paused"


# ---- Data B's real Gold output (fixtures/mock_big_ideas/gold.csv, SYNTHETIC) through the reader + trigger ----
import pathlib

import pandas as pd

GOLD_CSV = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "mock_big_ideas" / "gold.csv"
SHIFT = timedelta(days=2429, hours=23)  # +2430 local days, EST -> EDT (docs/decisions.md, Data B task B)


class ClockedGold:
    """Fake warehouse over gold.csv: only rows with window_end <= clock exist (the replay has not published later ones)."""
    def __init__(self):
        df = pd.read_csv(GOLD_CSV, dtype={"participant_id": str})
        for c in ("as_of", "window_start", "window_end", "baseline_cutoff"):
            df[c] = pd.to_datetime(df[c], utc=True) + SHIFT
        df["evidence_ids"] = df["evidence_ids"].map(lambda s: json.loads(s.replace("'", '"')))
        self.rows = [{k: (None if v is pd.NaT or (isinstance(v, float) and v != v) else
                          (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)) for k, v in r.items()}
                     for r in df.to_dict("records")]
        self.clock = None
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params):
        limit = min(c for c in (self.clock, params.get("clock")) if c is not None)
        rows = [r for r in self.rows if r["as_of"] <= limit and r["run_id"] == params.get("run_id", r["run_id"])]
        if "LIMIT 1" in sql:
            rows = rows[-1:]
        else:
            rows = [r for r in rows if params["start"] < r["window_end"] <= params["end"]]
        self.out = rows
        self.description = [(k,) for k in self.rows[0]]
    def fetchall(self): return [tuple(r.values()) for r in self.out]


def mock_gold_at(clock):
    conn = ClockedGold()
    conn.clock = clock
    s = DatabricksSource(lambda: conn, "focusflow.main.gold_wearable_state")  # blank FOCUSFLOW_RUN_ID
    return Services(s, Store(), "trigger", data_source="databricks").compose()


def test_mock_gold_fires_at_cramming_trigger_moment():
    st = mock_gold_at(datetime(2026, 10, 13, 3, 20, tzinfo=timezone.utc))  # 2020-02-16 23:20 source time
    assert st.source_kind == "synthetic_fixture"
    assert st.trigger.replan_recommended
    assert {"SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST"} <= set(st.trigger.reason_codes)


def test_mock_gold_does_not_fire_during_exercise_or_warmup():
    exercise = mock_gold_at(datetime(2026, 10, 10, 21, 20, tzinfo=timezone.utc))  # 2020-02-14 17:20 local
    assert not exercise.trigger.replan_recommended and exercise.wearable.physiological_load == 1.0
    warmup = mock_gold_at(datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc))  # 2020-02-13 20:00 local
    assert not warmup.trigger.replan_recommended and warmup.wearable.physiological_load is None
    assert warmup.wearable.quality.missing_reasons["physiological_load"] == "baseline_warmup"


def test_gold_latest_sql_used_only_with_run_id():
    s = src([])
    assert ":run_id" not in s._latest_sql()
    s.run_id = "mock-demo-002"
    sql = s._latest_sql()
    assert "focusflow.main.gold_wearable_state" in sql and ":run_id" in sql and not sql.endswith(";")


def test_reader_follows_replay_clock_over_preloaded_gold():
    """Data B bulk-loads the whole 84 h run; reads must stop at the replay clock, never jump to the end."""
    conn = ClockedGold()
    conn.clock = conn.rows[-1]["as_of"]  # everything is already in the table
    s = DatabricksSource(lambda: conn, "focusflow.main.gold_wearable_state", run_id="mock-1")
    s.start(1, datetime(2026, 10, 13, 2, 30, tzinfo=timezone.utc))
    snap = s.latest()
    assert snap.as_of == datetime(2026, 10, 13, 2, 30, tzinfo=timezone.utc) and not snap.stale
    assert snap.lag_seconds < 60 and s.status("r").published_time >= snap.as_of
    assert all(datetime.fromisoformat(w["window_end"]) <= snap.as_of for w in s.history())
    s.pause()
    s.start(1, datetime(2026, 10, 13, 3, 20, tzinfo=timezone.utc))  # jump to a bookmark
    st = Services(s, Store(), "trigger", data_source="databricks").compose()
    assert st.as_of == datetime(2026, 10, 13, 3, 20, tzinfo=timezone.utc) and st.trigger.replan_recommended
    s.reset()
    assert s.state == "idle" and s._good is None


def test_clock_clause_added_to_gold_latest_sql():
    s = src([])
    s.run_id = "mock-demo-002"
    assert "as_of <= :clock" in s._latest_sql(clock=True) and "as_of <= :clock" not in s._latest_sql()
    s.run_id = None
    assert "WHERE as_of <= :clock" in s._latest_sql(clock=True)
