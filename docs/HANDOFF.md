# WolfHacks 2026 — Adaptive Exam-Week Copilot

**Working name:** FocusFlow (alternatives discussed: CramSense, PulsePlan)  
**Document date:** October 3, 2026  
**Status:** Implementation handoff; proposed contracts and defaults for team review  
**Origin:** The “Wearable AI Project Idea” discussion

> Replay one person's recorded wearable signals through Databricks, overlay a synthetic exam-week workload, and let a tool-calling agent request a constrained study-plan revision and explain the evidence behind it.

This document preserves the project direction from the discussion and fills in engineering details needed for independent development. **Nothing here implies that the application, pipeline, scores, or demo has already been implemented or validated.** Owner letters are placeholders. JSON examples, score thresholds, dates, and schedules below are illustrative fixtures, not observations from an inspected participant.

## 1. Product idea and scope

The student supplies exams, deadlines, remaining study estimates, task priorities, preferred study hours, fixed commitments, and a protected sleep window. A replay service supplies changing wearable context. The system asks:

**Given the work still remaining, the time available, and the recent wearable patterns, should the study plan change?**

The central interaction is an observable action: flexible study blocks move, immovable commitments stay in place, and the student sees why the revision occurred. The agent investigates and explains; a deterministic Python scheduler decides exact times and checks constraints.

### Decisions carried forward from the discussion

- Use **one BIG IDEAs participant**, targeting their available 8–10-day recording.
- Replay recorded signals chronologically through **Databricks Structured Streaming**.
- Overlay a clearly labeled **synthetic exam calendar**.
- Use personal baseline comparisons and interpretable features rather than training a large new model.
- Separate data, dashboard, agent, scheduler, and API responsibilities.
- Work in one GitHub monorepo, with stable interfaces and fixtures for parallel development.
- Build a browser dashboard with React/TypeScript; a native desktop wrapper is optional later.
- Keep schedule generation deterministic and separate from the LLM.

### Proposed defaults added by this handoff

Use server-sent events (SSE) for dashboard updates, file-based replay ingestion, an API-side Databricks reader, versioned schedule proposals, and explicit quality gates. These resolve open implementation choices; they are not prior team commitments.

### What changed from earlier brainstorming

The conversation began with a baby-monitor concept, then explored metabolic insights and a second dataset called IMU50. The exam-week copilot is the selected direction for this handoff. Infant monitoring, audio, SpO₂, glucose prediction, and joining datasets are outside the MVP. Do not treat separate studies as recordings of the same people. Glucose and meals may become secondary context after the planning loop works.

## 2. Evidence, synthetic context, and honest framing

The BIG IDEAs release describes 16 adults aged 35–65, monitored for 8–10 days with an Empatica E4 and Dexcom G6. Dates were shifted for de-identification. It provides HR, EDA, ACC, IBI, skin temperature, BVP, glucose, and food logs; the documented files do not supply exam calendars or ground-truth sleep/stress annotations. This is not a student exam study. [Dataset documentation](https://physionet.org/content/big-ideas-glycemic-wearable/1.1.3/)

| Category | What the application uses | What to display |
|---|---|---|
| Recorded measurements | Selected participant wearable channels | “Recorded wearable data” |
| Derived estimates | Arousal/load index, movement, likely rest intervals | “Estimated” and quality status |
| Synthetic context | Exams, assignments, study estimates, preferences | “Synthetic exam-week scenario” |
| Agent output | Explanation of retrieved evidence and validated schedule changes | Evidence timestamps and schedule revision |
| Optional injected scenario | Fabricated sensor values for development or a fallback | “Synthetic sensor scenario” |

Use **Physiological Load**, **Estimated Rest**, **Estimated Recovery**, and **Academic Pressure**. Do not claim to measure psychological stress, diagnose poor sleep, infer sleep stages, predict grades, or prove that a revised plan improves health or performance. Inactivity may be quiet wakefulness or a removed device. Elevated HR and EDA may have several explanations.

Suggested pitch:

> FocusFlow combines replayed wearable data with a synthetic exam-week calendar. When sustained physiological load, limited estimated rest, and upcoming deadlines coincide, an agent investigates the evidence, requests a valid schedule revision, and explains what changed.

## 3. System architecture

```text
Recorded participant CSVs
          |
          v
Dataset adapter + chronological replay controller
          |
          v
New event files in a Databricks-readable landing location
          |
          v
Structured Streaming -> Bronze: normalized wearable events
          |
          v
Structured Streaming -> Silver: one-minute features + quality
          |
          v
Incremental state computation -> Gold: WearableState history
          |
          v
FastAPI Databricks reader + latest-state cache
          |
          +---- Synthetic calendar + task progress
          |                |
          v                v
      StudentState composer + deterministic trigger rules
          |
          v
Tool-calling agent -> Python scheduler -> validated proposal
          |                                  |
          +---- explanation + decision log ---+
                                             |
                                             v
                          Versioned in-app schedule commit
                                             |
                                             v
                                  SSE -> React dashboard
```

Databricks supports Delta tables as Structured Streaming sources and sinks. This makes it suitable for incremental ingestion and a history that the application can query. [Delta streaming documentation](https://docs.databricks.com/aws/en/structured-streaming/delta-lake)

### Ownership refinement: wearable state versus student state

The original sketch put academic pressure and wearable estimates together in `gold_student_state`. To avoid two teams owning the same calculations, use this default:

- **Databricks owns `WearableState`:** features, baselines, quality, activity and rest estimates.
- **The backend owns academic context:** calendar, remaining work, time until exams, and pressure.
- **The backend composes `StudentState`:** the single object used by the agent and frontend.
- **The scheduler owns feasibility:** whether the requested work actually fits the available time.

Name the initial Gold table `gold_wearable_state`. If the team later needs a fully joined `gold_student_state` table, persist the composed snapshots with calendar/task versions. Do not implement competing pressure formulas in Spark and FastAPI.

### Databricks-to-application bridge

FastAPI reads new Gold rows through a server-side adapter, caches the latest state, and publishes changes to the browser. A proposed initial reader uses Databricks SQL access; verify the team's workspace supports the required compute and credentials. The official Python SQL connector provides a supported query interface. [Connector documentation](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector)

Poll after new batches become available, starting around every five seconds and adjusting after measurement. This is a tuning target, not a latency promise. Use a stable cursor such as `(run_id, window_end, state_id)`, not only “latest timestamp.” Never put Databricks credentials in the frontend. UI refresh rate and actual streaming latency are separate measurements.

## 4. Team split and collaboration

| Owner | Module / owned paths | Deliverable | Dependency boundary |
|---|---|---|---|
| A | `databricks/`, `simulator/` | Replay, Bronze/Silver/Gold, quality report, `WearableState` | Publishes contract-shaped records |
| B | `frontend/` | Calendar, signal timeline, state cards, explanations, replay controls | Uses HTTP/SSE and fixtures |
| C | `agent/` | Tools, prompts, investigation flow, grounded explanations | Consumes `StudentState`; calls scheduler wrapper |
| D | `scheduler/` | Initial plan, replanning, constraint validator, schedule diff | Pure Python functions with typed inputs/outputs |
| E or named integrator | `backend/`, `contracts/`, shared config | API, state composition, persistence, integration | Owns cross-module orchestration |

**Four people:** A/B/C/D own their modules; assign one of them explicit integration responsibility and reduce that person's feature scope. **Three people:** combine agent and scheduler; name an integration owner. Do not leave shared responsibilities as “everyone will handle it.”

### Suggested monorepo

```text
focusflow/
├── frontend/             # React UI and API client
├── backend/              # FastAPI, state composition, persistence, SSE
├── databricks/
│   ├── ingestion/
│   ├── streaming/
│   ├── features/
│   └── sql/
├── simulator/            # CSV adapter, replay clock, scenario manifests
├── agent/                # Tool definitions, prompts, orchestration
├── scheduler/            # Pure scheduling logic and validation
├── contracts/            # JSON Schema + API specification
├── fixtures/             # Small, clearly synthetic development examples
├── tests/                # Cross-module contract/integration checks
├── docs/                 # Decisions, data provenance, demo runbook
├── .env.example          # Names only; no real credentials
└── README.md             # Quick start and module entry points
```

### GitHub and AI-assisted development rules

1. Freeze contract version `1.0` and representative fixtures before independent implementation.
2. Use short feature branches and small PRs scoped to owned directories.
3. Designate one owner for root dependencies, lockfiles, environment examples, CI, and contract changes.
4. Discuss cross-module changes in an issue/PR; update producer, consumers, and fixtures together.
5. Give Claude/Codex the same handoff, module instructions, contract version, and acceptance criteria.
6. Ask coding assistants to avoid edits outside their module without coordinating with its owner.
7. Keep raw participant files, large exports, credentials, and local environment files out of Git.
8. Merge an end-to-end fixture path early; integrate real data incrementally.

Suggested teammate prompt: “Implement the assigned module against `contracts/` and `fixtures/`. Follow this handoff. Keep public field names unchanged, document assumptions, and include the module's acceptance checks. Propose any contract change before implementing it.”

## 5. Technology choices

| Area | Proposed choice | Rationale / scope |
|---|---|---|
| Dashboard | React + TypeScript + Vite | Browser application with typed API models |
| Styling / plots | Tailwind CSS + Recharts | Small design system and time-series views |
| Calendar | Simple custom weekly grid; FullCalendar optional | Prioritize movable blocks and a readable diff |
| API | Python + FastAPI + Pydantic | Shared language with data, agent, scheduler |
| Live UI updates | SSE; regular HTTP for commands | One-way event delivery fits the demo |
| Data pipeline | PySpark + Structured Streaming + Delta Lake | Incremental signal processing and queryable history |
| Agent | Tool-capable LLM behind a provider adapter | Keep provider choice independent of module APIs |
| Agent hosting | Databricks-hosted if access is ready; local backend fallback | Deployment must not block tool development |
| Scheduler | Plain Python greedy algorithm | Deterministic, testable constraint enforcement |
| App persistence | SQLite for a single backend process | Store tasks, schedules, proposals, decisions |
| Tests | pytest, JSON Schema validation, frontend build/checks | Focus on boundaries and schedule correctness |
| Collaboration | GitHub monorepo + directory ownership | Limit overlapping edits |

Databricks offers agent tool integration, including Unity Catalog functions and MCP-based access. Local Python tool wrappers are adequate for the first integration; adopting a managed tool surface is optional and depends on workspace availability. [Agent tools documentation](https://docs.databricks.com/aws/en/agents/mcp-tools)

Pin actual dependency versions at setup after confirming the Databricks runtime. Tauri, Kafka, a vector database, a complex solver, native wearable hardware, and multi-user deployment are not prerequisites.

## 6. Data selection and intake

Use BIG IDEAs version **1.1.3**. Its documented nominal rates are HR 1 Hz; EDA and temperature 4 Hz; ACC 32 Hz; BVP 64 Hz; glucose every five minutes. IBI is event-based. Typical signal files have `Timestamp`/`Value`, while ACC has `Timestamp`/`X`/`Y`/`Z`. The full release is 34.1 GB uncompressed, so select only needed participant files. [Dataset details](https://physionet.org/content/big-ideas-glycemic-wearable/1.1.3/)

| Signal | Priority | Planned use |
|---|---|---|
| HR | Required | Minute statistics and personal baseline deviation |
| EDA | Required | Minute statistics, trend, baseline deviation |
| ACC | Required | Movement context and rest-candidate screening |
| IBI | Add once core path works | Quality-gated pulse-interval variability |
| TEMP | Secondary | Skin-temperature trend / sensor context |
| Dexcom | Optional | Separate contextual chart; no core trigger dependency |
| Food logs | Optional | Historical context after MVP |
| BVP | Defer | Raw waveform processing adds scope |

### What the data owner needs next

- Candidate participant ID and actual available recording dates.
- Headers and a few hundred sample rows from HR, EDA, ACC, IBI, TEMP; Dexcom if desired.
- File sizes, row counts, timestamp examples, observed units, duplicate counts, and gaps.
- Confirmation of any timestamp timezone assumptions; do not silently assume UTC.
- An overlap/coverage report, especially for overnight periods and the intended demo segment.

Select for usable coverage first. Inspect several candidate segments if necessary; no participant is selected by this document. Preserve source filenames, dataset version, checksums, and all transformations in `docs/data-provenance.md`.

## 7. Processing plan

### 7.1 Normalize and validate

Parse files with a dataset-specific adapter, preserve original timestamps, and convert to a documented internal time basis. Reject or flag malformed values and units. Sort within each signal; merge signal streams by time. Retain source row identity for reproducibility.

Represent ACC as a three-value vector so axes remain aligned. Verify accelerometer scaling before converting to `g`; verify IBI units before converting to milliseconds. Mark units as unresolved and block affected feature calculations until checked. Do not treat missing readings as zeros.

### 7.2 Bronze: normalized events

`bronze_wearable_events` stores append-only events with source provenance, signal, units, event time, ingestion time, run identity, and quality. A source-row-based event ID makes replay deterministic. Deduplicate on `(run_id, event_id)`; another replay run must not collide with a prior run.

The source stream should see only completed immutable landing files. Publish each batch once using a staging mechanism appropriate to the storage system. Begin with file ingestion rather than introducing a message broker.

### 7.3 Silver: one row per minute

Use half-open windows `[window_start, window_end)`, grouped by participant and replay run. Compute:

| Feature family | Proposed fields | Processing notes |
|---|---|---|
| HR | `hr_mean_bpm`, min/max/std, `hr_baseline_z` | Report coverage with statistics |
| EDA | Mean/std, minute-to-minute change, `eda_baseline_z` | Consider a documented log transform for baseline comparisons |
| Movement | Dynamic magnitude mean/std/max, `stillness_ratio` | Remove gravity/static offset or use magnitude variation; raw magnitude alone is not movement intensity |
| IBI | Mean IBI, `rmssd_ms`, `sdnn_ms` | Compute over a trailing five-minute clean segment, emitted each minute; null if insufficient |
| Temperature | Mean and change | Skin temperature only |
| Glucose, optional | Latest value, age, change | A display carry-forward does not create a new measurement |
| Quality | Per-signal counts/coverage, gap flags | Keep quality alongside every derived value |

For an accelerometer sample, `sqrt(x*x + y*y + z*z)` is a starting magnitude calculation, not a complete inactivity classifier. Keep preprocessing causal: no future samples in filters or trailing windows.

For IBI, compute RMSSD from successive valid intervals within contiguous segments and SDNN from their sample standard deviation. Do not bridge gaps or concatenate separated segments as if beats were adjacent. Treat these as exploratory pulse-derived features, not validated clinical HRV measures.

### 7.4 Baselines without future leakage

Use an initial calibration period, proposed as the first 24–48 usable recorded hours. During warm-up, show “insufficient baseline” and suppress automatic physiology-driven replanning. Baselines must use only data earlier than the current replay time.

A proposed robust normalization is `(value - median) / max(1.4826 * MAD, epsilon)`. Store the transform, epsilon, valid count, and baseline cutoff. For an evening-specific claim, actually compute an earlier-evening baseline; otherwise say “recent baseline.” Do not fit against the whole recording and imply an online prediction.

### 7.5 Gold: interpreted wearable state

Emit `WearableState` containing bounded estimates, raw summary features, quality, baseline metadata, and supporting evidence-window IDs. Scores are **engineering heuristics**, not calibrated probabilities.

Proposed load formula:

```text
component(z) = clamp(z / 3, 0, 1)
load = weighted mean of available valid components:
       0.40 * component(HR z)
       0.40 * component(EDA z)
       0.20 * component(-RMSSD z)
```

Require usable HR and EDA for a load score; if optional RMSSD is absent, renormalize the two remaining weights. If movement is elevated, mark activity as a confound and suppress the exam-load trigger. Do not silently convert exercise into psychological stress or report an invented confidence probability.

**Rest estimate:** look for sustained low movement and compatible HR patterns in the scenario's overnight window. Separate observed inactivity from sensor gaps. An initial rest-duration index can be `clamp(estimated_rest_minutes / target_rest_minutes, 0, 1)` only when enough overnight data exists. Display the underlying duration and coverage. Interruption count is contextual; avoid inventing sleep efficiency or sleep stages. Keep `recovery_score` null when evidence is inadequate.

### 7.6 Academic pressure

Compute from unfinished tasks and the synthetic calendar, independently of wearable signals. Proposed display heuristic:

```text
u_i = (priority_i / 10) * remaining_minutes_i
      / max(minutes_until_deadline_i, 30)
deadline_pressure = clamp(sum(u_i), 0, 1)
```

Overdue tasks receive a separate flag. This rough urgency index does not account for all blocked time. The scheduler separately checks available capacity before each deadline and reports shortfalls; do not call a high pressure value a proven probability of missing an exam.

### 7.7 Trigger policy

Starter configuration, to tune using the selected recording:

- Valid baseline and sufficient current HR/EDA/ACC coverage.
- Load at or above `0.70` in at least 15 of the last 20 valid minutes.
- Low movement and `recovery_score` below `0.50`, with adequate overnight evidence.
- Pressure at or above `0.70` and at least one future flexible block.
- No pending decision; at least 60 replay minutes since the previous applied revision.

Require 20 consecutive observed minutes for this first rule; a data gap resets the persistence window. If recovery is unknown, the combined trigger does not fire. Manual replanning and calendar-only scheduling still work. Use a lower reset threshold (proposed load below `0.55`) to avoid repeated toggling. Thresholds belong in versioned configuration, not in LLM prose.

## 8. Replay and streaming semantics

- Preserve three clocks: `source_timestamp` from the release, mapped scenario `event_time`, and wall-clock `ingested_at`.
- Map every signal with the same offset: `scenario_start + (source_timestamp - source_start)`. Document the scenario timezone separately.
- All scheduling and deadline calculations use the replay clock, not the laptop's current time.
- Proposed speeds: 1×, 10×, 60×, and 300×. At 300×, one real second represents five recorded minutes; eight full days still take about 38.4 minutes. Use bookmarks for a short presentation.
- A replay speed setting controls publication targets, not a guarantee that Databricks keeps up. Show actual processed time and backlog; pause/slow when necessary.
- Use unique checkpoint locations per query and replay run. Resume a run with its existing checkpoint; a reset creates a new run, new state, and new checkpoint locations.
- Start with one-minute windows and a two-minute event-time lateness allowance. Finalized append output will lag incoming event time. Set the dashboard clock to the latest fully processed state and explain the lag.
- Keep Bronze/Silver/Gold append-only for the first version. Delta source updates require additional handling; do not silently skip changes that matter. [Streaming source behavior](https://docs.databricks.com/aws/en/structured-streaming/delta-lake)
- Advance the source beyond the last demo window by the watermark allowance to finalize it. Label any unfinalized tail; do not invent wearable samples to flush a stream.
- If implementing Gold via `foreachBatch`, make writes idempotent and order records explicitly. A failed/retried microbatch must not duplicate decisions or schedule revisions.
- Jumping to a bookmark requires prior baseline/rest history. Restore a prepared state snapshot or replay the prefix; do not jump straight into a high-load window with a fabricated baseline.

For a compute-constrained fallback, precompute minute features and replay them through state processing. Label this **feature replay** and explain which transforms were offline. A fixture animation must not be presented as a live Databricks run.

## 9. Contracts and interfaces

These are proposed version-1 interfaces to turn into JSON Schema/Pydantic models before implementation. Examples demonstrate shape, not a scientific scoring result.

### 9.1 Shared conventions

| Concern | Rule |
|---|---|
| Schema version | `schema_version: "1.0"`; breaking changes require a coordinated version bump |
| Time | RFC 3339 UTC on interfaces; IANA timezone in calendar metadata |
| Unknowns | JSON `null` with a reason; never `NaN`, fabricated zero, or stale values marked fresh |
| Scores | Numbers in `[0,1]`; UI may multiply by 100; not probabilities |
| Durations | Integer minutes for work; milliseconds for variability; named units for measurements |
| IDs | Stable opaque strings; participant IDs remain strings to preserve leading zeros |
| Intervals | Half-open; start must precede end |
| Provenance | Distinguish `recorded_replay`, `synthetic_fixture`, and `synthetic_injection` |
| Consistency | Carry run, state, calendar, task, and schedule versions through decisions |

### 9.2 Normalized event

```json
{
  "schema_version": "1.0",
  "run_id": "demo-run-001",
  "event_id": "fixture-hr-000001",
  "participant_id": "fixture-participant",
  "source_kind": "synthetic_fixture",
  "source_timestamp": "2026-10-13T03:19:59Z",
  "event_time": "2026-10-13T03:19:59Z",
  "ingested_at": "2026-10-03T16:00:01Z",
  "signal": "hr",
  "values": {"value": 91.0},
  "unit": "bpm",
  "quality": "valid"
}
```

For ACC, `values` contains `x`, `y`, and `z`; validate this with a signal-specific schema. Recorded events additionally reference a provenance manifest containing file/checksum/row information. `source_timestamp` on the API is the normalized interpretation; preserve original timestamp text and assumptions in provenance.

### 9.3 WearableState and composed StudentState

The `wearable` object below is the data team's `WearableState` payload. The backend adds `academic`, versioning, and `trigger`. Raw summaries are available separately through the history API.

```json
{
  "schema_version": "1.0",
  "state_id": "state-0042",
  "run_id": "demo-run-001",
  "participant_id": "fixture-participant",
  "as_of": "2026-10-13T03:20:00Z",
  "scenario_timezone": "America/New_York",
  "source_kind": "synthetic_fixture",
  "wearable": {
    "window_start": "2026-10-13T03:19:00Z",
    "window_end": "2026-10-13T03:20:00Z",
    "heart_rate_bpm": 91.0,
    "physiological_load": 0.81,
    "activity_level": 0.08,
    "estimated_rest_minutes": 210,
    "target_rest_minutes": 480,
    "recovery_score": 0.4375,
    "quality": {
      "status": "sufficient",
      "hr_coverage": 0.98,
      "eda_coverage": 0.96,
      "acc_coverage": 0.99,
      "overnight_coverage": 0.93,
      "missing_reasons": {}
    },
    "baseline_id": "baseline-01",
    "baseline_cutoff": "2026-10-12T00:00:00Z",
    "evidence_ids": ["window-0023", "window-0042", "rest-0002"]
  },
  "academic": {
    "calendar_version": 1,
    "tasks_version": 3,
    "schedule_version": 2,
    "deadline_pressure": 0.87,
    "hours_until_next_exam": 9.67,
    "remaining_work_minutes": 240,
    "overdue_task_ids": []
  },
  "trigger": {
    "replan_recommended": true,
    "reason_codes": ["SUSTAINED_LOAD", "LIMITED_ESTIMATED_REST", "HIGH_PRESSURE"],
    "rule_version": "demo-rules-1"
  }
}
```

The pressure and sensor numbers here are independent synthetic test values; generate a coherent full scenario fixture before an integrated demo. A null score requires a `missing_reasons` entry. `hours_until_next_exam` is null when no future exam exists. Quality statuses are `sufficient`, `limited`, or `unavailable`.

### 9.4 Tasks, fixed events, and preferences

```json
{
  "schema_version": "1.0",
  "calendar_version": 1,
  "tasks_version": 3,
  "timezone": "America/New_York",
  "tasks": [
    {
      "task_id": "algorithms-review",
      "title": "Algorithms review",
      "remaining_minutes": 90,
      "deadline": "2026-10-14T19:30:00Z",
      "priority": 6,
      "splittable": true,
      "minimum_block_minutes": 30,
      "status": "todo"
    }
  ],
  "fixed_events": [
    {
      "event_id": "stat-exam",
      "title": "STAT exam",
      "kind": "exam",
      "start": "2026-10-13T13:00:00Z",
      "end": "2026-10-13T14:00:00Z"
    }
  ],
  "preferences": {
    "minimum_sleep_minutes": 420,
    "target_sleep_minutes": 480,
    "minimum_study_block_minutes": 30,
    "maximum_continuous_study_minutes": 90,
    "break_minutes": 15
  }
}
```

The production contract must also contain explicit allowed study intervals and protected sleep intervals for the planning horizon. Do not rely on vague strings such as “morning.” Task completion comes from user input or a labeled scripted progress event; elapsed calendar time does not prove work was completed.

### 9.5 Scheduler function

```python
optimize_schedule(
    now,
    planning_horizon,
    tasks,
    fixed_events,
    allowed_study_intervals,
    protected_sleep_intervals,
    current_schedule,
    student_state,
    policy,
) -> ScheduleProposal
```

`ScheduleProposal` contains `proposal_id`, `based_on_state_id`, input versions, `status` (`feasible`, `partial`, or `infeasible`), `blocks`, `changes`, `unscheduled_work`, and `validation`. Every block includes `block_id`, nullable `task_id`, `kind`, `start`, `end`, and `locked`. Each change identifies old/new block IDs and a machine-readable reason. `unscheduled_work` lists task ID, minutes, deadline, and reason.

The scheduler is a pure function with deterministic tie-breaking. It never writes the calendar or calls an LLM. The backend commits a validated proposal and increments the schedule version only if all input versions still match.

### 9.6 Agent tools

| Tool | Returns / purpose |
|---|---|
| `get_current_student_state(run_id)` | Latest composed state and versions |
| `get_physiology_history(start, end, metrics)` | Bounded windows, values, quality, evidence IDs |
| `compare_to_baseline(metric, window)` | Baseline cutoff and actual deviation |
| `get_recent_rest(as_of)` | Estimated intervals, coverage, limitations |
| `get_upcoming_deadlines(as_of)` | Calendar events and task deadlines |
| `get_remaining_tasks()` | Explicit task progress and priorities |
| `request_schedule_replan(state_id, schedule_version, reason_codes)` | Validated proposal from scheduler |
| `get_schedule_change(decision_id)` | Saved before/after diff and evidence |

The agent supplies permitted reason codes, not arbitrary new hard constraints. The backend maps them to a versioned scheduling policy. Tool results include time ranges and IDs so explanations can be checked. The API commits proposals; agent text alone never changes the schedule.

### 9.7 HTTP and live-event API

| Endpoint | Contract |
|---|---|
| `GET /api/state?run_id=...` | `StudentState` or explicit not-ready response |
| `GET /api/history?run_id=...&start=...&end=...` | Bounded wearable history and quality |
| `GET /api/schedule` | Current versioned blocks and unscheduled work |
| `POST /api/replan` | State ID + input versions + reason codes; returns job ID |
| `GET /api/replans/{job_id}` | Status, proposal, explanation, validation result |
| `POST /api/replans/{job_id}/apply` | Expected schedule version; commits once |
| `POST /api/chat` | Message + optional decision ID; returns answer/evidence or job ID |
| `POST /api/tasks/{task_id}/progress` | Explicit completed minutes and expected task version |
| `POST /api/replay/start` | Scenario ID, speed, optional bookmark; returns run ID |
| `POST /api/replay/pause` | Pauses publication for a run |
| `POST /api/replay/reset` | Creates clean run state; preserves prior audit history |
| `GET /api/replay/status` | Published time, processed time, speed, lag, mode |
| `GET /api/events` | SSE updates to dashboard |

For asynchronous responses, use `202` with a job identifier; avoid keeping an HTTP request open indefinitely during agent work. Use `409` for stale versions, `422` for invalid payloads, and structured error bodies `{code, message, retryable}`. Each mutating request carries an idempotency key. Keep a manual “Apply” action; an explicit demo auto-apply setting may commit valid in-app proposals automatically.

SSE event types: `state.updated`, `replay.updated`, `agent.started`, `agent.tool_result`, `schedule.proposed`, `schedule.applied`, `agent.explanation`, and `pipeline.error`. Envelope fields: `event_id`, `sequence`, `run_id`, `event_time`, `type`, `payload`. Deduplicate by event ID; on reconnect, replay retained events or refresh complete state/schedule snapshots if the cursor expired.

## 10. Scheduling behavior

### Hard constraints

- Never overlap fixed events, protected sleep, or another scheduled block.
- Keep exams, classes, and user-locked blocks fixed.
- Never allocate study time in the past or finish a task after its deadline.
- Allocate each task's remaining minutes at most once.
- Respect allowed study intervals, split permissions, minimum block sizes, and breaks.
- Keep completed/in-progress blocks stable unless the user explicitly edits them.
- Preserve the configured minimum sleep duration; it is a user preference, not a medical recommendation.

### Soft preferences

Preserve near-deadline/high-priority study first, prefer moving lower-priority flexible work, minimize total disruption, and prefer earlier feasible slots when a recovery policy requests an earlier finish. If an existing sleep block is already protected, it cannot be overwritten; sleep may be extended into genuinely free or movable time.

### First algorithm

Build free intervals from the planning horizon minus fixed/protected intervals. Keep valid locked work. Rank remaining tasks using deadline, priority, and a stable task-ID tie-breaker. Place valid blocks into free intervals; split only when allowed. Insert required breaks, compute changes, then run an independent constraint validator.

The greedy approach may miss a feasible arrangement. Report “no feasible plan found by this scheduler” rather than claiming mathematical impossibility. Return explicit shortfalls instead of silently dropping work or violating sleep/deadline constraints. Replan requests must be idempotent; one trigger must not generate repeated schedule churn.

## 11. Agent responsibilities and explanation quality

The agent investigates current state, compares historical context, checks rest evidence and deadlines, requests a plan, and explains the returned diff. It does not infer physiology from raw CSVs, calculate authoritative scores in prose, invent study completion, or claim a calendar change succeeded before commit.

Every explanation should distinguish:

1. **Observation:** which features changed, over what window, compared with which baseline.
2. **Uncertainty:** missing data and possible activity/sensor confounds.
3. **Planning reason:** deadline order, remaining work, and movable blocks.
4. **Action/status:** proposed or applied changes, plus any unscheduled work.

Save state ID, tool results, rule version, model identifier, before/after schedule versions, and evidence IDs with each decision. “Why did you move this?” should retrieve that saved decision, not reconstruct it from today's state.

Cap tool calls and execution time. If the model is unavailable, show a deterministic explanation from actual evidence and the schedule diff, labeled as a fallback. Failed or malformed tool output must leave the current schedule intact.

## 12. Dashboard and demo controls

Use four main areas:

- **Physiology:** HR, load estimate, movement, estimated rest/recovery, coverage status.
- **Today's plan:** fixed events, flexible study blocks, before/after changes, unscheduled work.
- **Wearable timeline:** aligned HR/EDA/movement plots and decision markers.
- **AI coach:** explanation, short tool-action log, and questions about the week.

Show recorded versus synthetic labels, scenario time, replay speed, and pipeline freshness. Display missing values as unavailable and gaps as gaps. Keep optional glucose separate from the core decision cards. A small demo panel provides play/pause/reset, participant/scenario selection, and prepared bookmarks. The replay engine serves as the wearable simulator; a separate simulator app is unnecessary.

## 13. MVP and acceptance criteria

### Required end-to-end slice

1. One selected participant; HR/EDA/ACC ingestion and usable history.
2. Chronological replay into Databricks with visible incremental results.
3. Minute features, causal personal baseline, quality flags, and rest estimate or explicit unknown.
4. Synthetic calendar with roughly **5–8 total assessments**; for example 3 exams and 4 assignments, plus fixed commitments.
5. Deterministic initial study plan with valid constraints.
6. One evidence-backed trigger leading to a multi-step tool investigation.
7. Valid schedule revision, persisted decision, and clear explanation.
8. Calendar animation and historical “Why did this change?” interaction.

The later discussion suggested 3–4 exams plus 3–5 assignments; keep that larger calendar optional. A small coherent workload is sufficient.

### Definition of done

- Frontend and agent operate against fixtures before Databricks integration.
- One replayed segment traverses source → Bronze → Silver → Gold → API → UI.
- Duplicate delivery or reconnect does not duplicate schedule revisions.
- Every applied plan passes overlap, deadline, duration, and protected-time checks.
- Missing channels and baseline warm-up produce explicit unknowns rather than false certainty.
- Explanation numbers match tool results and the actual schedule diff.
- Reset/replay reproduces features and deterministic schedules; LLM wording may differ.
- A fresh teammate can run the documented fixture mode without Databricks credentials.

### Deferred features

Raw BVP processing, clinical sleep/stress classification, multi-participant models, glucose prediction, meal reasoning, native desktop packaging, real hardware, external calendar writes, and production authentication. Revisit only after the core loop is demonstrated.

## 14. Demo story and presentation runbook

Prepare a full recording replay and a short bookmarked presentation. Inspect the selected recording before choosing the trigger window. Real data may not satisfy every proposed threshold; choose a defensible segment, revise documented heuristics, or use a clearly labeled synthetic scenario. Never silently alter recorded measurements for dramatic effect.

### Suggested three-minute presentation

| Time | Show | Explain |
|---|---|---|
| 0:00–0:25 | Initial exam-week schedule and data labels | Real wearable recording, synthetic student workload |
| 0:25–0:55 | Accelerated timeline and Databricks batch progress | Signals becoming minute features and state |
| 0:55–1:20 | Sustained load / limited estimated rest / deadline pressure | What crossed the rule, with quality context |
| 1:20–1:55 | Agent tool calls and schedule comparison | Investigation followed by constrained action |
| 1:55–2:25 | Applied calendar revision and explanation | Work preserved; fixed events and sleep constraints respected |
| 2:25–3:00 | Ask “Why did you move this?” | Retrieve the saved evidence and decision |

### Illustrative schedule moment

At Monday 11:20 PM in the synthetic scenario, 90 minutes of Algorithms review remain planned for 11:30 PM–1:00 AM. An existing protected sleep interval begins at 1:00 AM and ends at 8:00 AM. A STAT exam is Tuesday at 9:00 AM; the Algorithms deadline is later.

A valid revision could extend protected rest to 11:30 PM–8:00 AM and move Algorithms to **Tuesday 10:00–11:00 AM plus 1:00–1:30 PM**, provided those slots are free, within allowed study hours, and before the Algorithms deadline. Keep the STAT preparation and exam unchanged. The moved durations sum to the original 90 minutes.

Example explanation template:

> Recent heart rate and EDA were elevated relative to the available personal baseline while movement remained low. Estimated overnight rest was shorter than the scenario's target. I moved 90 minutes of flexible Algorithms review into two available Tuesday blocks and preserved the earlier STAT commitment. The rest estimate is uncertain and does not establish poor sleep.

Populate exact values and durations from retrieved evidence. Do not hardcode claims such as “54 minutes above baseline” unless the actual window supports them.

### Demo resilience

Keep three explicit modes: **live Databricks replay**, **replay of saved derived results**, and **synthetic fixture demo**. Show the active mode prominently. Warm up compute and validate credentials before presenting. Keep a recorded successful run available if the network fails; label it as a recording. Freeze or slow the replay during the explanation so the decision remains understandable and does not become stale.

## 15. Validation, risks, and limitations

| Risk | Required handling / check |
|---|---|
| Timestamp ambiguity or inconsistent shifts | Inspect samples; document assumptions; test shared alignment |
| Future leakage | Baseline and every feature cutoff must precede or equal state time |
| Gaps mistaken for rest | Coverage checks; no rest inference from absent readings |
| Exercise mistaken for academic pressure | Movement gate and uncertainty language |
| Score overclaiming | Mark heuristics; no accuracy percentages without a validation study |
| Schedule infeasibility | Explicit remaining minutes and reasons; never hide dropped work |
| Replay backlog | Show processed clock and lag; apply backpressure |
| Concurrent changes | Version checks; reject stale proposals before commit |
| LLM hallucination / outage | Structured tools, saved evidence, deterministic fallback |
| Merge conflicts | Directory ownership, stable schemas, one shared-config owner |
| Demo segment lacks desired pattern | Inspect early; honest alternate scenario mode |

Test malformed input, duplicate events, missing minutes, high movement, unknown recovery, baseline warm-up, overdue tasks, fixed-event overlaps, insufficient free time, replay reset, and SSE reconnect. Compare streaming minute features against a small offline reference calculation. Test the scheduler with at least one feasible and one deliberately overloaded calendar.

A single selected adult recording cannot validate student-specific recovery or scheduling outcomes. Wearable correlations do not establish that exams caused physiological changes. Synthetic deadlines demonstrate software behavior, not academic efficacy. Actual data quality, deployment access, and processing latency remain unverified until implementation.

## 16. Build sequence and immediate next steps

| Milestone | Work | Exit condition |
|---|---|---|
| 0 — Agree boundaries | Assign owners; choose provider/workspace; freeze schemas, fixtures, scenario | Everyone can develop without waiting on another module |
| 1 — Fixture loop | UI + FastAPI + scheduler + stub agent | Button produces a valid schedule revision and explanation |
| 2 — Data slice | Inspect participant; normalize a short segment; build Bronze/Silver/Gold | Real-derived `WearableState` reaches the UI |
| 3 — Historical context | Replay earlier calibration/rest history; implement quality and triggers | Reproducible state with no future leakage |
| 4 — Agent integration | Replace stub with tools; save decisions; support historical questions | Explanation grounded in actual returned evidence |
| 5 — Rehearsal | Extend to full recording; select bookmark; test failures and reset | Reliable short demo plus labeled fallback |

**First actions for the team:**

- [ ] Confirm team size and assign A/B/C/D/integrator names.
- [ ] Create the GitHub repository and module ownership rules.
- [ ] Confirm Databricks access, storage path, compute, SQL connectivity, and model availability.
- [ ] Select a candidate participant and collect sample rows/coverage summaries.
- [ ] Agree timestamp mapping, units, scenario timezone, and baseline warm-up period.
- [ ] Create versioned schemas and fixtures for normal, trigger, missing-data, and infeasible cases.
- [ ] Create the small synthetic calendar, explicit study/sleep intervals, and progress events.
- [ ] Build the fixture-only vertical slice before polishing individual modules.
- [ ] Confirm the current WolfHacks track rubric; track wording in the conversation was not independently verified here.

The project is intended to demonstrate streaming analytics, AI-supported dataset exploration, and tool-driven action. The first milestone is concrete: **one participant segment → Databricks minute features → state JSON → dashboard**. The second closes the loop: **state + workload → agent investigation → valid revised plan → explanation**.

## 17. Sources and attribution

Technical references were checked October 3, 2026. Implementation choices and scoring formulas in this document are team proposals, not claims made by these sources.

- **Dataset:** Cho, P., Kim, J., Bent, B., & Dunn, J. (2026). *BIG IDEAs Lab Glycemic Variability and Wearable Device Data*, version 1.1.3. PhysioNet. [Version DOI](https://doi.org/10.13026/aw6y-fc44). The release lists the Open Data Commons Attribution License v1.0; retain its attribution and license information with derived artifacts. [Release and license links](https://physionet.org/content/big-ideas-glycemic-wearable/1.1.3/)
- **Original study, requested by the dataset citation instructions:** Bent, B., Cho, P. J., Henriquez, M., et al. (2021). *Engineering digital biomarkers of interstitial glucose from noninvasive smartwatches.* npj Digital Medicine 4, 89. [Publication](https://doi.org/10.1038/s41746-021-00465-w)
- **PhysioNet platform citation listed by the release:** Pollard, T., Moody, B. E., Lehman, L., et al. (2026). *PhysioNet as a global platform for biomedical research.* Nature Health. [Publication](https://doi.org/10.1038/s44360-026-00096-z)
- **Databricks:** [Delta Lake streaming reads and writes](https://docs.databricks.com/aws/en/structured-streaming/delta-lake), [agent tools](https://docs.databricks.com/aws/en/agents/mcp-tools), and [Python SQL connector](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector).

Record the selected participant, source version, source checksums, timestamp mapping, dropped/flagged rows, feature definitions, heuristic version, and synthetic scenario separately in the repository's provenance notes. Keep the dataset's research findings separate from this application's unvalidated exam-week use case.
