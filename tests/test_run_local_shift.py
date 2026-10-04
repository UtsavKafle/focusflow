"""run_local.py --shift-days: a shifted run (the scenario clock) must give IDENTICAL loads, rest minutes and
baseline/rest reasons to the unshifted run on the same raw data -- only timestamps may differ, and the
mapped timestamps must land in EDT (Oct), not EST (Feb's own offset), confirming the local-time-of-day
preservation rule."""
import json
import pathlib
import shutil
import subprocess
import sys

import pandas as pd
import pytest

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "001"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(tmp_out: pathlib.Path, run_id: str, *, shift_days: int) -> pd.DataFrame:
    subprocess.run([sys.executable, "-m", "databricks.features.run_local", "--participant", "001", "--raw", "data/raw",
                    "--tz-assume", "America/New_York", "--acc-hz", "8", "--shift-days", str(shift_days),
                    "--source-kind", "synthetic_fixture", "--run-id", run_id, "--out", str(tmp_out)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    return pd.read_csv(tmp_out / run_id / "gold.csv", dtype={"participant_id": str},
                      parse_dates=["window_start", "window_end", "as_of"])


@pytest.mark.skipif(not RAW.exists(), reason="run fixtures/make_mock_big_ideas.py --out data/raw first")
def test_shifted_and_unshifted_runs_match_apart_from_timestamps(tmp_path):
    unshifted = run(tmp_path, "shift-test-0", shift_days=0)
    shifted = run(tmp_path, "shift-test-2430", shift_days=2430)
    shutil.rmtree(tmp_path / "shift-test-0", ignore_errors=True)
    shutil.rmtree(tmp_path / "shift-test-2430", ignore_errors=True)

    assert len(unshifted) == len(shifted)
    for c in ("heart_rate_bpm", "physiological_load", "activity_level", "estimated_rest_minutes", "recovery_score"):
        a = pd.to_numeric(unshifted[c], errors="coerce").to_numpy()
        b = pd.to_numeric(shifted[c], errors="coerce").to_numpy()
        import numpy as np
        assert np.allclose(a, b, equal_nan=True), c
    assert (unshifted["activity_confound"].to_numpy() == shifted["activity_confound"].to_numpy()).all()

    reasons_u = unshifted["quality_json"].map(lambda q: json.loads(q)["missing_reasons"])
    reasons_s = shifted["quality_json"].map(lambda q: json.loads(q)["missing_reasons"])
    assert (reasons_u == reasons_s).all()

    # UTC delta is 2430 days MINUS 1 hour (Feb is EST=UTC-5, Oct is EDT=UTC-4): local wall time shifts by
    # exactly 2430 days, but the UTC instant does not, since the offset itself changed.
    deltas = (shifted["window_end"] - unshifted["window_end"]).unique()
    assert len(deltas) == 1 and pd.Timedelta(deltas[0]) == pd.Timedelta(days=2430) - pd.Timedelta(hours=1)

    u_local = unshifted["window_end"].dt.tz_convert("America/New_York")
    s_local = shifted["window_end"].dt.tz_convert("America/New_York")
    assert ((u_local.dt.hour == s_local.dt.hour) & (u_local.dt.minute == s_local.dt.minute)).all()

    offsets = s_local.map(lambda t: t.utcoffset().total_seconds() / 3600)
    assert (offsets == -4.0).all()  # EDT across the whole mapped window, not EST
