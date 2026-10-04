# Data provenance

## Status

The intended recorded source is BIG IDEAs Lab Glycemic Variability and Wearable
Device Data **v1.1.3**. Its download was abandoned for this run. The supplied
`data/raw/001/{HR,EDA,ACC}_001.csv` files are mock generator outputs, labeled
`synthetic_fixture`; participant `001` is a synthetic identifier. Checksums and
inspection results below describe these mocks, not the PhysioNet release.
The five-minute smoke batch contains 3,900 events. Databricks job run
`783153108200122` succeeded: its notebook asserted the row count, unique event
IDs, synthetic source labels and preserved ACC unit flags, then reran ingestion
and verified the count remained 3,900. This verifies the smoke run only.

## Confirmed mock-generator assumptions

The user supplied the generator notes: naive timestamps are local
`America/New_York` wall time, formatted `YYYY-MM-DD HH:MM:SS.ffffff`.
Map the mock by adding **2,430 calendar days in local wall time**, then localize
to New York and convert to UTC. This differs from a constant UTC offset across
DST changes. Source timestamps retain their original date and UTC offset.
For example, February 13, 2020 12:00 EST maps to October 9, 2026 12:00 EDT
(source `17:00Z`, event `16:00Z`). Ambiguous/nonexistent mapped times fail the
publication rather than acquire a guessed offset. CLI runs print the explicit
naive-timezone assumption. This confirmation applies to the mock only; the
real dataset's timestamp format and timezone remain unverified.

Mock ACC consists of integer raw units at **8 Hz**, with an assumed scale of
**1/64 g per unit**. Raw values are not converted. Bronze ACC events retain
`unit=unverified`, `quality=flagged`; the manifest records the scale as a
synthetic assumption. Mock completeness reports explicitly use `--acc-hz 8`,
rather than the 32 Hz recorded-data default. Data B must explicitly configure
8 Hz and the synthetic scale before enabling mock ACC features. The 0.05 g
stillness threshold and 0.25 g activity scaling also depend on that assumption.
Mock consistency does not verify the real scale; real files/source metadata
still need to establish it. Unit-related quality flags must not be silently
treated as valid data when wiring downstream features.

## Data B mock demo segment

Use synthetic participant **001**, with unchanged raw files
`data/raw/001/HR_001.csv`, `EDA_001.csv`, and `ACC_001.csv`.
The mock files span February 13, 2020 12:00 through February 16, 2020
23:59:59 plus each signal's fractional samples, in New York local time.
The selected segment is half-open:

| Purpose | Source clock (America/New_York) | Scenario clock (America/New_York) |
| --- | --- | --- |
| 48 h history | 2020-02-13 12:00 to 2020-02-15 12:00 | 2026-10-09 12:00 to 2026-10-11 12:00 |
| 36 h demo | 2020-02-15 12:00 to 2020-02-17 00:00 | 2026-10-11 12:00 to 2026-10-13 00:00 |

The demo was extended by 12 hours to include the Feb 16 20:30–23:30 local
cramming episode. The trigger moment Feb 16 23:20 local maps to Oct 12 23:20
EDT, or `2026-10-13T03:20:00Z`. The original 72-hour prepared/uploaded run is
superseded; corrected publication requires a fresh run ID because both the end
boundary and the HR quality rule changed. Existing immutable files stay intact.

Rest calculation uses **22:00–08:00 America/New_York** on the scenario clock;
convert UTC event timestamps to that zone before assigning a night. This is
heuristic rest, not sleep staging. History availability does not itself prove
baseline sufficiency: Data B must still apply feature coverage/quality gates.

No CSVs were rewritten or physically cleaned. The inspection below counts the
entire original mock files. Data A omits the three nonfinite HR rows from event
publication, retains flagged finite rows and physical source-row IDs, and never
fills gaps. HR's 12 flags include 10 rows sharing five duplicate timestamps and
one zero measurement, plus the newly flagged 255 bpm reading (12 HR flags total);
EDA has one negative-value flag. HR values above 220 bpm are flagged with
`hr_above_engineering_range`, an engineering quality rule, and retained raw.
All ACC rows are flagged
solely for unverified units, rather than 2,392,800 malformed measurements.
Data B may evaluate the explicit synthetic scale assumption in its mock path,
retaining that uncertainty and other quality exclusions; real-data unit gates
remain unresolved.

Corrected run **`mock-demo-002`** has been prepared and uploaded in 39 immutable
batches: **3,890,102** events (298,502 HR; 1,198,800 EDA; 2,392,800 ACC).
Databricks verification job **`550393483724425`** succeeded. The notebook
asserted total/per-signal counts, unique event IDs, synthetic source labels,
ACC flags, the HR=255 flag and the trigger timestamp, then repeated ingestion
and verified the count remained 3,890,102. It ran on standard serverless compute
using `availableNow`; the compute terminated after the bounded run. This verifies
Data A's Bronze path, not Data B's Silver/Gold Spark wrappers. The earlier `mock-demo-001`
upload was stopped before job submission and is superseded.
See `databricks/ingestion/mock-handoff.md` for Data B's configuration and SQL.

Independent SQL verification confirmed the same per-signal counts, each equal
to its distinct event-ID count. All signals begin `2026-10-09T16:00:00Z`;
HR ends `2026-10-13T03:59:59Z`, EDA ends `03:59:59.750Z`, and ACC ends
`03:59:59.875Z` on that date. Quality counts: HR valid 298,490 / flagged 12;
EDA valid 1,198,799 / flagged 1; ACC flagged 2,392,800.

`DESCRIBE TABLE` confirmed the 14-column frozen Bronze schema. There is no
`flag_reason` or `quality_reason` Bronze column; the requested grouping query
failed with SQLSTATE 42703 (unresolved `flag_reason`). The adapter exposes
`quality_reason` only in local inspection DataFrames. Exact reason strings,
workspace/volume paths and ready-to-use Data B instructions are recorded in
`databricks/ingestion/DATA_B_HANDOFF.md`. Do not query placeholder columns.

## Sources and attribution

- Cho, P., Kim, J., Bent, B., & Dunn, J. (2026). *BIG IDEAs Lab Glycemic
  Variability and Wearable Device Data*, v1.1.3. PhysioNet.
  [Dataset and DOI](https://physionet.org/content/big-ideas-glycemic-wearable/1.1.3/).
- Bent, B., Cho, P. J., Henriquez, M., et al. (2021). *Engineering digital
  biomarkers of interstitial glucose from noninvasive smartwatches.*
  [Original publication](https://doi.org/10.1038/s41746-021-00465-w).
- Pollard, T., Moody, B. E., Lehman, L., et al. (2026). *PhysioNet as a global
  platform for biomedical research.*
  [PhysioNet citation](https://doi.org/10.1038/s44360-026-00096-z).
- Dataset license: Open Data Commons Attribution License v1.0; retain the
  release's `LICENSE.txt` and citations with exports and derived results.

## Timestamp and unit decisions

The dataset documentation specifies datetime `Timestamp` fields but does not
establish a timezone for the modified CSVs. Naive timestamps therefore require
an explicit `source_timezone`. Until supplied, the inspection report uses UTC
only as a duration/ordering surrogate, flags the unresolved assumption, and
withholds ET overnight calculations and participant recommendations. Source CSV
timestamp text is retained in inspection samples. Ambiguous/nonexistent local
times and malformed timestamps are dropped with a reason. Numeric epochs are
unsupported until their format is explicitly established.

Recorded replay defaults to one shared UTC-offset mapping:
`event_time = scenario_start + (source_timestamp - source_start)`.
Mapping anchors must be timezone-aware. Dataset dates are shifted and are not
real exam dates. Mock runs use the local-day mapping described above.
`ingested_at` is wall-clock UTC when a publication batch is prepared; retries
preserve that value.

HR is represented in `bpm`, EDA in `uS`, and TEMP in `degC`, following E4 channel
conventions. No values are scaled or downsampled by this adapter. ACC remains
the aligned raw `x/y/z` vector. The release explains that the original Empatica
format was modified; it does **not** specify the modified ACC scale or IBI units.
[Empatica's E4 documentation](https://www.empatica.com/blog/decoding-wearable-sensor-signals-what-to-expect-from-your-e4-data/)
provides device context, but cannot verify this release's transformed files.
**ACC scale and IBI units are unverified pending actual samples and source-format
confirmation.** They are emitted as `unit=unverified`, `quality=flagged` until
explicitly supplied. Data B must block affected feature calculations until the
unit choice is documented and confirmed. Even after verification, raw values
remain unchanged: e.g. `1/64g` is a raw unit, not a claim of conversion to `g`.

## Transformations and audit identifiers

- One-based `source_row` is assigned after the CSV header, before filtering;
  blank rows count. `event_id = <participant>-<signal>-<source_row:09d>`.
  The dedupe key includes `run_id`, so reset never collides with old audit data.
- Parsing and quality checks are vectorized, with bounded CSV chunks for ACC.
  Duplicate timestamps and reversed source order are flagged; distinct source
  rows are retained. The report counts timestamp duplicates exactly across chunks.
  Chunk parsing flags adjacent cross-chunk disorder/duplicates; nonadjacent
  duplicates across chunks are reported at file level. No missing samples are filled.
- Missing/nonfinite measurements and invalid timestamps are retained as dropped
  rows in local inspection, omitted from publication, and counted with reasons.
  The frozen event contract requires finite measurement values, so a malformed
  NaN payload cannot be published as a dropped event. Negative HR/EDA/IBI and
  zero HR/IBI are flagged, preserving the actual reading.
- Overnight coverage is measured over ET 22:00–08:00, using unique finite sample
  timestamps, expected samples per minute, a per-minute cap of one, and actual
  DST-aware night duration. This is sampling completeness, not estimated sleep.
  IBI has no nominal completeness denominator because it is event-based.
- Immutable JSONL files retain `source_file` and `source_row`. Bronze watches
  `.ready.json` commit markers published only after the final data upload returns.
  Remote copy/delete is not treated as an atomic move. Staging data are excluded
  from stream discovery. Insert-only MERGE enforces `(run_id,event_id)` dedupe.
- A bookmark publishes its real prefix first (at least 24 h); timestamp span
  alone does not establish a sufficient baseline. Data B must apply coverage and
  baseline quality gates. Reset uses new run and checkpoint paths and preserves
  old data. `processed_time` stays null until Data B supplies Gold progress.

## Scope and labeling

No BVP ingestion, sleep staging, or stress diagnosis. Heuristics from one adult
recording cannot validate student health or academic outcomes. Production raw
events use `source_kind=recorded_replay`; synthetic tests use `synthetic_fixture`.
The local demo command explicitly labels offline raw publication. Saved Silver/
Gold feature replay and calm/trigger bookmarks require Data B's actual derived
outputs and have not yet been prepared.

<!-- candidates:start -->
## Candidate inspection

Source kind: `synthetic_fixture`.

Selection is provisional; timestamp assumptions and channel units are recorded below.

### Participant 001

#### HR

```json
{
  "rows": 298505,
  "dropped_rows": 3,
  "flagged_rows": 12,
  "timestamp_rows": 298505,
  "quality_reasons": {
    "duplicate_timestamp;": 10,
    "missing_or_nonfinite_measurement;": 3,
    "nonpositive_hr_or_ibi;": 1,
    "hr_above_engineering_range;": 1
  },
  "file": "data/raw/001/HR_001.csv",
  "bytes": 9824700,
  "sha256": "b7752daccd6125f1e53ce31053f33adbff500e9cc71f643bf0c7b5e66d89d0f7",
  "samples": [
    {
      "Timestamp": "2020-02-13 12:00:00.000000",
      "Value": "88.0"
    },
    {
      "Timestamp": "2020-02-13 12:00:01.000000",
      "Value": "87.78"
    },
    {
      "Timestamp": "2020-02-13 12:00:02.000000",
      "Value": "87.42"
    }
  ],
  "timezone": "explicit assumption: America/New_York",
  "timezone_unresolved": false,
  "unique_timestamps": 298500,
  "duplicate_count": 5,
  "first_timestamp": "2020-02-13 17:00:00+00:00",
  "last_timestamp": "2020-02-17 04:59:59+00:00",
  "observed_hz": 1.0,
  "coverage_expected_hz": 1,
  "gaps_over_60s": 2,
  "largest_gap_seconds": 2701.0,
  "overnight_coverage": {
    "2020-02-13": 0.999972,
    "2020-02-14": 0.999972,
    "2020-02-15": 1.0,
    "2020-02-16": 0.2
  }
}
```

#### EDA

```json
{
  "rows": 1198800,
  "dropped_rows": 0,
  "flagged_rows": 1,
  "timestamp_rows": 1198800,
  "quality_reasons": {
    "negative_measurement;": 1
  },
  "file": "data/raw/001/EDA_001.csv",
  "bytes": 43023338,
  "sha256": "92049d6db7279198f8076323858a4f38c9f41931a6e94cc5d390e3f0713ff9d9",
  "samples": [
    {
      "Timestamp": "2020-02-13 12:00:00.000000",
      "Value": "0.594429"
    },
    {
      "Timestamp": "2020-02-13 12:00:00.250000",
      "Value": "0.608863"
    },
    {
      "Timestamp": "2020-02-13 12:00:00.500000",
      "Value": "0.59651"
    }
  ],
  "timezone": "explicit assumption: America/New_York",
  "timezone_unresolved": false,
  "unique_timestamps": 1198800,
  "duplicate_count": 0,
  "first_timestamp": "2020-02-13 17:00:00+00:00",
  "last_timestamp": "2020-02-17 04:59:59.750000+00:00",
  "observed_hz": 4.0,
  "coverage_expected_hz": 4,
  "gaps_over_60s": 1,
  "largest_gap_seconds": 2700.25,
  "overnight_coverage": {
    "2020-02-13": 1.0,
    "2020-02-14": 1.0,
    "2020-02-15": 1.0,
    "2020-02-16": 0.2
  }
}
```

#### ACC

```json
{
  "rows": 2392800,
  "dropped_rows": 0,
  "flagged_rows": 2392800,
  "timestamp_rows": 2392800,
  "quality_reasons": {
    "unit_unverified;": 2392800
  },
  "file": "data/raw/001/ACC_001.csv",
  "bytes": 85173304,
  "sha256": "2b2bf7e59149b172a7396a811bb2cf2a667c59dd82e524321e44f79c38a8a38b",
  "samples": [
    {
      "Timestamp": "2020-02-13 12:00:00.000000",
      "X": "-10",
      "Y": "26",
      "Z": "57"
    },
    {
      "Timestamp": "2020-02-13 12:00:00.125000",
      "X": "-22",
      "Y": "19",
      "Z": "45"
    },
    {
      "Timestamp": "2020-02-13 12:00:00.250000",
      "X": "-2",
      "Y": "10",
      "Z": "64"
    }
  ],
  "timezone": "explicit assumption: America/New_York",
  "timezone_unresolved": false,
  "unique_timestamps": 2392800,
  "duplicate_count": 0,
  "first_timestamp": "2020-02-13 17:00:00+00:00",
  "last_timestamp": "2020-02-17 04:59:59.875000+00:00",
  "observed_hz": 8.0,
  "coverage_expected_hz": 8.0,
  "gaps_over_60s": 2,
  "largest_gap_seconds": 2700.125,
  "overnight_coverage": {
    "2020-02-13": 1.0,
    "2020-02-14": 1.0,
    "2020-02-15": 1.0,
    "2020-02-16": 0.2
  }
}
```

Recommendation: {"participant": "001", "common_start": "2020-02-13 17:00:00+00:00", "baseline_history_start": "2020-02-13 17:00:00+00:00", "demo_start": "2020-02-15 17:00:00+00:00", "demo_end": "2020-02-17 05:00:00+00:00", "score": 3.199944, "status": "PROVISIONAL: inspect gaps and confirm timezone/units before selecting; no baseline quality claim"}

<!-- candidates:end -->
