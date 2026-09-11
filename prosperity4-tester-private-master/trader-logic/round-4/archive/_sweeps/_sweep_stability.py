"""Parameter stability audit for r4_final.py.

Sweeps each tuned parameter, classifies as FLAT / MODERATE / STEEP.
Writes JSON results to _sweep_tmp/stability.json
"""
import os, sys, re, json, subprocess, shutil, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
SRC = ROOT / "trader-logic" / "round-4" / "r4_final.py"
TMP = ROOT / "trader-logic" / "round-4" / "_sweep_tmp"
TMP.mkdir(exist_ok=True)

ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(ROOT / "prosperity4bt")

SRC_TEXT = SRC.read_text()

# (name, line_anchor_regex, replacement_lambda(value)) — replacement returns full new line
PATCHES = {
    "QUOTE_SIZE": (
        re.compile(r"^(\s*QUOTE_SIZE\s*=\s*)\d+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "OBI_POS_CAP": (
        re.compile(r"^(OBI_POS_CAP\s*=\s*)\d+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "VFE_MOMO_TP": (
        re.compile(r"^(VFE_MOMO_TP\s*=\s*)[\d.]+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "VFE_MOMO_LOOKBACK": (
        re.compile(r"^(VFE_MOMO_LOOKBACK\s*=\s*)\d+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "M49_SIZE": (
        re.compile(r"^(M49_SIZE\s*=\s*)\d+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "M55_THRESH": (
        re.compile(r"^(M55_THRESH\s*=\s*)\d+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
    "YOLO_DRIFT_THRESHOLD": (
        re.compile(r"^(YOLO_DRIFT_THRESHOLD\s*=\s*)-?[\d.]+(.*)$", re.M),
        lambda v: rf"\g<1>{v}\g<2>",
    ),
}

def make_variant(name, value):
    pat, repl = PATCHES[name]
    new_text, n = pat.subn(repl(value), SRC_TEXT, count=1)
    if n == 0:
        raise RuntimeError(f"Patch failed (no match) for {name}={value}")
    out = TMP / f"v_{name}_{str(value).replace('.', 'p').replace('-', 'm')}.py"
    out.write_text(new_text)
    return out

def run_bt(file_path, mode="default", ticks=10000, day=None):
    args = [sys.executable, "-m", "prosperity4bt", str(file_path)]
    if day is not None:
        args.append(f"4-{day}")
    else:
        args.append("4")
    args += ["--ticks", str(ticks), "--no-out", "--no-progress"]
    if mode == "imc":
        args += ["--match-mode", "imc"]
    res = subprocess.run(args, env=ENV, capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    out = res.stdout + res.stderr
    # parse "Total profit: N,NNN" — take the LAST occurrence (final aggregate)
    matches = re.findall(r"Total profit:\s*([-\d,]+)", out)
    if not matches:
        return None
    return int(matches[-1].replace(",", ""))

def sweep(name, values, mode="default", ticks=10000, day=None, label=""):
    print(f"\n=== Sweep {name} {label} mode={mode} ticks={ticks} day={day} ===", flush=True)
    files = [(v, make_variant(name, v)) for v in values]
    results = {}
    def task(item):
        v, f = item
        t0 = time.time()
        pnl = run_bt(f, mode=mode, ticks=ticks, day=day)
        dt = time.time() - t0
        print(f"  {name}={v}: ${pnl:,} ({dt:.1f}s)" if pnl is not None else f"  {name}={v}: FAIL", flush=True)
        return v, pnl
    # 3 parallel — leave headroom on a 4-core box
    with ThreadPoolExecutor(max_workers=3) as ex:
        for v, pnl in ex.map(task, files):
            results[v] = pnl
    return results

def classify(values, results, current):
    best = max(v for v in results.values() if v is not None)
    cur_pnl = results.get(current)
    sorted_vals = sorted(results.keys())
    cur_idx = sorted_vals.index(current)
    neighbors = []
    if cur_idx > 0:
        neighbors.append(sorted_vals[cur_idx - 1])
    if cur_idx < len(sorted_vals) - 1:
        neighbors.append(sorted_vals[cur_idx + 1])
    deltas = [abs(results[n] - cur_pnl) for n in neighbors if results.get(n) is not None]
    max_delta = max(deltas) if deltas else 0
    pct = (max_delta / abs(best)) * 100 if best else 0
    if pct < 5:
        cat = "FLAT"
    elif pct < 15:
        cat = "MODERATE"
    else:
        cat = "STEEP"
    return {
        "current": current,
        "current_pnl": cur_pnl,
        "best": best,
        "best_value": [k for k, v in results.items() if v == best][0],
        "max_neighbor_delta": max_delta,
        "delta_pct_of_best": round(pct, 2),
        "category": cat,
        "results": results,
    }

if __name__ == "__main__":
    out = {}
    # 10k 3-day default
    out["QUOTE_SIZE"] = classify([100,125,150,175,200,225,250],
        sweep("QUOTE_SIZE", [100,125,150,175,200,225,250], "default", 10000), 200)
    out["OBI_POS_CAP_default"] = classify([15,20,25,30,40,50,75],
        sweep("OBI_POS_CAP", [15,20,25,30,40,50,75], "default", 10000, label="default"), 30)
    out["OBI_POS_CAP_imc"] = classify([15,20,25,30,40,50,75],
        sweep("OBI_POS_CAP", [15,20,25,30,40,50,75], "imc", 10000, label="imc"), 30)
    out["VFE_MOMO_TP"] = classify([8,9,10,11,12,13,14,15,18],
        sweep("VFE_MOMO_TP", [8,9,10,11,12,13,14,15,18], "default", 10000), 12)
    out["VFE_MOMO_LOOKBACK"] = classify([15,20,25,30,35,40,50],
        sweep("VFE_MOMO_LOOKBACK", [15,20,25,30,35,40,50], "default", 10000), 25)
    out["M49_SIZE"] = classify([30,40,50,60,80,100],
        sweep("M49_SIZE", [30,40,50,60,80,100], "default", 10000), 60)
    out["M55_THRESH"] = classify([15,20,25,30,35,40,50],
        sweep("M55_THRESH", [15,20,25,30,35,40,50], "default", 10000), 30)
    # YOLO: 1k day-3 + 10k 3-day default
    out["YOLO_DRIFT_THRESHOLD_d3_1k"] = classify([-1.0,-1.5,-2.0,-2.5,-3.0],
        sweep("YOLO_DRIFT_THRESHOLD", [-1.0,-1.5,-2.0,-2.5,-3.0], "default", 1000, day=3, label="d3_1k"), -1.5)
    out["YOLO_DRIFT_THRESHOLD_3d_10k"] = classify([-1.0,-1.5,-2.0,-2.5,-3.0],
        sweep("YOLO_DRIFT_THRESHOLD", [-1.0,-1.5,-2.0,-2.5,-3.0], "default", 10000, label="3d_10k"), -1.5)

    (TMP / "stability.json").write_text(json.dumps(out, indent=2))
    print("\n=== SUMMARY ===")
    for k, v in out.items():
        print(f"{k}: {v['category']} (cur=${v['current_pnl']:,} best=${v['best']:,}@{v['best_value']} Δ%={v['delta_pct_of_best']})")
