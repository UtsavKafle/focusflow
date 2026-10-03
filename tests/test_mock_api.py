import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app


def mk(s="trigger"):
    return TestClient(create_app(s))


def test_state_and_schedule():
    c = mk()
    st = c.get("/api/state").json()
    assert st["source_kind"] == "synthetic_fixture"
    # Real pressure formula (pressure-v1) gives ~0.12 on this calendar, below the 0.70 rule: wearable codes hold,
    # HIGH_PRESSURE does not, so no recommendation. Team decision pending (see contracts/CHANGELOG.md).
    assert {"SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST"} <= set(st["trigger"]["reason_codes"])
    assert "HIGH_PRESSURE" not in st["trigger"]["reason_codes"] and not st["trigger"]["replan_recommended"]
    assert st["academic"]["deadline_pressure"] < 0.70
    assert c.get("/api/schedule").json()["schedule_version"] == 2
    assert c.get("/api/health").json()["mode"] == "synthetic_fixture"


def test_replan_apply_and_stale_409():
    c = mk()
    st = c.get("/api/state").json()
    body = dict(run_id=st["run_id"], state_id=st["state_id"], schedule_version=2, calendar_version=1, tasks_version=3,
                reason_codes=["SUSTAINED_LOAD", "HIGH_PRESSURE"])
    r = c.post("/api/replan", json=body); assert r.status_code == 202
    job = c.get(f"/api/replans/{r.json()['job_id']}").json()
    assert job["status"] == "ready" and job["proposal"]["validation"]["passed"]
    assert c.post(f"/api/replans/{job['job_id']}/apply", json={"expected_schedule_version": 1}).status_code == 409
    ok = c.post(f"/api/replans/{job['job_id']}/apply", json={"expected_schedule_version": 2})
    assert ok.status_code == 200 and ok.json()["schedule_version"] == 3
    assert c.post("/api/replan", json=body).status_code == 409   # stale after apply
    assert c.post("/api/replan", json=body).json()["code"] == "STALE_VERSION"


def test_replan_invalid_payload_422():
    assert mk().post("/api/replan", json={"run_id": "x"}).status_code == 422


def test_progress_and_events():
    c = mk()
    r = c.post("/api/tasks/algorithms-review/progress", json={"completed_minutes": 30, "expected_tasks_version": 3})
    assert r.status_code == 200 and r.json()["tasks_version"] == 4
    assert c.post("/api/tasks/algorithms-review/progress", json={"completed_minutes": 30, "expected_tasks_version": 3}).status_code == 409
    c.post("/api/replay/start", json={"scenario_id": "trigger"})
    c.post("/api/mock/advance?n=3")
    assert "state.updated" in c.get("/api/events?once=true").text
    assert c.get("/api/replay/status").json()["state"] == "running"


@pytest.mark.parametrize("s", ["normal", "missing_data", "infeasible"])
def test_other_scenarios(s):
    c = mk(s)
    st = c.get("/api/state").json()
    body = dict(run_id=st["run_id"], state_id=st["state_id"], schedule_version=2, calendar_version=1, tasks_version=3, reason_codes=["HIGH_PRESSURE"])
    jid = c.post("/api/replan", json=body).json()["job_id"]
    job = c.get(f"/api/replans/{jid}").json()
    if s == "infeasible":
        assert job["proposal"]["status"] == "partial"
    else:
        assert job["proposal"] is None
