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
