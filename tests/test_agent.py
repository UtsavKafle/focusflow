"""Agent tests (integrator tasks 9-13) with a fake LLM provider: no network, no keys."""
import pytest
from fastapi.testclient import TestClient

import agent.agent as ag
from agent.explain import FALLBACK_LABEL, SECTIONS, check_grounding, fallback_explanation, sources_for_check
from backend.app.main import create_app

REST = ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST"]


class FakeProvider:
    """Scripted turns: each item is a list of (tool, args) calls, or a callable(results) -> final text."""
    model_id = "fake-model"

    def __init__(self, turns):
        self.turns, self.results, self.n = list(turns), {}, 0

    def chat(self, system, messages, tools, timeout):
        for m in messages:  # remember tool outputs the "model" has seen
            if m["role"] == "tool":
                self.results[m["tool_call_id"]] = m["content"]
        t = self.turns.pop(0) if self.turns else (lambda r: "done")
        if callable(t) or tools is None:
            text = t(self) if callable(t) else "What we saw: x What we're unsure about: x What the coach suggests: x Status: x"
            return ag.AssistantMsg(text=text, raw=None)
        calls = []
        for name, args in t:
            self.n += 1
            calls.append(ag.ToolCall(f"c{self.n}", name, args))
        return ag.AssistantMsg(tool_calls=calls, raw=None)


def run(monkeypatch, provider, codes=REST, scn="trigger"):
    monkeypatch.setattr(ag, "select_provider", lambda: provider)
    app = create_app(scn)
    c = TestClient(app)
    st = c.get("/api/state").json()
    body = dict(run_id=st["run_id"], state_id=st["state_id"], schedule_version=2, calendar_version=1, tasks_version=3,
                reason_codes=codes)
    jid = c.post("/api/replan", json=body).json()["job_id"]
    return c, st, c.get(f"/api/replans/{jid}").json(), c.get(f"/api/decisions/{jid}").json()


def evidence_turn(st):
    return [("get_current_student_state", {"run_id": st["run_id"]}),
            ("compare_to_baseline", {"metric": "physiological_load", "window": "last_20_min"}),
            ("get_recent_rest", {"as_of": st["as_of"]}), ("get_upcoming_deadlines", {"as_of": st["as_of"]})]


def test_no_provider_uses_grounded_fallback(monkeypatch):
    c, st, job, d = run(monkeypatch, None)
    assert job["status"] == "ready" and job["explanation"].startswith(FALLBACK_LABEL)
    assert all(s in job["explanation"] for s in SECTIONS) and "proposed, not applied" in job["explanation"]
    assert "for 20 of the last 20 minutes" in job["explanation"]
    assert "state_id" not in job["explanation"] and "schedule_version" not in job["explanation"]
    assert d["explanation_kind"] == "fallback" and d["model_id"] == "none"
    ok, problems = check_grounding(job["explanation"], sources_for_check([t["result"] for t in d["tool_results"]]),
                                   "America/New_York")
    assert ok, problems


def _grounded_text():
    def final(prov):
        import json, re
        latest = {}
        for content in prov.results.values():  # strip _for_model's "(Mon 11:00 PM <tz>)" local-time annotations
            r = json.loads(re.sub(r'(\d{4}-\d{2}-\d{2}T[\d:]+Z) \([^)]*\)', r'\1', content))
            if "wearable" in r: latest["get_current_student_state"] = r
            elif "valid_minutes" in r: latest["compare_to_baseline"] = r
            elif "estimated_rest_minutes" in r and "metric" not in r: latest["get_recent_rest"] = r
            elif "fixed_events" in r: latest["get_upcoming_deadlines"] = r
            elif "proposal_id" in r: latest["request_schedule_replan"] = r
        return fallback_explanation(latest, "America/New_York").replace(FALLBACK_LABEL + "\n", "")
    return final


def test_grounded_llm_answer_is_used(monkeypatch):
    st = TestClient(create_app("trigger")).get("/api/state").json()  # same fixture clock as the app under test
    prov = FakeProvider([evidence_turn(st),
                         [("request_schedule_replan", {"state_id": None, "schedule_version": 2, "reason_codes": REST})],
                         _grounded_text()])
    orig = prov.chat
    def chat(system, messages, tools, timeout):  # the model copies state_id from the prompt, like a real one would
        msg = orig(system, messages, tools, timeout)
        for tc in msg.tool_calls:
            if tc.name == "request_schedule_replan":
                tc.input["state_id"] = messages[0]["content"].split("state_id=")[1].split(",")[0]
        return msg
    prov.chat = chat
    c, st, job, d = run(monkeypatch, prov)
    assert d["explanation_kind"] == "llm" and d["model_id"] == "fake-model", d["tool_results"][-1]
    assert not job["explanation"].startswith(FALLBACK_LABEL) and job["proposal"]["changes"]


def test_hallucinated_number_falls_back(monkeypatch):
    prov = FakeProvider([[("get_remaining_tasks", {})],
                         lambda p: "What we saw: load was 54 minutes above baseline. What we're unsure about: none. "
                                   "What the coach suggests: deadlines. Status: proposed."])
    c, st, job, d = run(monkeypatch, prov)
    assert d["explanation_kind"] == "fallback" and job["explanation"].startswith(FALLBACK_LABEL)
    notes = d["tool_results"][-1]["result"]["notes"]
    assert any("did not request a replan" in n or "grounding" in n for n in notes)


def test_model_failure_falls_back_and_keeps_proposal(monkeypatch):
    class Boom:
        model_id = "boom"
        def chat(self, *a, **k): raise TimeoutError("model unavailable")
    c, st, job, d = run(monkeypatch, Boom())
    assert job["status"] == "ready" and job["proposal"]["validation"]["passed"]
    assert d["explanation_kind"] == "fallback" and d["model_id"] == "boom (failed)"
    assert c.get("/api/schedule").json()["schedule_version"] == 2  # nothing applied by the agent


def test_tool_call_cap(monkeypatch):
    prov = FakeProvider([[("get_remaining_tasks", {})] * 3] * 5)
    c, st, job, d = run(monkeypatch, prov)
    model_calls = [t for t in d["tool_results"] if t["tool"] == "get_remaining_tasks"]
    assert len(model_calls) <= ag.MAX_TOOL_CALLS


def test_disallowed_reason_code_refused(monkeypatch):
    prov = FakeProvider([[("request_schedule_replan", {"state_id": "s", "schedule_version": 2,
                                                       "reason_codes": ["HIGH_PRESSURE"]})], lambda p: "x"])
    c, st, job, d = run(monkeypatch, prov, codes=["SUSTAINED_LOAD"])
    assert d["explanation_kind"] == "fallback"
    replans = [t for t in d["tool_results"] if t["tool"] == "request_schedule_replan"]
    assert replans and replans[0]["args"]["reason_codes"] == ["SUSTAINED_LOAD"]  # scripted call with permitted code


def test_chat_answers_from_saved_decision(monkeypatch):
    c, st, job, d = run(monkeypatch, None)
    r = c.post("/api/chat", json={"message": "Why did you move this?", "decision_id": d["decision_id"]}).json()
    assert r["kind"] == "saved" and d["decision_id"] in r["answer"] and job["explanation"] in r["answer"]
    assert c.post("/api/chat", json={"message": "why?", "decision_id": "nope"}).status_code == 404


def test_auto_apply_commits_valid_proposal(monkeypatch):
    monkeypatch.setenv("FOCUSFLOW_AUTO_APPLY", "1")
    c, st, job, d = run(monkeypatch, None)
    assert job["status"] == "applied" and d["after_version"] == 3
    assert c.get("/api/schedule").json()["schedule_version"] == 3


def test_databricks_provider_omits_null_fields():
    from agent.agent import AssistantMsg, DatabricksProvider, ToolCall
    p = DatabricksProvider("https://x", "t", "ep")
    out = p._convert("sys", [{"role": "assistant", "msg": AssistantMsg(text="", tool_calls=[ToolCall("c1", "get_state", {})], raw={})},
                             {"role": "assistant", "msg": AssistantMsg(text="done", tool_calls=[], raw={})}])
    assert "content" not in out[1] and out[1]["tool_calls"][0]["function"]["name"] == "get_state"
    assert out[2] == {"role": "assistant", "content": "done"}
