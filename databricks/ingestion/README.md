# Data A ingestion and setup

Implemented locally: CSV adapter, coverage report, immutable landing publication,
replay start/pause/reset/status/speed/bookmark, and a bounded demo CLI. The Bronze
job and DDL passed both the 3,900-event smoke test and the corrected 3,890,102-event
synthetic demo in Databricks, including unchanged counts after repeated ingestion.
Real participant selection, real unit verification and saved Silver/Gold remain pending.

## Current synthetic demo

The supplied mocks are `data/raw/001/{HR,EDA,ACC}_001.csv`. They are not a
downloaded BIG IDEAs recording. Use New York naive-time interpretation and
+2430 local calendar days; keep ACC raw/flagged and configure downstream ACC
coverage at 8 Hz. The 1/64 g scale is a synthetic assumption, not verified real
data. See `docs/data-provenance.md` for checksums, quality counts and the chosen
48-hour history plus 36-hour demo interval, extended to include cramming.

The following commands prepare, upload and run bounded verification separately:

```sh
python -m databricks.ingestion.mock_smoke
python -m databricks.ingestion.mock_smoke --sdk
python -m databricks.ingestion.mock_smoke --submit
python -m databricks.ingestion.mock_smoke --status
```

For the selected full segment, add these options to each command:

```sh
--output data/derived/mock-demo-002 --run-id mock-demo-002 --duration-minutes 5040
```

Preparation preserves raw files, assigns stable source-row IDs, and writes a
manifest and self-contained `bronze_smoke_notebook.py` under the output directory.
The notebook does not need this repository installed in the workspace. Upload
reuses prepared ingestion timestamps and immutable batch numbers on retries.
Job submission uses standard serverless compute, disables automatic retries,
and sets a 15-minute run / 10-minute task timeout. `--submit` does not create a
recurring job. Verify the small smoke job before submitting the full segment.

This bulk preparation is for building the baseline/demo data and validating
Bronze. It does not simulate publication pacing. The replay controller remains
the path for a paced live replay, using a new run ID and fresh checkpoint.

For paced mock replay:

```sh
python -m simulator.run_demo \
  --raw-directory data/raw/001 \
  --source-start '2020-02-13T12:00:00-05:00' \
  --scenario-start '2026-10-09T12:00:00-04:00' \
  --tz-assume America/New_York --wall-time-shift-days 2430 \
  --source-kind synthetic_fixture \
  --history-hours 48 --demo-hours 36 --speed 300 \
  --landing-root data/derived/landing --timeout-seconds 900
```

Omit `--acc-unit` while the scale is unverified. Add `--sdk` with the remote
landing root only when intentionally running paced publication in Databricks.

## Local setup

From repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r databricks/ingestion/requirements.txt
python -m pytest -q tests databricks/ingestion/tests simulator/tests
```

Data A tests live in the owned module directories; root `pytest -q` currently
only discovers Integrator tests because `pytest.ini` sets `testpaths=tests`.
The Integrator can add these directories to CI's testpaths.

Download only candidate participants' `HR.csv`, `EDA.csv`, and `ACC.csv` from
[BIG IDEAs v1.1.3](https://physionet.org/content/big-ideas-glycemic-wearable/1.1.3/)
to `data/raw/<participant>/`, preserving the participant's zero-padded ID.
Add `IBI.csv` and `TEMP.csv` after the core path works; omit BVP.
Retain release attribution and license. Raw files and local outputs are gitignored.

```sh
python -m databricks.ingestion.coverage_report --raw-root data/raw
```

This updates only the generated candidates section of `docs/data-provenance.md`.
If the CSV timestamps are naive, establish the source timezone before using
`--source-timezone <IANA-zone>`. Record that assumption and how it was confirmed.
The initial report still displays raw timestamp samples, SHA-256 values, counts,
sampling rates, duplicates, and gaps without silently choosing a zone.

`parse_signal(path, signal)` returns raw-row quality diagnostics. Use optional
`source_timezone` for naive timestamps and `verified_unit` for ACC/IBI, only
after confirming the release's actual scale/units. `to_events` returns contract
events; `iter_signal_chunks` + `iter_events` avoid loading an entire ACC recording
or event list. Pass the same `source_start`/`scenario_start` to every signal.

## Databricks setup the human must supply

1. Workspace access with Unity Catalog enabled. Create `focusflow.main` and the
   managed volumes `landing` and `checkpoints`. The SQL in
   `databricks/sql/ddl_bronze.sql` creates these and the Bronze table; an admin
   may need to create the catalog first or grant catalog/schema creation rights.
   The DDL adds CHECK constraints with separate `ALTER TABLE ... ADD CONSTRAINT`
   statements after table creation. Run each ADD once; on a rerun, skip ADDs
   whose named constraints already exist rather than removing existing checks.
2. The runtime identity needs `USE CATALOG`, `USE SCHEMA`, `READ VOLUME`,
   `WRITE VOLUME`, and table creation/write/read privileges for the intended
   objects. Use [Databricks volume guidance](https://docs.databricks.com/aws/en/volumes/volume-files)
   to apply your workspace's grants.
3. Configure SDK auth locally using `databricks auth login`, an existing SDK
   profile, or `DATABRICKS_HOST`/`DATABRICKS_TOKEN` in untracked `.env`.
   The SDK demo CLI loads `.env` without overriding existing environment settings.
   Never paste tokens into chat. A SQL warehouse is needed by the backend's
   eventual SQL reader, not by local CSV processing or Files API uploads.
4. Put this repository on compatible Databricks Spark/Delta compute and make
   its root importable. Run the Bronze DDL, then execute `run_bronze` below.
   Start with a tiny real-data slice and inspect counts before the full demo.
   SDK upload permission alone does not prove Spark/table access.
5. Use bounded jobs. If a SQL warehouse is created, choose the smallest suitable
   size and 5–10 minute auto-stop. Review the $30 credit budget at M2 with Data B.

## Bounded replay and Bronze consumption

Choose real timezone-aware `SOURCE_START` at the beginning of the 24/48 h
baseline prefix and `SCENARIO_START` as its mapped synthetic clock. The command
publishes the prefix quickly and then paces the selected demo interval.
The placeholders below must be replaced with inspected source dates:

```sh
python -m simulator.run_demo \
  --raw-directory data/raw/001 \
  --source-start '<SOURCE_START_WITH_OFFSET>' \
  --scenario-start '<SCENARIO_START_WITH_OFFSET>' \
  --history-hours 48 --demo-hours 12 --speed 300 \
  --landing-root data/derived/landing --timeout-seconds 600
```

For remote publication add `--sdk` and set
`--landing-root /Volumes/focusflow/main/landing`. For naive source timestamps add
`--source-timezone <confirmed-zone>`. Add `--acc-unit` or `--ibi-unit` only after
verification. Without them, those channels stay raw and flagged.
`--timeout-seconds` bounds publication and always closes the controller; slow
speeds may require a deliberately longer timeout for the selected interval.

On Databricks, after an initial batch creates the landing run directory:

```python
from databricks.ingestion.bronze_stream import run_bronze

run_bronze(spark, "<run_id>", timeout_seconds=600)
```

This uses [foreachBatch](https://docs.databricks.com/aws/en/structured-streaming/foreach)
with insert-only Delta MERGE. It consumes currently available commit markers
and exits. Run another bounded availableNow pass for files published later;
use the same run checkpoint. Do not run overlapping writers on the same table.
The stream deliberately does not scan final JSONL files directly: remote moves
can be copy/delete, so commit markers protect against partial publication.

Compare Bronze row counts with published marker `row_count` totals and verify
zero duplicate `(run_id,event_id)` groups. Confirm `values` is a map of doubles,
timestamps are mapped consistently, and source_kind/quality are preserved.
Actual workspace verification is still required; Spark/Delta are not installed
in the local test environment.

## Backend and Data B handoff

Import `ReplayController` from `simulator.replay`. Supply a factory
`event_source(run_id, scenario_id)` yielding chronological contract-shaped rows
plus Bronze `source_file` and `source_row`, and a `LandingWriter`. The
`simulator.run_demo.csv_source` factory demonstrates streaming candidate files.
The controller starts a daemon worker by default. Use `pause`, then `start`
with the same run/scenario/bookmark to resume; `set_speed` preserves elapsed
time. `reset` starts a new run while retaining old landing data. `close` stops
publication. `last_error` reports background failures; status then shows paused.

Provide `processed_time=lambda run_id: <Gold max as_of>` when Data B's Gold
reader is ready. Until then `processed_time` and `lag_seconds` stay null.
ACC/IBI features must gate `unit=unverified`. Bulk prefix publication establishes
available history, not baseline sufficiency; Data B owns the quality gate.
The backend's current mock replay routes have not been replaced by this controller.
Data B's Silver/Gold schema, feature calculations, saved feature replay, and
calm/trigger bookmark selection are subsequent integrations.
