# frontend (part-time teammate)
React + TypeScript + Vite + Tailwind + Recharts dashboard. Handoff and priorities: `../04-frontend.md`.

## Run against the backend (fixture mode, no credentials)
```bash
# terminal 1, repo root (needs `pip install -r requirements.txt`)
FOCUSFLOW_DATA_SOURCE=fixture FOCUSFLOW_FIXTURE=trigger uvicorn backend.app.main:app --port 8000

# terminal 2
cd frontend && npm install && npm run dev    # http://localhost:5173, proxies /api to :8000
```
`npm run build` type-checks and builds to `dist/`. `npm run lint` runs oxlint.
The scenario (normal | trigger | missing_data | infeasible) can also be switched from the Demo replay panel:
pick it and press Play or a Jump bookmark (fixture mode starts a new run). Other modes: `docs/demo-runbook.md`.

## Contract types
`npm run types` regenerates `src/types/generated/` from `../contracts/schema/*.json`. Never hand-edit those files.
`src/types/index.ts` re-exports them and holds loose types for the few responses that have no schema yet
(`/api/health`, `/api/history`, `/api/decisions/{id}`, `/api/chat`; fields per `contracts/API.md` and CHANGELOG #13/#14).

## Layout
- `src/api.ts` client for `contracts/API.md` (409/422/404 surface as `ApiError`).
- `src/hooks/useFocusFlow.ts` all server state: snapshot fetches, SSE (refetch on every connect), replan/apply, replay controls.
- `src/components/` header badge, physiology card, week grid + before/after diff, AI coach, timeline, demo panel, tasks, "why" dialog.
- `src/lib/time.ts` every time on screen is in `scenario_timezone` and relative to replay time (`as_of`).
- `src/demoBookmarks.ts` prepared bookmarks (currently fixture times; update for the real recording).

## Rules this UI keeps
- Mode badge (`/api/health`) and `source_kind` are always visible. The fixture-only "Step +1" control is hidden unless mode is `synthetic_fixture`.
- The backend drives the replay clock; the UI only follows `state.updated` and never steps it on its own.
- `503 STATE_NOT_READY` shows a waiting screen (polls every 3 s), `409 STALE_VERSION` refetches, `409 ALREADY_APPLIED` resyncs.
- Explanations with `kind: fallback` are labeled "fallback explanation"; chat answers show their `kind` (saved | llm | fallback).
- Null is shown as "unavailable" with the reason from `quality.missing_reasons`; never 0, never NaN. Timeline gaps stay gaps.

## Visual system
- `src/index.css` implements `../NEUMORPHIC_FRONTEND_STYLE_GUIDE.md`: matte gray surfaces, upper-left lighting, shared raised/inset shadows, and generous radii.
- `src/components/ui.tsx` owns reusable cards, chips, buttons, icon wells, and keyboard-safe dialogs; feature panels use the same `neu-*` classes.
- Text tokens are darker than the guide's decorative grays for readable contrast; muted accents indicate status, while labels and line patterns also identify states.
- The layout stacks below 1100px, keeps the source badge visible on mobile, and contains calendar scrolling within its own keyboard-focusable region.
- Controls have visible focus, pressed and disabled states, 44px minimum targets, and reduced-motion support. Dense calendar blocks keep their time-proportional heights.
- `../NEUMORPHIC_APPLE_GLASS_UI_ADDENDUM.md` adds a floating glass layer for navigation, status, actions, inputs, tooltips, dialogs, and the footer; data panels stay matte. CSS provides opaque and reduced-transparency fallbacks.
