import json, pathlib
import pandas as pd
import pytest
from contracts.models import StudentState  # noqa: F401  (import check)
from databricks.features.state import row_to_wearable_state

G = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "mock_big_ideas" / "gold.csv"


@pytest.fixture(scope="module")
def gold():
    g = pd.read_csv(G, dtype={"participant_id": str}, parse_dates=["window_start", "window_end", "as_of", "baseline_cutoff"])
    g["loc"] = g["window_end"].dt.tz_convert("America/New_York")
    return g


def at(g, s):
    return g[g["loc"] == pd.Timestamp(s, tz="America/New_York")].iloc[0]


def test_rows_validate(gold):
    for row in gold.iloc[::53].to_dict("records"):
        row["evidence_ids"] = eval(row["evidence_ids"]) if isinstance(row["evidence_ids"], str) else row["evidence_ids"]
        row_to_wearable_state(row)


def test_story(gold):
    assert pd.isna(at(gold, "2020-02-13 20:00")["physiological_load"])          # warm-up
    ex = at(gold, "2020-02-14 17:20")
    assert ex["activity_confound"] and ex["physiological_load"] == 1.0           # exercise
    end = at(gold, "2020-02-16 23:20")
    assert end["estimated_rest_minutes"] == 130 and end["recovery_score"] < 0.5
    assert not end["activity_confound"]
    last20 = gold.iloc[-20:]["physiological_load"]
    assert (last20 >= 0.7).sum() >= 15
    gap = gold[(gold["loc"] > "2020-02-14 15:10") & (gold["loc"] <= "2020-02-14 15:55")]
    assert gap["physiological_load"].isna().all()
    st = gold["quality_json"].map(lambda q: json.loads(q)["status"]).value_counts().to_dict()
    assert st == {"sufficient": 3525, "limited": 1450, "unavailable": 65}
