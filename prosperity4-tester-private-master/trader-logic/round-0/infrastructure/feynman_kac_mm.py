"""
feynman_kac_mm.py — Optimal Market Making via Feynman-Kac / HJB PDE

Models TOMATOES mid price as Ornstein-Uhlenbeck:
    dX = kappa * (mu - X) * dt + sigma * dW

Solves the HJB equation backward in time via finite differences.
Outputs a lookup table for the strategy: (time_bucket, position) -> (bid_offset, ask_offset)

Run from: c:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/
Usage: python feynman_kac_mm.py
"""

import csv
import math
import os
import json

DATA_DIR = "prosperity4bt/resources/round0"


def calibrate_ou(day):
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    mids, bids, asks, bv1s, av1s = [], [], [], [], []
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == 'TOMATOES':
                mids.append(float(r['mid_price']))
                bids.append(float(r['bid_price_1']))
                asks.append(float(r['ask_price_1']))
                bv1s.append(int(r['bid_volume_1']))
                av1s.append(int(r['ask_volume_1']))
    n = len(mids)
    dt = 1.0
    sx = sum(mids[i] for i in range(n-1))
    sy = sum(mids[i+1] for i in range(n-1))
    sxx = sum(mids[i]**2 for i in range(n-1))
    sxy = sum(mids[i]*mids[i+1] for i in range(n-1))
    nn = n - 1
    beta = (sxy - sx*sy/nn) / (sxx - sx*sx/nn)
    alpha = sy/nn - beta*sx/nn
    kappa = (1 - beta) / dt
    mu = alpha / (kappa * dt) if kappa * dt != 0 else mids[0]
    residuals = [mids[i+1] - alpha - beta*mids[i] for i in range(nn)]
    sigma = math.sqrt(sum(r**2 for r in residuals) / nn) / math.sqrt(dt)
    returns = [mids[i+1] - mids[i] for i in range(nn)]
    ret_mean = sum(returns) / len(returns)
    ret_std = math.sqrt(sum((r-ret_mean)**2 for r in returns) / len(returns))
    autocorrs = {}
    for lag in [1,2,3,5,10]:
        if n > lag + 1:
            cov = sum((returns[i]-ret_mean)*(returns[i+lag]-ret_mean) for i in range(len(returns)-lag)) / (len(returns)-lag)
            var = sum((r-ret_mean)**2 for r in returns) / len(returns)
            autocorrs[lag] = cov / var if var > 0 else 0
    half_life = math.log(2) / kappa if kappa > 0 else float('inf')
    n_trades = 0
    tf = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    if os.path.exists(tf):
        with open(tf) as f:
            for r in csv.DictReader(f, delimiter=';'):
                if r['symbol'] == 'TOMATOES': n_trades += 1
    fill_rate = n_trades / n if n > 0 else 0.04
    return {'kappa': kappa, 'mu': mu, 'sigma': sigma, 'beta': beta, 'alpha': alpha,
            'ret_mean': ret_mean, 'ret_std': ret_std, 'autocorrs': autocorrs,
            'half_life': half_life, 'n_ticks': n, 'fill_rate': fill_rate,
            'mids': mids, 'bids': bids, 'asks': asks, 'bv1s': bv1s, 'av1s': av1s}


def solve_hjb(kappa, sigma, T, q_max, gamma, fill_rate, n_time=500, n_price=81):
    dt = T / n_time
    sigma_sq = sigma**2
    y_min, y_max = -25.0, 25.0
    dy = (y_max - y_min) / (n_price - 1)
    y_grid = [y_min + j*dy for j in range(n_price)]
    q_grid = list(range(-q_max, q_max+1))
    n_q = len(q_grid)
    q_to_idx = {q: i for i, q in enumerate(q_grid)}
    cfl = max(abs(-kappa*y) for y in y_grid)*dt/dy + 0.5*sigma_sq*dt/(dy**2)
    if cfl > 0.8:
        n_time = int(n_time * cfl / 0.5) + 1
        dt = T / n_time
        print(f"  CFL fix: n_time={n_time}")
    V_next = [[0.0]*n_q for _ in range(n_price)]
    V_curr = [[0.0]*n_q for _ in range(n_price)]
    for j in range(n_price):
        for k in range(n_q):
            q = q_grid[k]
            V_next[j][k] = q * y_grid[j] - gamma * q * q
    time_samples = set(int(f*n_time) for f in [0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,0.95,0.99])
    policy = {}
    for t_idx in range(n_time-1, -1, -1):
        tau = (n_time - t_idx) * dt / T
        for j in range(n_price):
            y = y_grid[j]
            for k in range(n_q):
                q = q_grid[k]
                if j == 0 or j == n_price - 1:
                    V_curr[j][k] = V_next[j][k]; continue
                drift = -kappa * y
                Vy = (V_next[j+1][k] - V_next[j][k])/dy if drift >= 0 else (V_next[j][k] - V_next[j-1][k])/dy
                Vyy = (V_next[j+1][k] - 2*V_next[j][k] + V_next[j-1][k]) / (dy**2)
                hs = max(1.0, (gamma*sigma_sq*tau + (2.0/gamma)*math.log(1+gamma/fill_rate))/2.0) if gamma > 0 and fill_rate > 0 else 1.0
                fill_gain = 0.0
                if q+1 <= q_max:
                    ku = q_to_idx.get(q+1)
                    if ku is not None: fill_gain += fill_rate * max(0, V_next[j][ku] - V_next[j][k] + hs)
                if q-1 >= -q_max:
                    kd = q_to_idx.get(q-1)
                    if kd is not None: fill_gain += fill_rate * max(0, V_next[j][kd] - V_next[j][k] + hs)
                V_curr[j][k] = V_next[j][k] + dt * (drift*Vy + 0.5*sigma_sq*Vyy + fill_gain)
        if t_idx in time_samples:
            tf = round(t_idx/n_time, 2)
            for k, q in enumerate(q_grid):
                tv = (n_time - t_idx)*dt/T
                res = -q*gamma*sigma_sq*tv
                hs = max(1.0, (gamma*sigma_sq*tv + (2.0/gamma)*math.log(1+gamma/fill_rate))/2.0) if gamma > 0 and fill_rate > 0 else 1.0
                policy[(tf, q)] = {'res_shift': round(res,3), 'half_spread': round(hs,3), 'tau': round(tv,3)}
        V_next, V_curr = V_curr, V_next
    return V_next, policy, y_grid, q_grid


def simulate_optimal(ou, gamma_values, label=""):
    mids, bids, asks = ou['mids'], ou['bids'], ou['asks']
    bv1s, av1s = ou['bv1s'], ou['av1s']
    n = len(mids)
    sigma_sq = ou['sigma']**2
    fill_rate = ou['fill_rate']
    trade_map = {}
    for day in [-2, -1]:
        tf = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
        if os.path.exists(tf):
            with open(tf) as f:
                for r in csv.DictReader(f, delimiter=';'):
                    if r['symbol'] == 'TOMATOES':
                        ts = int(r['timestamp'])
                        trade_map.setdefault(ts, []).append({'price': float(r['price']), 'qty': int(r['quantity'])})
    print(f"\n{'='*70}")
    print(f"  SIMULATION — {label}")
    print(f"  {'gamma':>7s} | {'fills':>5s} | {'lots':>5s} | {'pos':>5s} | {'MTM_full':>9s} | {'MTM_2k':>8s} | {'edge':>7s}")
    print(f"  {'-'*7}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*9}-+-{'-'*8}-+-{'-'*7}")

    for g in gamma_values:
        results = {}
        for tick_limit, tag in [(n, "full"), (2000, "2k")]:
            pos = 0; cash = 0.0; fills = 0; lots = 0; max_pos = 80
            mp_cache = []
            for i in range(min(tick_limit, n)):
                tau = max(0.01, (n - i) / n)
                bv, av = bv1s[i], av1s[i]
                spread = asks[i] - bids[i]
                mp = bids[i] + (bv/(bv+av))*spread if (bv+av) > 0 else mids[i]
                mp_cache.append(mp)
                if len(mp_cache) > 4: mp_cache = mp_cache[-4:]
                fv = (2.208667 + 0.059694*mp_cache[0] + 0.117270*mp_cache[1] + 0.244154*mp_cache[2] + 0.578440*mp_cache[3]) if len(mp_cache) == 4 else mp
                reservation = fv - pos * g * sigma_sq * tau
                hs = max(1.0, (g*sigma_sq*tau + (2.0/g)*math.log(1+g/fill_rate))/2.0) if g > 0 else 1.0
                our_bid = round(reservation - hs)
                our_ask = round(reservation + hs)
                our_bid = min(our_bid, int(asks[i]) - 1)
                our_ask = max(our_ask, int(bids[i]) + 1)
                tb = max_pos - pos; ts_ = max_pos + pos
                actual_ts = i * 100
                if actual_ts in trade_map:
                    for t in trade_map[actual_ts]:
                        is_buy = t['price'] >= mids[i]
                        if is_buy and our_ask <= asks[i] and ts_ > 0:
                            fq = min(t['qty'], ts_); cash += fq*our_ask; pos -= fq; ts_ -= fq; fills += 1; lots += fq
                        elif not is_buy and our_bid >= bids[i] and tb > 0:
                            fq = min(t['qty'], tb); cash -= fq*our_bid; pos += fq; tb -= fq; fills += 1; lots += fq
                tv = round(fv)
                if int(asks[i]) <= tv and tb > 0:
                    q = min(tb, abs(av1s[i])); cash -= q*int(asks[i]); pos += q
                if int(bids[i]) >= tv and ts_ > 0:
                    q = min(ts_, bv1s[i]); cash += q*int(bids[i]); pos -= q
            last_mid = mids[min(tick_limit, n)-1]
            results[tag] = {'mtm': cash + pos*last_mid, 'fills': fills, 'lots': lots, 'pos': pos}
        r_f, r_2 = results["full"], results["2k"]
        edge = r_f['mtm'] / max(r_f['lots'], 1)
        print(f"  {g:7.4f} | {r_f['fills']:5d} | {r_f['lots']:5d} | {r_f['pos']:+5d} | {r_f['mtm']:+9.0f} | {r_2['mtm']:+8.0f} | {edge:+7.2f}")


def generate_constants(ou, best_gamma):
    sigma_sq = ou['sigma']**2
    fill_rate = ou['fill_rate']
    inv_penalty = best_gamma * sigma_sq
    spread_const = (2.0/best_gamma) * math.log(1 + best_gamma/fill_rate)
    print(f"\n{'#'*70}")
    print(f"#  PASTE INTO STRATEGY")
    print(f"{'#'*70}")
    print(f"""
# Feynman-Kac / A-S optimal constants
FK_GAMMA = {best_gamma}
FK_SIGMA_SQ = {sigma_sq:.6f}
FK_INV_PENALTY = {inv_penalty:.6f}   # gamma * sigma^2
FK_SPREAD_CONST = {spread_const:.6f}  # (2/gamma) * ln(1 + gamma/k)
FK_KAPPA = {ou['kappa']:.6f}
FK_HALF_LIFE = {ou['half_life']:.1f}

# In run():
# tau = max(0.01, (T_MAX - timestamp) / T_MAX)
# reservation = fair_value - position * FK_INV_PENALTY * tau
# half_spread = max(1, round((FK_INV_PENALTY * tau + FK_SPREAD_CONST) / 2))
# bid = round(reservation) - half_spread
# ask = round(reservation) + half_spread
""")
    print("# Position shift table (reservation - FV):")
    print("# pos  | tau=1.0  | tau=0.5  | tau=0.2  | tau=0.1")
    for p in [-80,-40,-20,-10,0,10,20,40,80]:
        s = [f"{-p*inv_penalty*t:+8.2f}" for t in [1.0,0.5,0.2,0.1]]
        print(f"# {p:+4d}  | {'  | '.join(s)}")
    print("\n# Half-spread table:")
    print("# tau   | half_spread")
    for tau in [1.0,0.8,0.5,0.3,0.2,0.1,0.05]:
        hs = max(1.0, (inv_penalty*tau + spread_const)/2.0)
        print(f"# {tau:.2f}  | {hs:.2f}")


def main():
    print("="*70)
    print("  FEYNMAN-KAC OPTIMAL MARKET MAKING")
    print("="*70)
    params = {}
    for day in [-2, -1]:
        p = calibrate_ou(day)
        params[day] = p
        print(f"\n  Day {day}: kappa={p['kappa']:.6f}, sigma={p['sigma']:.6f}, "
              f"half_life={p['half_life']:.1f}, fill_rate={p['fill_rate']:.4f}")
        print(f"    autocorr: {p['autocorrs']}")
        print(f"    beta(AR1)={p['beta']:.6f}")
    # Stability
    p1, p2 = params[-2], params[-1]
    print(f"\n  Stability: kappa_diff={abs(p1['kappa']-p2['kappa']):.6f}, "
          f"sigma_diff={abs(p1['sigma']-p2['sigma']):.6f}, "
          f"AC1_diff={abs(p1['autocorrs'][1]-p2['autocorrs'][1]):.4f}")

    # Solve HJB
    ou = params[-1]
    print(f"\n  Solving HJB (kappa={ou['kappa']:.4f}, sigma={ou['sigma']:.4f})...")
    V, policy, yg, qg = solve_hjb(ou['kappa'], ou['sigma'], 1.0, 80, 0.01, ou['fill_rate'])
    print(f"  Policy samples:")
    for tf in [0.0, 0.5, 0.9]:
        for q in [-40, 0, 40]:
            k = (round(tf,2), q)
            if k in policy:
                print(f"    t={tf:.1f} q={q:+3d}: {policy[k]}")

    # Simulate
    gammas = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]
    for day in [-1, -2]:
        simulate_optimal(params[day], gammas, f"Day {day}")

    # Generate constants (use 0.01 as default, adjust from sim output)
    generate_constants(ou, 0.01)
    print("\nDone.")


if __name__ == "__main__":
    main()
