"""Local runner: raw BIG IDEAs-style CSVs -> Bronze-shaped rows -> quality policy -> Silver + Gold + a tuning
summary. No Spark, no Databricks.
  python -m databricks.features.run_local --participant 001 --raw data/raw --tz-assume America/New_York \
      --acc-hz 8 --shift-days 2430 --source-kind synthetic_fixture --run-id local-1
Timestamp handling is an ASSUMPTION until Data A documents it (docs/data-provenance.md): naive timestamps are
interpreted in --tz-assume and printed loudly. --shift-days adds whole days to LOCAL wall time before
localizing (never a fixed UTC offset -- Feb is EST, Oct is EDT), to map a recording onto the scenario replay
clock. --history-start/--segment-end bound the run (local wall time, before the shift) to limit memory,
since ACC can be dense."""
from __future__ import annotations

import argparse, pathlib, sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from databricks.features.baselines import BaselineConfig, add_baselines
from databricks.features.bronze_adapter import bronze_rows_for_participant, bronze_to_minute_frames
from databricks.features.minute_features import minute_features
from databricks.features.quality_policy import ACC_UNVERIFIED_UNITS_REASON, QualityPolicy, acc_is_usable
from databricks.features.state import GoldConfig, build_gold


def local_bound_to_utc(ts: str, tz_assume: str, shift_days: int) -> pd.Timestamp:
    t = pd.Timestamp(ts) + pd.Timedelta(days=shift_days)
    return t.tz_localize(tz_assume).tz_convert("UTC")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participant", required=True); ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--tz-assume", default="America/New_York")
    ap.add_argument("--shift-days", type=int, default=0,
                    help="days added to LOCAL wall time before localizing (e.g. 2430 for the exam-week scenario mapping)")
    ap.add_argument("--source-kind", default="recorded_replay", choices=["recorded_replay", "synthetic_fixture", "synthetic_injection"])
    ap.add_argument("--history-start", default="2020-02-13 12:00:00", help="local wall time, before --shift-days")
    ap.add_argument("--segment-end", default="2020-02-17 00:00:00", help="local wall time, before --shift-days")
    ap.add_argument("--run-id", default="local-run"); ap.add_argument("--out", default="data/derived")
    ap.add_argument("--warmup-minutes", type=int, default=24 * 60)
    ap.add_argument("--acc-unit-scale-g", type=float, default=1 / 64)
    ap.add_argument("--hr-hz", type=float, default=1); ap.add_argument("--eda-hz", type=float, default=4)
    ap.add_argument("--acc-hz", type=float, default=32)
    a = ap.parse_args()
    print(f"!! ASSUMPTION: naive timestamps interpreted as {a.tz_assume}. Confirm with docs/data-provenance.md")

    st = local_bound_to_utc(a.history_start, a.tz_assume, a.shift_days)
    en = local_bound_to_utc(a.segment_end, a.tz_assume, a.shift_days)
    print(f"mapping: shift_days={a.shift_days} source_kind={a.source_kind} window=[{st}, {en})")

    policy = QualityPolicy.for_source_kind(a.source_kind)
    bronze = bronze_rows_for_participant(a.raw, a.participant, tz_assume=a.tz_assume, run_id=a.run_id,
                                         source_kind=a.source_kind, shift_days=a.shift_days)
    bronze = bronze[(bronze["event_time"] >= st) & (bronze["event_time"] < en)]
    frames = bronze_to_minute_frames(bronze, policy)
    if not acc_is_usable(policy):
        print("!! ACC excluded: unit scale unverified for this source_kind (quality_policy.exclude_until_verified)")

    sil = minute_features(frames["hr"], frames["eda"], frames["acc"],
                          expected_hz={"hr": a.hr_hz, "eda": a.eda_hz, "acc": a.acc_hz}, acc_unit_scale_g=a.acc_unit_scale_g)
    z = add_baselines(sil, BaselineConfig(warmup_minutes=a.warmup_minutes))
    gold_cfg = GoldConfig(acc_unavailable_reason="acc_unavailable" if acc_is_usable(policy) else ACC_UNVERIFIED_UNITS_REASON)
    g = build_gold(z, run_id=a.run_id, participant_id=a.participant, source_kind=a.source_kind, cfg=gold_cfg)

    out = pathlib.Path(a.out) / a.run_id; out.mkdir(parents=True, exist_ok=True)
    z.to_csv(out / "silver.csv", index=False); g.to_csv(out / "gold.csv", index=False)
    print(f"rows: silver={len(z)} gold={len(g)} -> {out}")
    print("coverage mean:", z[["hr_coverage", "eda_coverage", "acc_coverage"]].mean().round(3).to_dict())
    L = g["physiological_load"].dropna()
    print("load quantiles:", L.quantile([.1, .5, .9, .99]).round(3).to_dict(), "share>=0.70:", round(float((L >= .7).mean()), 4))
    print("rest by night:\n", g.dropna(subset=["estimated_rest_minutes"]).groupby(g["evidence_ids"].map(lambda e: [x for x in e if x.startswith("rest-")][:1][0] if any(x.startswith("rest-") for x in e) else None))["estimated_rest_minutes"].first())


if __name__ == "__main__":
    main()
