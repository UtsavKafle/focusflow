"""FocusFlow API (contracts/API.md). Real state composition, SQLite store, SSE publisher, background replan jobs.
FOCUSFLOW_DATA_SOURCE=fixture (default, no credentials) | databricks. FOCUSFLOW_FIXTURE picks the fixture scenario."""
from __future__ import annotations

import asyncio, json, os
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from contracts.models import ApplyRequest, ChatRequest, ReplanRequest, ReplayStartRequest, TaskProgressRequest
from agent.agent import run_chat
from backend.app.services import ApiError, Services, dumps
from backend.app.sources import FixtureSource
from backend.app.store import Store


def _ts(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def build_services(scenario: str, data_source: str, db_path: str) -> Services:
    if data_source == "databricks":
        from backend.app.databricks_reader import DatabricksSource  # task 6; import only when configured
        source = DatabricksSource.from_env()
    else:
        source = FixtureSource(scenario)
    return Services(source, Store(db_path), scenario, data_source,
                    auto_apply=os.getenv("FOCUSFLOW_AUTO_APPLY", "0").split()[0] in ("1", "true"))


def create_app(scenario: str = "trigger", data_source: str = "fixture", db_path: str = ":memory:") -> FastAPI:
    app = FastAPI(title="FocusFlow API", version="1.0")
    svc = build_services(scenario, data_source, db_path)
    app.state.svc = svc

    @app.exception_handler(ApiError)
    def _api_error(_: Request, e: ApiError):
        return JSONResponse(status_code=e.status, content=e.body.model_dump())

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": svc.source.mode, "data_source": svc.data_source, "scenario": svc.scenario,
                "label": svc.source.label, "run_id": svc.run_id}

    @app.get("/api/state")
    def state(run_id: Optional[str] = None):
        st = svc.compose()
        if st is None:
            raise ApiError(503, "STATE_NOT_READY", "no wearable state processed yet for this run", retryable=True)
        return dumps(st)

    @app.get("/api/history")
    def history(run_id: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None):
        return svc.history(_ts(start), _ts(end))

    @app.get("/api/calendar")
    def calendar():
        return dumps(svc.calendar())

    @app.get("/api/schedule")
    def schedule():
        return dumps(svc.schedule())

    @app.post("/api/replan", status_code=202)
    def replan(req: ReplanRequest, bg: BackgroundTasks):
        job, created = svc.create_job(req)
        if created:
            bg.add_task(svc.run_job, job.job_id, req)
        return {"job_id": job.job_id}

    @app.get("/api/replans/{job_id}")
    def get_job(job_id: str):
        return dumps(svc.job(job_id))

    @app.post("/api/replans/{job_id}/apply")
    def apply(job_id: str, body: ApplyRequest):
        return dumps(svc.apply(job_id, body.expected_schedule_version))

    @app.get("/api/decisions/{decision_id}")
    def decision(decision_id: str):
        return svc.decision(decision_id)

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        if req.decision_id:
            svc.decision(req.decision_id)  # 404 if unknown
        return run_chat(svc, req.message, req.decision_id)  # answers from saved decisions, not a fresh guess

    @app.post("/api/tasks/{task_id}/progress")
    def progress(task_id: str, body: TaskProgressRequest):
        return dumps(svc.progress(task_id, body.completed_minutes, body.expected_tasks_version))

    def _status():
        return dumps(svc.source.status(svc.run_id))

    @app.post("/api/replay/start")
    def r_start(body: ReplayStartRequest):
        if svc.data_source == "fixture" and body.scenario_id != svc.scenario:
            svc.scenario, svc.source = body.scenario_id, FixtureSource(body.scenario_id)
            svc.new_run()
        svc.source.start(body.speed, body.bookmark)
        svc.bus.emit(svc.run_id, "replay.updated", _status())
        return {"run_id": svc.run_id}

    @app.post("/api/replay/pause")
    def r_pause():
        svc.source.pause()
        svc.bus.emit(svc.run_id, "replay.updated", _status())
        return _status()

    @app.post("/api/replay/reset")
    def r_reset():
        svc.source.reset()
        svc.new_run()  # new run state; earlier proposals/decisions stay in the store
        svc.bus.emit(svc.run_id, "replay.updated", _status())
        return _status()

    @app.get("/api/replay/status")
    def r_status():
        return _status()

    if data_source == "fixture":
        @app.post("/api/mock/advance")  # fixture only: step the replay cursor
        def advance(n: int = 1):
            cursor = svc.source.advance(n)
            svc.compose()  # emits state.updated if the state changed
            return {"cursor": cursor, "of": len(svc.source.states)}

    @app.get("/api/events")
    def events(once: bool = Query(False, description="send backlog then close (tests)")):
        async def gen():
            seq = 0
            while True:
                svc.compose()  # detect replay progress -> state.updated
                for e in svc.bus.since(seq):
                    seq = e.sequence
                    yield f"id: {e.event_id}\nevent: {e.type}\ndata: {e.model_dump_json()}\n\n"
                if once:
                    return
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


app = create_app(os.getenv("FOCUSFLOW_FIXTURE", "trigger"), os.getenv("FOCUSFLOW_DATA_SOURCE", "fixture").split()[0],
                 os.getenv("FOCUSFLOW_DB_PATH", ":memory:"))
