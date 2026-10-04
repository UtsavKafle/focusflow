"""Causal robust baselines. z = (value - median) / max(1.4826 * MAD, epsilon).
For each minute the baseline uses ONLY windows with window_start < the baseline refresh time, which is <= the
current window_start (refresh every `refresh_minutes`). No future data. During warm-up (fewer than
`warmup_minutes` valid prior minutes) z is NULL with reason `baseline_warmup`."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826


@dataclass(frozen=True)
class BaselineConfig:
    warmup_minutes: int = 24 * 60          # first 24 usable recorded hours
    refresh_minutes: int = 10
    max_history_minutes: int = 4 * 24 * 60
    hr_epsilon: float = 1.0                # bpm
    eda_epsilon: float = 0.02              # on log1p(EDA) scale
    eda_log: bool = True
    transform_id: str = "median-mad-1.4826"

    def baseline_id(self) -> str:
        return f"baseline-{self.transform_id}-w{self.warmup_minutes}-r{self.refresh_minutes}"


def robust_z(values: np.ndarray, current: float, epsilon: float) -> tuple[float, float, float]:
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    scale = max(MAD_SCALE * mad, epsilon)
    return (current - med) / scale, med, scale


def causal_z(series: pd.Series, cfg: BaselineConfig, epsilon: float) -> pd.DataFrame:
    """series indexed 0..n-1 by minute order (complete minute grid); NaN = missing.
    Returns columns z, reason, n_valid, cutoff_idx (index of refresh used)."""
    v = series.to_numpy(dtype=float)
    n = len(v)
    z = np.full(n, np.nan)
    reason = np.array([None] * n, dtype=object)
    nvalid = np.zeros(n, dtype=int)
    cutoff = np.full(n, -1)
    valid_prefix = np.cumsum(~np.isnan(v))          # valid_prefix[i] = valid count in [0..i]
    base_med = base_scale = np.nan
    base_idx = -1
    for i in range(n):
        if i % cfg.refresh_minutes == 0:           # refresh uses windows strictly before i
            lo = max(0, i - cfg.max_history_minutes)
            hist = v[lo:i]
            hist = hist[~np.isnan(hist)]
            cnt = int(valid_prefix[i - 1]) if i > 0 else 0
            if cnt >= cfg.warmup_minutes and len(hist) > 0:
                med = float(np.median(hist)); mad = float(np.median(np.abs(hist - med)))
                base_med, base_scale = med, max(MAD_SCALE * mad, epsilon)
            else:
                base_med = base_scale = np.nan
            base_idx = i
        cutoff[i] = base_idx
        nvalid[i] = int(valid_prefix[base_idx - 1]) if base_idx > 0 else 0
        if np.isnan(v[i]):
            reason[i] = "no_value"
        elif np.isnan(base_med):
            reason[i] = "baseline_warmup"
        else:
            z[i] = (v[i] - base_med) / base_scale
    return pd.DataFrame({"z": z, "reason": reason, "n_valid": nvalid, "cutoff_idx": cutoff}, index=series.index)


def add_baselines(silver: pd.DataFrame, cfg: BaselineConfig = BaselineConfig()) -> pd.DataFrame:
    s = silver.reset_index(drop=True).copy()
    hr = causal_z(s["hr_mean_bpm"], cfg, cfg.hr_epsilon)
    eda_v = np.log1p(s["eda_mean"]) if cfg.eda_log else s["eda_mean"]
    eda = causal_z(eda_v, cfg, cfg.eda_epsilon)
    s["hr_baseline_z"], s["hr_z_reason"] = hr["z"], hr["reason"]
    s["eda_baseline_z"], s["eda_z_reason"] = eda["z"], eda["reason"]
    s["baseline_id"] = cfg.baseline_id()
    s["baseline_n_valid"] = hr["n_valid"]
    s["baseline_cutoff"] = s["window_start"].to_numpy()[hr["cutoff_idx"].to_numpy()]
    s["baseline_cutoff"] = pd.to_datetime(s["baseline_cutoff"], utc=True)
    return s
