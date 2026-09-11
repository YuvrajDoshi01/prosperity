"""vol_smile_fit.py — IV smile shape EDA + parabolic-fit residual analysis.

Goal: replicate Frankfurt Hedgehogs (P3 #2) approach. Fit parabola
    iv(K) = a*m^2 + b*m + c     where m = log(K/spot)
across observed strikes per tick. Detrend → moneyness-independent residual.

Outputs:
  - per-strike summary stats (median IV, residual std, ac1)
  - smile shape table (mean IV by m bucket)
  - residual vs |residual| > thresh diagnostic for trade gating

CONSTRAINT: numpy + stdlib only. Manual least-squares parabola fit.
"""
from __future__ import annotations
import csv, math, os, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES = ROOT / "prosperity4bt/resources/round4"

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
SYM = {k: f"VEV_{k}" for k in STRIKES}
VEFE = "VELVETFRUIT_EXTRACT"
TTE_DAYS_AT_START = 4.0
TTE_YEAR = 250.0


def bs_call(spot, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(spot - K, 0.0)
    sd = sigma * math.sqrt(T)
    d1 = (math.log(spot / K) + 0.5 * sigma * sigma * T) / sd
    d2 = d1 - sd
    from statistics import NormalDist
    nd = NormalDist()
    return spot * nd.cdf(d1) - K * nd.cdf(d2)


def implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return None
    for _ in range(60):
        m = 0.5 * (lo + hi)
        if bs_call(spot, K, T, m) < mkt:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def wall_mid(bids: dict, asks: dict):
    if not bids or not asks: return None
    pop_bid = max(bids.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(asks.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def plain_mid(bids: dict, asks: dict):
    if not bids or not asks: return None
    return 0.5 * (max(bids) + min(asks))


def parse_prices(path: Path):
    """Yield (ts, product, bids_dict, asks_dict) for each row."""
    with open(path, newline='') as f:
        r = csv.DictReader(f, delimiter=';')
        for row in r:
            ts = int(row['timestamp']); product = row['product']
            bids, asks = {}, {}
            for i in (1, 2, 3):
                bp = row.get(f'bid_price_{i}'); bv = row.get(f'bid_volume_{i}')
                ap = row.get(f'ask_price_{i}'); av = row.get(f'ask_volume_{i}')
                if bp and bv: bids[int(float(bp))] = int(float(bv))
                if ap and av: asks[int(float(ap))] = int(float(av))
            yield ts, product, bids, asks


def load_day(day: int):
    """Returns ticks: dict[ts] -> {product: (bids, asks)}."""
    ticks = defaultdict(dict)
    for ts, product, bids, asks in parse_prices(RES / f"prices_round_4_day_{day}.csv"):
        ticks[ts][product] = (bids, asks)
    return ticks


def fit_parabola(xs, ys):
    """Least-squares fit y = a*x^2 + b*x + c. Manual normal equations.
    Returns (a, b, c) or None if singular / insufficient points."""
    n = len(xs)
    if n < 3: return None
    # Sums
    S0 = float(n)
    S1 = sum(xs); S2 = sum(x*x for x in xs)
    S3 = sum(x*x*x for x in xs); S4 = sum(x*x*x*x for x in xs)
    Sy = sum(ys); Sxy = sum(x*y for x, y in zip(xs, ys))
    Sx2y = sum(x*x*y for x, y in zip(xs, ys))
    # Normal equations: [S4 S3 S2; S3 S2 S1; S2 S1 S0] [a;b;c] = [Sx2y; Sxy; Sy]
    M = [[S4, S3, S2], [S3, S2, S1], [S2, S1, S0]]
    rhs = [Sx2y, Sxy, Sy]
    # 3x3 inverse via cofactors
    def det3(m):
        return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    D = det3(M)
    if abs(D) < 1e-12: return None
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for r in range(3): Mc[r][col] = rhs[r]
        out.append(det3(Mc) / D)
    return tuple(out)  # a, b, c


def analyze_day(day: int):
    print(f"\n========== DAY {day} ==========")
    ticks = load_day(day)
    timestamps = sorted(ticks.keys())
    print(f"Ticks: {len(timestamps)}  (range {timestamps[0]} - {timestamps[-1]})")

    iv_by_K = defaultdict(list)            # K -> list of iv (one per tick where defined)
    smile_records = []                     # list of (ts, spot, T, [(K,m,iv)])
    residuals_by_K = defaultdict(list)
    fit_quality = []                       # list of R^2 per tick

    for ts in timestamps:
        prods = ticks[ts]
        if VEFE not in prods: continue
        bids_v, asks_v = prods[VEFE]
        spot = plain_mid(bids_v, asks_v)
        if spot is None: continue
        T = max(TTE_DAYS_AT_START - ts / 1_000_000.0, 0.01) / TTE_YEAR
        rec = []  # (K, m, iv)
        for K in STRIKES:
            sym = SYM[K]
            if sym not in prods: continue
            b, a = prods[sym]
            wm = wall_mid(b, a)
            if wm is None: continue
            iv = implied_vol(wm, spot, K, T)
            if iv is None: continue
            m = math.log(K / spot)
            rec.append((K, m, iv))
            iv_by_K[K].append(iv)
        if len(rec) < 4: continue
        smile_records.append((ts, spot, T, rec))
        # Fit parabola in m-space
        ms = [r[1] for r in rec]; ivs = [r[2] for r in rec]
        coef = fit_parabola(ms, ivs)
        if coef is None: continue
        a_, b_, c_ = coef
        ymean = sum(ivs) / len(ivs)
        ss_tot = sum((y - ymean) ** 2 for y in ivs)
        ss_res = 0.0
        for K, m, iv in rec:
            fit = a_ * m * m + b_ * m + c_
            res = iv - fit
            residuals_by_K[K].append(res)
            ss_res += res * res
        if ss_tot > 0:
            fit_quality.append(1.0 - ss_res / ss_tot)

    # Per-strike summary
    print(f"\nPer-strike IV stats ({len(smile_records)} fitted ticks):")
    print(f"{'K':>5} {'count':>6} {'iv_mean':>9} {'iv_med':>9} {'iv_std':>9} "
          f"{'res_mean':>10} {'res_std':>10} {'res_p95':>10} {'res_ac1':>9}")
    for K in STRIKES:
        ivs = iv_by_K[K]; res = residuals_by_K[K]
        if not ivs:
            print(f"{K:>5} {0:>6}  (no IV)")
            continue
        iv_mean = statistics.mean(ivs); iv_med = statistics.median(ivs)
        iv_std = statistics.pstdev(ivs)
        if res:
            r_mean = statistics.mean(res); r_std = statistics.pstdev(res)
            r_abs_sorted = sorted(abs(x) for x in res)
            r_p95 = r_abs_sorted[int(0.95 * len(r_abs_sorted))]
            # AC1
            if len(res) > 2:
                xs = res[:-1]; ys = res[1:]
                mx = statistics.mean(xs); my = statistics.mean(ys)
                num = sum((a-mx)*(b-my) for a,b in zip(xs,ys))
                d1 = math.sqrt(sum((a-mx)**2 for a in xs))
                d2 = math.sqrt(sum((b-my)**2 for b in ys))
                ac1 = num / (d1*d2) if d1*d2 > 0 else 0.0
            else:
                ac1 = 0.0
        else:
            r_mean = r_std = r_p95 = ac1 = 0.0
        print(f"{K:>5} {len(ivs):>6} {iv_mean:>9.4f} {iv_med:>9.4f} {iv_std:>9.4f} "
              f"{r_mean:>10.5f} {r_std:>10.5f} {r_p95:>10.5f} {ac1:>9.3f}")

    # Smile shape
    print("\nSmile shape — mean IV by moneyness bucket m=log(K/spot):")
    bucket_iv = defaultdict(list)
    for ts, spot, T, rec in smile_records:
        for K, m, iv in rec:
            b = round(m * 20) / 20.0  # 0.05 buckets
            bucket_iv[b].append(iv)
    for b in sorted(bucket_iv):
        ivs = bucket_iv[b]
        if len(ivs) < 30: continue
        print(f"  m={b:>+.3f}  n={len(ivs):>6}  mean_iv={statistics.mean(ivs):.4f}  "
              f"std_iv={statistics.pstdev(ivs):.4f}")

    if fit_quality:
        fq_sorted = sorted(fit_quality)
        print(f"\nParabola fit R^2: mean={statistics.mean(fit_quality):.4f}  "
              f"median={fq_sorted[len(fq_sorted)//2]:.4f}  "
              f"p10={fq_sorted[int(0.1*len(fq_sorted))]:.4f}  "
              f"p90={fq_sorted[int(0.9*len(fq_sorted))]:.4f}")

    # Residual threshold sweep — what fraction of ticks have |res| > thr per strike?
    print("\nFrac |residual| > threshold (signal frequency):")
    print(f"{'K':>5} " + " ".join(f"{t:>9}" for t in [0.005, 0.01, 0.015, 0.02, 0.03, 0.05]))
    for K in STRIKES:
        res = residuals_by_K[K]
        if not res: continue
        n = len(res)
        fracs = []
        for thr in [0.005, 0.01, 0.015, 0.02, 0.03, 0.05]:
            f = sum(1 for r in res if abs(r) > thr) / n
            fracs.append(f)
        print(f"{K:>5} " + " ".join(f"{f:>9.3f}" for f in fracs))

    # Mean reversion of residuals: signed-residual t+H autocorr
    print("\nResidual mean-reversion (autocorr at lag H, neg = mean-revert):")
    print(f"{'K':>5} {'lag1':>7} {'lag5':>7} {'lag10':>7} {'lag25':>7} {'lag50':>7}")
    for K in STRIKES:
        res = residuals_by_K[K]
        if len(res) < 60: continue
        out = []
        for H in (1, 5, 10, 25, 50):
            xs = res[:-H]; ys = res[H:]
            mx = statistics.mean(xs); my = statistics.mean(ys)
            num = sum((a-mx)*(b-my) for a,b in zip(xs,ys))
            d1 = math.sqrt(sum((a-mx)**2 for a in xs))
            d2 = math.sqrt(sum((b-my)**2 for b in ys))
            ac = num / (d1*d2) if d1*d2 > 0 else 0.0
            out.append(ac)
        print(f"{K:>5} " + " ".join(f"{a:>7.3f}" for a in out))

    return iv_by_K, residuals_by_K, smile_records


if __name__ == "__main__":
    for d in (1, 2, 3):
        analyze_day(d)
