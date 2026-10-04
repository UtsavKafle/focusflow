# Databricks runbook (Data B streaming demo)

## Cluster / warehouse
- **Compute:** a single-user cluster (DBR 14+, Delta enabled) or serverless compute. Smallest size that
  runs -- this is one participant, bounded by `--history-start`/`--segment-end`, not a big-data job.
- **SQL warehouse** (for `verify_gold.sql` / the backend): smallest size (2X-Small/X-Small). **Auto-stop:
  5-10 minutes.** Never leave a warehouse or an always-on stream running unattended.
- Budget: $30 total credits. Check usage before and after each run (below). Under $8 remaining -> switch
  the demo to saved-results replay, per `docs/handoffs/00-common.md`.

## Credentials
`.env` lives at the **repo root** (not `backend/`), git-ignored, filled in from the Databricks workspace
admin console (Settings -> Developer -> Access tokens for `DATABRICKS_TOKEN`; the workspace URL for
`DATABRICKS_HOST`; SQL Warehouses page for `DATABRICKS_SQL_WAREHOUSE_ID`). `DATABRICKS_CATALOG`/
`DATABRICKS_SCHEMA` default to `focusflow`/`main`.
**Never paste these into a notebook cell or commit `.env`** -- on a cluster, set them as cluster environment
variables or Databricks secrets instead, and reference the catalog/schema as job parameters.

**PAT vs Token ID:** a Databricks personal access token (PAT) starts with `dapi` and is shown only once,
at creation. The "Token ID" shown afterward in the tokens table (64 hex characters) is not the secret --
it is just an identifier for revoking the token later. Putting the Token ID in `DATABRICKS_TOKEN` fails
with a 401 `Credential was not sent or was of an unsupported type`; only the original `dapi...` value
works. Keep the PAT only in the git-ignored repo-root `.env`, never in chat, notebooks, or commits. If a
PAT is ever exposed, delete it in the admin console and generate a new one immediately; ours is set to
expire after 7 days.

## Running the demo
1. Confirm Bronze has rows for the run (Data A's job): `SELECT COUNT(*) FROM focusflow.main.bronze_wearable_events WHERE run_id = '<run_id>'`.
2. Upload or sync the repo to the workspace (Repos, or `databricks sync`).
3. Run `databricks/streaming/run_demo.py` as a notebook cell or a Job/Task with parameters:
   `--run-id mock-demo-002 --participant 001` (defaults match the mock demo; override `--catalog`/`--schema`
   if not using `focusflow.main`). **Also pass `--acc-hz 8`** for the synthetic mock data: the mock ACC
   signal is generated at 8 Hz, but `run_demo.py`'s default expected rate is 32 Hz (the real device rate).
   Without `--acc-hz 8`, every minute's `acc_coverage` reads as about 8/32 = 0.25, every window comes back
   `"limited"`, and there is no rest estimate for any night. It creates Silver/Gold tables if missing,
   catches up Silver then Gold (availableNow trigger -- processes everything available, then stops; pass
   `--continuous` only for a live, always-on replay), and prints row counts, the window_end range, quality
   status counts, null reasons, and rest-per-night.
4. **Expected runtime:** a few minutes for the full 3.5-day mock segment on the smallest cluster/serverless
   size (it's ~300k HR rows, ~2.4M ACC rows single-participant -- small). A live continuous replay runs for
   the length of the replay instead.
5. Run `databricks/sql/verify_gold.sql` (one query at a time) in a SQL editor against the same `:run_id`/
   `:participant_id`, and compare to the comments above each query.
6. In `.env`, set `FOCUSFLOW_REPLAY_SOURCE_KIND=synthetic_fixture` for the mock demo. If it is unset, the
   backend's `/api/health` label reads "Recorded wearable replay via Databricks" instead of the correct
   "SYNTHETIC mock wearable replay via Databricks - not real wearable data".

## Serverless compute: pickle repo modules by value
On serverless compute, `foreachBatch` runs the batch function in a separate Python worker process that
cannot import this repo's modules by reference (it has no access to the driver's `sys.path`). Both
`silver_stream.py` and `gold_stream.py` fail with `STREAMING_PYTHON_RUNNER_INITIALIZATION_FAILURE` and
`ModuleNotFoundError: databricks.streaming` until every already-loaded module under `databricks.streaming`
and `databricks.features` is registered for pickling **by value** instead of by reference. In the
notebook, before starting the streams:
```python
import sys
sys.path.insert(0, "/path/to/the/repo/root")   # the notebook needs the repo root on sys.path too

from pyspark import cloudpickle as cp   # must be pyspark's cloudpickle, not the standalone cloudpickle package
for name, mod in list(sys.modules.items()):
    if name.startswith("databricks.streaming") or name.startswith("databricks.features"):
        cp.register_pickle_by_value(mod)
```
Registering with the plain `cloudpickle` package (not `pyspark.cloudpickle`) does not work -- Spark's
Python worker only honors the registry on the `pyspark`-vendored copy. This was 13 modules at the time it
was hit; register whichever of this repo's modules are actually imported in the notebook.

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
(`/Volumes/<catalog>/<schema>/checkpoints/<checkpoint-root>/<run_id>/{silver,gold}`) are both keyed by
`run_id`, so nothing needs to be deleted.

To actually discard a bad run's rows: `DELETE FROM focusflow.main.silver_wearable_minute WHERE
run_id = '<run_id>'` (and same for gold), **then use a fresh checkpoint root** (bump the version, e.g.
`checkpoints/v4/...`) or delete the old checkpoint directory for that `run_id`, before rebuilding Silver
then Gold. If the rows are deleted but the old checkpoint is kept, Spark believes it already processed
that data and reads 0 new rows -- this showed up as Gold coming back with 0 rows, then a `KeyError` on
`estimated_rest_minutes` because Silver was empty.

Other gotchas hit while resetting a run on serverless:
- Never re-run the `DELETE` cell as part of "Run all" -- run Silver and Gold as separate cells so a
  reset does not race a stream that is already consuming the just-deleted rows.
- If a run hangs or a cancel gets stuck, terminate the serverless session entirely and start a fresh one
  (Memory setting High, 32GB) rather than retrying in the same session.

## Backend Gold reads: connector defaults and TLS
- `databricks-sql-connector` defaults both the per-socket timeout and the total retry duration to 900
  seconds (15 minutes), to tolerate a cold cluster start. A stopped SQL warehouse (common with a short
  `auto_stop_mins`) made `/api/state` hang for up to 15 minutes with no error before this was bounded in
  `backend/app/databricks_reader.py` (`CONNECT_TIMEOUT_SECONDS`, currently 30s). See `docs/decisions.md`
  for the fix details.
- On some machines, every Python connection to `*.cloud.databricks.com` fails with "self-signed
  certificate in certificate chain" while `curl` to the identical URL succeeds -- a local TLS-inspecting
  tool's root CA is trusted by the OS trust store (which `curl` uses) but not by Python's `certifi`
  bundle. `pip install pip-system-certs` (in `requirements.txt`) fixes this by pointing Python's `ssl`
  module at the OS trust store too. Not every machine needs it, but it is harmless if already trusted.
