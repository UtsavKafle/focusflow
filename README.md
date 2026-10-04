# !Presh (FocusFlow)

An exam-week study planner that looks at how you are doing, not just what is due.

!Presh replays wearable signals (heart rate, skin response, movement) next to an exam-week calendar. When the signals show sustained strain and too little rest while deadlines pile up, an AI coach looks into it and asks for a revised study plan. A simple rule-based scheduler decides the actual times, and you see exactly what changed and why before you apply it.

Built for WolfHacks 2026. The codebase and its contracts still use the working name FocusFlow.

> **About the data:** the wearable recording in this repo is synthetic. It is shaped like the BIG IDEAs Lab wearable dataset, but it is generated mock data, and the exam calendar is made up too. The app labels it as synthetic on every screen. Scores are rough engineering estimates, not medical measurements.

## How it works

1. **Replay.** A wearable recording is replayed minute by minute as if it were live. You can play, pause, change speed, jump to prepared moments, or reset.
2. **Pipeline (Databricks).** Raw signals are cleaned and turned into one row per minute: heart rate, a 0 to 100 load score compared to the person's own baseline, an activity level, and an estimate of last night's rest.
3. **Trigger.** The backend combines body signals with deadline pressure from the calendar. Sustained high load plus limited rest plus a busy calendar means a replan is recommended. Exercise is tracked separately so it is not mistaken for stress, and a cooldown stops it from firing over and over.
4. **AI coach.** The agent gathers evidence with a few tools (current state, baseline comparison, recent rest, upcoming deadlines) and requests a replan. It never edits the schedule itself.
5. **Scheduler.** A deterministic Python scheduler builds the new plan. It never moves classes or exams and never cuts into protected sleep.
6. **Dashboard.** You see the vitals, the proposed plan next to the current one, a plain-language explanation, and an Apply button. You can also ask "Why did you move this?" and get an answer from the saved decision.

If anything fails, the app falls back gracefully and says so on screen: live Databricks first, then saved results, then a built-in fixture. If the AI model is unavailable, a rule-based explanation is used instead, labeled as a fallback.

## Quick start (no accounts or keys needed)

You need Python 3 and Node.js (we used Python 3.14 and Node 22).

```bash
# Terminal 1, from the repo root: start the backend on port 8000
pip install -r requirements.txt
FOCUSFLOW_DATA_SOURCE=fixture uvicorn backend.app.main:app --port 8000

# Terminal 2: start the dashboard
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dashboard forwards API calls to the backend on port 8000.

To run the demo, open **Demo replay** in the header, press **Play from start**, or jump to a prepared moment. **Reset** in the same panel starts the whole demo over: the replay rewinds and the original schedule and tasks come back.

## Configuration

Settings come from environment variables or a `.env` file in the repo root. The `.env` file is ignored by git, so never commit real values. Everything is optional for the fixture demo above.

| Variable | What it does |
|---|---|
| `FOCUSFLOW_DATA_SOURCE` | `fixture` (default, no credentials) or `databricks` |
| `FOCUSFLOW_FIXTURE` | Fixture scenario: `trigger` (default), `normal`, `missing_data`, `infeasible` |
| `FOCUSFLOW_REPLAY_MODE` | With Databricks: `live` (default) or `saved` to replay exported results from disk |
| `FOCUSFLOW_RUN_ID` | Which pipeline run to read. Required for `saved` mode |
| `FOCUSFLOW_DB_PATH` | Where the app keeps its SQLite file |
| `FOCUSFLOW_AUTO_APPLY` | `1` applies valid proposals automatically. Default is manual Apply |
| `FOCUSFLOW_CORS_ORIGINS` | Only needed if the dashboard is not served through the dev proxy |
| `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_SQL_WAREHOUSE_ID` | Databricks connection for live mode |
| `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`, `DATABRICKS_VOLUME_PATH` | Where the pipeline tables and landing files live |
| `DATABRICKS_MODEL_ENDPOINT` | Optional Databricks model endpoint for the AI coach |
| `LLM_API_KEY` | Optional Anthropic API key for the AI coach |
| `AGENT_MAX_TOOL_CALLS`, `AGENT_TIME_CAP_S` | Limits on the coach (defaults 8 calls, 60 seconds) |
| `FOCUSFLOW_REPLAY_*` | Replay timing for live mode. See `docs/databricks-runbook.md` |

Without a model endpoint or API key, the coach still works and uses the rule-based fallback explanation.

## Running the tests

```bash
pytest -q                          # backend, agent, scheduler, pipeline and contract tests
cd frontend && npm run build       # type-checks and builds the dashboard
```

The tests need no credentials. A few data-quality tests are skipped until you generate the mock raw data with `python fixtures/make_mock_big_ideas.py --out data/raw`.

## Project layout

| Folder | What is in it |
|---|---|
| `backend/` | FastAPI app: state composition, trigger rules, replan jobs, SQLite storage, live updates over SSE |
| `agent/` | The AI coach: model providers, tools, and the fallback explanation |
| `scheduler/` | The deterministic scheduler and its validator |
| `simulator/` | Replay controller that feeds the recording in as if it were live |
| `databricks/` | Ingestion, feature pipeline, streaming jobs and SQL for the Databricks side |
| `contracts/` | Shared data models, JSON schemas and the API description (`contracts/API.md`) |
| `fixtures/` | Demo scenarios and the synthetic wearable data used for tests and the offline demo |
| `frontend/` | React dashboard (see `frontend/README.md`) |
| `tests/` | Test suite |
| `docs/` | Product spec, runbooks, data notes, design guides and team handoffs |

## Further reading

- `docs/demo-runbook.md`: running the demo and the fallback options
- `docs/databricks-runbook.md`: setting up and running the Databricks side
- `docs/data-provenance.md`: where the data comes from and how it is labeled
- `docs/HANDOFF.md`: the full product spec
- `contracts/API.md`: every API endpoint

## Limitations

- The wearable data and the exam calendar are synthetic. Nothing here has been validated on real students.
- Load, rest and recovery scores are heuristics. They are not diagnoses and they are not sleep staging.
- The trigger thresholds are tuned so the demo scenario fires. They are not calibrated.
- The app is built for one person and one backend process. It has no login and no multi-user support.
