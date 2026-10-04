# simulator (Data A)
Replay controller: reads normalized events for one participant, shifts to the scenario clock, writes event files into the landing volume at speed N, supports start/pause/reset/bookmark. Scenario overlay (calendar, tasks) comes from `fixtures/scenarios/*/calendar.json` (synthetic).

Implemented controller: `replay.py`; bounded replay command: `python -m simulator.run_demo --help`.
See `databricks/ingestion/README.md` for local tests, source-clock configuration,
workspace setup, and backend/Data B integration. Real participant and saved
Silver/Gold fallback selection remain pending the actual data.

Current inputs are synthetic participant 001 mocks. Use `--tz-assume
America/New_York --wall-time-shift-days 2430 --source-kind synthetic_fixture`.
The chosen history maps to Oct 9–11, 2026 at noon; the demo runs from Oct 11
at noon through Oct 13 at midnight, all New York local time. ACC is 8 Hz with an unverified 1/64 g scale
assumption, remains unscaled and flagged, and requires explicit Data B handling.
See the ingestion README for exact commands and the separate bulk Bronze test.
