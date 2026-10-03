"""Local runner: raw BIG IDEAs-style CSVs -> Silver + Gold + a tuning summary. No Spark, no Databricks.
  python -m databricks.features.run_local --participant 004 --raw data/raw --tz-assume UTC --start 2026-.. --end 2026-.. --run-id local-1
Timestamp handling is an ASSUMPTION until Data A documents it (docs/data-provenance.md): naive timestamps are
interpreted in --tz-assume and printed loudly. Use --start/--end to bound memory (ACC is 32 Hz)."""
from __future__ import annotations

import argparse, pathlib, sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from databricks.features.baselines import BaselineConfig, add_baselines
from databricks.features.minute_features import minute_features
from databricks.features.state import GoldConfig, build_gold


def load(path: pathlib.Path, cols: dict[str, str], tz: str, start, end) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    ts = ts.dt.tz_localize(tz) if ts.dt.tz is None else ts
    df = df.assign(event_time=ts.dt.tz_convert("UTC")).dropna(subset=["event_time"])
    if start is not None: df = df[df["event_time"] >= start]
    if end is not None: df = df[df["event_time"] < end]
    return df[["event_time", *cols.values()]].rename(columns={v: k for k, v in cols.items()}) if False else df[["event_time", *cols.values()]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participant", required=True); ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--tz-assume", default="UTC"); ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--run-id", default="local-run"); ap.add_argument("--out", default="data/derived")
    ap.add_argument("--warmup-minutes", type=int, default=24 * 60)
    ap.add_argument("--acc-unit-scale-g", type=float, default=1 / 64)
    ap.add_argument("--hr-hz", type=float, default=1); ap.add_argument("--eda-hz", type=float, default=4)
    ap.add_argument("--acc-hz", type=float, default=32)
    a = ap.parse_args()
    print(f"!! ASSUMPTION: naive timestamps interpreted as {a.tz_assume}. Confirm with docs/data-provenance.md")
    d = pathlib.Path(a.raw) / a.participant
    st = pd.Timestamp(a.start, tz="UTC") if a.start else None
    en = pd.Timestamp(a.end, tz="UTC") if a.end else None
    def find(sig):  # real files are named like HR_001.csv; also accept HR.csv
        c = sorted(d.glob(f"{sig}_*.csv")) + sorted(d.glob(f"{sig}.csv"))
        if not c: raise SystemExit(f"missing {sig} file in {d}")
        return c[0]
    hr = load(find("HR"), {"value": "value"}, a.tz_assume, st, en)
    eda = load(find("EDA"), {"value": "value"}, a.tz_assume, st, en)
    acc = load(find("ACC"), {"x": "x", "y": "y", "z": "z"}, a.tz_assume, st, en)
    sil = minute_features(hr, eda, acc, expected_hz={'hr': a.hr_hz, 'eda': a.eda_hz, 'acc': a.acc_hz}, acc_unit_scale_g=a.acc_unit_scale_g)
    z = add_baselines(sil, BaselineConfig(warmup_minutes=a.warmup_minutes))
    g = build_gold(z, run_id=a.run_id, participant_id=a.participant, source_kind="recorded_replay")
    out = pathlib.Path(a.out) / a.run_id; out.mkdir(parents=True, exist_ok=True)
    z.to_csv(out / "silver.csv", index=False); g.to_csv(out / "gold.csv", index=False)
    print(f"rows: silver={len(z)} gold={len(g)} -> {out}")
    print("coverage mean:", z[["hr_coverage", "eda_coverage", "acc_coverage"]].mean().round(3).to_dict())
    L = g["physiological_load"].dropna()
    print("load quantiles:", L.quantile([.1, .5, .9, .99]).round(3).to_dict(), "share>=0.70:", round(float((L >= .7).mean()), 4))
    print("rest by night:\n", g.dropna(subset=["estimated_rest_minutes"]).groupby(g["evidence_ids"].map(lambda e: [x for x in e if x.startswith("rest-")][:1][0] if any(x.startswith("rest-") for x in e) else None))["estimated_rest_minutes"].first())


if __name__ == "__main__":
    main()
