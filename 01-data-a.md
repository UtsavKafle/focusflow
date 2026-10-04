# 01 Handoff: Data A (ingestion, normalization, Bronze, replay controller)

You are the coding agent for Data A. Read `00-common.md` first. You own `databricks/ingestion/`, `simulator/`, `databricks/sql/ddl_bronze.sql`, `docs/data-provenance.md`.

**Mission:** get one participant's HR, EDA, ACC (then IBI, TEMP) from raw BIG IDEAs CSVs into a clean, replayable Bronze table in Databricks, and give the backend a replay controller (start, pause, reset, status, speed, bookmark).

## Inputs
- Raw files: BIG IDEAs v1.1.3, folders `001` to `016`, each with `ACC.csv, BVP.csv, Dexcom.csv, EDA.csv, HR.csv, IBI.csv, TEMP.csv` plus `Demographics.csv` at the top. `Timestamp`/`Value`; ACC has `Timestamp`/`X`/`Y`/`Z`. Nominal rates: HR 1 Hz, EDA and TEMP 4 Hz, ACC 32 Hz, IBI event-based. Put files in `data/raw/<participant>/` (gitignored). Do not download the full 34 GB.
- Contract: `NormalizedEvent` in `contracts/models.py`. Fixture calendar for the overlay: `fixtures/scenarios/trigger/calendar.json` (synthetic).

## Tasks in order
**M1 (to Sat 19:00)**
1. `databricks/ingestion/coverage_report.py`: for each candidate participant, print per-signal row counts, first/last timestamp, observed sampling rate, duplicate count, gaps over 60 s, overnight coverage per night (ET 22:00 to 08:00 using the shifted dates as given), file sizes, and sample rows. Output markdown to `docs/data-provenance.md` candidates section. Run it on whatever files exist. Do not assume the timezone: print raw timestamp text and flag the assumption.
2. Recommend a participant (best HR+EDA+ACC overnight coverage across 8 to 10 days) and a demo segment with a prior 24 to 48 h of history. Tell your human and Data B immediately.
3. `databricks/ingestion/adapter.py`: pure Python/pandas, no Spark. `parse_signal(path, signal) -> DataFrame` and `to_events(df, signal, run_id, participant_id) -> list[NormalizedEvent-shaped dicts]`. Deterministic `event_id = f"{participant}-{signal}-{source_row:09d}"`. ACC as x/y/z. Verify and document ACC scale and IBI units (do not guess, check the dataset page and the data; block affected features until verified and say so in provenance). Drop/flag malformed rows with `quality`, never zeros. Unit tests with 20-row fixtures.
4. Write `docs/data-provenance.md`: dataset version, participant, file sha256, timestamp mapping, dropped/flagged counts, units verified.

**M2 (to Sun 00:00)**
5. `databricks/sql/ddl_bronze.sql`: `bronze_wearable_events` per `00-common.md`.
6. Landing writer `databricks/ingestion/landing_writer.py`: writes immutable JSON-lines files to `/Volumes/focusflow/main/landing/<run_id>/<signal>/batch-<n>.jsonl`, written to a temp name then moved so Spark never sees a partial file. Uses `databricks-sdk` (Files API) or `dbutils` depending on where it runs. Time-offset mapping: `event_time = scenario_start + (source_timestamp - source_start)` for all signals identically; record `ingested_at` as wall-clock.
7. Replay controller `simulator/replay.py`:
   ```python
   class ReplayController:
       def start(self, run_id: str, scenario_id: str, speed: float, bookmark: datetime | None) -> str
       def pause(self) -> None
       def reset(self) -> str      # new run_id, new checkpoint paths, old data preserved
       def status(self) -> ReplayStatus   # contracts.models.ReplayStatus
   ```
   Speeds 1, 10, 60, 300. Publication is paced by speed; status reports published_time vs processed_time (Data B supplies processed_time from Gold max `as_of`; stub it until then). Bookmark requires history: either replay the prefix quickly in bulk first, or restore a prepared snapshot. Never jump into a high-load window with a fabricated baseline.
8. Bronze stream job `databricks/ingestion/bronze_stream.py`: Auto Loader or `readStream` on the landing path into `bronze_wearable_events`, dedupe on `(run_id, event_id)`, checkpoint at `/Volumes/.../checkpoints/<run_id>/bronze`. If serverless forbids the trigger you need, use `availableNow` in a loop and say so.
9. Bounded demo run script: replay the chosen 12 to 24 h segment with the prior baseline history, and finish. No always-on streams.

**M3 and M4**
10. Add IBI and TEMP ingestion if time allows (after the HR/EDA path is proven end to end).
11. Prepare the **saved-results fallback**: export derived Silver/Gold for the demo segment to `data/derived/<run>/` (gitignored) or a Delta table, and a `FEATURE REPLAY` mode in the controller that replays Gold rows without recompute. Label it everywhere.
12. Bookmarks for the 3-minute demo: one "calm" and one "trigger" moment with prepared history.

## Definition of done
- Provenance doc complete and honest. Unit tests pass. Bronze has the demo segment, no duplicates, nulls not zeros.
- Controller start/pause/reset/status works in fixture-less mode against a real run and from the backend via import.
- Reset creates a new run with new checkpoints and keeps old audit data.

## Gotchas
- Dates in the dataset are shifted but time of day is preserved. Do not claim real calendar dates.
- Do not process BVP. Do not put 32 Hz ACC through slow row-by-row Python at scale: batch writes, and consider downsampling ACC to 1 s summaries in the adapter only if documented in provenance.
- If you have no workspace access yet, finish steps 1 to 4 locally (they need none) and tell your human.
