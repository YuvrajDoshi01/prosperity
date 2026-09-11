"""Wrapper that loads r4_final_v3.Trader and times each run() call."""
import os, sys, time, atexit, importlib.util
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_r4v3_inner", os.path.join(_HERE, "r4_final_v3.py"))
_mod = importlib.util.module_from_spec(_spec)
sys.modules["_r4v3_inner"] = _mod
_spec.loader.exec_module(_mod)

_times = []

class Trader:
    def __init__(self):
        self._inner = _mod.Trader()

    def run(self, state):
        t0 = time.perf_counter()
        r = self._inner.run(state)
        _times.append((time.perf_counter() - t0) * 1000.0)
        return r

def _report():
    if not _times:
        return
    ts = sorted(_times)
    n = len(ts)
    p50 = ts[n // 2]
    p90 = ts[int(n * 0.9)]
    p99 = ts[int(n * 0.99)]
    pmax = ts[-1]
    avg = sum(ts) / n
    sys.stderr.write(f"\n[PERF] n={n} avg={avg:.3f}ms p50={p50:.3f}ms p90={p90:.3f}ms p99={p99:.3f}ms max={pmax:.3f}ms total={sum(ts):.1f}ms\n")

atexit.register(_report)
