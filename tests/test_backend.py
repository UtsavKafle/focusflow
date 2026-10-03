"""Backend integration tests (integrator tasks 2, 5, 14) in fixture mode, no credentials."""
from fastapi.testclient import TestClient

from backend.app.main import create_app

REST = ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST"]


def setup(scn="trigger"):
    app = create_app(scn)
    c = TestClient(app)
    st = c.get("/api/state").json()
    a = st["academic"]
    body = dict(run_id=st["run_id"], state_id=st["state_id"], schedule_version=a["schedule_version"],
                calendar_version=a["calendar_version"], tasks_version=a["tasks_version"], reason_codes=REST)
    return app, c, st, body


def test_duplicate_replan_returns_same_job_and_apply_once():
    app, c, st, body = setup()
    j1 = c.post("/api/replan", json=body).json()["job_id"]
    assert c.post("/api/replan", json=body).json()["job_id"] == j1  # idempotent on state + versions
    job = c.get(f"/api/replans/{j1}").json()
    assert job["status"] == "ready" and job["proposal"]["validation"]["passed"]
    assert c.post(f"/api/replans/{j1}/apply", json={"expected_schedule_version": 2}).json()["schedule_version"] == 3
    again = c.post(f"/api/replans/{j1}/apply", json={"expected_schedule_version": 3})
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_APPLIED"
    assert c.get(f"/api/replans/{j1}").json()["status"] == "applied"


def test_pending_then_cooldown_suppress_trigger():
    app, c, st, body = setup()
    jid = c.post("/api/replan", json=body).json()["job_id"]
    assert "PENDING_DECISION" in c.get("/api/state").json()["trigger"]["suppressed_reason_codes"]
    c.post(f"/api/replans/{jid}/apply", json={"expected_schedule_version": 2})
    after = c.get("/api/state").json()
    assert "COOLDOWN" in after["trigger"]["suppressed_reason_codes"] and after["state_id"] != st["state_id"]


def test_failed_job_leaves_schedule_intact():
    app, c, st, body = setup()
    def boom(*a, **k): raise RuntimeError("tool output malformed")
    app.state.svc.investigator = boom
    before = c.get("/api/schedule").json()
    job = c.get(f"/api/replans/{c.post('/api/replan', json=body).json()['job_id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "JOB_FAILED"
    assert c.get("/api/schedule").json() == before
    assert "pipeline.error" in c.get("/api/events?once=true").text


def test_decision_history_survives_reset():
    app, c, st, body = setup()
    jid = c.post("/api/replan", json=body).json()["job_id"]
    c.post(f"/api/replans/{jid}/apply", json={"expected_schedule_version": 2})
    d = c.get(f"/api/decisions/{jid}").json()
    assert d["before_version"] == 2 and d["after_version"] == 3 and d["state_id"] == st["state_id"]
    assert d["rule_version"] == "demo-rules-2" and d["proposal"]["changes"]
    c.post("/api/replay/reset")
    assert c.get("/api/schedule").json()["schedule_version"] == 2   # fresh run
    assert c.get(f"/api/decisions/{jid}").json()["decision_id"] == jid  # audit kept
    assert c.get("/api/decisions/nope").status_code == 404


def test_sse_sequence_and_types():
    app, c, st, body = setup()
    jid = c.post("/api/replan", json=body).json()["job_id"]
    c.post(f"/api/replans/{jid}/apply", json={"expected_schedule_version": 2})
    text = c.get("/api/events?once=true").text
    order = [t for t in ("agent.started", "schedule.proposed", "schedule.applied") if f"event: {t}" in text]
    assert order == ["agent.started", "schedule.proposed", "schedule.applied"]


def test_history_never_past_replay_clock():
    app, c, st, body = setup()
    c.post("/api/replay/start", json={"scenario_id": "trigger", "speed": 1})
    now = c.get("/api/replay/status").json()["processed_time"]
    rows = c.get("/api/history").json()["windows"]
    assert rows and max(r["window_end"] for r in rows) <= now
    assert c.get("/api/state").json()["as_of"] == now


def test_state_not_ready_is_explicit():
    app, c, st, body = setup()
    app.state.svc.source.latest = lambda: None
    r = c.get("/api/state")
    assert r.status_code == 503 and r.json()["code"] == "STATE_NOT_READY"


def test_health_mode():
    h = TestClient(create_app("normal")).get("/api/health").json()
    assert h["mode"] == "synthetic_fixture" and h["label"].startswith("SYNTHETIC")


def test_reconnect_and_duplicate_delivery():
    import re
    app, c, st, body = setup()
    for _ in range(3):  # client retries / duplicate delivery of the same replan request
        c.post("/api/replan", json=body)
    first = c.get("/api/events?once=true").text
    second = c.get("/api/events?once=true").text  # reconnect: same retained events, same ids -> client dedupes
    ids = lambda t: re.findall(r"^id: (\S+)", t, re.M)
    assert ids(first) == ids(second) and len(set(ids(first))) == len(ids(first))
    assert first.count("event: agent.started") == 1 and first.count("event: schedule.proposed") == 1
    assert len(app.state.svc.store.decisions(app.state.svc.run_id)) == 1
