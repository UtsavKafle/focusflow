"""Export a derived Gold run to CSV + Parquet for the saved-results fallback ("feature replay" mode,
docs/handoffs/00-common.md's honest-labeling section). No Spark, no Databricks -- reads the Gold CSV
run_local.py already writes (data/derived/<run_id>/gold.csv by default) and re-saves it under a
feature-replay-labeled output directory.

Refuses to export anything whose source_kind isn't entirely synthetic_fixture: this script is for the
mock/demo saved-results fallback only. Exporting a recorded_replay run as a "fixture" fallback would
violate the "never show a fixture as a live run" rule in reverse (silently relabeling real data as
synthetic); that needs an explicit, separate decision, not this script's default path.

  python -m databricks.features.export_gold_fixture --run-id local-1
"""
from __future__ import annotations

import argparse
import pathlib

import pandas as pd


def export(gold_csv: pathlib.Path, out_dir: pathlib.Path, run_id: str) -> pathlib.Path:
    gold = pd.read_csv(gold_csv)
    if gold.empty:
        raise ValueError(f"{gold_csv} has no rows -- nothing to export")
    bad = sorted(set(gold["source_kind"].dropna()) - {"synthetic_fixture"})
    if bad:
        raise ValueError(
            f"refusing to export: source_kind values {bad} found alongside synthetic_fixture in "
            f"{gold_csv} -- this script only exports all-synthetic_fixture runs for the saved-results "
            "fallback; a mixed or recorded_replay run needs an explicit, reviewed export decision"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    gold.to_csv(out_dir / "gold.csv", index=False)
    try:
        gold.to_parquet(out_dir / "gold.parquet", index=False)
        parquet_note = "gold.parquet"
    except ImportError:
        # requirements.txt doesn't pin a parquet engine (pyarrow/fastparquet) -- CSV alone is still a
        # complete saved-results fallback; Parquet is a nice-to-have, not pinned as a new dependency here.
        parquet_note = "SKIPPED (no pyarrow/fastparquet installed)"
    print(f"exported {len(gold)} rows (run_id={run_id}, source_kind=synthetic_fixture) -> "
          f"{out_dir}/gold.csv, {parquet_note}")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--derived", default="data/derived", help="directory run_local.py wrote <run-id>/gold.csv into")
    ap.add_argument("--out", default="data/derived", help="base directory for the feature-replay export")
    a = ap.parse_args()
    gold_csv = pathlib.Path(a.derived) / a.run_id / "gold.csv"
    out_dir = pathlib.Path(a.out) / a.run_id / "feature_replay"
    export(gold_csv, out_dir, a.run_id)


if __name__ == "__main__":
    main()
