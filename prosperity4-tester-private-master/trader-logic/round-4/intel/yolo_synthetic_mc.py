"""
yolo_synthetic_mc.py — Bootstrap-based Monte Carlo for YOLO regime gate sanity check.

Methodology:
  1. Pull per-100ts VFE returns from days 1/2/3 of R4 CSVs (3 × 10000 returns each).
  2. Bootstrap returns to synthesize 50 day-4 paths (each path = 10,000 ticks).
  3. For each path:
     a. Decide YOLO gate at ts=3000 using same rule (drift_3k <= -1.5 from open).
     b. Compute analytical PnL for 4 strategies: full-yolo (-300×8 + -200 VFE),
        half-yolo deep ITM only (-300 × {VEV_4000,4500,5100,5200}),
        small-yolo (-100 across 8 vouchers + -100 VFE), no-yolo.
  4. Voucher prices simulated from Black-76 reusing fixed sigma per strike (calibrated to ts=3000 of each real day).

Outputs:
  - Distribution mean / SD / P5 / P50 / P95 per strategy across 50 paths
  - Sharpe = mean / SD ; CVaR_5 = mean of bottom-5%
  - Decision rule: max Sharpe with hard CVaR_5 floor

Note: Voucher closes derived from the VFE close via Black-76 with simulated 0% interest;
this captures *delta* exposure correctly which is the dominant YOLO P&L driver.
"""
import numpy as np
import pandas as pd
from math import log, sqrt, exp, erf
import json

np.random.seed(42)

ROOT = r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"

VOUCHERS = ["VEV_4000","VEV_4500","VEV_5000","VEV_5100","VEV_5200","VEV_5300","VEV_5400","VEV_5500"]
STRIKES  = {"VEV_4000":4000,"VEV_4500":4500,"VEV_5000":5000,"VEV_5100":5100,
            "VEV_5200":5200,"VEV_5300":5300,"VEV_5400":5400,"VEV_5500":5500}

# TTE in trading days at start of day-4 (= round-4 day-4 = R4 final day = 4 trading days remaining)
# After 3000 ticks (3% of day) we have ~3.97 days left
DAY_TTE_START = 4.0  # day-4 first day of trading
TICKS_PER_DAY = 10000

def cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))

def bs_call(S, K, T, sigma):
    """Black-Scholes call, r=0."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (log(S/K) + 0.5*sigma*sigma*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S*cdf(d1) - K*cdf(d2)

# ---------- 1. Calibrate per-strike IVs from real day-2 data ts=3000 ----------
# Use day-2 (mid-regime) for IV calibration; assumes vol regime persistent
df2 = pd.read_csv(f"{ROOT}/prices_round_4_day_2.csv", sep=";")
S0 = df2[(df2['product']=='VELVETFRUIT_EXTRACT') & (df2.timestamp==3000)].iloc[0]
S0_mid = (S0.bid_price_1 + S0.ask_price_1) / 2.0

# Calibrate sigma per strike
def implied_vol(S, K, T, market_price):
    if market_price < max(S-K, 0): return 0.20
    lo, hi = 0.001, 5.0
    for _ in range(50):
        mid = 0.5*(lo+hi)
        v = bs_call(S, K, T, mid)
        if v < market_price: lo = mid
        else: hi = mid
    return 0.5*(lo+hi)

T0 = max(DAY_TTE_START - 3000/1_000_000, 0.01) / 250.0  # match r4_final.py convention
SIGMAS = {}
for sym in VOUCHERS:
    K = STRIKES[sym]
    rec = df2[(df2['product']==sym) & (df2.timestamp==3000)]
    if len(rec)==0: continue
    pmid = (rec.iloc[0].bid_price_1 + rec.iloc[0].ask_price_1)/2.0
    iv = implied_vol(S0_mid, K, T0, pmid)
    # Floor for deep ITM where solver collapses (intrinsic-dominated)
    if iv < 0.05: iv = 0.245   # ATM-region average
    SIGMAS[sym] = iv
    print(f"Calib {sym}: K={K} mkt={pmid:.1f} IV={SIGMAS[sym]:.3f}")

# ---------- 2. Build pooled returns ----------
# Per-day return arrays for regime-stratified analysis
per_day_rets = {}
for d in [1,2,3]:
    df = pd.read_csv(f"{ROOT}/prices_round_4_day_{d}.csv", sep=";")
    vfe = df[df['product']=='VELVETFRUIT_EXTRACT'].sort_values('timestamp').reset_index(drop=True)
    mid = (vfe.bid_price_1 + vfe.ask_price_1)/2.0
    per_day_rets[d] = mid.diff().dropna().values
all_rets = np.concatenate(list(per_day_rets.values()))
print(f"\nReturns pool: N={len(all_rets)}, mean={all_rets.mean():.4f}, std={all_rets.std():.3f}")
print(f"  Per-day means: D1={per_day_rets[1].mean():.4f}, D2={per_day_rets[2].mean():.4f}, D3={per_day_rets[3].mean():.4f}")
print(f"  Per-day SDs:   D1={per_day_rets[1].std():.3f}, D2={per_day_rets[2].std():.3f}, D3={per_day_rets[3].std():.3f}")

# ---------- 3. Generate synthetic paths ----------
# We test 3 priors:
#   (A) "day-3 repeats" prior  (P=1.00, returns from D3)
#   (B) "uniform over days"   prior  (P=0.33 each, pooled rets)
#   (C) "day-1/2 like"        prior  (P=0.50 each, no D3) — IMC said "no big regime change"
#                                                        + days 1/2 are both bullish
N_PATHS = 50
N_TICKS = 10000
S_OPEN = 5295.5  # day-3 actual open

PRIORS = {
    "A_day3_repeats": per_day_rets[3],
    "B_uniform_pooled": all_rets,
    "C_no_d3_bullish": np.concatenate([per_day_rets[1], per_day_rets[2]]),
}

def gen_paths(rets_pool, n=N_PATHS, T=N_TICKS, S0=S_OPEN, seed=42):
    rng = np.random.default_rng(seed)
    P = np.zeros((n, T+1))
    P[:,0] = S0
    for i in range(n):
        rets = rng.choice(rets_pool, T, replace=True)
        P[i, 1:] = S0 + np.cumsum(rets)
    return P

# ---------- 4. YOLO gate + PnL per path ----------
TICK_3K = 30  # ts=3000 → tick index 30 (step 100)
T_YOLO_ENTRY = max(DAY_TTE_START - 3000/1_000_000, 0.01) / 250.0
T_YOLO_EXIT  = max(DAY_TTE_START - 999900/1_000_000, 0.01) / 250.0

YOLO_VOUCHER_QTY = 300
YOLO_VFE_QTY     = 200

def yolo_pnl(path, voucher_qtys, vfe_qty, gate_fires):
    """Compute YOLO PnL for one path given strategy quantities. gate_fires=False -> 0."""
    if not gate_fires:
        return 0.0
    S_entry = path[TICK_3K]
    S_exit  = path[-1]
    pnl = 0.0
    for sym in VOUCHERS:
        K = STRIKES[sym]
        sig = SIGMAS.get(sym, 0.20)
        # Voucher mid prices via BS
        p_entry = bs_call(S_entry, K, T_YOLO_ENTRY, sig)
        p_exit  = bs_call(S_exit, K, T_YOLO_EXIT, sig)
        # Short: PnL = qty * (entry - exit)  [qty positive = size of short]
        q = voucher_qtys.get(sym, 0)
        pnl += q * (p_entry - p_exit)
    # VFE
    pnl += vfe_qty * (S_entry - S_exit)
    return pnl

# Strategy specs
strategies = {
    "no_yolo": (dict(), 0),
    "full_yolo": ({s: 300 for s in VOUCHERS}, 200),
    "half_yolo_small": ({s: 100 for s in VOUCHERS}, 100),
    "deep_itm_only": ({s: 300 for s in ["VEV_4000","VEV_4500","VEV_5100","VEV_5200"]}, 0),
    "deep_itm_with_vfe": ({s: 300 for s in ["VEV_4000","VEV_4500","VEV_5100","VEV_5200"]}, 200),
}

# Run all 3 priors
all_metrics = {}
for prior_name, rets_pool in PRIORS.items():
    paths = gen_paths(rets_pool)
    results = {name: [] for name in strategies}
    gate_fires_count = 0
    for i in range(N_PATHS):
        path = paths[i]
        drift_3k = path[TICK_3K] - path[0]
        fires = drift_3k <= -1.5
        if fires: gate_fires_count += 1
        for name, (vqs, vfeq) in strategies.items():
            pnl = yolo_pnl(path, vqs, vfeq, fires)
            results[name].append(pnl)

    print(f"\n=== Prior: {prior_name} ===  Gate fires {gate_fires_count}/{N_PATHS} = {100.0*gate_fires_count/N_PATHS:.0f}%")
    print(f"{'Strategy':<20} {'Mean':>10} {'SD':>10} {'P5':>10} {'P50':>10} {'P95':>10} {'Sharpe':>8} {'CVaR5':>10}")
    print("-"*98)
    metrics = {}
    for name in strategies:
        arr = np.array(results[name])
        mean = arr.mean(); sd = arr.std(); p5,p50,p95 = np.percentile(arr,[5,50,95])
        sharpe = mean / sd if sd > 0 else 0.0
        cutoff = max(1, int(N_PATHS * 0.05))
        cvar5 = np.sort(arr)[:cutoff].mean()
        print(f"{name:<20} {mean:>10.0f} {sd:>10.0f} {p5:>10.0f} {p50:>10.0f} {p95:>10.0f} {sharpe:>8.3f} {cvar5:>10.0f}")
        metrics[name] = dict(mean=float(mean), sd=float(sd), p5=float(p5), p50=float(p50), p95=float(p95), sharpe=float(sharpe), cvar5=float(cvar5))
    all_metrics[prior_name] = dict(gate_fires_pct=100.0*gate_fires_count/N_PATHS, metrics=metrics)

# Save all
with open("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/yolo_mc_metrics.json","w") as f:
    json.dump({
        "n_paths": N_PATHS,
        "priors": all_metrics,
        "calibrated_sigmas": SIGMAS,
    }, f, indent=2)

print("\nSaved -> intel/yolo_mc_metrics.json")
