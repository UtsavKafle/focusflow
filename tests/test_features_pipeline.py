import json
import numpy as np
import pandas as pd
import pytest

from databricks.features.baselines import BaselineConfig, add_baselines
from databricks.features.minute_features import minute_features
from databricks.features.state import GoldConfig, build_gold, row_to_wearable_state
from databricks.features.synthetic import make_signals

CFG = BaselineConfig(warmup_minutes=360, refresh_minutes=10)


def run(days=3.0, **kw):
    hr, eda, acc, hz = make_signals(days=days, **kw)
    sil = minute_features(hr, eda, acc, expected_hz=hz)
    z = add_baselines(sil, CFG)
    g = build_gold(z, run_id="r1", participant_id="p1", source_kind="synthetic_fixture")
    return sil, z, g


@pytest.fixture(scope="module")
def base():
    return run(episode_minutes=90)


def test_minute_windows_half_open_and_coverage(base):
    sil, _, _ = base
    assert (sil["window_end"] - sil["window_start"] == pd.Timedelta(minutes=1)).all()
    assert sil["hr_coverage"].between(0, 1).all()
    assert sil["hr_coverage"].iloc[5] == pytest.approx(1.0)


def test_gap_is_null_not_zero():
    sil, _, g = run(days=1.0, night_gap=(600, 640))
    gap = sil[(sil["window_start"] >= pd.Timestamp("2026-10-10T22:00Z")) & (sil["window_start"] < pd.Timestamp("2026-10-10T22:40Z"))]
    assert gap["hr_mean_bpm"].isna().all() and (gap["hr_coverage"] == 0).all()
    gg = g[(g["window_start"] >= pd.Timestamp("2026-10-10T22:05Z")) & (g["window_start"] < pd.Timestamp("2026-10-10T22:35Z"))]
    assert gg["heart_rate_bpm"].isna().all() and gg["physiological_load"].isna().all()
    for q in gg["quality_json"]:
        assert "physiological_load" in json.loads(q)["missing_reasons"]


def test_warmup_nulls_then_values(base):
    _, z, g = base
    early = g.iloc[:300]
    assert early["physiological_load"].isna().all()
    assert all(json.loads(q)["missing_reasons"]["physiological_load"] == "baseline_warmup" for q in early["quality_json"][:300])
    assert g["physiological_load"].iloc[2000:].notna().all()


def test_no_future_leakage():
    hr, eda, acc, hz = make_signals(days=2.0, episode_minutes=0)
    full = add_baselines(minute_features(hr, eda, acc, expected_hz=hz), CFG)
    cut = pd.Timestamp("2026-10-11T12:00:00Z")
    part = add_baselines(minute_features(hr[hr.event_time < cut], eda[eda.event_time < cut], acc[acc.event_time < cut], expected_hz=hz), CFG)
    n = len(part)
    a, b = full.iloc[:n]["hr_baseline_z"].to_numpy(), part["hr_baseline_z"].to_numpy()
    assert np.allclose(a, b, equal_nan=True)
    a, b = full.iloc[:n]["eda_baseline_z"].to_numpy(), part["eda_baseline_z"].to_numpy()
    assert np.allclose(a, b, equal_nan=True)
    assert (full["baseline_cutoff"] <= full["window_start"]).all()


def test_future_spike_does_not_change_past():
    hr, eda, acc, hz = make_signals(days=2.0)
    base_ = add_baselines(minute_features(hr, eda, acc, expected_hz=hz), CFG)
    hr2 = hr.copy(); hr2.loc[hr2.event_time >= pd.Timestamp("2026-10-12T06:00Z"), "value"] += 100
    spiked = add_baselines(minute_features(hr2, eda, acc, expected_hz=hz), CFG)
    mask = base_["window_start"] < pd.Timestamp("2026-10-12T06:00Z")
    assert np.allclose(base_.loc[mask, "hr_baseline_z"], spiked.loc[mask, "hr_baseline_z"], equal_nan=True)


def test_episode_gives_high_load_and_no_confound(base):
    _, _, g = base
    tail = g.iloc[-30:]
    assert (tail["physiological_load"] >= 0.7).all()
    assert not tail["activity_confound"].any()
    assert g["physiological_load"].dropna().iloc[1500:3500].mean() < 0.5


def test_movement_sets_confound(base):
    _, _, g = base
    day = g[(g["window_start"] >= pd.Timestamp("2026-10-12T15:00Z")) & (g["window_start"] < pd.Timestamp("2026-10-12T16:00Z"))]
    assert day["activity_confound"].mean() > 0.3


def test_rest_estimate_on_synthetic_night(base):
    _, _, g = base
    # night 22:30 -> 06:30 ET = 480 min still; last completed night at end of run is Oct 11 -> Oct 12
    last = g.iloc[-1]
    assert 440 <= last["estimated_rest_minutes"] <= 485
    assert last["recovery_score"] == pytest.approx(min(1, last["estimated_rest_minutes"] / 480), abs=1e-3)
    assert any(e.startswith("rest-") for e in last["evidence_ids"])


def test_rest_null_when_night_has_gap():
    _, _, g = run(days=3.0, night_gap=(14 * 60, 20 * 60))   # 02:00Z..08:00Z of night 1 missing
    row = g[g["window_end"] == pd.Timestamp("2026-10-11T13:00:00Z")].iloc[0]
    assert pd.isna(row["estimated_rest_minutes"]) and pd.isna(row["recovery_score"])
    mr = json.loads(row["quality_json"])["missing_reasons"]
    assert mr["estimated_rest_minutes"] == "overnight_coverage_below_minimum" and mr["recovery_score"]


def test_gold_rows_validate_against_contract(base):
    _, _, g = base
    for row in g.iloc[::37].to_dict("records"):
        ws = row_to_wearable_state(row)
        assert ws.target_rest_minutes == 480
    assert g.iloc[0]["source_kind"] == "synthetic_fixture"


def test_determinism(base):
    _, _, g1 = base
    _, _, g2 = run(episode_minutes=90)
    pd.testing.assert_frame_equal(g1, g2)


def test_implausible_values_become_missing_not_zero():
    from databricks.features.minute_features import minute_features as mf
    hr, eda, acc, hz = make_signals(days=0.05)
    hr.loc[hr.index[10:70], "value"] = 0.0          # one full minute of HR=0 artifacts
    eda.loc[eda.index[10:70], "value"] = -1.0
    sil = mf(hr, eda, acc, expected_hz=hz)
    row = sil.iloc[0]
    assert pd.isna(sil["hr_mean_bpm"].iloc[0]) or sil["hr_mean_bpm"].iloc[0] > 30
    assert (sil["hr_mean_bpm"].dropna() > 30).all() and (sil["eda_mean"].dropna() >= 0).all()
