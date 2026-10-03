"""Fixture-backed MOCK API implementing contracts/API.md so frontend + agent can start before Databricks.
Replace the store with a Databricks SQL reader later (FOCUSFLOW_DATA_SOURCE=databricks); keep the routes."""
from __future__ import annotations

import itertools, json, os, pathlib, uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from contracts.models import (ApplyRequest, CalendarBundle, ChatRequest, ReplanJob, ReplanRequest, ReplayStartRequest,
                              ReplayStatus, Schedule, ScheduleProposal, StudentState, TaskProgressRequest)
from scheduler.validate import validate_proposal

FIX = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"


def _load(name: str):
    d = FIX / name
    rd = lambda f: json.loads((d / f).read_text())
    return rd("meta.json"), rd("calendar.json"), rd("schedule.json"), rd("states.json"), rd("history.json"), rd("proposal.json"), rd("explanation.json")


def err(status: int, code: str, message: str, retryable: bool = False):
    return JSONResponse(status_code=status, content={"code": code, "message": message, "retryable": retryable})


def create_app(scenario: str = "trigger") -> FastAPI:
    app = FastAPI(title="FocusFlow mock API", version="1.0")
    meta, cal, sched, states, history, proposal, expl = _load(scenario)
    S = {"cal": CalendarBundle.model_validate(cal), "sched": Schedule.model_validate(sched),
         "states": [StudentState.model_validate(s) for s in states], "cursor": len(states) - 1,
         "replay": "idle", "jobs": {}, "events": [], "seq": itertools.count(1), "decisions": {}}

    def emit(type_: str, payload: dict):
        S["events"].append({"event_id": f"evt-{uuid.uuid4().hex[:8]}", "sequence": next(S["seq"]), "run_id": meta["run_id"],
                            "event_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "type": type_, "payload": payload})

    def cur() -> StudentState:
        st = S["states"][S["cursor"]].model_copy(deep=True)
        st.academic.schedule_version = S["sched"].schedule_version
        st.academic.tasks_version = S["cal"].tasks_version
        return st

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": "synthetic_fixture", "scenario": scenario, "label": meta["label"]}

    @app.get("/api/state")
    def state(run_id: str | None = None):
        return json.loads(cur().model_dump_json())

    @app.get("/api/history")
    def hist(run_id: str | None = None, start: str | None = None, end: str | None = None):
        rows = history
        if start: rows = [r for r in rows if r["window_end"] >= start]
        if end: rows = [r for r in rows if r["window_end"] <= end]
        return {"schema_version": "1.0", "source_kind": "synthetic_fixture", "windows": rows}

    @app.get("/api/calendar")
    def calendar():
        return json.loads(S["cal"].model_dump_json())

    @app.get("/api/schedule")
    def schedule():
        return json.loads(S["sched"].model_dump_json())

    @app.post("/api/replan", status_code=202)
    def replan(req: ReplanRequest):
        if req.schedule_version != S["sched"].schedule_version or req.tasks_version != S["cal"].tasks_version \
                or req.calendar_version != S["cal"].calendar_version:
            return err(409, "STALE_VERSION", "input versions are stale; refetch state and schedule")
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        emit("agent.started", {"job_id": job_id})
        prop = ScheduleProposal.model_validate(proposal) if proposal else None
        if prop:
            rep = validate_proposal(S["cal"], prop)
            if not rep.passed:
                S["jobs"][job_id] = ReplanJob(job_id=job_id, status="failed", error={"code": "INVALID_PROPOSAL", "message": "; ".join(rep.messages)})
                return {"job_id": job_id}
            emit("schedule.proposed", {"job_id": job_id, "proposal_id": prop.proposal_id, "status": prop.status})
        text = expl["text"] if expl else "No schedule change recommended right now."
        S["jobs"][job_id] = ReplanJob(job_id=job_id, status="ready", proposal=prop, explanation=text,
                                      evidence_ids=(expl or {}).get("evidence_ids", []))
        emit("agent.explanation", {"job_id": job_id, "text": text})
        return {"job_id": job_id}

    @app.get("/api/replans/{job_id}")
    def get_job(job_id: str):
        j = S["jobs"].get(job_id)
        if not j: return err(404, "NOT_FOUND", "unknown job")
        return json.loads(j.model_dump_json())

    @app.post("/api/replans/{job_id}/apply")
    def apply(job_id: str, body: ApplyRequest):
        j = S["jobs"].get(job_id)
        if not j: return err(404, "NOT_FOUND", "unknown job")
        if not j.proposal or j.status != "ready": return err(422, "NOTHING_TO_APPLY", "job has no applicable proposal")
        if body.expected_schedule_version != S["sched"].schedule_version:
            return err(409, "STALE_VERSION", "schedule changed since proposal; refetch", retryable=False)
        p = j.proposal
        S["sched"] = Schedule(schedule_version=S["sched"].schedule_version + 1, blocks=p.blocks, unscheduled_work=p.unscheduled_work)
        j.status = "applied"
        S["decisions"][job_id] = {"proposal": json.loads(p.model_dump_json()), "explanation": j.explanation}
        emit("schedule.applied", {"job_id": job_id, "schedule_version": S["sched"].schedule_version})
        return json.loads(S["sched"].model_dump_json())

    @app.get("/api/decisions/{decision_id}")
    def decision(decision_id: str):
        d = S["decisions"].get(decision_id)
        return d if d else err(404, "NOT_FOUND", "unknown decision")

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        text = (expl or {}).get("text", "Nothing unusual in the recent window.")
        return {"answer": f"[fixture answer] {text}", "evidence_ids": (expl or {}).get("evidence_ids", []), "synthetic": True}

    @app.post("/api/tasks/{task_id}/progress")
    def progress(task_id: str, body: TaskProgressRequest):
        if body.expected_tasks_version != S["cal"].tasks_version:
            return err(409, "STALE_VERSION", "tasks changed; refetch")
        t = next((t for t in S["cal"].tasks if t.task_id == task_id), None)
        if not t: return err(404, "NOT_FOUND", "unknown task")
        t.remaining_minutes = max(0, t.remaining_minutes - body.completed_minutes)
        if t.remaining_minutes == 0: t.status = "done"
        S["cal"].tasks_version += 1
        return json.loads(S["cal"].model_dump_json())

    def status() -> ReplayStatus:
        st = S["states"][S["cursor"]]
        return ReplayStatus(run_id=meta["run_id"], mode="synthetic_fixture", state=S["replay"], speed=1.0,
                            published_time=st.as_of, processed_time=st.as_of, lag_seconds=0.0)

    @app.post("/api/replay/start")
    def r_start(body: ReplayStartRequest):
        S["replay"], S["cursor"] = "running", 0
        emit("replay.updated", {"state": "running"})
        return {"run_id": meta["run_id"]}

    @app.post("/api/replay/pause")
    def r_pause():
        S["replay"] = "paused"; emit("replay.updated", {"state": "paused"}); return json.loads(status().model_dump_json())

    @app.post("/api/replay/reset")
    def r_reset():
        S["replay"], S["cursor"] = "idle", len(S["states"]) - 1
        S["sched"] = Schedule.model_validate(sched); S["cal"] = CalendarBundle.model_validate(cal); S["jobs"].clear()
        emit("replay.updated", {"state": "idle"}); return json.loads(status().model_dump_json())

    @app.get("/api/replay/status")
    def r_status():
        return json.loads(status().model_dump_json())

    @app.post("/api/mock/advance")  # MOCK ONLY: step the fixture cursor to simulate a live stream
    def advance(n: int = 1):
        S["cursor"] = min(len(S["states"]) - 1, S["cursor"] + n)
        emit("state.updated", {"state_id": S["states"][S["cursor"]].state_id})
        return {"cursor": S["cursor"], "of": len(S["states"])}

    @app.get("/api/events")
    def events(once: bool = Query(False, description="mock/test: send backlog then close")):
        import asyncio
        async def gen():
            sent = 0
            while True:
                while sent < len(S["events"]):
                    yield f"event: {S['events'][sent]['type']}\ndata: {json.dumps(S['events'][sent])}\n\n"; sent += 1
                if once: return
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


app = create_app(os.getenv("FOCUSFLOW_FIXTURE", "trigger"))
