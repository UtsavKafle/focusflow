"""SQLite persistence (integrator task 2): calendar, tasks, versioned schedules, proposals (replan jobs), decisions.
Reset starts a new run and reloads calendar/schedule; proposals and decisions are never deleted (audit history).
Single backend process; one connection guarded by a lock (replan jobs run in background threads)."""
from __future__ import annotations

import json, sqlite3, threading
from datetime import datetime, timezone
from typing import Any, Optional

from contracts.models import CalendarBundle, ReplanJob, Schedule, Task

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar (calendar_version INTEGER, run_id TEXT, body TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (run_id TEXT, task_id TEXT, tasks_version INTEGER, body TEXT, PRIMARY KEY (run_id, task_id));
CREATE TABLE IF NOT EXISTS task_versions (run_id TEXT PRIMARY KEY, tasks_version INTEGER);
CREATE TABLE IF NOT EXISTS schedules (run_id TEXT, schedule_version INTEGER, body TEXT, created_at TEXT,
                                      PRIMARY KEY (run_id, schedule_version));
CREATE TABLE IF NOT EXISTS proposals (job_id TEXT PRIMARY KEY, run_id TEXT, state_id TEXT, versions TEXT, status TEXT,
                                      body TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS decisions (decision_id TEXT PRIMARY KEY, run_id TEXT, job_id TEXT, state_id TEXT,
                                      tool_results TEXT, rule_version TEXT, model_id TEXT, explanation_kind TEXT,
                                      before_version INTEGER, after_version INTEGER, evidence_ids TEXT,
                                      explanation TEXT, proposal TEXT, applied_replay_time TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, scenario TEXT, created_at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(m) -> str:
    return m.model_dump_json() if hasattr(m, "model_dump_json") else json.dumps(m, default=str)


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    def _q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.fetchall()

    # ---- runs / reset ----
    def start_run(self, run_id: str, scenario: str, cal: CalendarBundle, sched: Schedule) -> None:
        """New run with a fresh calendar/schedule. Older runs' proposals and decisions stay for audit."""
        with self.lock:
            self._q("INSERT OR IGNORE INTO runs VALUES (?,?,?)", (run_id, scenario, _now()))
            if self._q("SELECT 1 FROM schedules WHERE run_id=?", (run_id,)):
                return  # resuming an existing run
            body = cal.model_dump(mode="json")
            tasks = body.pop("tasks")
            self._q("INSERT INTO calendar VALUES (?,?,?,?)", (cal.calendar_version, run_id, json.dumps(body), _now()))
            self._q("INSERT INTO task_versions VALUES (?,?)", (run_id, cal.tasks_version))
            for t in tasks:
                self._q("INSERT INTO tasks VALUES (?,?,?,?)", (run_id, t["task_id"], cal.tasks_version, json.dumps(t)))
            self.save_schedule(run_id, sched)

    def latest_run(self) -> Optional[str]:
        r = self._q("SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1")
        return r[0]["run_id"] if r else None

    # ---- calendar / tasks ----
    def calendar(self, run_id: str) -> CalendarBundle:
        c = self._q("SELECT body FROM calendar WHERE run_id=? ORDER BY calendar_version DESC LIMIT 1", (run_id,))[0]
        tv = self._q("SELECT tasks_version FROM task_versions WHERE run_id=?", (run_id,))[0]["tasks_version"]
        tasks = [json.loads(r["body"]) for r in self._q("SELECT body FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,))]
        return CalendarBundle.model_validate({**json.loads(c["body"]), "tasks": tasks, "tasks_version": tv})

    def record_progress(self, run_id: str, task_id: str, completed: int, expected_tasks_version: int) -> CalendarBundle:
        """Explicit user progress only. Raises KeyError (unknown task) or ValueError (stale version)."""
        with self.lock:
            cal = self.calendar(run_id)
            if cal.tasks_version != expected_tasks_version:
                raise ValueError("STALE_VERSION")
            t = next((t for t in cal.tasks if t.task_id == task_id), None)
            if t is None:
                raise KeyError(task_id)
            t.remaining_minutes = max(0, t.remaining_minutes - completed)
            t.status = "done" if t.remaining_minutes == 0 else "in_progress"
            nv = cal.tasks_version + 1
            self._q("UPDATE tasks SET body=?, tasks_version=? WHERE run_id=? AND task_id=?", (_dump(t), nv, run_id, task_id))
            self._q("UPDATE task_versions SET tasks_version=? WHERE run_id=?", (nv, run_id))
            return self.calendar(run_id)

    # ---- schedules ----
    def save_schedule(self, run_id: str, sched: Schedule) -> None:
        self._q("INSERT INTO schedules VALUES (?,?,?,?)", (run_id, sched.schedule_version, _dump(sched), _now()))

    def schedule(self, run_id: str, version: Optional[int] = None) -> Schedule:
        if version is None:
            r = self._q("SELECT body FROM schedules WHERE run_id=? ORDER BY schedule_version DESC LIMIT 1", (run_id,))
        else:
            r = self._q("SELECT body FROM schedules WHERE run_id=? AND schedule_version=?", (run_id, version))
        return Schedule.model_validate_json(r[0]["body"])

    # ---- proposals (replan jobs) ----
    def save_job(self, run_id: str, state_id: str, versions: dict, job: ReplanJob) -> None:
        self._q("INSERT OR REPLACE INTO proposals VALUES (?,?,?,?,?,?,COALESCE((SELECT created_at FROM proposals WHERE job_id=?),?),?)",
                (job.job_id, run_id, state_id, json.dumps(versions, sort_keys=True), job.status, _dump(job),
                 job.job_id, _now(), _now()))

    def job(self, job_id: str) -> Optional[ReplanJob]:
        r = self._q("SELECT body FROM proposals WHERE job_id=?", (job_id,))
        return ReplanJob.model_validate_json(r[0]["body"]) if r else None

    def job_for_state(self, run_id: str, state_id: str, versions: dict) -> Optional[ReplanJob]:
        """Idempotency without keys: same state + same input versions -> same job."""
        r = self._q("SELECT body FROM proposals WHERE run_id=? AND state_id=? AND versions=? AND status!='failed' "
                    "ORDER BY rowid DESC LIMIT 1", (run_id, state_id, json.dumps(versions, sort_keys=True)))
        return ReplanJob.model_validate_json(r[0]["body"]) if r else None

    def pending_jobs(self, run_id: str, versions: dict) -> list[ReplanJob]:
        """Undecided jobs for the CURRENT versions (a proposal for older versions is stale, not pending)."""
        rows = self._q("SELECT body FROM proposals WHERE run_id=? AND versions=? AND status IN ('queued','running','ready')",
                       (run_id, json.dumps(versions, sort_keys=True)))
        return [j for j in (ReplanJob.model_validate_json(r["body"]) for r in rows)
                if j.status != "ready" or j.proposal is not None]

    # ---- decisions ----
    def save_decision(self, decision_id: str, run_id: str, job_id: str, state_id: str, *, tool_results: list[dict],
                      rule_version: str, model_id: str, explanation_kind: str, before_version: int,
                      after_version: Optional[int], evidence_ids: list[str], explanation: str,
                      proposal: Optional[dict]) -> None:
        self._q("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (decision_id, run_id, job_id, state_id, json.dumps(tool_results, default=str), rule_version, model_id,
                 explanation_kind, before_version, after_version, json.dumps(evidence_ids), explanation,
                 json.dumps(proposal, default=str) if proposal is not None else None, None, _now()))

    def mark_applied(self, decision_id: str, after_version: int, replay_time: datetime) -> None:
        self._q("UPDATE decisions SET after_version=?, applied_replay_time=? WHERE decision_id=?",
                (after_version, replay_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), decision_id))

    def decision(self, decision_id: str) -> Optional[dict[str, Any]]:
        r = self._q("SELECT * FROM decisions WHERE decision_id=?", (decision_id,))
        if not r:
            return None
        d = dict(r[0])
        for k in ("tool_results", "evidence_ids", "proposal"):
            d[k] = json.loads(d[k]) if d[k] else ([] if k != "proposal" else None)
        return d

    def decisions(self, run_id: str) -> list[dict[str, Any]]:
        ids = [r["decision_id"] for r in self._q("SELECT decision_id FROM decisions WHERE run_id=? ORDER BY rowid", (run_id,))]
        return [self.decision(i) for i in ids]

    def last_applied_replay_time(self, run_id: str) -> Optional[datetime]:
        r = self._q("SELECT applied_replay_time FROM decisions WHERE run_id=? AND applied_replay_time IS NOT NULL "
                    "ORDER BY applied_replay_time DESC LIMIT 1", (run_id,))
        return datetime.fromisoformat(r[0]["applied_replay_time"].replace("Z", "+00:00")) if r else None
