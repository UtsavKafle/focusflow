# Data A final summary and UI session handoff

## Outcome

Data A's mock ingestion path is implemented and verified through Databricks
Bronze. The corrected run **`mock-demo-002`** contains **3,890,102 synthetic
events**, with unique event IDs within the run. Repeated ingestion left the
count unchanged. The full job also verified the planted HR=255 quality flag
and the cramming episode's trigger timestamp.

Code was pushed to **`data-a/mock-bronze-handoff`**, commit **`506c7e8`**:

- [Data A branch](https://github.com/UtsavKafle/focusflow/tree/data-a/mock-bronze-handoff)
- [Data B handoff](https://github.com/UtsavKafle/focusflow/blob/data-a/mock-bronze-handoff/databricks/ingestion/DATA_B_HANDOFF.md)
- [Complete provenance](https://github.com/UtsavKafle/focusflow/blob/data-a/mock-bronze-handoff/docs/data-provenance.md)

This branch has not been merged into the current UI branch. Raw/generated data,
credentials and screenshots are excluded from Git.

## Implemented code

- `databricks/ingestion/adapter.py`: chunked CSV parsing, stable physical-row
  event IDs, quality checks, finite contract events and scenario timestamp mapping.
- `coverage_report.py`: file checksums, row/quality counts, observed sampling
  rates, duplicates, gaps and New York overnight coverage.
- `landing_writer.py`: immutable JSONL batches and ready markers, local or SDK
  upload, with byte-identical retry checks and protection against partial files.
- `bronze_stream.py` / `databricks/sql/ddl_bronze.sql`: bounded `availableNow`
  streaming, commit checksum/count validation, insert-only Delta MERGE and
  `(run_id,event_id)` deduplication.
- `simulator/replay.py` / `run_demo.py`: importable start/pause/resume/reset,
  speed control (1/10/60/300), history warmup, status and bounded replay.
  Reset preserves old audit data and uses a new run/checkpoint.
- `mock_smoke.py`: bounded mock preparation/upload and standalone serverless
  verification notebook; blocks incomplete or superseded publications.
- `remote_report.py`: bounded read-only SQL verification using an existing warehouse.

## Verified dataset and clock

The original dataset download was replaced with mock generator output.
**`001` is a synthetic identifier, not a selected real BIG IDEAs participant.**

Raw files: `data/raw/001/HR_001.csv`, `EDA_001.csv`, `ACC_001.csv`.
They are unchanged. Checksums and diagnostics are in the Data A provenance doc.

| Signal | Published rows / unique IDs | Flagged rows | Last event (UTC) |
| --- | ---: | ---: | --- |
| HR | 298,502 | 12 | 2026-10-13T03:59:59Z |
| EDA | 1,198,800 | 1 | 2026-10-13T03:59:59.750Z |
| ACC | 2,392,800 | 2,392,800 | 2026-10-13T03:59:59.875Z |

All signals begin **`2026-10-09T16:00:00Z`**. Three nonfinite HR readings
were omitted. HR flags are 10 duplicate-timestamp rows, one zero reading and
one planted 255 bpm reading. HR >220 is an engineering quality gate, not a
clinical diagnosis. EDA has one negative-value flag. All ACC flags are solely
for unverified units.

- Naive source clock: **America/New_York**; timestamps include fractional seconds.
- Mapping: add **2,430 local calendar days**, then localize and convert to UTC.
  This preserves local time-of-day across February EST and October EDT.
- Baseline history: **48 h**, Oct 9 noon → Oct 11 noon New York
  (`2026-10-09T16:00:00Z` → `2026-10-11T16:00:00Z`).
- Demo: **36 h**, Oct 11 noon → Oct 13 midnight New York
  (`2026-10-11T16:00:00Z` → `2026-10-13T04:00:00Z`), end exclusive.
- The demo was extended from 24 h to include Feb 16 20:30–23:30 source-time
  cramming. Trigger snapshot: **`2026-10-13T03:20:00Z`**.
- Rest calculation window: **22:00–08:00 America/New_York** on scenario dates.
- Rates: HR **1 Hz**, EDA **4 Hz**, ACC **8 Hz** (not the real-data 32 Hz default).
- ACC scale: **1/64 g per raw unit**, an explicit synthetic assumption. Raw
  vectors remain unscaled and flagged; real-data units are not verified.
  The 0.05 g stillness threshold and 0.25 g activity scaling depend on this scale.

## Workspace and schema

| Setting | Value |
| --- | --- |
| Workspace | https://dbc-ed0d4fbc-76da.cloud.databricks.com |
| Catalog / schema | `focusflow` / `main` |
| Bronze | `focusflow.main.bronze_wearable_events` |
| Landing volume | `/Volumes/focusflow/main/landing` |
| Corrected run landing | `/Volumes/focusflow/main/landing/mock-demo-002` |
| Checkpoint volume | `/Volumes/focusflow/main/checkpoints` |
| Run checkpoint | `/Volumes/focusflow/main/checkpoints/mock-demo-002/bronze` |
| Ingestion compute | Standard serverless notebook job; `availableNow` tested |
| SQL verification | Serverless Starter Warehouse `b2bf91a257e3ec76`, 10-minute auto-stop |

Bronze columns:

```text
schema_version, run_id, event_id, participant_id, source_kind,
source_timestamp, event_time, ingested_at, signal, values, unit, quality,
source_file, source_row
```

`values` is `MAP<STRING,DOUBLE>`. **There is no Bronze `flag_reason` or
`quality_reason` column.** The requested `flag_reason` grouping query was run
and failed with SQLSTATE 42703. Use Bronze's `quality` enum
(`valid`, `flagged`, `dropped`); do not use placeholder reason columns.

Only local adapter DataFrames expose `quality_reason`. Tokens are semicolon
separated with a trailing semicolon; the empty string means no reason:

```text
duplicate_timestamp
out_of_order
negative_measurement
nonpositive_hr_or_ibi
hr_above_engineering_range
unit_unverified
invalid_or_ambiguous_timestamp
missing_or_nonfinite_measurement
cross_chunk_order_or_duplicate
```

## Verification evidence

- **59 tests passed** at Data A commit `506c7e8`:
  `python -m pytest tests databricks/ingestion/tests simulator/tests -q`.
- 3,900-event smoke job `783153108200122`: succeeded.
- [Full Bronze job `550393483724425`](https://dbc-ed0d4fbc-76da.cloud.databricks.com/jobs/880998357430058/runs/550393483724425?o=7474653575076682): succeeded.
- Independent SQL confirmed signal/quality counts, unique IDs, UTC time ranges
  and the actual 14-column schema.
- Local evidence: `data/derived/mock-demo-002/manifest.json`,
  `bronze-report.json`, `bronze_smoke_notebook.py`, `usage-credits.png`.
- The credit screenshot displayed $398 remaining out of $400, marked updated
  about four hours earlier. This does not establish current-session cost or
  change the project's $30 spend budget.

## What remains

- Data B: smoke-test Silver/Gold Spark wrappers, explicitly handle mock ACC
  assumptions, validate baseline/coverage gates and confirm downstream trigger
  behavior. Bronze timestamp presence alone does not prove a trigger fires.
- Integrator: merge Data A as appropriate and connect replay/Gold to backend
  routes. At Data A handoff the backend routes remained fixture-backed.
- Saved derived-results fallback and calm/trigger feature bookmarks require
  actual Data B outputs. No Silver/Gold fallback was fabricated.
- Real participant selection, real timestamp timezone/format and actual ACC/IBI
  units remain unverified and are deferred for this mock demo. No IBI/TEMP
  mock files were supplied; parsing support exists but workspace ingestion of
  those signals has not been demonstrated.
- Bulk Bronze contains future demo rows. Data B must enforce feature cutoffs;
  max Bronze timestamp is not current live replay progress.

## New UI session starting point

The workspace is on **`frontend/ui`**, created from and pulled up to date with
**`origin/frontend/dashboard`**, commit **`b81b3c3`** (`Stage 1 frontend`).
The frontend is under `frontend/`. Read its README/package scripts and the
shared contracts before editing. Data A code is on its separate branch; do not
assume its modules or updated provenance are already present on the UI branch.

Suggested first message in the new session:

> Work on UI in `/Users/aaravtiwari/focusflow`, branch `frontend/ui`. Read
> `docs/data-a-final-summary.md`, `frontend/README.md`, and the shared contracts.
> The frontend/dashboard work is pulled. Data A's mock-demo-002 Bronze run is
> verified, but backend/Gold integration still needs coordination. I will give
> you the UI changes next.

No frontend implementation changes were made while preparing this summary.
