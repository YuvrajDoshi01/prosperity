"""smile_resid_momo.py — Test SMILE RESIDUAL MOMENTUM hypothesis.

User insight: "persistent != untradeable. If residuals are autocorrelated,
trade momentum on the residual: BUY voucher when residual rising (vol going
up = call price rising), SELL when falling."

Pipeline (per day):
  1. Per tick: fit parabolic smile iv(K)=a*m^2+b*m+c over wall-mid IVs.
  2. Per strike: compute residual r_t = iv_obs - iv_fit.
  3. Compute momentum signal mom_t(K, lookback) = r_t - r_{t-lookback}.
  4. Forward return: dprice_h(K) = wall_mid_t+h - wall_mid_t  (h ticks ahead).
  5. Diagnostics:
       - IC = corr(mom, dprice) for each (K, lookback, h)
       - Hit rate sign(mom) vs sign(dprice)
       - Strategy SR via simple thresholded signal:
             when mom > +thr: long voucher for h ticks
             when mom < -thr: short voucher for h ticks
       - Per-trade PnL distribution

Output: console table, no plotting (numpy/stdlib only).
"""
from __future__ import annotations
import csv, math, statistics
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


def wall_mid(bids, asks):
    if not bids or not asks: return None
    pop_bid = max(bids.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(asks.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def plain_mid(bids, asks):
    if not bids or not asks: return None
    return 0.5 * (max(bids) + min(asks))


def parse_prices(path):
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


def load_day(day):
    ticks = defaultdict(dict)
    for ts, product, bids, asks in parse_prices(RES / f"prices_round_4_day_{day}.csv"):
        ticks[ts][product] = (bids, asks)
    return ticks


def fit_parabola(xs, ys):
    n = len(xs)
    if n < 3: return None
    S0 = float(n); S1 = sum(xs); S2 = sum(x*x for x in xs)
    S3 = sum(x*x*x for x in xs); S4 = sum(x*x*x*x for x in xs)
    Sy = sum(ys); Sxy = sum(x*y for x, y in zip(xs, ys))
    Sx2y = sum(x*x*y for x, y in zip(xs, ys))
    M = [[S4, S3, S2], [S3, S2, S1], [S2, S1, S0]]
    rhs = [Sx2y, Sxy, Sy]
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
    return tuple(out)


def pearson(xs, ys):
    n = len(xs)
    if n < 5: return 0.0
    mx = sum(xs) / n; my = sum(ys) / n
    num = sum((a-mx)*(b-my) for a,b in zip(xs,ys))
    dx = math.sqrt(sum((a-mx)**2 for a in xs))
    dy = math.sqrt(sum((b-my)**2 for b in ys))
    return num / (dx*dy) if dx*dy > 0 else 0.0


def build_residual_series(day):
    """Returns dict K -> list of (ts, wm, residual). Aligned ticks only."""
    ticks = load_day(day)
    timestamps = sorted(ticks.keys())
    series = defaultdict(list)
    for ts in timestamps:
        prods = ticks[ts]
        if VEFE not in prods: continue
        bids_v, asks_v = prods[VEFE]
        spot = plain_mid(bids_v, asks_v)
        if spot is None: continue
        T = max(TTE_DAYS_AT_START - ts / 1_000_000.0, 0.01) / TTE_YEAR
        rec = []
        wm_by_K = {}
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
            wm_by_K[K] = wm
        if len(rec) < 4: continue
        ms = [r[1] for r in rec]; ivs = [r[2] for r in rec]
        coef = fit_parabola(ms, ivs)
        if coef is None: continue
        a_, b_, c_ = coef
        for K, m, iv in rec:
            fit = a_*m*m + b_*m + c_
            res = iv - fit
            series[K].append((ts, wm_by_K[K], res))
    return series


def compute_signals(series, lookback, horizon):
    """For each strike, build (mom, fwd_return) pairs from aligned series.
    mom_t = res_t - res_{t-lookback}
    fwd_t = wm_{t+horizon} - wm_t

    Note: res series is irregular (only ticks where strike traded), so we
    align by index — lookback / horizon are in 'observation' counts, not
    raw ts. With ATM strikes >9k obs out of 10k ticks, this is ~equivalent.
    """
    out = defaultdict(list)  # K -> list of (mom, fwd_ret)
    for K, recs in series.items():
        n = len(recs)
        if n < lookback + horizon + 5: continue
        for i in range(lookback, n - horizon):
            res_t = recs[i][2]; res_prev = recs[i - lookback][2]
            wm_t = recs[i][1]; wm_fwd = recs[i + horizon][1]
            mom = res_t - res_prev
            fwd = wm_fwd - wm_t
            out[K].append((mom, fwd))
    return out


def evaluate(signals, thr):
    """Compute IC, hit rate, threshold-trade SR, mean PnL/trade."""
    rows = []
    for K, pairs in signals.items():
        if len(pairs) < 100: continue
        mom = [p[0] for p in pairs]
        fwd = [p[1] for p in pairs]
        ic = pearson(mom, fwd)
        # Hit rate (sign agreement)
        hits = sum(1 for m, f in pairs if (m > 0 and f > 0) or (m < 0 and f < 0))
        non_zero = sum(1 for m, f in pairs if m != 0 and f != 0)
        hit_rate = hits / non_zero if non_zero else 0.0
        # Thresholded long/short PnL
        trades = []
        for m, f in pairs:
            if m > thr: trades.append(f)
            elif m < -thr: trades.append(-f)
        if len(trades) < 30:
            mean_p = sd_p = sr = 0.0
            n_tr = len(trades)
        else:
            mean_p = sum(trades) / len(trades)
            sd_p = statistics.pstdev(trades) if len(trades) > 1 else 0.0
            sr = mean_p / sd_p * math.sqrt(len(trades)) if sd_p > 0 else 0.0
            n_tr = len(trades)
        rows.append((K, len(pairs), ic, hit_rate, n_tr, mean_p, sd_p, sr))
    return rows


def main():
    print("=" * 100)
    print("SMILE RESIDUAL MOMENTUM — IC + signal evaluation")
    print("=" * 100)

    # Sweep configurations
    LOOKBACKS = [10, 25, 50, 100]
    HORIZONS = [25, 50, 100]
    THR = 0.02  # in IV-units, per user spec

    all_days = {}
    for day in (1, 2, 3):
        print(f"\n----- Day {day}: building residual series -----")
        s = build_residual_series(day)
        for K in STRIKES:
            n = len(s.get(K, []))
            if n: print(f"  K={K}: {n} obs")
        all_days[day] = s

    print("\n" + "=" * 100)
    print(f"GRID: lookback x horizon, threshold={THR}")
    print("=" * 100)

    for lb in LOOKBACKS:
        for h in HORIZONS:
            print(f"\n--- lookback={lb}  horizon={h} ---")
            print(f"{'day':>3} {'K':>5} {'n':>6} {'IC':>8} {'hit':>6} "
                  f"{'n_tr':>5} {'mPnL':>9} {'sdPnL':>9} {'SR':>7}")
            agg_pairs = defaultdict(list)
            for day in (1, 2, 3):
                sigs = compute_signals(all_days[day], lb, h)
                rows = evaluate(sigs, THR)
                for K, n, ic, hit, n_tr, mp, sd, sr in rows:
                    print(f"{day:>3} {K:>5} {n:>6} {ic:>+8.4f} {hit:>6.3f} "
                          f"{n_tr:>5} {mp:>+9.3f} {sd:>9.3f} {sr:>+7.2f}")
                    agg_pairs[K].extend(sigs.get(K, []))
            # 3-day aggregate
            print(f"  --- 3-day aggregate ---")
            for K in STRIKES:
                pairs = agg_pairs[K]
                if len(pairs) < 100: continue
                mom = [p[0] for p in pairs]; fwd = [p[1] for p in pairs]
                ic = pearson(mom, fwd)
                hits = sum(1 for m, f in pairs if (m > 0 and f > 0) or (m < 0 and f < 0))
                non_zero = sum(1 for m, f in pairs if m != 0 and f != 0)
                hit_rate = hits / non_zero if non_zero else 0.0
                trades = []
                for m, f in pairs:
                    if m > THR: trades.append(f)
                    elif m < -THR: trades.append(-f)
                if len(trades) < 30: continue
                mean_p = sum(trades)/len(trades)
                sd_p = statistics.pstdev(trades)
                sr = mean_p/sd_p*math.sqrt(len(trades)) if sd_p > 0 else 0.0
                print(f"all   {K:>5} {len(pairs):>6} {ic:>+8.4f} {hit_rate:>6.3f} "
                      f"{len(trades):>5} {mean_p:>+9.3f} {sd_p:>9.3f} {sr:>+7.2f}")

    # Threshold sweep at fixed lb=50, h=50
    print("\n" + "=" * 100)
    print(f"THRESHOLD SWEEP at lookback=50, horizon=50 (3-day pooled)")
    print("=" * 100)
    for lb_use, h_use in [(25, 50), (50, 50), (50, 100), (100, 100)]:
        print(f"\n[lb={lb_use} h={h_use}]")
        agg_pairs = defaultdict(list)
        for day in (1, 2, 3):
            sigs = compute_signals(all_days[day], lb_use, h_use)
            for K, pairs in sigs.items():
                agg_pairs[K].extend(pairs)
        print(f"{'K':>5} " + " ".join(f"{f'thr={t}':>14}" for t in [0.005, 0.01, 0.02, 0.03, 0.05]))
        print(f"{'':>5} " + " ".join(f"{'n_tr | SR':>14}" for _ in range(5)))
        for K in STRIKES:
            pairs = agg_pairs[K]
            if len(pairs) < 100: continue
            cells = []
            for thr in [0.005, 0.01, 0.02, 0.03, 0.05]:
                trades = []
                for m, f in pairs:
                    if m > thr: trades.append(f)
                    elif m < -thr: trades.append(-f)
                if len(trades) < 30:
                    cells.append(f"{len(trades):>4}|   na")
                else:
                    mean_p = sum(trades)/len(trades)
                    sd_p = statistics.pstdev(trades)
                    sr = mean_p/sd_p*math.sqrt(len(trades)) if sd_p > 0 else 0.0
                    cells.append(f"{len(trades):>4}|{sr:>+6.2f}")
            print(f"{K:>5} " + " ".join(f"{c:>14}" for c in cells))


if __name__ == "__main__":
    main()
