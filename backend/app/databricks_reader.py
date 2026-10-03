"""Databricks Gold reader (integrator tasks 6 + 8). Same interface as sources.FixtureSource.
- One SQL query per poll (~5 s cache); bounded history ranges. Credentials from .env only (never the frontend).
- Every Gold row passes WearableState.model_validate at the boundary. On failure: emit pipeline.error and keep the
  last good state labeled stale. No rows yet -> latest() is None (API answers 503 STATE_NOT_READY).
- Never serve a stale row as fresh: if the newest row stops advancing while replay runs, mark stale and show lag.
SQL: databricks/sql/gold_latest.sql (Data B) when present, else the inline default below (same columns)."""
from __future__ import annotations

import json, os, pathlib, time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from pydantic import ValidationError

from contracts.models import ReplayStatus, WearableState
from backend.app.sources import WearableSnapshot
from backend.app.trigger import MinuteLoad

SQL_DIR = pathlib.Path(__file__).resolve().parents[2] / "databricks" / "sql"
WS_FIELDS = ("window_start", "window_end", "heart_rate_bpm", "physiological_load", "activity_level",
             "estimated_rest_minutes", "target_rest_minutes", "recovery_score", "baseline_id", "baseline_cutoff",
             "evidence_ids")
COLS = "run_id, participant_id, as_of, " + ", ".join(WS_FIELDS) + ", quality_json, activity_confound, source_kind"
MAX_HISTORY = timedelta(hours=6)


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    return v


def parse_gold_row(row: dict) -> tuple[WearableState, dict]:
    """Gold row -> (WearableState, extras). Raises ValidationError / ValueError on a contract violation."""
    q = row.get("quality_json")
    quality = json.loads(q) if isinstance(q, str) else q
    if quality is None:
        raise ValueError("quality_json is null")
    data = {f: _iso(row.get(f)) for f in WS_FIELDS if f in row}
    data["evidence_ids"] = list(row.get("evidence_ids") or [])
    if data.get("target_rest_minutes") is None:
        data.pop("target_rest_minutes", None)
    ws = WearableState.model_validate({**data, "quality": quality})
    as_of = row.get("as_of") or row["window_end"]
    extras = {"run_id": row["run_id"], "participant_id": str(row["participant_id"]),
              "as_of": datetime.fromisoformat(str(_iso(as_of)).replace("Z", "+00:00")),
              "activity_confound": bool(row.get("activity_confound")), "source_kind": row.get("source_kind") or "recorded_replay"}
    return ws, extras


class DatabricksSource:
    POLL_SECONDS = 5.0
    STALE_AFTER_SECONDS = 30.0

    def __init__(self, connect: Callable[[], Any], table: str, run_id: Optional[str] = None,
                 mode: str = "live_databricks"):
        self._connect, self.table, self.run_id, self.mode = connect, table, run_id, mode
        self.label = "Recorded wearable replay via Databricks" if mode == "live_databricks" else \
            "Feature replay (saved derived results)"
        self.on_error: Callable[[str, str], None] = lambda code, msg: None
        self._conn = None
        self._last_poll = 0.0
        self._good: Optional[WearableSnapshot] = None
        self._good_changed_at = 0.0
        self.state, self.speed = "idle", 1.0

    @classmethod
    def from_env(cls) -> "DatabricksSource":
        host, token, wh = (os.getenv(k, "") for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_SQL_WAREHOUSE_ID"))
        if not (host and token and wh):
            raise RuntimeError("FOCUSFLOW_DATA_SOURCE=databricks needs DATABRICKS_HOST/TOKEN/SQL_WAREHOUSE_ID in .env")

        def connect():
            from databricks import sql  # lazy: fixture mode never needs the connector
            return sql.connect(server_hostname=host.replace("https://", "").rstrip("/"),
                               http_path=f"/sql/1.0/warehouses/{wh}", access_token=token)
        table = f"{os.getenv('DATABRICKS_CATALOG', 'focusflow')}.{os.getenv('DATABRICKS_SCHEMA', 'main')}.gold_wearable_state"
        mode = "saved_replay" if os.getenv("FOCUSFLOW_REPLAY_MODE", "live") == "saved" else "live_databricks"
        return cls(connect, table, os.getenv("FOCUSFLOW_RUN_ID") or None, mode)

    # ---- SQL ----
    def _query(self, sql: str, params: dict) -> list[dict]:
        if self._conn is None:
            self._conn = self._connect()
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

    def _latest_sql(self) -> str:
        f = SQL_DIR / "gold_latest.sql"
        if f.exists():
            return f.read_text().replace("${table}", self.table)
        where = "WHERE run_id = :run_id" if self.run_id else ""
        return f"SELECT {COLS} FROM {self.table} {where} ORDER BY window_end DESC LIMIT 1"

    # ---- interface ----
    def poll(self) -> None:
        """One query per poll. Invalid rows never replace the last good state."""
        self._last_poll = time.monotonic()
        try:
            rows = self._query(self._latest_sql(), {"run_id": self.run_id} if self.run_id else {})
        except Exception as e:  # noqa: BLE001 - warehouse cold / network: keep last good, label stale
            self.on_error("DATABRICKS_QUERY_FAILED", str(e)[:300])
            return
        if not rows:
            return
        try:
            ws, ex = parse_gold_row(rows[0])
        except (ValidationError, ValueError, KeyError) as e:
            self.on_error("GOLD_CONTRACT_VIOLATION", str(e)[:300])
            if self._good: self._good.stale = True
            return
        key = f"{ex['run_id']}:{ws.window_end:%Y%m%dT%H%M}"
        if self._good is None or key != self._good.key:
            self._good_changed_at = time.monotonic()
        self._good = WearableSnapshot(key=key, run_id=ex["run_id"], participant_id=ex["participant_id"], as_of=ex["as_of"],
                                      source_kind=ex["source_kind"], wearable=ws, activity_confound=ex["activity_confound"])

    def latest(self) -> Optional[WearableSnapshot]:
        if time.monotonic() - self._last_poll >= self.POLL_SECONDS:
            self.poll()
        if self._good is None:
            return None
        g = self._good
        idle = time.monotonic() - self._good_changed_at
        if self.state == "running" and idle > self.STALE_AFTER_SECONDS:
            g.stale = True
        g.lag_seconds = round(idle, 1) if self.state == "running" else None
        return g

    def history(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> list[dict]:
        clock = self._good.as_of if self._good else None
        if clock is None:
            return []
        end = min(end, clock) if end else clock
        start = max(start, end - MAX_HISTORY) if start else end - timedelta(hours=2)
        rows = self._query(f"SELECT {COLS} FROM {self.table} WHERE window_end > :start AND window_end <= :end"
                           + (" AND run_id = :run_id" if self.run_id else "") + " ORDER BY window_end LIMIT 2000",
                           {"start": start, "end": end, **({"run_id": self.run_id} if self.run_id else {})})
        out = []
        for r in rows:
            try:
                ws, _ = parse_gold_row(r)
            except (ValidationError, ValueError, KeyError) as e:
                self.on_error("GOLD_CONTRACT_VIOLATION", str(e)[:300]); continue
            out.append({"window_start": _iso(ws.window_start), "window_end": _iso(ws.window_end),
                        "heart_rate_bpm": ws.heart_rate_bpm, "physiological_load": ws.physiological_load,
                        "activity_level": ws.activity_level, "quality": ws.quality.status,
                        "evidence_id": (ws.evidence_ids or [None])[0]})
        return out

    def minute_loads(self, end: datetime, minutes: int) -> list[MinuteLoad]:
        rows = self.history(end - timedelta(minutes=minutes), end)
        ts = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
        return [MinuteLoad(ts(r["window_end"]), r["physiological_load"] if r["quality"] == "sufficient" else None) for r in rows]

    def status(self, run_id: Optional[str]) -> ReplayStatus:
        g = self._good
        return ReplayStatus(run_id=run_id, mode=self.mode, state=self.state, speed=self.speed,
                            published_time=None, processed_time=g.as_of if g else None,
                            lag_seconds=g.lag_seconds if g else None)

    # Replay control: Data A's simulator.replay.ReplayController is wired here in task 7. Until then, local state only.
    def start(self, speed: float = 1.0, bookmark: Optional[datetime] = None) -> None:
        self.state, self.speed = "running", speed

    def pause(self) -> None:
        self.state = "paused"

    def reset(self) -> None:
        self.state, self._good = "idle", None
