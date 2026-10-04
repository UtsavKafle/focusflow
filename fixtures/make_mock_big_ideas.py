"""Generate a SYNTHETIC BIG IDEAs-shaped dataset so nobody waits on the real download.
NOT real wearable data. Mirrors the file layout/names of PhysioNet BIG IDEAs v1.1.3 (folder 001, files like HR_001.csv).
Deterministic (seed). numpy + pandas only.

  python fixtures/make_mock_big_ideas.py --out data/mock [--acc-hz 8] [--eda-hz 4] [--temp-hz 4]

Naive timestamps are LOCAL America/New_York wall time (use --tz-assume America/New_York in run_local).
Story (local time): 2020-02-13 12:00 -> 2020-02-17 00:00 (3.5 days).
  nights 13->14 and 14->15: normal (~7-8 h still). Night 15->16: restless, short (two still stretches ~2 h each).
  2020-02-14 17:00-17:40 exercise (movement confound). 2020-02-16 20:30-23:30 sustained cramming: HR/EDA ramp up, body still.
Planted data problems (for adapters/quality flags): 45-min all-signal gap (02-14 15:10), HR-only dropout (02-15 09:00),
  ACC-only gap (02-15 14:00, 10 min), duplicate HR rows, empty Value rows, implausible HR/EDA values.
"""
from __future__ import annotations

import argparse, pathlib
import numpy as np
import pandas as pd

START = pd.Timestamp("2020-02-13 12:00:00")
END = pd.Timestamp("2020-02-17 00:00:00")


def sec(ts) -> int:
    return int((pd.Timestamp(ts) - START).total_seconds())


def build_schedule():
    """list of (start, end, hr, eda, temp, acc_sd, orient) in local wall time."""
    S = []
    add = lambda a, b, hr, eda, temp, sd, o=(-10, 6, 56): S.append((a, b, hr, eda, temp, sd, o))
    days = pd.date_range("2020-02-13", "2020-02-16", freq="D")
    for d in days:
        ds = d.strftime("%Y-%m-%d")
        t = lambda hhmm: pd.Timestamp(f"{ds} {hhmm}")
        nxt = lambda hhmm: pd.Timestamp((d + pd.Timedelta(days=1)).strftime("%Y-%m-%d") + f" {hhmm}")
        if d.day != 13:   # morning of this date (day 13 starts at 12:00)
            add(t("07:00"), t("08:00"), 70, .40, 33.0, 4)
            add(t("08:00"), t("12:00"), 74, .50, 33.2, 4)
        add(t("12:00"), t("13:00"), 88, .60, 33.0, 12, (-5, 10, 58))
        add(t("13:00"), t("17:00"), 73 if d.day != 16 else 77, .50 if d.day != 16 else .65, 33.2, 4)
        if d.day == 14:
            add(t("17:00"), t("17:40"), 150, 1.2, 33.8, 26, (-20, 5, 52))
            add(t("17:40"), t("18:00"), 95, .8, 33.5, 8)
        else:
            add(t("17:00"), t("18:00"), 85, .60, 33.0, 10, (-5, 10, 58))
        if d.day == 16:
            add(t("18:00"), t("20:30"), 78, .70, 33.1, 4)
            add(t("20:30"), nxt("00:00"), 98, 2.2, 33.0, 2.0)       # cramming, hunched and still (ramped below)
            continue
        add(t("18:00"), t("22:00"), 70, .40, 33.2, 3.5)
        if d.day == 15:  # restless night 15 -> 16
            add(t("22:00"), nxt("01:30"), 74, .55, 33.2, 4.0)          # studying in bed, small movements
            add(nxt("01:30"), nxt("03:30"), 58, .28, 34.0, 0.4, (-2, 1, 63))
            add(nxt("03:30"), nxt("04:10"), 70, .45, 33.6, 6.0)        # awake
            add(nxt("04:10"), nxt("06:20"), 59, .28, 34.0, 0.4, (-2, 1, 63))
            add(nxt("06:20"), nxt("07:00"), 72, .45, 33.3, 5.0)
        else:            # normal nights 13->14, 14->15
            add(t("22:00"), t("23:00"), 66, .35, 33.3, 4.0)
            add(t("23:00"), nxt("07:00"), 56, .25, 34.2, 0.4, (-2, 1, 63))
    return S


def per_second_state(rs):
    n = sec(END)
    hr, eda, temp, sd = (np.full(n, np.nan) for _ in range(4))
    orient = np.zeros((n, 3))
    for a, b, h, e, tmp, s, o in build_schedule():
        i, j = max(0, sec(a)), min(n, sec(b))
        if j <= i:
            continue
        hr[i:j], eda[i:j], temp[i:j], sd[i:j] = h, e, tmp, s
        orient[i:j] = o
    # ramp the cramming window and smooth transitions (causal-ish 120 s boxcar)
    i, j = sec("2020-02-16 20:30"), sec("2020-02-17 00:00")
    ramp = np.clip((np.arange(j - i)) / 3600.0, 0, 1)             # reaches full level after 60 min
    hr[i:j] = 78 + (98 - 78) * ramp
    eda[i:j] = .7 + (2.2 - .7) * ramp
    k = np.ones(120) / 120
    sm = lambda x: np.convolve(np.pad(x, (119, 0), mode="edge"), k, mode="valid")
    hr, eda, temp = sm(hr), sm(eda), sm(temp)
    # brief awakenings in normal nights (3 min bursts) so the bridge logic is exercised
    for day in ("2020-02-14", "2020-02-15"):
        for hh in ("01:40", "04:20"):
            a = sec(f"{day} {hh}")
            sd[a:a + 180], hr[a:a + 180] = 6.0, hr[a:a + 180] + 8
    ar = np.zeros(n)
    eps = rs.normal(0, 1.8 * np.sqrt(1 - .9 ** 2), n)
    for t in range(1, n):
        ar[t] = .9 * ar[t - 1] + eps[t]
    hr = hr + ar
    return hr, eda, temp, sd, orient


def fmt(ts):
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")


def upsample(x, hz):
    return np.repeat(x, hz) if hz >= 1 else x


def drop_ranges(ts: pd.DatetimeIndex, ranges):
    keep = np.ones(len(ts), bool)
    for a, b in ranges:
        keep &= ~((ts >= pd.Timestamp(a)) & (ts < pd.Timestamp(b)))
    return keep


ALL_GAP = [("2020-02-14 15:10", "2020-02-14 15:55")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/mock"); ap.add_argument("--pid", default="001")
    ap.add_argument("--acc-hz", type=int, default=8); ap.add_argument("--eda-hz", type=int, default=4)
    ap.add_argument("--temp-hz", type=int, default=4); ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rs = np.random.RandomState(a.seed)
    out = pathlib.Path(a.out) / a.pid
    out.mkdir(parents=True, exist_ok=True)
    hr, eda, temp, sd, orient = per_second_state(rs)
    n = len(hr)
    t1 = START + pd.to_timedelta(np.arange(n), unit="s")

    # ---- HR 1 Hz
    keep = drop_ranges(t1, ALL_GAP + [("2020-02-15 09:00", "2020-02-15 09:20")])
    df = pd.DataFrame({"Timestamp": fmt(t1[keep]), "Value": np.round(hr[keep], 2)})
    dup = df.iloc[[5000, 90000, 150000, 200000, 250000]]
    df = pd.concat([df, dup]).sort_values("Timestamp", kind="stable")             # duplicate rows
    df.loc[df.index[[1000, 70000, 140000]], "Value"] = np.nan                       # empty Value rows
    df.loc[df.index[[3000]], "Value"] = 0.0                                         # implausible
    df.loc[df.index[[3500]], "Value"] = 255.0                                       # implausible
    df.to_csv(out / f"HR_{a.pid}.csv", index=False)

    # ---- EDA / TEMP
    for name, base, hz, scale in (("EDA", eda, a.eda_hz, 0.04), ("TEMP", temp, a.temp_hz, 0.05)):
        m = n * hz
        ts = START + pd.to_timedelta(np.arange(m) / hz, unit="s")
        x = np.repeat(base, hz)
        slow = np.convolve(rs.normal(0, 1, m), np.ones(40) / 40, mode="same") * (scale * 3)
        if name == "EDA":
            x = np.clip(x * (1 + 0.15 * slow / scale / 3) + np.abs(rs.normal(0, scale / 4, m)), 0.01, None)
        else:
            x = x + slow
        keep = drop_ranges(ts, ALL_GAP)
        d = pd.DataFrame({"Timestamp": fmt(ts[keep]), "Value": np.round(x[keep], 6)})
        if name == "EDA":
            d.loc[d.index[[20000]], "Value"] = -0.5                                    # implausible
        d.to_csv(out / f"{name}_{a.pid}.csv", index=False)

    # ---- ACC (int raw units, 1/64 g; real data is 32 Hz, --acc-hz 32 for full rate)
    hz = a.acc_hz
    m = n * hz
    ts = START + pd.to_timedelta(np.arange(m) / hz, unit="s")
    sdv = np.repeat(sd, hz)[:, None]
    o = np.repeat(orient, hz, axis=0)
    xyz = o + rs.normal(0, 1, (m, 3)) * sdv
    xyz = np.clip(np.rint(xyz), -128, 127).astype(int)
    keep = drop_ranges(ts, ALL_GAP + [("2020-02-15 14:00", "2020-02-15 14:10")])
    pd.DataFrame({"Timestamp": fmt(ts[keep]), "X": xyz[keep, 0], "Y": xyz[keep, 1], "Z": xyz[keep, 2]}).to_csv(out / f"ACC_{a.pid}.csv", index=False)

    # ---- IBI (event based; seconds; only while fairly still, like a wrist PPG)
    tt, vals, cur = [], [], 0.0
    still = sd < 5
    while cur < n:
        i = int(cur)
        if i >= n: break
        ibi = 60.0 / max(40.0, hr[i]) + rs.normal(0, 0.025)
        cur += ibi
        if still[min(int(cur), n - 1)]:
            tt.append(cur); vals.append(ibi)
    tt = START + pd.to_timedelta(np.array(tt), unit="s")
    keep = drop_ranges(tt, ALL_GAP + [("2020-02-15 09:00", "2020-02-15 09:20")])
    pd.DataFrame({"Timestamp": fmt(tt[keep]), "Value": np.round(np.array(vals)[keep], 4)}).to_csv(out / f"IBI_{a.pid}.csv", index=False)

    # ---- Dexcom (5 min) + Food log + Demographics
    g_t = pd.date_range(START, END, freq="5min", inclusive="left")
    meals = [("2020-02-13 12:30", 38), ("2020-02-13 18:45", 45), ("2020-02-14 08:15", 30), ("2020-02-14 12:40", 40), ("2020-02-14 19:00", 50),
             ("2020-02-15 08:30", 28), ("2020-02-15 13:00", 42), ("2020-02-15 19:10", 36), ("2020-02-16 08:10", 30), ("2020-02-16 12:50", 44), ("2020-02-16 19:20", 40)]
    g = 98 + 4 * np.sin(np.arange(len(g_t)) / 40.0)
    for mt, c in meals:
        dt = (g_t - pd.Timestamp(mt)).total_seconds() / 60
        g = g + np.where(dt > 0, c * 1.1 * (dt / 45) * np.exp(1 - dt / 45), 0)
    g = g + rs.normal(0, 1.5, len(g_t))
    keep = drop_ranges(g_t, ALL_GAP)
    pd.DataFrame({"Timestamp": g_t[keep].strftime("%Y-%m-%d %H:%M:%S"), "Value": np.round(g[keep]).astype(int)}).to_csv(out / f"Dexcom_{a.pid}.csv", index=False)
    foods = ["oatmeal", "chicken salad", "pasta", "toast and eggs", "rice bowl", "sandwich", "yogurt and fruit", "burrito", "stir fry", "cereal", "pizza slice"]
    rows = [[m_[0][:10], m_[0][11:] + ":00", f, 1, "serving", c * 8, c, round(c * .25, 1), round(c * .3, 1)] for m_, f, c in zip(meals, foods, [m[1] for m in meals])]
    pd.DataFrame(rows, columns=["date", "time_begin", "logged_food", "amount", "unit", "calorie", "total_carb", "sugar", "protein"]).to_csv(out / f"Food_Log_{a.pid}.csv", index=False)
    pd.DataFrame([{"ID": a.pid, "Age": 52, "BMI": 27.4, "HbA1c": 5.7, "Fasting_GLU_mgdl": 104, "NOTE": "SYNTHETIC MOCK, not real data"}]).to_csv(out.parent / "Demographics.csv", index=False)
    print("wrote", out, {p.name: f"{p.stat().st_size/1e6:.1f} MB" for p in sorted(out.glob("*.csv"))})


if __name__ == "__main__":
    main()
