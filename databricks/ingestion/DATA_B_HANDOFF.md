# Data B handoff — verified synthetic Bronze demo

**Ready for Data B's Spark smoke test.** Run `mock-demo-002`, participant `001`,
source kind `synthetic_fixture`. This is mock generator output, not a downloaded
BIG IDEAs recording. Real participant selection is deferred.

## Verified results

Bronze job [550393483724425](https://dbc-ed0d4fbc-76da.cloud.databricks.com/jobs/880998357430058/runs/550393483724425?o=7474653575076682)
**succeeded**. It checked total/per-signal counts, unique IDs, source labels,
ACC flags, the planted HR=255 flag and trigger timestamp; a second ingestion
pass kept the count unchanged. Independent SQL queries confirmed:

| Signal | Rows = unique event IDs | First event (UTC) | Last event (UTC) |
| --- | ---: | --- | --- |
| HR | 298,502 | 2026-10-09 16:00:00Z | 2026-10-13 03:59:59Z |
| EDA | 1,198,800 | 2026-10-09 16:00:00Z | 2026-10-13 03:59:59.750Z |
| ACC | 2,392,800 | 2026-10-09 16:00:00Z | 2026-10-13 03:59:59.875Z |

Total: **3,890,102**, no duplicate event IDs within this run.

| Signal | Quality | Rows |
| --- | --- | ---: |
| ACC | flagged | 2,392,800 |
| EDA | flagged | 1 |
| EDA | valid | 1,198,799 |
| HR | flagged | 12 |
| HR | valid | 298,490 |

Three nonfinite HR readings were omitted before publication; flagged finite
readings remain. Raw CSVs are unchanged.

## Workspace and paths

| Setting | Value |
| --- | --- |
| Workspace | https://dbc-ed0d4fbc-76da.cloud.databricks.com |
| Catalog / schema | `focusflow` / `main` |
| Bronze table | `focusflow.main.bronze_wearable_events` |
| Landing volume | `/Volumes/focusflow/main/landing` |
| Run landing | `/Volumes/focusflow/main/landing/mock-demo-002` |
| Checkpoint volume | `/Volumes/focusflow/main/checkpoints` |
| Run checkpoint | `/Volumes/focusflow/main/checkpoints/mock-demo-002/bronze` |
| Ingestion compute | Standard serverless notebook job, environment version 1 |
| Streaming trigger | `availableNow` allowed and tested twice |
| SQL verification | Existing Serverless Starter Warehouse, `b2bf91a257e3ec76`, 10-minute auto-stop |

Never start another Bronze writer concurrently. Data B owns Silver/Gold
processing and their separate checkpoints. The existing Bronze checkpoint is
for Data A only.

## Important schema correction

The requested `SELECT signal, quality, flag_reason, COUNT(*) ...` was run and
failed with **`UNRESOLVED_COLUMN.WITH_SUGGESTION`, SQLSTATE 42703**:
`flag_reason` does not exist. `DESCRIBE TABLE` confirmed 14 columns:

```text
schema_version, run_id, event_id, participant_id, source_kind,
source_timestamp, event_time, ingested_at, signal, values, unit, quality,
source_file, source_row
```

`values` is `MAP<STRING,DOUBLE>`; timestamps are `TIMESTAMP`.
**Bronze quality column: `quality`, values `valid`, `flagged`, `dropped`.**
There is no Bronze `flag_reason` or `quality_reason`. Spark wrappers must not
query those placeholder columns. A reason-column extension needs coordinated
schema agreement; this branch does not change the frozen contract.

The local adapter's DataFrame column is **`quality_reason`**. Tokens are joined
with semicolons, including a trailing semicolon; no reason is an empty string:

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

For this mock, all ACC flags are solely `unit_unverified`. HR flags comprise
10 duplicate-timestamp rows, one zero reading and the planted 255 bpm reading.
EDA's single flag is a negative value. HR >220 is an engineering quality gate,
not a clinical diagnosis.

## Clock, units and baseline

- Raw naive timestamps: `America/New_York`; use `--tz-assume America/New_York`.
- Add **2,430 local calendar days**, then localize the mapped time and store UTC.
- History: `[2026-10-09T16:00:00Z, 2026-10-11T16:00:00Z)` — 48 hours.
- Demo: `[2026-10-11T16:00:00Z, 2026-10-13T04:00:00Z)` — 36 hours.
- Trigger snapshot: **`2026-10-13T03:20:00Z`**, HR event `001-hr-000296106`.
- Rest window: 22:00–08:00 `America/New_York` on scenario dates.
- Rates: HR 1 Hz, EDA 4 Hz, **ACC 8 Hz**; use `--acc-hz 8`.
- ACC scale: **1/64 g per unit**, explicit synthetic assumption; unverified for
  real files. Bronze remains raw, `unit=unverified`, `quality=flagged`. Data B
  needs explicit mock handling rather than excluding every ACC row.
- The 0.05 g stillness threshold and 0.25 g activity scaling depend on that scale.
- Bulk Bronze includes future demo data. Enforce feature/baseline cutoffs; never
  read future rows into a baseline or trailing feature. Max Bronze event time
  is not live replay progress.

Use `mock-demo-002` only. `mock-demo-001` is superseded; `mock-smoke-001` is a
five-minute test and has insufficient baseline history.

## Next action and evidence

Data B can now smoke-test its Silver/Gold Spark wrappers against this run.
Those wrappers and downstream trigger behavior have **not** been verified by
Data A. The backend remains fixture-backed; derived-results fallback still
requires actual Data B outputs.

The credit-page screenshot is saved locally at
`data/derived/mock-demo-002/usage-credits.png`; its balance was marked updated
about four hours earlier, so it does not prove current-session spending. It is
excluded from Git. SQL verification used the existing warehouse; no new
warehouse was created.

See [provenance](../../docs/data-provenance.md) for file checksums and the
[detailed mock handoff](mock-handoff.md) for read queries and event identifiers.
Local machine-readable SQL results: `data/derived/mock-demo-002/bronze-report.json`
(gitignored). Local checks: **59 tests passed**.
