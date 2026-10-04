"""Databricks Gold reader (integrator tasks 6 + 8). Same interface as sources.FixtureSource.
- One SQL query per poll (~5 s cache); bounded history ranges. Credentials from .env only (never the frontend).
- Every Gold row passes WearableState.model_validate at the boundary. On failure: emit pipeline.error and keep the
  last good state labeled stale. No rows yet -> latest() is None (API answers 503 STATE_NOT_READY).
- Never serve a stale row as fresh: if the newest row stops advancing while replay runs, mark stale and show lag.
SQL: databricks/sql/gold_latest.sql (Data B) when present, else the inline default below (same columns).
Feature replay (FOCUSFLOW_REPLAY_MODE=saved): the same reader over Data B's exported CSV
(data/derived/<run_id>/feature_replay/gold.csv) via SavedGoldConnection; no Databricks credentials needed."""
from __future__ import annotations

import ast, json, os, pathlib, time, uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from pydantic import ValidationError

from contracts.models import ReplayStatus, WearableState
from backend.app.sources import WearableSnapshot
from backend.app.trigger import MinuteLoad

ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "databricks" / "sql"
# databricks-sql-connector defaults both the per-socket timeout and the total retry duration to 900s
# (15 minutes, to tolerate a cold cluster start). A request thread waiting on /api/state cannot wait
# that long: a stopped SQL warehouse (auto_stop_mins is commonly 10) makes every poll after an idle
# period retry silently for up to 15 minutes with no error, which looks exactly like a hang. Bound both
# knobs so a slow or stopped warehouse fails fast instead.
CONNECT_TIMEOUT_SECONDS = 30.0
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
    ev = row.get("evidence_ids")
    if isinstance(ev, str):
        ev = ast.literal_eval(ev)  # CSV: "['window-…']"
    # `ev or []` would call bool(ev) first: fine for a Python list/None, but a live Databricks row's
    # evidence_ids (ARRAY<STRING>) comes back as a numpy array with pyarrow installed, and numpy raises
    # "truth value of an array with more than one element is ambiguous" instead of ever reaching `or`.
    data["evidence_ids"] = [] if ev is None else [str(x) for x in ev]
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
    STALE_REPLAY_SECONDS = 300.0

    def __init__(self, connect: Callable[[], Any], table: str, run_id: Optional[str] = None,
                 mode: str = "live_databricks", replay: Any = None, scenario_id: str = "trigger",
                 default_bookmark: Optional[datetime] = None):
        self._connect, self.table, self.run_id, self.mode = connect, table, run_id, mode
        self.label = "Recorded wearable replay via Databricks" if mode == "live_databricks" else \
            "Feature replay (saved derived results)"
        self.on_error: Callable[[str, str], None] = lambda code, msg: None
        self._conn = None
        self._last_poll = 0.0
        self._good: Optional[WearableSnapshot] = None
        self._good_changed_at = 0.0
        self._state, self._speed = "idle", 1.0
        # Local replay clock (no controller): Gold holds the whole run, so reads stop at bookmark + elapsed * speed.
        self._clock_base, self._clock_started, self._clock_elapsed = default_bookmark, 0.0, 0.0
        # Task 7: Data A's simulator.replay.ReplayController (None -> local replay state only, e.g. feature replay).
        self.replay, self.scenario_id, self.default_bookmark = replay, scenario_id, default_bookmark
        if replay is not None:
            replay.processed_reader = self._processed_time

    @property
    def state(self) -> str:
        return self.replay.state if self.replay is not None else self._state

    @property
    def speed(self) -> float:
        return self.replay.speed if self.replay is not None else self._speed

    @classmethod
    def from_env(cls) -> "DatabricksSource":
        mode = "saved_replay" if os.getenv("FOCUSFLOW_REPLAY_MODE", "live").split("#")[0].strip() == "saved" else "live_databricks"
        run_id = os.getenv("FOCUSFLOW_RUN_ID", "").split("#")[0].strip() or None
        if mode == "saved_replay":
            if not run_id:
                raise RuntimeError("FOCUSFLOW_REPLAY_MODE=saved needs FOCUSFLOW_RUN_ID (reads data/derived/<run_id>/feature_replay/gold.csv)")
            conn = SavedGoldConnection(ROOT / "data" / "derived" / run_id / "feature_replay" / "gold.csv")
            connect, table = (lambda: conn), str(conn.path)
        else:
            host, token, wh = (os.getenv(k, "") for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_SQL_WAREHOUSE_ID"))
            if not (host and token and wh):
                raise RuntimeError("FOCUSFLOW_DATA_SOURCE=databricks needs DATABRICKS_HOST/TOKEN/SQL_WAREHOUSE_ID in .env")

            def connect():
                from databricks import sql  # lazy: fixture mode never needs the connector
                return sql.connect(server_hostname=host.replace("https://", "").rstrip("/"),
                                   http_path=f"/sql/1.0/warehouses/{wh}", access_token=token,
                                   _socket_timeout=CONNECT_TIMEOUT_SECONDS,
                                   _retry_stop_after_attempts_duration=CONNECT_TIMEOUT_SECONDS)
            table = f"{os.getenv('DATABRICKS_CATALOG', 'focusflow')}.{os.getenv('DATABRICKS_SCHEMA', 'main')}.gold_wearable_state"
        replay, bookmark = (_replay_from_env() if mode == "live_databricks" else (None, None))
        bookmark = bookmark or _bookmark_from_env()
        src = cls(connect, table, run_id, mode, replay=replay,
                  scenario_id=os.getenv("FOCUSFLOW_FIXTURE", "trigger").split()[0], default_bookmark=bookmark)
        synthetic = conn.synthetic if mode == "saved_replay" else \
            os.getenv("FOCUSFLOW_REPLAY_SOURCE_KIND", "").split("#")[0].strip().startswith("synthetic")
        if synthetic:
            src.label = "SYNTHETIC mock wearable replay via Databricks - not real wearable data" if mode == "live_databricks" \
                else "SYNTHETIC feature replay (saved derived results) - not real wearable data"
        return src

    # ---- SQL ----
    def _query(self, sql: str, params: dict) -> list[dict]:
        try:
            if self._conn is None:
                self._conn = self._connect()
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                names = [d[0] for d in cur.description]
                return [dict(zip(names, r)) for r in cur.fetchall()]
        except Exception:
            # Connect timed out, the session died mid-query, or the warehouse reset the socket: drop the
            # connection so the next poll opens a fresh one instead of reusing one that may be half-open.
            self._conn = None
            raise

    def _latest_sql(self, clock: bool = False) -> str:
        f = SQL_DIR / "gold_latest.sql"
        if self.run_id and f.exists():  # Data B's file always binds :run_id
            sql = "\n".join(l for l in f.read_text().splitlines() if not l.lstrip().startswith("--"))
            sql = sql.strip().rstrip(";").replace("${table}", self.table)
            return sql.replace("ORDER BY", "AND as_of <= :clock\nORDER BY", 1) if clock else sql
        conds = (["run_id = :run_id"] if self.run_id else []) + (["as_of <= :clock"] if clock else [])
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return f"SELECT {COLS} FROM {self.table} {where} ORDER BY window_end DESC LIMIT 1"

    def clock(self) -> Optional[datetime]:
        """Replay clock (scenario time). None = unknown -> read the newest Gold row (no bookmark configured)."""
        if self.replay is not None:
            return self.replay.published_time
        if self._clock_base is None:
            return None
        elapsed = self._clock_elapsed + ((time.monotonic() - self._clock_started) * self._speed
                                         if self._state == "running" else 0.0)
        return self._clock_base + timedelta(seconds=elapsed)

    # ---- interface ----
    def poll(self) -> None:
        """One query per poll. Invalid rows never replace the last good state."""
        self._last_poll = time.monotonic()
        clock = self.clock()
        if clock is None and self.replay is not None and self.replay.state == "idle":
            return  # live replay not started: nothing of this run is published yet
        params = ({"run_id": self.run_id} if self.run_id else {}) | ({"clock": clock} if clock else {})
        try:
            rows = self._query(self._latest_sql(clock is not None), params)
        except Exception as e:  # noqa: BLE001 - warehouse cold / network: keep last good, label stale
            self.on_error("DATABRICKS_QUERY_FAILED", str(e)[:300])
            if self._good: self._good.stale = True
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
        g, clock = self._good, self.clock()
        idle = time.monotonic() - self._good_changed_at
        behind = (clock - g.as_of).total_seconds() if clock else None  # replay seconds Gold trails the clock
        # Stale = no new row for a while AND Gold trails the replay clock (Gold is per minute, so allow a few minutes).
        if self.state == "running" and idle > self.STALE_AFTER_SECONDS and (behind is None or behind > self.STALE_REPLAY_SECONDS):
            g.stale = True
        g.lag_seconds = round(max(behind, 0.0), 1) if behind is not None else (round(idle, 1) if self.state == "running" else None)
        return g

    def history(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> list[dict]:
        clock = self._good.as_of if self._good else None
        if clock is None:
            return []
        end = min(end, clock) if end else clock
        start = max(start, end - MAX_HISTORY) if start else end - timedelta(hours=2)
        run_id = self.run_id or self._good.run_id  # blank FOCUSFLOW_RUN_ID: never mix runs in one history
        rows = self._query(f"SELECT {COLS} FROM {self.table} WHERE run_id = :run_id AND window_end > :start"
                           " AND window_end <= :end ORDER BY window_end LIMIT 2000",
                           {"start": start, "end": end, "run_id": run_id})
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
        if self.replay is not None:  # published_time from the controller, processed_time from Gold as_of
            return self.replay.status()
        g, clock = self._good, self.clock()
        return ReplayStatus(run_id=run_id, mode=self.mode, state=self.state, speed=self.speed,
                            published_time=clock, processed_time=g.as_of if g else None,
                            lag_seconds=max(0.0, (clock - g.as_of).total_seconds()) if g and clock else None)

    def _processed_time(self, run_id: str) -> Optional[datetime]:
        g = self._good
        return g.as_of if g is not None and g.run_id == run_id else None

    def _follow(self, run_id: str) -> None:
        """Gold reads follow the controller's run; the previous run's state is never shown as this run's."""
        self.run_id, self._good, self._last_poll = run_id, None, 0.0

    def _default_clock(self) -> Optional[datetime]:
        """No bookmark was ever configured for this run (no FOCUSFLOW_REPLAY_SCENARIO_START, no explicit
        bookmark on start()). Without this, clock() stays None forever and poll() reads the newest Gold
        row on every single poll -- for a finite replayed run that row never changes, so the UI looks
        frozen even though every request returns 200. Default to 24h after the run's earliest Gold row
        (clear of baseline_warmup) instead. Returns None (leaving the old "read the newest row" behavior)
        if run_id is unset or the lookup itself fails -- this is a best-effort default, never a hard error."""
        if not self.run_id:
            return None
        try:
            rows = self._query(f"SELECT {COLS} FROM {self.table} WHERE run_id = :run_id ORDER BY window_end ASC LIMIT 1",
                               {"run_id": self.run_id, "earliest": True})
        except Exception:
            return None
        if not rows or rows[0].get("window_end") is None:
            return None
        we = rows[0]["window_end"]
        if isinstance(we, str):
            we = datetime.fromisoformat(we.replace("Z", "+00:00"))
        elif we.tzinfo is None:
            we = we.replace(tzinfo=timezone.utc)
        return we + timedelta(hours=24)

    # Replay control (task 7). Controller errors (e.g. speed not in 1/10/60/300) raise ValueError -> API 409.
    def start(self, speed: float = 1.0, bookmark: Optional[datetime] = None) -> None:
        if self.replay is None:
            if bookmark is None and self._clock_base is None:  # never configured: don't default to "newest row forever"
                bookmark = self._default_clock()
                if bookmark is not None:
                    print(f"DatabricksSource: no bookmark configured for run_id={self.run_id!r}; "
                          f"defaulting clock to {bookmark.isoformat()} (earliest Gold row + 24h warm-up)")
            if bookmark is not None and bookmark != self._clock_base:  # jump: restart the local clock there
                self._clock_base, self._clock_elapsed, self._last_poll = bookmark, 0.0, 0.0
            elif self._state == "running":  # speed change keeps the current position
                self._clock_elapsed += (time.monotonic() - self._clock_started) * self._speed
            self._state, self._speed, self._clock_started = "running", speed, time.monotonic()
            return
        r, bookmark = self.replay, bookmark or self.default_bookmark
        if r.run_id and r.state != "idle" and bookmark == self._replay_bookmark:
            if r.state == "running":
                r.set_speed(speed)
            else:  # resume the same run from pause
                r.start(r.run_id, self.scenario_id, speed, bookmark)
            return
        r.pause()
        self._follow(r.start(f"replay-{uuid.uuid4().hex}", self.scenario_id, speed, bookmark))
        self._replay_bookmark = bookmark

    _replay_bookmark: Optional[datetime] = None

    def pause(self) -> None:
        if self.replay is None:
            if self._state == "running":
                self._clock_elapsed += (time.monotonic() - self._clock_started) * self._speed
            self._state = "paused"
        else:
            self.replay.pause()

    def reset(self) -> None:
        if self.replay is None:
            self._state, self._good, self._clock_elapsed, self._last_poll = "idle", None, 0.0, 0.0
            self._clock_base = self.default_bookmark
        elif self.replay.scenario_id is None:  # never started: nothing to reset
            self._good = None
        else:  # Data A semantics: new run id + checkpoint, old audit files kept, replay restarts from the bookmark
            self._follow(self.replay.reset())


class SavedGoldConnection:
    """Feature replay: Data B's exported Gold CSV behind the DB-API calls DatabricksSource makes, so the saved rung
    reads exactly like live Databricks (as_of <= clock, run_id, bounded history). Loaded once; rows keep CSV text
    for quality_json / evidence_ids and parse_gold_row validates them like any Gold row."""
    TIME_COLS = ("as_of", "window_start", "window_end", "baseline_cutoff")

    def __init__(self, path: pathlib.Path):
        import pandas as pd
        self.path = pathlib.Path(path)
        if not self.path.exists():
            raise RuntimeError(f"feature replay file not found: {self.path} (run databricks.features.export_gold_fixture)")
        df = pd.read_csv(self.path, dtype={"participant_id": str, "run_id": str, "quality_json": str, "evidence_ids": str})
        for c in self.TIME_COLS:
            df[c] = pd.to_datetime(df[c], utc=True)
        df = df.sort_values("window_end", kind="stable")
        df = df.astype(object).where(df.notna(), None)  # NaN / NaT -> None (missing values keep their reasons)
        self.rows = [{k: (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for k, v in r.items()}
                     for r in df.to_dict("records")]
        self.synthetic = bool(self.rows) and all(r.get("source_kind") == "synthetic_fixture" for r in self.rows)
        self.description: list = []
        self._out: list[dict] = []

    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql: str, params: dict) -> None:
        rows = [r for r in self.rows if params.get("run_id") in (None, r["run_id"])]
        if params.get("earliest"):  # _default_clock(): earliest row for this run (self.rows sorted ascending)
            self._out = rows[:1]
        elif "start" in params:  # history(): window_end in (start, end], oldest first
            self._out = [r for r in rows if params["start"] < r["window_end"] <= params["end"]][:2000]
        else:  # latest row published by the replay clock
            clock = params.get("clock")
            self._out = [r for r in rows if clock is None or r["as_of"] <= clock][-1:]
        self.description = [(k,) for k in (self.rows[0] if self.rows else {})]

    def fetchall(self) -> list[tuple]:
        return [tuple(r.values()) for r in self._out]


def _replay_from_env() -> tuple[Any, Optional[datetime]]:
    """Build Data A's ReplayController like simulator/run_demo.py. Needs FOCUSFLOW_REPLAY_RAW_DIR; else (None, None).
    Returns (controller, default bookmark = scenario start + history hours)."""
    raw = os.getenv("FOCUSFLOW_REPLAY_RAW_DIR", "").strip()
    if not raw:
        return None, None
    from simulator.replay import ReplayController
    from simulator.run_demo import aware, csv_source
    from databricks.ingestion.landing_writer import LandingWriter, SDKStore
    env = lambda k, d=None: (os.getenv(k) or "").split("#")[0].strip() or d
    source_start, scenario_start = aware(env("FOCUSFLOW_REPLAY_SOURCE_START")), aware(env("FOCUSFLOW_REPLAY_SCENARIO_START"))
    history, demo = int(env("FOCUSFLOW_REPLAY_HISTORY_HOURS", "48")), int(env("FOCUSFLOW_REPLAY_DEMO_HOURS", "36"))
    shift = env("FOCUSFLOW_REPLAY_SHIFT_DAYS")
    source = csv_source(raw, source_start, source_start + timedelta(hours=history + demo), scenario_start,
                        source_timezone=env("FOCUSFLOW_REPLAY_SOURCE_TZ"),
                        source_kind=env("FOCUSFLOW_REPLAY_SOURCE_KIND", "recorded_replay"),
                        wall_time_shift_days=int(shift) if shift else None)
    root = env("DATABRICKS_VOLUME_PATH", "/Volumes/focusflow/main/landing")
    writer = LandingWriter(root, SDKStore() if root.startswith("/Volumes/") else None)
    controller = ReplayController(source, writer, batch_size=int(env("FOCUSFLOW_REPLAY_BATCH_SIZE", "100000")))
    return controller, scenario_start + timedelta(hours=history)


def _bookmark_from_env() -> Optional[datetime]:
    """Default replay position without a controller: scenario start + history hours (same as Data A's run_demo)."""
    env = lambda k, d=None: (os.getenv(k) or "").split("#")[0].strip() or d
    start = env("FOCUSFLOW_REPLAY_SCENARIO_START")
    if not start:
        return None
    return datetime.fromisoformat(start).astimezone(timezone.utc) + timedelta(hours=int(env("FOCUSFLOW_REPLAY_HISTORY_HOURS", "48")))
