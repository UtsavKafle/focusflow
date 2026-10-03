"""Silver: one row per half-open minute [window_start, window_end). Pure pandas, no Spark, causal.
Input frames: columns `event_time` (tz-aware UTC) and `value` (hr, eda) or `x,y,z` (acc).
Missing is NaN/None, never zero. Coverage = samples present / samples expected.
ACC scale: Empatica E4 documents 1/64 g per raw unit. UNVERIFIED for this release until Data A confirms
(see docs/data-provenance.md). Override via acc_unit_scale_g."""
from __future__ import annotations

import numpy as np
import pandas as pd

EXPECTED_HZ = {"hr": 1.0, "eda": 4.0, "acc": 32.0}
# Plausible physical ranges. Values outside are treated as missing (never as zero). Starter values; Data A may tighten.
PLAUSIBLE = {"hr": (30.0, 220.0), "eda": (0.0, 100.0)}


def _clean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame({"event_time": pd.to_datetime([], utc=True), **{c: [] for c in cols}})
    out = df[["event_time", *cols]].copy()
    out["event_time"] = pd.to_datetime(out["event_time"], utc=True)
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    return out.sort_values("event_time", kind="stable").reset_index(drop=True)


def _agg_scalar(df: pd.DataFrame, expected_per_min: float, prefix: str, stats: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[f"{prefix}_{k}" for k in stats] + [f"{prefix}_coverage"])
    g = df.groupby(df["event_time"].dt.floor("min"))["value"]
    a = g.agg(["mean", "min", "max", "std", "count"])
    out = pd.DataFrame(index=a.index)
    for name, col in stats.items():
        out[f"{prefix}_{name}"] = a[col]
    out[f"{prefix}_coverage"] = (a["count"] / expected_per_min).clip(upper=1.0)
    return out


def _acc_features(acc: pd.DataFrame, expected_per_min: float, unit_scale_g: float, still_thresh_g: float) -> pd.DataFrame:
    cols = ["acc_dyn_mean_g", "acc_dyn_std_g", "acc_dyn_max_g", "stillness_ratio", "acc_coverage"]
    if acc.empty:
        return pd.DataFrame(columns=cols)
    mag = np.sqrt(acc["x"] ** 2 + acc["y"] ** 2 + acc["z"] ** 2)
    s = pd.Series(mag.values, index=pd.DatetimeIndex(acc["event_time"]))
    # causal static-offset removal: subtract a trailing 10 s mean (gravity/orientation), then take |deviation|
    dyn = (s - s.rolling("10s").mean()).abs() * unit_scale_g
    d = pd.DataFrame({"dyn": dyn.values, "still": (dyn.values < still_thresh_g).astype(float)}, index=s.index)
    g = d.groupby(d.index.floor("min"))
    out = pd.DataFrame({
        "acc_dyn_mean_g": g["dyn"].mean(), "acc_dyn_std_g": g["dyn"].std(), "acc_dyn_max_g": g["dyn"].max(),
        "stillness_ratio": g["still"].mean(), "acc_coverage": (g["dyn"].count() / expected_per_min).clip(upper=1.0)})
    return out


def minute_features(hr: pd.DataFrame, eda: pd.DataFrame, acc: pd.DataFrame, *, expected_hz: dict | None = None,
                    acc_unit_scale_g: float = 1 / 64, still_thresh_g: float = 0.05,
                    start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    hz = {**EXPECTED_HZ, **(expected_hz or {})}
    hr, eda = _clean(hr, ["value"]), _clean(eda, ["value"])
    hr = hr[hr["value"].between(*PLAUSIBLE["hr"])]
    eda = eda[eda["value"].between(*PLAUSIBLE["eda"])]
    acc = _clean(acc, ["x", "y", "z"])
    parts = [
        _agg_scalar(hr, hz["hr"] * 60, "hr", {"mean_bpm": "mean", "min_bpm": "min", "max_bpm": "max", "std_bpm": "std"}),
        _agg_scalar(eda, hz["eda"] * 60, "eda", {"mean": "mean", "std": "std"}),
        _acc_features(acc, hz["acc"] * 60, acc_unit_scale_g, still_thresh_g),
    ]
    idxs = [p.index for p in parts if len(p)]
    if not idxs and start is None:
        return pd.DataFrame()
    lo = start if start is not None else min(i.min() for i in idxs)
    hi = end if end is not None else max(i.max() for i in idxs)
    full = pd.date_range(pd.Timestamp(lo).floor("min"), pd.Timestamp(hi).floor("min"), freq="min", tz="UTC")
    sil = pd.concat([p.reindex(full) for p in parts], axis=1)
    for c in ("hr_coverage", "eda_coverage", "acc_coverage"):
        sil[c] = sil[c].fillna(0.0)          # coverage 0 is a real fact (no samples); values stay NaN
    sil["eda_delta"] = sil["eda_mean"].diff()  # NaN when previous minute missing
    sil.index.name = "window_start"
    sil = sil.reset_index()
    sil.insert(1, "window_end", sil["window_start"] + pd.Timedelta(minutes=1))
    return sil
