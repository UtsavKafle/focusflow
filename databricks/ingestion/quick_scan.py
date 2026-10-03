"""Run on YOUR machine inside the BIG IDEAs folder (the one containing 001, 002, ... 016). Streams each CSV in
chunks (ACC is huge), writes scan_report.md next to where you run it. Paste or attach that file.
  python quick_scan.py /path/to/big-ideas-folder [--participants 001 004 007]
Needs only pandas."""
import argparse, pathlib, sys
import numpy as np
import pandas as pd

NOMINAL = {"HR": 1, "EDA": 4, "TEMP": 4, "ACC": 32, "IBI": None, "BVP": 64, "Dexcom": 1 / 300}
ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--participants", nargs="*")
ap.add_argument("--signals", nargs="*", default=["HR", "EDA", "ACC", "IBI", "TEMP", "Dexcom"])
a = ap.parse_args()
root = pathlib.Path(a.root)
parts = a.participants or sorted(p.name for p in root.iterdir() if p.is_dir() and p.name[:3].isdigit())
out = ["# scan_report\n", f"root: {root}\n"]
demo = next(root.rglob("Demographics.csv"), None)
if demo:
    out += ["\n## Demographics.csv (head)\n```\n", pd.read_csv(demo).head(20).to_string(), "\n```\n"]
for p in parts:
    out.append(f"\n## Participant {p}\n")
    for s in a.signals:
        f = next((x for x in (root / p).glob("*.csv") if x.stem.lower().startswith(s.lower())), None)
        if not f:
            out.append(f"- {s}: MISSING\n"); continue
        n, first, last, dup, gaps, big_gaps, prev, head = 0, None, None, 0, 0, [], None, None
        for ch in pd.read_csv(f, chunksize=2_000_000):
            if head is None: head = ch.head(3)
            ts = pd.to_datetime(ch.iloc[:, 0], errors="coerce")
            ch = ch.assign(_t=ts)
            n += len(ch); first = first or ts.dropna().iloc[0] if ts.notna().any() else first
            if ts.notna().any(): last = ts.dropna().iloc[-1]
            tt = ts.dropna()
            if prev is not None: tt = pd.concat([pd.Series([prev]), tt], ignore_index=True)
            if len(tt):
                d = tt.diff().dt.total_seconds().dropna()
                dup += int((d == 0).sum())
                for i in np.where(d > 60)[0][:50]: big_gaps.append((tt.iloc[i], float(d.iloc[i])))
                gaps += int((d > 60).sum()); prev = tt.iloc[-1]
        hrs = (last - first).total_seconds() / 3600 if first is not None and last is not None else float("nan")
        rate = n / (hrs * 3600) if hrs and hrs > 0 else float("nan")
        out.append(f"- **{s}** {f.name} ({f.stat().st_size/1e6:.1f} MB): rows={n:,} first={first} last={last} span_h={hrs:.1f} "
                   f"observed_rate_hz={rate:.3f} (nominal {NOMINAL.get(s)}) dup_ts={dup:,} gaps>60s={gaps}\n")
        out.append(f"  - columns: {list(head.columns)}; sample:\n```\n{head.to_string()}\n```\n")
        if big_gaps: out.append("  - largest gaps (start, seconds): " + "; ".join(f"{t} {s_:.0f}" for t, s_ in sorted(big_gaps, key=lambda x: -x[1])[:8]) + "\n")
pathlib.Path("scan_report.md").write_text("".join(out))
print("wrote scan_report.md", len("".join(out)), "chars")
