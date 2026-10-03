import json, pathlib
import pytest
from pydantic import ValidationError
from contracts.models import (CalendarBundle, Schedule, ScheduleProposal, StudentState, NormalizedEvent)
from scheduler.validate import validate_proposal

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
SCN = ["normal", "trigger", "missing_data", "infeasible"]
rd = lambda s, f: json.loads((FIX / s / f).read_text())


@pytest.mark.parametrize("s", SCN)
def test_fixture_files_validate(s):
    cal = CalendarBundle.model_validate(rd(s, "calendar.json"))
    Schedule.model_validate(rd(s, "schedule.json"))
    states = [StudentState.model_validate(x) for x in rd(s, "states.json")]
    assert states and all(x.source_kind == "synthetic_fixture" for x in states)
    assert rd(s, "meta.json")["label"].startswith("SYNTHETIC")
    p = rd(s, "proposal.json")
    if p:
        assert validate_proposal(cal, ScheduleProposal.model_validate(p)).passed


def test_trigger_expectations():
    assert [x["trigger"]["replan_recommended"] for x in rd("normal", "states.json")][-1] is False
    assert rd("trigger", "states.json")[-1]["trigger"]["reason_codes"] == ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"]
    last = rd("missing_data", "states.json")[-1]
    assert last["wearable"]["physiological_load"] is None and last["trigger"]["replan_recommended"] is False
    assert rd("trigger", "proposal.json")["status"] == "feasible"
    assert rd("infeasible", "proposal.json")["unscheduled_work"]


def test_null_requires_reason():
    s = rd("missing_data", "states.json")[-1]
    s["wearable"]["quality"]["missing_reasons"].pop("physiological_load")
    with pytest.raises(ValidationError):
        StudentState.model_validate(s)


def test_interval_and_tz_rules():
    p = rd("trigger", "proposal.json")
    p["blocks"][0]["end"] = p["blocks"][0]["start"]
    with pytest.raises(ValidationError):
        ScheduleProposal.model_validate(p)
    p = rd("trigger", "proposal.json")
    p["blocks"][0]["start"] = "2026-10-13T12:00:00"  # naive
    with pytest.raises(ValidationError):
        ScheduleProposal.model_validate(p)


def test_validator_catches_sleep_violation():
    cal = CalendarBundle.model_validate(rd("trigger", "calendar.json"))
    p = rd("trigger", "proposal.json")
    for b in p["blocks"]:
        if b["block_id"] == "blk-alg-2":
            b["start"], b["end"] = "2026-10-13T06:00:00Z", "2026-10-13T07:00:00Z"
    rep = validate_proposal(cal, ScheduleProposal.model_validate(p))
    assert not rep.passed and not rep.checks["protected_sleep_respected"]


def test_event_schema():
    e = dict(run_id="r", event_id="e", participant_id="001", source_kind="synthetic_fixture",
             source_timestamp="2026-10-13T03:19:59Z", event_time="2026-10-13T03:19:59Z",
             ingested_at="2026-10-03T16:00:01Z", signal="hr", values={"value": 91.0}, unit="bpm")
    NormalizedEvent.model_validate(e)
    with pytest.raises(ValidationError):
        NormalizedEvent.model_validate({**e, "values": {"x": 1.0}})
    with pytest.raises(ValidationError):
        NormalizedEvent.model_validate({**e, "values": {"value": float("nan")}})


def test_schemas_up_to_date(tmp_path):
    import subprocess, sys
    root = pathlib.Path(__file__).resolve().parents[1]
    before = {p.name: p.read_text() for p in (root / "contracts/schema").glob("*.json")}
    subprocess.run([sys.executable, "contracts/generate_schemas.py"], cwd=root, check=True, capture_output=True)
    after = {p.name: p.read_text() for p in (root / "contracts/schema").glob("*.json")}
    assert before == after, "run contracts/generate_schemas.py and commit"
