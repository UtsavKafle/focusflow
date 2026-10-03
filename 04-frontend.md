# 04 Handoff: Frontend (part-time teammate)

You are the coding agent for the frontend teammate. Read `00-common.md` first. You own only `frontend/`. Your human has limited hours, so work in priority order and keep every step demoable. Ship the smallest vertical slice first.

**Mission:** a dashboard that makes the story obvious in 3 minutes: wearable load rises, the agent investigates, the calendar changes with a visible before/after, and the student gets a clear explanation.

## Setup
- React + TypeScript + Vite + Tailwind + Recharts. `cd frontend && npm create vite@latest . -- --template react-ts`, add Tailwind and Recharts.
- Backend mock: `uvicorn backend.app.main:app --port 8000` from repo root (needs `pip install -r requirements.txt`). Switch scenario with `FOCUSFLOW_FIXTURE=normal|trigger|missing_data|infeasible`. Vite dev proxy `/api` to `http://localhost:8000`.
- Types: generate from `contracts/schema/*.json` (e.g. `npx json-schema-to-typescript contracts/schema -o frontend/src/types`). Do not hand-write contract types. If a schema looks wrong, tell the Integrator.
- API reference: `contracts/API.md`. For a demo without the player, use `POST /api/mock/advance?n=1` to step the fixture stream and `POST /api/replay/start`.

## Priorities
**P0 (to Sat 19:00): slice on the mock**
1. Fetch `/api/state`, `/api/schedule`, `/api/calendar`; render a header badge for `source_kind` and mode (from `/api/health`): "SYNTHETIC FIXTURE", "LIVE DATABRICKS REPLAY", or "SAVED REPLAY". Always visible.
2. Physiology card: HR, load (0 to 100 display, label "estimated load, heuristic"), recovery/estimated rest as minutes plus coverage, quality status. Null shows "unavailable" with the reason from `quality.missing_reasons`. Never show 0 for null.
3. Weekly plan view: simple custom grid (no heavy calendar lib), fixed events, study blocks, protected sleep, sleep extension.
4. Subscribe to `/api/events` (SSE). On `state.updated` refetch state. On reconnect refetch state + schedule (no replay cursor exists).

**P1 (to Sun 00:00): the core demo moment**
5. When `trigger.replan_recommended`, show trigger reasons as chips; button "Ask coach to replan" -> `POST /api/replan` (send the versions from state/schedule; handle 409 by refetching) -> poll `/api/replans/{job_id}` or follow SSE.
6. Before/after diff: render `proposal.blocks` and `changes` (moved/added highlighted, old position ghosted). Show `unscheduled_work` clearly in the infeasible scenario. "Apply" -> `POST /api/replans/{job_id}/apply` with `expected_schedule_version`; handle 409 gracefully.
7. AI coach panel: tool-action log from SSE `agent.started` / `agent.tool_result`, then `agent.explanation` text. Show "fallback explanation" label if the payload says so.

**P2 (to Sun 05:00)**
8. Wearable timeline: Recharts of `/api/history` (HR, load, activity) with decision markers and gaps rendered as gaps.
9. "Why did this change?" : click a changed block, call `/api/decisions/{id}` and show the saved explanation; plus a chat box on `/api/chat`.
10. Demo panel: play/pause/reset/scenario selector, speed buttons (1, 10, 60, 300), replay status (published vs processed time, lag), prepared bookmarks.
11. Task progress: mark minutes done via `POST /api/tasks/{id}/progress`.

**P3 (to Sun 08:00)**
12. Polish: loading and error states, a visible disclaimer ("Heuristic estimates from wearable signals. Not medical advice. One adult recording; not validated."), responsive layout for the projector, dark mode optional, keyboard-safe demo flow.
13. Build check: `npm run build` clean. Static build served by the backend or Vercel is fine; confirm with the Integrator.

## Definition of done
- All four fixture scenarios render correctly (normal: no trigger, trigger: diff + explanation, missing_data: unavailable states, infeasible: unscheduled work).
- Labels never lie: mode and `source_kind` always visible.
- No crashes on null fields. No NaN displayed.
- `npm run build` passes and the full demo flow works from a fresh clone against the mock.

## Gotchas
- Times from the API are UTC; display in `scenario_timezone` (America/New_York) using the replay time (`as_of`), not the browser clock.
- The mock exposes `/api/mock/advance`; real mode will not. Hide mock controls unless mode is `synthetic_fixture`.
- Do not edit `contracts/`, backend or data code. If you need an endpoint or field, message the Integrator.
- Use design care but spend little time: clear hierarchy beats decoration. If you are short on hours, finish P0 and P1 well rather than starting P2 half-done.
