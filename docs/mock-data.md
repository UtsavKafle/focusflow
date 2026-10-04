# Mock BIG IDEAs data (SYNTHETIC, so nobody waits on the real download)

**Not real wearable data.** It mimics the file layout of PhysioNet BIG IDEAs v1.1.3 (folder `001`, files `HR_001.csv`, `EDA_001.csv`, ...) so adapters, features and the replay can be built now and pointed at the real files later with no code change. Label it `synthetic_fixture` in any payload. Never present it as real, and never use it to claim validity.

## Generate (10 s, deterministic, numpy + pandas only)
```bash
python fixtures/make_mock_big_ideas.py --out data/mock          # ~190 MB: data/mock/001/*.csv + data/mock/Demographics.csv
# full 32 Hz ACC (about 340 MB for ACC alone):  --acc-hz 32
```
`data/mock/` is gitignored. Everyone generates their own copy (same seed gives identical files).

## What is in `data/mock/001/`
| File | Rate in the mock | Columns | Notes |
|---|---|---|---|
| `HR_001.csv` | 1 Hz | `Timestamp,Value` | bpm. 5 duplicate rows, 3 empty `Value`, 2 implausible (0 and 255) |
| `EDA_001.csv` | 4 Hz | `Timestamp,Value` | microsiemens. 1 implausible negative value |
| `TEMP_001.csv` | 4 Hz | `Timestamp,Value` | degrees C (skin) |
| `ACC_001.csv` | **8 Hz** (real is 32 Hz) | `Timestamp,X,Y,Z` | integer raw units, assumed 1/64 g (UNVERIFIED) |
| `IBI_001.csv` | event-based | `Timestamp,Value` | seconds; only emitted while fairly still |
| `Dexcom_001.csv` | every 5 min | `Timestamp,Value` | mg/dL |
| `Food_Log_001.csv` | 11 meals | `date,time_begin,logged_food,amount,unit,calorie,total_carb,sugar,protein` | |
| `../Demographics.csv` | 1 row | `ID,Age,BMI,HbA1c,Fasting_GLU_mgdl,NOTE` | |

Timestamps: `YYYY-MM-DD HH:MM:SS.ffffff`, naive, **local America/New_York wall time** (use `--tz-assume America/New_York`). The real dataset's exact timestamp format and timezone are still unverified; treat the mock as a stand-in. Real ACC is 32 Hz, so pass the true rates to anything that computes coverage (`--acc-hz 8` for the mock).

## The story inside it (local time, 2020-02-13 12:00 to 2020-02-17 00:00, 3.5 days)
- Nights 02-13 to 02-14 and 02-14 to 02-15: normal (about 474 still minutes each).
- Night 02-15 to 02-16: restless and short (two still stretches of about 2 h each, estimated rest 130 min of 480, recovery about 0.27).
- 02-14 17:00 to 17:40: exercise (HR about 150). Movement confound. The load trigger must be suppressed here.
- 02-16 20:30 to 23:30: sustained cramming (HR 78 to 98, EDA 0.7 to 2.2, body still). By 23:20 the last 20 minutes have load >= 0.70. This is the trigger moment.
- First 24 h is baseline warm-up (load is null with reason `baseline_warmup` until 02-14 12:00).
- Planted problems: 45-min all-signal gap (02-14 15:10 to 15:55), HR-only dropout (02-15 09:00 to 09:20), ACC-only gap (02-15 14:00 to 14:10).

## Mapping into the exam-week scenario (Data A replay)
Trigger moment source `2020-02-16 23:20` local maps to scenario `2026-10-12 23:20` local ET (= `2026-10-13T03:20:00Z`, the fixture's `as_of`). Shift by whole days in LOCAL wall time, then localize to America/New_York: `+2430 days`. Do not add a UTC timedelta (Feb is EST, Oct is EDT; the local time of day must be preserved). The fixture calendar (`fixtures/scenarios/trigger/calendar.json`) then lines up: Algorithms review planned 11:30 PM to 1:00 AM, STAT exam Tuesday 9:00 AM.

## Precomputed expected outputs (tracked in git): `fixtures/mock_big_ideas/`
`silver.csv` and `gold.csv` produced by `python -m databricks.features.run_local --participant 001 --raw data/mock --tz-assume America/New_York --acc-hz 8 --run-id mock-1`. Use them to build and test the backend reader, the Gold-to-contract path and the UI against realistic Gold rows before Databricks works. Expected: rest 474, 474 and 130 minutes for the three completed nights; load 1.0 and `activity_confound=True` during the exercise; last 20 minutes load >= 0.70 with recovery about 0.27; 3525 sufficient / 1450 limited / 65 unavailable windows. `tests/test_mock_story.py` pins these.

Read the CSVs with `dtype={"participant_id": str}` so `001` keeps its leading zeros.

## Who uses it for what
- **Data A:** run `quick_scan.py data/mock` and your coverage report on it; build the adapter, `NormalizedEvent` conversion (duplicates, empty and implausible values must become flagged or dropped, never zeros), landing writer, Bronze and the replay controller against it. Swap to real files by changing the folder.
- **Data B:** `run_local` on the mock; tune nothing on it (it is built to behave). Build the Spark wrappers and idempotency tests against it. Compare your Spark Gold with `fixtures/mock_big_ideas/gold.csv`.
- **Integrator:** read `gold.csv` rows through `row_to_wearable_state`, compose `StudentState`, drive the trigger engine over the whole 3.5 days (it should fire near the end and not during the exercise or warm-up).
- **Frontend:** the mock API fixtures are enough; optionally plot `gold.csv` history to test gaps-as-gaps rendering.
