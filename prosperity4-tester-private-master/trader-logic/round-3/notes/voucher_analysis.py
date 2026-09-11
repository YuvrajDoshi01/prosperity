"""Exhaustive R3 EDA — IV dynamics, smile, arb bounds, cross-strike signals.

Runs Parts 1-8 from the spec. Outputs go to stdout and a sibling .txt file
via shell redirection.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, mean, pstdev

_ND = NormalDist()

BASE = Path(__file__).resolve().parents[3] / "prosperity4bt" / "resources" / "round3"
DAYS = [0, 1, 2]
TTE_DAYS = {0: 8, 1: 7, 2: 6}
TTE_YEAR = 250.0
UNDERLYING = "VELVETFRUIT_EXTRACT"
STRIKES_ALL = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
STRIKES_IV = [5000, 5100, 5200, 5300, 5400]
STRIKES_DEEP_ITM = [4000, 4500]
STRIKES_PENNY = [6000, 6500]
SYM = {k: f"VEV_{k}" for k in STRIKES_ALL}

# ────────────────────────── helpers ──────────────────────────

def autocorr(xs, lag=1):
    n = len(xs)
    if n <= lag + 1:
        return 0.0
    mu = sum(xs) / n
    num = sum((xs[i] - mu) * (xs[i + lag] - mu) for i in range(n - lag))
    den = sum((x - mu) ** 2 for x in xs)
    return num / den if den > 1e-15 else 0.0


def variance_ratio(xs, k):
    """VR(k) = Var(sum of k returns) / (k * Var(1 return)). VR=1 for RW, <1 for MR."""
    if len(xs) < k * 2 + 2:
        return float("nan")
    rets = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    var1 = sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)
    if var1 < 1e-15:
        return float("nan")
    k_rets = [xs[i + k] - xs[i] for i in range(len(xs) - k)]
    muk = sum(k_rets) / len(k_rets)
    vark = sum((r - muk) ** 2 for r in k_rets) / len(k_rets)
    return vark / (k * var1)


def bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * _ND.cdf(d1) - K * _ND.cdf(d2)


def implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0:
        return float("nan")
    if mkt >= spot:
        return float("nan")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_call(spot, K, T, mid) < mkt:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fit_linear(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den < 1e-15:
        return None
    b = num / den
    a = my - b * mx
    # SE of slope
    yhat = [a + b * x for x in xs]
    resid = [y - yh for y, yh in zip(ys, yhat)]
    sse = sum(r * r for r in resid)
    se_b = math.sqrt(sse / (n - 2) / den) if n > 2 else float("nan")
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sse / ss_tot if ss_tot > 1e-15 else 0.0
    return a, b, se_b, r2


def fit_quadratic(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    s1 = n
    sx = sum(xs); sxx = sum(x * x for x in xs)
    sxxx = sum(x ** 3 for x in xs); sxxxx = sum(x ** 4 for x in xs)
    sy = sum(ys); sxy = sum(x * y for x, y in zip(xs, ys))
    sxxy = sum(x * x * y for x, y in zip(xs, ys))
    M = [[sxxxx, sxxx, sxx], [sxxx, sxx, sx], [sxx, sx, s1]]
    b = [sxxy, sxy, sy]
    det = (M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
           - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
           + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]))
    if abs(det) < 1e-15:
        return None
    coefs = []
    for col in range(3):
        Mi = [row[:] for row in M]
        for r in range(3):
            Mi[r][col] = b[r]
        di = (Mi[0][0] * (Mi[1][1] * Mi[2][2] - Mi[1][2] * Mi[2][1])
              - Mi[0][1] * (Mi[1][0] * Mi[2][2] - Mi[1][2] * Mi[2][0])
              + Mi[0][2] * (Mi[1][0] * Mi[2][1] - Mi[1][1] * Mi[2][0]))
        coefs.append(di / det)
    yhat = [coefs[0] * x * x + coefs[1] * x + coefs[2] for x in xs]
    resid = [y - yh for y, yh in zip(ys, yhat)]
    my = sum(ys) / n
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum(r * r for r in resid)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-15 else 0.0
    return (*coefs, r2)


# ────────────────────────── data load ──────────────────────────

def load_day(day):
    """Return dict {product: [(ts, mid, bb, ba, bv1, av1, spread), ...]} and trades."""
    prices = defaultdict(list)
    with open(BASE / f"prices_round_3_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if not row["mid_price"]:
                continue
            try:
                ts = int(row["timestamp"])
                mid = float(row["mid_price"])
                bb = float(row["bid_price_1"] or 0)
                ba = float(row["ask_price_1"] or 0)
                bv1 = float(row["bid_volume_1"] or 0)
                av1 = float(row["ask_volume_1"] or 0)
            except (ValueError, TypeError):
                continue
            spread = ba - bb if ba and bb else 0
            prices[row["product"]].append((ts, mid, bb, ba, bv1, av1, spread))
    trades = defaultdict(list)
    trade_path = BASE / f"trades_round_3_day_{day}.csv"
    if trade_path.exists():
        with open(trade_path) as f:
            r = csv.DictReader(f, delimiter=";")
            for row in r:
                try:
                    ts = int(row["timestamp"])
                    p = float(row["price"])
                    q = int(row["quantity"])
                    trades[row["symbol"]].append((ts, p, q))
                except (ValueError, KeyError):
                    continue
    return prices, trades


# ────────────────────────── Part 1: dynamics ──────────────────────────

def part1_dynamics(all_data):
    print("\n=== PART 1: Product Dynamics ===\n")
    print(f"{'product':<22}{'day':<4}{'mean':>10}{'std':>8}{'range':>8}"
          f"{'AR1_lev':>8}{'AR1_ret':>8}{'VR(2)':>7}{'VR(20)':>8}"
          f"{'spread':>7}{'drift%':>8}")
    for prod in ["HYDROGEL_PACK", UNDERLYING] + [SYM[k] for k in STRIKES_ALL]:
        for day in DAYS:
            data = all_data[day][0].get(prod, [])
            if len(data) < 100:
                continue
            data.sort()
            mids = [d[1] for d in data]
            spreads = [d[6] for d in data if d[6] > 0]
            ar1_lev = autocorr(mids)
            rets = [mids[i + 1] - mids[i] for i in range(len(mids) - 1)]
            ar1_ret = autocorr(rets)
            vr2 = variance_ratio(mids, 2)
            vr20 = variance_ratio(mids, 20)
            avg_spread = mean(spreads) if spreads else 0
            half = len(mids) // 2
            drift = (mean(mids[half:]) - mean(mids[:half])) / mean(mids[:half]) * 100
            print(f"{prod:<22}{day:<4}{mean(mids):>10.2f}{pstdev(mids):>8.2f}"
                  f"{max(mids)-min(mids):>8.2f}{ar1_lev:>8.3f}{ar1_ret:>8.3f}"
                  f"{vr2:>7.2f}{vr20:>8.2f}{avg_spread:>7.2f}{drift:>7.2f}%")


# ────────────────────────── Part 2: IV analysis ──────────────────────────

def compute_iv_series(all_data):
    """Return dict {(day, K): [(ts, iv), ...]}."""
    iv = defaultdict(list)
    for day in DAYS:
        prices, _ = all_data[day]
        und = {t: m for t, m, *_ in prices.get(UNDERLYING, [])}
        for K in STRIKES_IV + STRIKES_DEEP_ITM + STRIKES_PENNY:
            rows = prices.get(SYM[K], [])
            for ts, mid, bb, ba, *_ in rows:
                if ts not in und:
                    continue
                spot = und[ts]
                # Intra-day TTE decay
                T = (TTE_DAYS[day] - ts / 1_000_000.0) / TTE_YEAR
                iv_val = implied_vol(mid, spot, K, T)
                if not math.isnan(iv_val):
                    iv[(day, K)].append((ts, iv_val))
    return iv


def part2_iv(iv_series):
    print("\n=== PART 2: Black-Scholes IV (per strike per day) ===\n")
    print(f"{'day':<4}{'K':<6}{'n':>6}{'mean':>8}{'std':>8}{'min':>8}{'max':>8}"
          f"{'AR1_lev':>10}{'AR1_ΔIV':>10}{'half_life':>12}")
    for day in DAYS:
        for K in STRIKES_IV + STRIKES_DEEP_ITM:
            series = iv_series.get((day, K), [])
            if len(series) < 100:
                print(f"{day:<4}{K:<6}{len(series):>6} (too few)")
                continue
            ivs = [s[1] for s in series]
            n = len(ivs)
            mu, sd = mean(ivs), pstdev(ivs)
            ar1 = autocorr(ivs)
            div = [ivs[i + 1] - ivs[i] for i in range(n - 1)]
            ar1_d = autocorr(div)
            # Half-life from OLS: ΔIV_t = α + β(IV_{t-1} − μ); half = −ln2/ln(1+β)
            xs = [ivs[i] - mu for i in range(n - 1)]
            ys = div
            fit = fit_linear(xs, ys)
            if fit and fit[1] < 0 and fit[1] > -2:
                hl = -math.log(2) / math.log(1 + fit[1])
                hl_str = f"{hl:.0f}" if 0 < hl < 1e5 else ">inf"
            else:
                hl_str = "no MR"
            print(f"{day:<4}{K:<6}{n:>6}{mu:>8.3f}{sd:>8.3f}"
                  f"{min(ivs):>8.3f}{max(ivs):>8.3f}{ar1:>10.4f}{ar1_d:>10.4f}"
                  f"{hl_str:>12}")


# ────────────────────────── Part 3: smile structure ──────────────────────────

def part3_smile(all_data, iv_series):
    print("\n=== PART 3: Smile Structure ===\n")
    print(f"{'day':<4}{'ticks':>7}{'a_mean':>9}{'a_std':>9}{'b_mean':>9}{'b_std':>9}"
          f"{'c_mean':>9}{'c_std':>9}{'R2_mean':>9}{'resid_std':>11}{'convex?':>10}")
    for day in DAYS:
        prices, _ = all_data[day]
        und = {t: m for t, m, *_ in prices.get(UNDERLYING, [])}
        iv_by_ts = {K: dict(iv_series.get((day, K), [])) for K in STRIKES_IV}
        # Build per-tick smile fit
        a_s, b_s, c_s, r2_s = [], [], [], []
        resid_per_strike = defaultdict(list)
        ticks = sorted(und.keys())
        for ts in ticks:
            spot = und[ts]
            xs, ys, Ks = [], [], []
            T = (TTE_DAYS[day] - ts / 1_000_000.0) / TTE_YEAR
            if T <= 0:
                continue
            for K in STRIKES_IV:
                ivv = iv_by_ts[K].get(ts)
                if ivv is None:
                    continue
                m = math.log(K / spot) / math.sqrt(T)
                xs.append(m); ys.append(ivv); Ks.append(K)
            if len(xs) < 4:
                continue
            fit = fit_quadratic(xs, ys)
            if fit is None:
                continue
            a, b, c, r2 = fit
            a_s.append(a); b_s.append(b); c_s.append(c); r2_s.append(r2)
            for m, y, K in zip(xs, ys, Ks):
                yhat = a * m * m + b * m + c
                resid_per_strike[K].append(y - yhat)
        if not a_s:
            print(f"{day:<4} no valid fits"); continue
        all_resid = [r for v in resid_per_strike.values() for r in v]
        convex_pct = 100 * sum(1 for a in a_s if a > 0) / len(a_s)
        print(f"{day:<4}{len(a_s):>7}{mean(a_s):>9.3f}{pstdev(a_s):>9.3f}"
              f"{mean(b_s):>9.3f}{pstdev(b_s):>9.3f}"
              f"{mean(c_s):>9.3f}{pstdev(c_s):>9.3f}"
              f"{mean(r2_s):>9.3f}{pstdev(all_resid):>11.5f}"
              f"{convex_pct:>9.1f}%")
        print(f"  Per-strike residual AR1:")
        for K in STRIKES_IV:
            rs = resid_per_strike.get(K, [])
            if len(rs) > 10:
                print(f"    K={K}: n={len(rs)} mean={mean(rs):.5f} std={pstdev(rs):.5f} AR1={autocorr(rs):.4f}")


# ────────────────────────── Part 4: no-arb bounds ──────────────────────────

def part4_arb_bounds(all_data):
    print("\n=== PART 4: No-Arbitrage Bound Violations ===\n")
    for day in DAYS:
        prices, _ = all_data[day]
        und_prices = {t: (m, bb, ba) for t, m, bb, ba, *_ in prices.get(UNDERLYING, [])}
        voucher_prices = {K: {t: (m, bb, ba) for t, m, bb, ba, *_ in prices.get(SYM[K], [])}
                           for K in STRIKES_ALL}
        # Intrinsic floor + upper bound violations
        print(f"\n--- Day {day}: intrinsic/upper-bound violations (counts per strike) ---")
        print(f"{'K':<6}{'lower_mid':>11}{'lower_exec':>12}{'upper_mid':>11}{'upper_exec':>12}{'tot_ticks':>11}")
        for K in STRIKES_ALL:
            vp = voucher_prices[K]
            n_lower_mid = n_lower_exec = n_upper_mid = n_upper_exec = 0
            tot = 0
            for ts, (m, bb, ba) in vp.items():
                if ts not in und_prices:
                    continue
                spot, u_bb, u_ba = und_prices[ts]
                lower = max(spot - K, 0.0)
                if m < lower - 1e-9:
                    n_lower_mid += 1
                if ba and ba < lower - 1e-9:  # ask below intrinsic = executable arb (buy)
                    n_lower_exec += 1
                if m > spot + 1e-9:
                    n_upper_mid += 1
                if bb and bb > spot + 1e-9:  # bid above spot = executable (sell)
                    n_upper_exec += 1
                tot += 1
            print(f"{K:<6}{n_lower_mid:>11}{n_lower_exec:>12}{n_upper_mid:>11}{n_upper_exec:>12}{tot:>11}")
        # Butterfly and call-spread
        print(f"\n--- Day {day}: butterfly + call-spread arb (triples/pairs in mid/exec) ---")
        consecutive_triples = []
        # 5000-5100-5200, 5100-5200-5300, 5200-5300-5400, 5300-5400-5500
        ks_small_gap = [5000, 5100, 5200, 5300, 5400, 5500]
        for i in range(len(ks_small_gap) - 2):
            consecutive_triples.append((ks_small_gap[i], ks_small_gap[i + 1], ks_small_gap[i + 2]))
        # Also wider: 4500-5000-5500, 5000-5500-6000
        consecutive_triples.extend([(4500, 5000, 5500), (5000, 5500, 6000)])
        print(f"{'triple':<24}{'butterfly_mid<0':>18}{'butterfly_exec<0':>18}")
        for (K1, K2, K3) in consecutive_triples:
            vp1 = voucher_prices[K1]; vp2 = voucher_prices[K2]; vp3 = voucher_prices[K3]
            mid_viol = exec_viol = 0
            common_ts = set(vp1.keys()) & set(vp2.keys()) & set(vp3.keys())
            for ts in common_ts:
                m1, bb1, ba1 = vp1[ts]; m2, bb2, ba2 = vp2[ts]; m3, bb3, ba3 = vp3[ts]
                # Butterfly (mid): 2*m2 - m1 - m3 should be <= 0 (convex)
                if m1 + m3 - 2 * m2 < 0:
                    mid_viol += 1
                # Executable: buy K1@ask, sell 2*K2@bid, buy K3@ask → profit = -ba1 + 2*bb2 - ba3
                if ba1 and bb2 and ba3 and (2 * bb2 - ba1 - ba3) > 0:
                    exec_viol += 1
            print(f"{str((K1, K2, K3)):<24}{mid_viol:>18}{exec_viol:>18}")
        # Call-spread (C(K1) - C(K2)) must be in [0, K2-K1]
        print(f"\n{'pair':<20}{'negative_spread':>18}{'exceeds_cap':>15}{'exec_neg':>11}{'exec_exceeds':>14}")
        test_pairs = [(4500, 5000), (5000, 5100), (5100, 5200), (5200, 5300), (5300, 5400), (5400, 5500)]
        for (K1, K2) in test_pairs:
            vp1 = voucher_prices[K1]; vp2 = voucher_prices[K2]
            neg_mid = cap_mid = neg_exec = cap_exec = 0
            common_ts = set(vp1.keys()) & set(vp2.keys())
            for ts in common_ts:
                m1, bb1, ba1 = vp1[ts]; m2, bb2, ba2 = vp2[ts]
                spread_mid = m1 - m2
                if spread_mid < 0: neg_mid += 1
                if spread_mid > K2 - K1: cap_mid += 1
                # Executable negative: ask1 - bid2 < 0 means buying K1 + selling K2 gives positive cash
                if ba1 and bb2 and ba1 - bb2 < 0: neg_exec += 1
                # Executable exceeds: bid1 - ask2 > K2-K1 means selling K1 + buying K2 locks arb
                if bb1 and ba2 and bb1 - ba2 > K2 - K1: cap_exec += 1
            print(f"{str((K1, K2)):<20}{neg_mid:>18}{cap_mid:>15}{neg_exec:>11}{cap_exec:>14}")


# ────────────────────────── Part 5: cross-product ──────────────────────────

def part5_cross(all_data):
    print("\n=== PART 5: Cross-Product Relationships ===\n")
    for day in DAYS:
        prices, _ = all_data[day]
        und = prices.get(UNDERLYING, [])
        hp = prices.get("HYDROGEL_PACK", [])
        if not und or not hp:
            continue
        und_mid = {t: m for t, m, *_ in und}
        hp_mid = {t: m for t, m, *_ in hp}
        common = sorted(set(und_mid) & set(hp_mid))
        u_ret = [und_mid[common[i+1]] - und_mid[common[i]] for i in range(len(common)-1)]
        h_ret = [hp_mid[common[i+1]] - hp_mid[common[i]] for i in range(len(common)-1)]
        if len(u_ret) > 20:
            # Pearson correlation
            mu_u, mu_h = mean(u_ret), mean(h_ret)
            num = sum((u_ret[i] - mu_u) * (h_ret[i] - mu_h) for i in range(len(u_ret)))
            denu = math.sqrt(sum((u - mu_u) ** 2 for u in u_ret))
            denh = math.sqrt(sum((h - mu_h) ** 2 for h in h_ret))
            corr = num / (denu * denh) if denu * denh > 0 else 0
            print(f"Day {day}: HYDROGEL vs VELVETFRUIT returns corr = {corr:.4f} (n={len(u_ret)})")
        # Lead-lag: voucher return predicted by underlying 1-lag return
        print(f"\nDay {day}: lead-lag regression  ret_voucher_t ~ ret_underlying_{{t-1}}")
        print(f"{'strike':<8}{'β':>10}{'t-stat':>10}{'R²':>10}{'n':>6}")
        for K in STRIKES_IV + STRIKES_DEEP_ITM:
            vp = prices.get(SYM[K], [])
            v_mid = {t: m for t, m, *_ in vp}
            ts_sorted = sorted(set(und_mid) & set(v_mid))
            if len(ts_sorted) < 50:
                continue
            u_rets = [und_mid[ts_sorted[i]] - und_mid[ts_sorted[i-1]] for i in range(1, len(ts_sorted))]
            v_rets = [v_mid[ts_sorted[i]] - v_mid[ts_sorted[i-1]] for i in range(1, len(ts_sorted))]
            # Predictor = lagged u_ret, response = current v_ret
            xs = u_rets[:-1]
            ys = v_rets[1:]
            fit = fit_linear(xs, ys)
            if fit:
                a, b, se, r2 = fit
                t = b / se if se and not math.isnan(se) and se > 0 else 0
                print(f"{K:<8}{b:>10.4f}{t:>10.2f}{r2:>10.4f}{len(xs):>6}")
        # OBI predictiveness
        print(f"\nDay {day}: OBI predictiveness  ret_voucher_{{t+1}} ~ OBI_underlying_t")
        und_obi = {t: (bv - av) / (bv + av) if (bv + av) > 0 else 0
                   for t, m, bb, ba, bv, av, sp in und}
        print(f"{'strike':<8}{'β':>12}{'t-stat':>10}{'R²':>10}{'n':>6}")
        for K in STRIKES_IV + STRIKES_DEEP_ITM:
            vp = prices.get(SYM[K], [])
            v_mid = {t: m for t, m, *_ in vp}
            ts_sorted = sorted(set(und_obi) & set(v_mid))
            if len(ts_sorted) < 50:
                continue
            obi_series = [und_obi[ts_sorted[i]] for i in range(len(ts_sorted))]
            v_rets = [v_mid[ts_sorted[i+1]] - v_mid[ts_sorted[i]] for i in range(len(ts_sorted)-1)]
            xs = obi_series[:-1]
            ys = v_rets
            fit = fit_linear(xs, ys)
            if fit:
                a, b, se, r2 = fit
                t = b / se if se and not math.isnan(se) and se > 0 else 0
                print(f"{K:<8}{b:>12.4f}{t:>10.2f}{r2:>10.4f}{len(xs):>6}")


# ────────────────────────── Part 6: taker flow ──────────────────────────

def part6_taker(all_data):
    print("\n=== PART 6: Taker Flow ===\n")
    for day in DAYS:
        prices, trades = all_data[day]
        print(f"\n--- Day {day} ---")
        print(f"{'product':<22}{'n_trades':>10}{'arr_rate':>10}{'avg_size':>10}"
              f"{'|avg_signed|':>14}{'CoV_iat':>10}")
        und_mids = {t: m for t, m, *_ in prices.get(UNDERLYING, [])}
        for prod in ["HYDROGEL_PACK", UNDERLYING] + [SYM[k] for k in STRIKES_ALL]:
            tlist = trades.get(prod, [])
            if not tlist:
                print(f"{prod:<22}{0:>10}")
                continue
            # Sign trades vs own product mids
            prod_mids = {t: m for t, m, *_ in prices.get(prod, [])}
            signed = []
            for ts, p, q in tlist:
                mid = prod_mids.get(ts)
                if mid is None:
                    continue
                sign = 1 if p > mid else (-1 if p < mid else 0)
                signed.append((ts, sign * q))
            n = len(tlist)
            arr = n / 10000
            avg_size = mean([q for _, _, q in tlist])
            avg_signed = mean([s for _, s in signed]) if signed else 0
            # Inter-arrival CoV
            ts_list = sorted(ts for ts, _, _ in tlist)
            if len(ts_list) > 1:
                iat = [ts_list[i+1] - ts_list[i] for i in range(len(ts_list)-1)]
                mu_iat = mean(iat)
                cov = pstdev(iat) / mu_iat if mu_iat > 0 else 0
            else:
                cov = float("nan")
            print(f"{prod:<22}{n:>10}{arr:>10.3f}{avg_size:>10.2f}"
                  f"{abs(avg_signed):>14.3f}{cov:>10.2f}")


# ────────────────────────── Part 7: regimes ──────────────────────────

def part7_regimes(all_data):
    print("\n=== PART 7: Regime Detection (HYDROGEL_PACK focus) ===\n")
    print(f"{'day':<4}{'q25_σ100':>12}{'median_σ100':>14}{'q75_σ100':>12}{'max_σ100':>12}")
    for day in DAYS:
        prices, _ = all_data[day]
        hp = sorted(prices.get("HYDROGEL_PACK", []))
        if len(hp) < 100:
            continue
        mids = [d[1] for d in hp]
        roll = []
        for i in range(99, len(mids)):
            window = mids[i-99:i+1]
            mu = sum(window) / 100
            var = sum((x - mu) ** 2 for x in window) / 100
            roll.append(math.sqrt(var))
        roll_sorted = sorted(roll)
        q25 = roll_sorted[len(roll_sorted) // 4]
        med = roll_sorted[len(roll_sorted) // 2]
        q75 = roll_sorted[3 * len(roll_sorted) // 4]
        print(f"{day:<4}{q25:>12.2f}{med:>14.2f}{q75:>12.2f}{max(roll):>12.2f}")

    # Day 0 vs Day 2 HYDROGEL intraday breakdown
    print("\nHYDROGEL_PACK intraday quartiles (mid):")
    for day in [0, 1, 2]:
        hp = sorted(all_data[day][0].get("HYDROGEL_PACK", []))
        if not hp: continue
        n = len(hp)
        q = [hp[min(n * i // 4, n - 1)] for i in range(5)]
        print(f"  Day {day}: Q0={q[0][1]:.0f} Q1={q[1][1]:.0f} Q2={q[2][1]:.0f} "
              f"Q3={q[3][1]:.0f} Q4={q[4][1]:.0f}  (range {q[4][1]-q[0][1]:.0f})")

    # IV term structure: does mean IV decay as TTE shrinks?
    print("\nIV term structure across days (mean IV per strike):")
    iv_series = compute_iv_series(all_data)
    for K in STRIKES_IV:
        vals = []
        for day in DAYS:
            s = iv_series.get((day, K), [])
            if s:
                vals.append(f"d{day}(T={TTE_DAYS[day]}d)={mean([x[1] for x in s]):.4f}")
            else:
                vals.append(f"d{day}=none")
        print(f"  K={K}: {' | '.join(vals)}")


# ────────────────────────── Part 8: deep ITM TV ──────────────────────────

def part8_deep_itm(all_data):
    print("\n=== PART 8: Deep ITM Time Value ===\n")
    print(f"{'day':<4}{'K':<6}{'n':>6}{'TV_mean':>10}{'TV_std':>10}"
          f"{'TV_min':>10}{'TV_max':>10}{'AR1':>10}{'TV_neg':>9}{'half_life':>12}")
    for day in DAYS:
        prices, _ = all_data[day]
        und_mid = {t: m for t, m, *_ in prices.get(UNDERLYING, [])}
        for K in STRIKES_DEEP_ITM:
            vp = prices.get(SYM[K], [])
            tv = []
            for ts, m, *_ in vp:
                if ts not in und_mid:
                    continue
                spot = und_mid[ts]
                intr = max(spot - K, 0.0)
                tv.append(m - intr)
            if not tv:
                continue
            tv_neg = sum(1 for x in tv if x < 0)
            ar1 = autocorr(tv)
            mu_tv = mean(tv)
            xs = [tv[i] - mu_tv for i in range(len(tv) - 1)]
            ys = [tv[i+1] - tv[i] for i in range(len(tv) - 1)]
            fit = fit_linear(xs, ys)
            if fit and fit[1] < 0 and fit[1] > -1 + 1e-6:
                try:
                    hl = -math.log(2) / math.log(1 + fit[1])
                    hl_str = f"{hl:.0f}" if 0 < hl < 1e5 else ">inf"
                except (ValueError, ZeroDivisionError):
                    hl_str = "no MR"
            else:
                hl_str = "no MR"
            print(f"{day:<4}{K:<6}{len(tv):>6}{mu_tv:>10.2f}{pstdev(tv):>10.2f}"
                  f"{min(tv):>10.2f}{max(tv):>10.2f}{ar1:>10.4f}{tv_neg:>9}{hl_str:>12}")


# ────────────────────────── main ──────────────────────────

def main():
    print("R3 EXHAUSTIVE EDA — IMC Prosperity 4 Round 3")
    print("=" * 100)
    all_data = {}
    for day in DAYS:
        all_data[day] = load_day(day)
        print(f"Loaded day {day}: {sum(len(v) for v in all_data[day][0].values())} price rows, "
              f"{sum(len(v) for v in all_data[day][1].values())} trades")
    iv_series = compute_iv_series(all_data)

    part1_dynamics(all_data)
    part2_iv(iv_series)
    part3_smile(all_data, iv_series)
    part4_arb_bounds(all_data)
    part5_cross(all_data)
    part6_taker(all_data)
    part7_regimes(all_data)
    part8_deep_itm(all_data)

    print("\n" + "=" * 100)
    print("EDA COMPLETE")


if __name__ == "__main__":
    main()
