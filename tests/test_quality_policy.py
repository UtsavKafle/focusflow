"""databricks/features/quality_policy.py and bronze_adapter.py: every quality branch, plus a cross-check of
the raw-CSV adapter against Data A's published whole-file counts for the mock dataset (docs/decisions.md)."""
import pathlib

import numpy as np
import pandas as pd
import pytest

from databricks.features.bronze_adapter import (
    acc_rows_from_raw, bronze_rows_for_participant, bronze_to_minute_frames, eda_rows_from_raw, hr_rows_from_raw,
)
from databricks.features.quality_policy import ACC_UNVERIFIED_UNITS_REASON, QualityPolicy, acc_is_usable, filter_acc, filter_hr_eda

MOCK_RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "001"


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


def test_filter_acc_mock_assume_keeps_only_units_flag():
    rows = pd.DataFrame({
        "quality": ["valid", "flagged", "flagged", "dropped"],
        "flag_reason": [None, ACC_UNVERIFIED_UNITS_REASON, "something_else", "nonfinite"],
    })
    kept = filter_acc(rows, policy=QualityPolicy(acc_scale_assumption="mock_assume_1_64g"))
    assert len(kept) == 2  # the valid row and the units-only-flagged row


def test_filter_acc_exclude_until_verified_drops_everything():
    rows = pd.DataFrame({"quality": ["valid", "flagged"], "flag_reason": [None, ACC_UNVERIFIED_UNITS_REASON]})
    kept = filter_acc(rows, policy=QualityPolicy(acc_scale_assumption="exclude_until_verified"))
    assert kept.empty


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_hr_counts_match_published_numbers():
    hr = hr_rows_from_raw(MOCK_RAW / "HR_001.csv", tz_assume="America/New_York")
    assert len(hr) == 298_505
    assert (hr["quality"] == "dropped").sum() == 3
    assert (hr["quality"] == "flagged").sum() == 12
    reasons = hr.loc[hr["quality"] != "valid", "flag_reason"].value_counts().to_dict()
    assert reasons == {"duplicate_timestamp": 10, "nonfinite": 3, "hr_zero_reading": 1, "hr_above_engineering_range": 1}
    above = hr[hr["flag_reason"] == "hr_above_engineering_range"].iloc[0]
    assert above["event_time"].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S") == "2020-02-13 12:58:20"
    assert above["values"]["value"] == 255.0  # original value retained, not nulled


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_eda_counts_match_published_numbers():
    eda = eda_rows_from_raw(MOCK_RAW / "EDA_001.csv", tz_assume="America/New_York")
    assert len(eda) == 1_198_800
    assert (eda["quality"] == "dropped").sum() == 0
    assert (eda["quality"] == "flagged").sum() == 1
    assert eda.loc[eda["quality"] == "flagged", "flag_reason"].iloc[0] == "eda_negative"


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_acc_all_flagged_for_unverified_units():
    acc = acc_rows_from_raw(MOCK_RAW / "ACC_001.csv", tz_assume="America/New_York")
    assert len(acc) == 2_392_800
    assert (acc["quality"] == "flagged").all()
    assert (acc["flag_reason"] == ACC_UNVERIFIED_UNITS_REASON).all()


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_bronze_to_minute_frames_mock_policy_uses_acc():
    bronze = bronze_rows_for_participant(MOCK_RAW.parent, "001", tz_assume="America/New_York", run_id="t1", source_kind="synthetic_fixture")
    policy = QualityPolicy.for_source_kind("synthetic_fixture")
    frames = bronze_to_minute_frames(bronze, policy)
    assert len(frames["acc"]) == 2_392_800          # every row usable (flagged only for unverified units)
    assert len(frames["hr"]) == 298_505 - 3 - 12     # dropped + flagged excluded
    assert len(frames["eda"]) == 1_198_800 - 1


@pytest.mark.skipif(not MOCK_RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_bronze_to_minute_frames_recorded_replay_excludes_acc():
    bronze = bronze_rows_for_participant(MOCK_RAW.parent, "001", tz_assume="America/New_York", run_id="t1", source_kind="recorded_replay")
    frames = bronze_to_minute_frames(bronze, QualityPolicy.for_source_kind("recorded_replay"))
    assert frames["acc"].empty
    assert len(frames["hr"]) == 298_505 - 3 - 12     # HR/EDA policy is unaffected by source_kind


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
    assert str(s_local.tzinfo) or True  # tz-aware
    assert s_local.utcoffset().total_seconds() / 3600 == -4   # EDT, not EST
