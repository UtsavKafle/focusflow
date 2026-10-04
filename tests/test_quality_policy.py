"""databricks/features/quality_policy.py and bronze_adapter.py: every quality branch, plus a cross-check of
the raw-CSV adapter against Data A's VERIFIED Bronze counts (databricks/ingestion/DATA_B_HANDOFF.md) -- the
real table, not just the local mock CSVs. No `flag_reason`/`quality_reason` column exists on real Bronze;
ACC usability is decided from `unit`."""
import pathlib

import pandas as pd
import pytest

from databricks.features.bronze_adapter import (
    acc_rows_from_raw, bronze_rows_for_participant, bronze_to_minute_frames, eda_rows_from_raw, hr_rows_from_raw,
)
from databricks.features.quality_policy import ACC_UNVERIFIED_UNIT, QualityPolicy, acc_is_usable, filter_acc, filter_hr_eda
from databricks.streaming.bronze_contract import BRONZE_COLUMNS, validate_bronze_columns, validate_bronze_values

MOCK_RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "001"

# Data A's verified Bronze counts for run mock-demo-002 (databricks/ingestion/DATA_B_HANDOFF.md).
DATA_A_HR_TOTAL, DATA_A_HR_FLAGGED = 298_502, 12
DATA_A_EDA_TOTAL, DATA_A_EDA_FLAGGED = 1_198_800, 1
DATA_A_ACC_TOTAL = 2_392_800


def test_policy_for_source_kind():
    assert QualityPolicy.for_source_kind("synthetic_fixture").acc_scale_assumption == "mock_assume_1_64g"
    assert QualityPolicy.for_source_kind("recorded_replay").acc_scale_assumption == "exclude_until_verified"
    assert not acc_is_usable(QualityPolicy(acc_scale_assumption="exclude_until_verified"))
    assert acc_is_usable(QualityPolicy(acc_scale_assumption="mock_assume_1_64g"))


def test_filter_hr_eda_excludes_flagged_dropped_and_out_of_range():
    rows = pd.DataFrame({
        "quality": ["valid", "flagged", "dropped", "valid"],
        "values": [{"value": 70.0}, {"value": 70.0}, {"value": 70.0}, {"value": 500.0}],
    })
    kept = filter_hr_eda(rows, plausible=(30.0, 220.0))
    assert len(kept) == 1 and kept["values"].iloc[0]["value"] == 70.0


def test_filter_acc_mock_assume_keeps_unverified_unit_drops_dropped_and_other_units():
    rows = pd.DataFrame({
        "quality": ["valid", "flagged", "flagged", "dropped"],
        "unit": [ACC_UNVERIFIED_UNIT, ACC_UNVERIFIED_UNIT, "g", ACC_UNVERIFIED_UNIT],
        "values": [{"x": 1.0, "y": 1.0, "z": 1.0}] * 4,
    })
    kept = filter_acc(rows, policy=QualityPolicy(acc_scale_assumption="mock_assume_1_64g"))
    assert len(kept) == 2  # rows 0 and 1: unit=unverified, not dropped. Row 2 (verified unit) and row 3 (dropped) excluded.


def test_filter_acc_exclude_until_verified_drops_unverified_unit_only():
    rows = pd.DataFrame({
        "quality": ["valid", "flagged"],
        "unit": [ACC_UNVERIFIED_UNIT, "g"],
        "values": [{"x": 1.0, "y": 1.0, "z": 1.0}] * 2,
    })
    kept = filter_acc(rows, policy=QualityPolicy(acc_scale_assumption="exclude_until_verified"))
    assert len(kept) == 1 and kept["unit"].iloc[0] == "g"  # only the (hypothetical) verified-unit row survives


def test_filter_acc_excludes_nonfinite_values():
    rows = pd.DataFrame({
        "quality": ["valid", "valid"],
        "unit": [ACC_UNVERIFIED_UNIT, ACC_UNVERIFIED_UNIT],
        "values": [{"x": 1.0, "y": 1.0, "z": 1.0}, {"x": float("nan"), "y": 1.0, "z": 1.0}],
    })
    kept = filter_acc(rows, policy=QualityPolicy(acc_scale_assumption="mock_assume_1_64g"))
    assert len(kept) == 1


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_hr_counts_match_data_a_verified_bronze():
    """Nonfinite HR readings are OMITTED entirely (never written with quality=dropped) -- matching Data A's
    verified Bronze exactly: 298,502 rows, not the mock CSV's raw 298,505."""
    hr = hr_rows_from_raw(MOCK_RAW / "HR_001.csv", tz_assume="America/New_York", participant_id="001")
    assert len(hr) == DATA_A_HR_TOTAL
    assert (hr["quality"] == "dropped").sum() == 0
    assert (hr["quality"] == "flagged").sum() == DATA_A_HR_FLAGGED
    assert (hr["quality"] == "valid").sum() == DATA_A_HR_TOTAL - DATA_A_HR_FLAGGED
    above = hr[hr["values"].map(lambda v: v["value"]) == 255.0].iloc[0]
    assert above["quality"] == "flagged"
    assert above["event_time"].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S") == "2020-02-13 12:58:20"


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_eda_counts_match_data_a_verified_bronze():
    eda = eda_rows_from_raw(MOCK_RAW / "EDA_001.csv", tz_assume="America/New_York", participant_id="001")
    assert len(eda) == DATA_A_EDA_TOTAL
    assert (eda["quality"] == "dropped").sum() == 0
    assert (eda["quality"] == "flagged").sum() == DATA_A_EDA_FLAGGED


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_acc_counts_match_data_a_verified_bronze():
    acc = acc_rows_from_raw(MOCK_RAW / "ACC_001.csv", tz_assume="America/New_York", participant_id="001")
    assert len(acc) == DATA_A_ACC_TOTAL
    assert (acc["quality"] == "flagged").all()
    assert (acc["unit"] == ACC_UNVERIFIED_UNIT).all()


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_bronze_rows_for_participant_match_bronze_contract():
    bronze = bronze_rows_for_participant(MOCK_RAW.parent, "001", tz_assume="America/New_York", run_id="t1", source_kind="synthetic_fixture")
    validate_bronze_columns(bronze)
    validate_bronze_values(bronze)
    assert len(bronze) == DATA_A_HR_TOTAL + DATA_A_EDA_TOTAL + DATA_A_ACC_TOTAL


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_bronze_to_minute_frames_mock_policy_uses_acc():
    bronze = bronze_rows_for_participant(MOCK_RAW.parent, "001", tz_assume="America/New_York", run_id="t1", source_kind="synthetic_fixture")
    policy = QualityPolicy.for_source_kind("synthetic_fixture")
    frames = bronze_to_minute_frames(bronze, policy)
    assert len(frames["acc"]) == DATA_A_ACC_TOTAL          # every row usable (flagged only for unverified units)
    assert len(frames["hr"]) == DATA_A_HR_TOTAL - DATA_A_HR_FLAGGED
    assert len(frames["eda"]) == DATA_A_EDA_TOTAL - DATA_A_EDA_FLAGGED


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_bronze_to_minute_frames_recorded_replay_excludes_acc():
    bronze = bronze_rows_for_participant(MOCK_RAW.parent, "001", tz_assume="America/New_York", run_id="t1", source_kind="recorded_replay")
    frames = bronze_to_minute_frames(bronze, QualityPolicy.for_source_kind("recorded_replay"))
    assert frames["acc"].empty
    assert len(frames["hr"]) == DATA_A_HR_TOTAL - DATA_A_HR_FLAGGED     # HR/EDA policy is unaffected by source_kind


def test_shift_days_preserves_local_time_of_day_across_dst():
    hr = pd.DataFrame({"Timestamp": ["2020-02-13 12:00:00.000000"], "Value": [70.0]})
    tmp = pathlib.Path("/tmp") / "shift_hr.csv"
    hr.to_csv(tmp, index=False)
    unshifted = hr_rows_from_raw(tmp, tz_assume="America/New_York")
    shifted = hr_rows_from_raw(tmp, tz_assume="America/New_York", shift_days=2430)
    tmp.unlink()
    u_local = unshifted["event_time"].iloc[0].tz_convert("America/New_York")
    s_local = shifted["event_time"].iloc[0].tz_convert("America/New_York")
    assert (u_local.hour, u_local.minute) == (s_local.hour, s_local.minute) == (12, 0)
    assert s_local.strftime("%Y-%m-%d") == "2026-10-09"   # +2430 days, Feb -> Oct (EST -> EDT)
    assert s_local.utcoffset().total_seconds() / 3600 == -4   # EDT, not EST


def test_validate_bronze_columns_fails_closed_on_missing_column():
    df = pd.DataFrame({c: [] for c in BRONZE_COLUMNS if c != "unit"})
    with pytest.raises(ValueError, match="unit"):
        validate_bronze_columns(df)


def test_validate_bronze_values_fails_closed_on_bad_value():
    df = pd.DataFrame({c: ["x"] for c in BRONZE_COLUMNS})
    df["source_kind"] = ["synthetic_fixture"]
    df["signal"] = ["hr"]
    df["quality"] = ["not_a_real_quality_value"]
    with pytest.raises(ValueError, match="quality"):
        validate_bronze_values(df)
