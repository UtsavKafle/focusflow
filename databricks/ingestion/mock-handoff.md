# Data B handoff: corrected synthetic run

Run ID: **`mock-demo-002`**. Synthetic participant: **`001`**.
Source kind: **`synthetic_fixture`**. The source files are generator output,
not a downloaded PhysioNet recording. Bronze verification status is recorded
in `docs/data-provenance.md`; preparation/upload alone does not prove ingestion.

| Signal | Published rows | Flagged rows | Dropped before publication | Expected Hz |
| --- | ---: | ---: | ---: | ---: |
| HR | 298,502 | 12 | 3 | 1 |
| EDA | 1,198,800 | 1 | 0 | 4 |
| ACC | 2,392,800 | 2,392,800 | 0 | 8 |

Expected total: **3,890,102** unique `(run_id,event_id)` rows.

## Clock and feature configuration

- Raw naive timestamps: `America/New_York`; pass `--tz-assume America/New_York`.
- Add 2,430 local calendar days before localizing the mapped clock. Store UTC.
- History: Oct 9, 2026 noon to Oct 11 noon New York, or
  `[2026-10-09T16:00:00Z, 2026-10-11T16:00:00Z)`.
- Demo: Oct 11 noon to Oct 13 midnight New York, or
  `[2026-10-11T16:00:00Z, 2026-10-13T04:00:00Z)`.
- Trigger snapshot: `2026-10-13T03:20:00Z`; its HR event is
  `001-hr-000296106`. Presence does not prove the downstream trigger fires.
- Night calculation: 22:00–08:00 `America/New_York`, computed on scenario dates.
- ACC: `--acc-hz 8`, `acc_unit_scale_g=0.015625` as an explicit mock assumption.
  Raw Bronze vectors remain `unit=unverified`, `quality=flagged`. Data B must
  explicitly handle synthetic assumed units, while retaining uncertainty and
  excluding measurement anomalies. The real-data scale remains unverified.
- Stillness threshold 0.05 g and activity scaling 0.25 g depend on that scale.
- HR above 220 bpm: `hr_above_engineering_range` flag, retained raw.
  HR=255 is event `001-hr-000003501`, at `2026-10-09T16:58:20Z`.
- No missing readings are filled. The three nonfinite HR rows are omitted.
  Ten HR duplicate-timestamp rows, one zero HR and one negative EDA remain flagged.

## Reading Bronze

Bronze has **no `flag_reason` or `quality_reason` column**. Its frozen event
contract includes `quality` (`valid`, `flagged`, `dropped`), plus the two Bronze
provenance fields `source_file` and `source_row`. Do not query placeholder reason
columns in Spark wrappers. The adapter's local inspection DataFrames expose
`quality_reason`: semicolon-separated tokens with a trailing semicolon; no
reason is the empty string. Those tokens are:

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

These are local inspection diagnostics, not Bronze columns. If per-row reasons
must be persisted, agree an additive Bronze metadata/schema change with the
Integrator and both data roles first. This handoff does not change the contract.

Always filter by run ID. The table also contains the successful five-minute
smoke run, which is not the demo and does not provide baseline history.

```sql
SELECT signal, quality, unit, COUNT(*) AS row_count,
       MIN(event_time) AS first_event, MAX(event_time) AS last_event
FROM focusflow.main.bronze_wearable_events
WHERE run_id = 'mock-demo-002'
GROUP BY signal, quality, unit
ORDER BY signal, quality;

SELECT run_id, event_id, COUNT(*) AS copies
FROM focusflow.main.bronze_wearable_events
WHERE run_id = 'mock-demo-002'
GROUP BY run_id, event_id
HAVING COUNT(*) > 1;
```

The old `mock-demo-001` landing upload was stopped and is superseded. Its
immutable audit files are preserved; do not use them for features.

Raw files/checksums and global inspection: `docs/data-provenance.md`.
Local prepared manifest/notebook: `data/derived/mock-demo-002/` (gitignored).
Landing root: `/Volumes/focusflow/main/landing/mock-demo-002/`.
Checkpoint: `/Volumes/focusflow/main/checkpoints/mock-demo-002/bronze`.
All bulk data are prepared before feature calculation; compute baselines and
trailing windows using only rows at/before the current feature cutoff, never
future rows. The backend still serves fixtures; Silver/Gold/API wiring and
derived-results fallback require Data B and Integrator work.
