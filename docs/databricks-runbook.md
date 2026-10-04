# Databricks runbook (Data B streaming demo)

## Cluster / warehouse
- **Compute:** a single-user cluster (DBR 14+, Delta enabled) or serverless compute. Smallest size that
  runs -- this is one participant, bounded by `--history-start`/`--segment-end`, not a big-data job.
- **SQL warehouse** (for `verify_gold.sql` / the backend): smallest size (2X-Small/X-Small). **Auto-stop:
  5-10 minutes.** Never leave a warehouse or an always-on stream running unattended.
- Budget: $30 total credits. Check usage before and after each run (below). Under $8 remaining -> switch
  the demo to saved-results replay, per `docs/handoffs/00-common.md`.

## Credentials
Copy `.env.example` to `.env`, fill in from the Databricks workspace admin console (Settings -> Developer ->
Access tokens for `DATABRICKS_TOKEN`; the workspace URL for `DATABRICKS_HOST`; SQL Warehouses page for
`DATABRICKS_SQL_WAREHOUSE_ID`). `DATABRICKS_CATALOG`/`DATABRICKS_SCHEMA` default to `focusflow`/`main`.
**Never paste these into a notebook cell or commit `.env`** -- on a cluster, set them as cluster environment
variables or Databricks secrets instead, and reference the catalog/schema as job parameters.

## Running the demo
1. Confirm Bronze has rows for the run (Data A's job): `SELECT COUNT(*) FROM focusflow.main.bronze_wearable_events WHERE run_id = '<run_id>'`.
2. Upload or sync the repo to the workspace (Repos, or `databricks sync`).
3. Run `databricks/streaming/run_demo.py` as a notebook cell or a Job/Task with parameters:
   `--run-id mock-demo-002 --participant 001` (defaults match the mock demo; override `--catalog`/`--schema`
   if not using `focusflow.main`). It creates Silver/Gold tables if missing, catches up Silver then Gold
   (availableNow trigger -- processes everything available, then stops; pass `--continuous` only for a live,
   always-on replay), and prints row counts, the window_end range, quality status counts, null reasons, and
   rest-per-night.
4. **Expected runtime:** a few minutes for the full 3.5-day mock segment on the smallest cluster/serverless
   size (it's ~300k HR rows, ~2.4M ACC rows single-participant -- small). A live continuous replay runs for
   the length of the replay instead.
5. Run `databricks/sql/verify_gold.sql` (one query at a time) in a SQL editor against the same `:run_id`/
   `:participant_id`, and compare to the comments above each query.

## Checking spend
Workspace admin console -> **Usage** (or **Account Console -> Usage** for serverless), filtered to today.
Cross-check against the job/warehouse run history (duration x DBU rate). Log it in `docs/decisions.md`
(decision log already has a line for this -- append numbers, don't replace it) every time you check.

## Local smoke test (no Databricks needed)
Validates the Spark glue (`silver_stream.py`, `gold_stream.py`, `merge.py`) against local Spark + Delta,
chunked to exercise the incremental/checkpoint/MERGE path a live replay would use, then diffs Gold against
the pandas baseline (`fixtures/mock_big_ideas/gold.csv`) and checks idempotency.

```bash
pip install -r requirements-spark.txt   # pyspark==3.5.3, delta-spark==3.2.1 (matches DBR 15.x/serverless)
export JAVA_HOME=$(/usr/libexec/java_home -v 17) && export PATH="$JAVA_HOME/bin:$PATH" && export SPARK_LOCAL_IP=127.0.0.1
python scripts/local_spark_smoke.py --acc-stride 8   # fast (~2 min): keep every 8th ACC row
python scripts/local_spark_smoke.py                  # full (~3 min): the one that actually validates ACC-dependent fields
```
Both must print `RESULT: PASS`. Writes only under `./.smoke/` (git-ignored).

## Resetting a run
Pass a **new `--run-id`** to `run_demo.py` -- Silver/Gold rows and the Structured Streaming checkpoints
(`/Volumes/<catalog>/<schema>/checkpoints/<run_id>/...`) are both keyed by `run_id`, so nothing needs to be
deleted. To actually discard a bad run's rows: `DELETE FROM focusflow.main.silver_wearable_minute WHERE
run_id = '<run_id>'` (and same for gold), then delete the checkpoint directory for that `run_id` so a
reused id doesn't skip data it thinks it already processed.
