"""Gold: interpreted WearableState rows from Silver + causal z-scores. Heuristics, not diagnoses.
Rest = longest sustained low-movement stretch (HR not elevated vs own baseline) in the last COMPLETED local
overnight window. Not sleep staging. Trigger rules live in the backend, not here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from contracts.models import Quality, WearableState


@dataclass(frozen=True)
class GoldConfig:
    tz: str = "America/New_York"
    min_signal_coverage: float = 0.5        # per-minute coverage needed to use HR/EDA for load
    sufficient_coverage: float = 0.8
    z_full_scale: float = 3.0               # component(z) = clamp(z/3, 0, 1)
    w_hr: float = 0.5                       # MVP: HR+EDA only; 0.4/0.4/0.2 when RMSSD is added
    w_eda: float = 0.5
    activity_full_g: float = 0.25           # dyn magnitude (g) mapped to activity_level 1.0
    activity_confound_level: float = 0.35
    night_start_hour: int = 22
    night_end_hour: int = 8
    still_ratio: float = 0.9
    hr_compat_z: float = 0.5
    bridge_minutes: int = 5                 # tolerate short interruptions inside a rest stretch
    min_rest_run_minutes: int = 30
    min_overnight_coverage: float = 0.7
    target_rest_minutes: int = 480
    acc_unavailable_reason: str = "acc_unavailable"   # override to "acc_units_unverified" when ACC was excluded by quality policy


def _clamp01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _nn(x):
    if x is None:
        return None
    try:
        return None if (isinstance(x, float) and np.isnan(x)) or pd.isna(x) else x
    except (TypeError, ValueError):
        return x


def estimate_rest_nights(s: pd.DataFrame, cfg: GoldConfig) -> list[dict]:
    """One estimate per local overnight window [start_hour d, end_hour d+1). Pure function of that night's data."""
    if s.empty:
        return []
    t0, t1 = s["window_start"].min(), s["window_end"].max()
    tz = cfg.tz
    d0 = t0.tz_convert(tz).date() - timedelta(days=1)
    d1 = t1.tz_convert(tz).date()
    out, idx = [], s.set_index("window_start")
    d = d0
    while d <= d1:
        st = pd.Timestamp(datetime(d.year, d.month, d.day, cfg.night_start_hour)).tz_localize(tz).tz_convert("UTC")
        nd = d + timedelta(days=1)
        en = pd.Timestamp(datetime(nd.year, nd.month, nd.day, cfg.night_end_hour)).tz_localize(tz).tz_convert("UTC")
        d += timedelta(days=1)
        if en > t1 or st < t0 - pd.Timedelta(minutes=1):
            if en > t1:
                continue
        grid = pd.date_range(st, en - pd.Timedelta(minutes=1), freq="min", tz="UTC")
        n = idx.reindex(grid)
        obs = (n["acc_coverage"].fillna(0) >= cfg.min_signal_coverage).to_numpy()
        still = (n["stillness_ratio"].fillna(0) >= cfg.still_ratio).to_numpy() & obs
        z = n["hr_baseline_z"].to_numpy(dtype=float)
        hr_ok = np.isnan(z) | (z <= cfg.hr_compat_z)
        cand = still & hr_ok
        checked = float(np.mean(~np.isnan(z[cand]))) if cand.any() else 0.0
        coverage = float(obs.mean())
        best = (0, None, None)
        i, L = 0, len(grid)
        while i < L:
            if not cand[i]:
                i += 1; continue
            j, last, gap = i, i, 0
            while j < L:
                if cand[j]:
                    last, gap = j, 0
                elif not obs[j]:
                    break                     # sensor gap breaks the run
                else:
                    gap += 1
                    if gap > cfg.bridge_minutes:
                        break
                j += 1
            minutes = int(cand[i:last + 1].sum())
            if minutes > best[0]:
                best = (minutes, grid[i], grid[last] + pd.Timedelta(minutes=1))
            i = max(last + 1, i + 1)
        out.append({"night_id": f"rest-{(nd - timedelta(days=1)).strftime('%Y%m%d')}", "night_end": en, "coverage": coverage,
                    "minutes": best[0] if best[0] >= cfg.min_rest_run_minutes else 0,
                    "run_start": best[1], "run_end": best[2], "hr_compat_checked_fraction": checked})
    return out


def build_gold(silver_z: pd.DataFrame, *, run_id: str, participant_id: str, source_kind: str,
               cfg: GoldConfig = GoldConfig()) -> pd.DataFrame:
    s = silver_z.reset_index(drop=True)
    nights = estimate_rest_nights(s, cfg)
    rows = []
    load_hist: list[tuple[str, float]] = []
    for r in s.itertuples(index=False):
        t_end = r.window_end
        reasons: dict[str, str] = {}
        hr_cov, eda_cov, acc_cov = float(r.hr_coverage), float(r.eda_coverage), float(r.acc_coverage)
        hr = _nn(r.hr_mean_bpm)
        if hr is None:
            reasons["heart_rate_bpm"] = "no_valid_hr_in_window"
        # load
        load = None
        if hr_cov < cfg.min_signal_coverage or hr is None:
            reasons["physiological_load"] = "hr_coverage_below_threshold"
        elif eda_cov < cfg.min_signal_coverage or _nn(r.eda_mean) is None:
            reasons["physiological_load"] = "eda_coverage_below_threshold"
        elif _nn(r.hr_baseline_z) is None:
            reasons["physiological_load"] = r.hr_z_reason or "hr_baseline_unavailable"
        elif _nn(r.eda_baseline_z) is None:
            reasons["physiological_load"] = r.eda_z_reason or "eda_baseline_unavailable"
        else:
            comp = lambda z: _clamp01(z / cfg.z_full_scale)
            load = round((cfg.w_hr * comp(r.hr_baseline_z) + cfg.w_eda * comp(r.eda_baseline_z)) / (cfg.w_hr + cfg.w_eda), 4)
        # activity
        act = None
        if acc_cov < cfg.min_signal_coverage or _nn(r.acc_dyn_mean_g) is None:
            reasons["activity_level"] = cfg.acc_unavailable_reason
        else:
            act = round(_clamp01(r.acc_dyn_mean_g / cfg.activity_full_g), 4)
        confound = bool(act is not None and act >= cfg.activity_confound_level)
        # rest: last completed night
        done = [n for n in nights if n["night_end"] <= t_end]
        est = rec = None
        evid = [f"window-{r.window_start:%Y%m%dT%H%MZ}"]
        ov_cov = None
        if not done:
            reasons["estimated_rest_minutes"] = "no_completed_night"
            reasons["recovery_score"] = "estimated_rest_unavailable"
        else:
            n = done[-1]
            ov_cov = round(n["coverage"], 4)
            if n["coverage"] < cfg.min_overnight_coverage:
                reasons["estimated_rest_minutes"] = "overnight_coverage_below_minimum"
                reasons["recovery_score"] = "estimated_rest_unavailable"
            else:
                est = int(n["minutes"])
                rec = round(_clamp01(est / cfg.target_rest_minutes), 4)
                evid.append(n["night_id"])
                if n["hr_compat_checked_fraction"] < 1.0:
                    reasons["rest_hr_check"] = "hr_baseline_unavailable_for_part_of_night"
        if load is not None:
            load_hist.append((f"window-{r.window_start:%Y%m%dT%H%MZ}", load))
            load_hist = load_hist[-20:]
            top = max(load_hist, key=lambda p: (p[1], p[0]))[0]
            if top not in evid:
                evid.append(top)
        status = "sufficient"
        if load is None and hr is None:
            status = "unavailable"
        elif load is None or est is None or min(hr_cov, eda_cov, acc_cov) < cfg.sufficient_coverage:
            status = "limited"
        q = {"status": status, "hr_coverage": round(hr_cov, 4), "eda_coverage": round(eda_cov, 4),
             "acc_coverage": round(acc_cov, 4), "overnight_coverage": ov_cov, "missing_reasons": reasons}
        rows.append({
            "run_id": run_id, "participant_id": participant_id, "as_of": t_end, "window_start": r.window_start, "window_end": t_end,
            "heart_rate_bpm": None if hr is None else round(float(hr), 2), "physiological_load": load, "activity_level": act,
            "estimated_rest_minutes": est, "target_rest_minutes": cfg.target_rest_minutes, "recovery_score": rec,
            "quality_json": json.dumps(q, sort_keys=True), "baseline_id": r.baseline_id,
            "baseline_cutoff": r.baseline_cutoff, "evidence_ids": evid, "activity_confound": confound, "source_kind": source_kind})
    return pd.DataFrame(rows)


def row_to_wearable_state(row: dict) -> WearableState:
    """Gold row (dict) -> contract WearableState. Used by tests and by the backend reader."""
    q = row["quality_json"]
    q = Quality.model_validate(json.loads(q) if isinstance(q, str) else q)
    g = lambda k: _nn(row.get(k))
    return WearableState(
        window_start=row["window_start"], window_end=row["window_end"], heart_rate_bpm=g("heart_rate_bpm"),
        physiological_load=g("physiological_load"), activity_level=g("activity_level"),
        estimated_rest_minutes=None if g("estimated_rest_minutes") is None else int(row["estimated_rest_minutes"]),
        target_rest_minutes=int(row["target_rest_minutes"]), recovery_score=g("recovery_score"), quality=q,
        baseline_id=g("baseline_id"), baseline_cutoff=g("baseline_cutoff"), evidence_ids=list(row.get("evidence_ids") or []))
