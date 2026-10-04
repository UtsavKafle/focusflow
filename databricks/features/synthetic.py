"""SYNTHETIC raw-signal generator for tests and local tuning. Deterministic. NOT wearable data; never present as real."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_signals(start="2026-10-10T12:00:00Z", days=3.0, seed=7, hz=None, episode_minutes=0, night_gap=None,
                 bursts=True):
    """Awake HR~75, night (22:30-06:30 ET) HR~58 and still, optional high-load sitting episode at the end.
    night_gap=(start_min, end_min) minutes from `start` to drop all signals."""
    hz = {"hr": 1, "eda": 1, "acc": 2, **(hz or {})}
    rs = np.random.RandomState(seed)
    t0 = pd.Timestamp(start)
    total = int(days * 86400)

    def frame(rate):
        n = int(total * rate)
        ts = t0 + pd.to_timedelta(np.arange(n) / rate, unit="s")
        return ts, n

    def phase(ts):
        loc = ts.tz_convert("America/New_York")
        h = loc.hour + loc.minute / 60
        night = (h >= 22.5) | (h < 6.5)
        return night

    end = t0 + pd.Timedelta(seconds=total)
    ep_start = end - pd.Timedelta(minutes=episode_minutes)

    ts, n = frame(hz["hr"])
    night = np.asarray(phase(ts))
    ep = np.asarray(ts >= ep_start) if episode_minutes else np.zeros(n, bool)
    hr = np.where(night, 58, 75) + rs.normal(0, 2.0, n) + np.where(ep, 22, 0)
    hr_df = pd.DataFrame({"event_time": ts, "value": hr})

    ts, n = frame(hz["eda"])
    night = np.asarray(phase(ts))
    ep = np.asarray(ts >= ep_start) if episode_minutes else np.zeros(n, bool)
    eda = np.where(night, 0.3, 0.6) + np.abs(rs.normal(0, 0.05, n)) + np.where(ep, 1.2, 0)
    eda_df = pd.DataFrame({"event_time": ts, "value": eda})

    ts, n = frame(hz["acc"])
    night = np.asarray(phase(ts))
    ep = np.asarray(ts >= ep_start) if episode_minutes else np.zeros(n, bool)
    sec_of_min = np.asarray((ts.minute * 60 + ts.second) // 30 % 4 == 0)
    sd = np.where(night | ep, 0.3, 2.0)
    if bursts:
        sd = np.where(~night & ~ep & sec_of_min, 14.0, sd)   # daytime movement bursts
    acc_df = pd.DataFrame({"event_time": ts, "x": rs.normal(0, 1, n) * sd, "y": rs.normal(0, 1, n) * sd, "z": 64 + rs.normal(0, 1, n) * sd})

    if night_gap:
        a, b = t0 + pd.Timedelta(minutes=night_gap[0]), t0 + pd.Timedelta(minutes=night_gap[1])
        drop = lambda d: d[~((d["event_time"] >= a) & (d["event_time"] < b))].reset_index(drop=True)
        hr_df, eda_df, acc_df = drop(hr_df), drop(eda_df), drop(acc_df)
    return hr_df, eda_df, acc_df, hz
