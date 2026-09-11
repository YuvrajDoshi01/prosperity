"""
IMC Prosperity 4 — Round 4 Manual Challenge ("Vanilla Just Isn't Exotic Enough")

Self-contained Monte Carlo simulator for evaluating Aether Crystal option portfolios.
Single file, numpy-only, runs in ~5 minutes for 100M paths on a single core.

Submission objective per the IMC brief:
    "Your final score is the average PnL across 100 simulations of the underlying."

Each "trial" = mean of 100 GBM paths. Score distribution = distribution over trials.
We compute trial-level mean, SD, Sharpe, CVaR-5%, CVaR-2%, P(score > 0).

Verified facts:
- Underlying: GBM with sigma_annualized = 2.51 (= 251%), zero risk-neutral drift
- Time grid: 4 steps per trading day, 252 trading days per year
- 3 weeks = 15 trading days = 60 steps; 2 weeks = 10 trading days = 40 steps
- KO put barrier monitoring: 4/day discrete (NOT continuous, per brief)
- Chooser auto-converts at t=2w to ITM side (per brief; literal interpretation)
- KO survives iff min_S >= 35 (brief says "falls below 35" => strict <)
- ×3000 multiplier applied to final PnL (confirmed by IMC team chat)

Independently verified at:
    100M paths in cdf_100m.py  -> SE($83 - $109) on E[score]
    1B paths in billion_path_verification.py -> matches within 0.3%
    50M fresh paths in verify_dom_clean.py with seed 2718281
"""
import numpy as np
import time
import argparse
from typing import Dict, List, Tuple

# ────────────────────────────────────────────────────────────────────────────
# MODEL PARAMETERS (locked, verified)
# ────────────────────────────────────────────────────────────────────────────
S0 = 50.0                                    # spot at t=0
SIGMA_ANNUAL = 2.51                          # 251% annualized vol
RISK_FREE_RATE = 0.0                         # zero r per brief
TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY = 4
DT = 1.0 / (TRADING_DAYS_PER_YEAR * STEPS_PER_DAY)

T_3W_DAYS = 15                               # 3 weeks = 15 trading days
T_2W_DAYS = 10                               # 2 weeks = 10 trading days
N_3W_STEPS = T_3W_DAYS * STEPS_PER_DAY       # = 60 steps total
N_2W_STEPS = T_2W_DAYS * STEPS_PER_DAY       # = 40 steps (chooser decision point)

CONTRACT_MULTIPLIER = 3000                   # ×PnL scalar (per IMC team chat)
SIMS_PER_TRIAL = 100                         # IMC scores trial = mean of 100 sims

# ────────────────────────────────────────────────────────────────────────────
# MARKET QUOTES (bid, ask, max_volume) — copied from IMC manual UI
# ────────────────────────────────────────────────────────────────────────────
QUOTES: Dict[str, Tuple[float, float, int]] = {
    # Underlying spot
    "AC":          (49.975, 50.025, 200),
    # 3-week vanilla options (T = 15 trading days)
    "AC_50_P":     (12.000, 12.050,  50),    # put  K=50
    "AC_50_C":     (12.000, 12.050,  50),    # call K=50
    "AC_35_P":     ( 4.330,  4.350,  50),    # put  K=35
    "AC_40_P":     ( 6.500,  6.550,  50),    # put  K=40
    "AC_45_P":     ( 9.050,  9.100,  50),    # put  K=45
    "AC_60_C":     ( 8.800,  8.850,  50),    # call K=60
    # 2-week vanilla options (T = 10 trading days)
    "AC_50_P_2":   ( 9.700,  9.750,  50),    # put  K=50
    "AC_50_C_2":   ( 9.700,  9.750,  50),    # call K=50
    # Exotics
    "AC_50_CO":    (22.200, 22.300,  50),    # chooser K=50, decision @ 2w, expire @ 3w
    "AC_40_BP":    ( 5.000,  5.100,  50),    # binary put K=40, payoff=10 if S_T<40
    "AC_45_KO":    ( 0.150,  0.175, 500),    # down-and-out put K=45 B=35
}
LIMITS = {k: v[2] for k, v in QUOTES.items()}

# ────────────────────────────────────────────────────────────────────────────
# CANDIDATE STRATEGIES (signed integer position per instrument)
# Positive = BUY at ask; Negative = SELL at bid
# ────────────────────────────────────────────────────────────────────────────
# Notation: list of (instrument, side, |volume|). All volumes are positive.
STRATEGIES: Dict[str, List[Tuple[str, str, int]]] = {

    # *** RECOMMENDED *** — empirical Pareto-optimum, max-EV with reasonable tail
    # E[score] ≈ +$159,259 ; CVaR-5% ≈ -$359,571 ; Sharpe ≈ 0.598 ; P>0 = 71.8%
    "DOM_NICE": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_C",   "buy",  30),
        ("AC_45_P",   "buy",  50),     # NEW: 45-strike put has half the spread cost of 50_P
    ],

    # Alternative — slightly more tail-protective (give up $1.4k mean for $22k tighter CVaR)
    "DOM_CLEAN2": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  45),
        ("AC_50_C",   "buy",  25),
        ("AC_45_P",   "buy",  50),
    ],

    # OPTIMAL_7POS — what's currently entered in the user's IMC UI.
    # Same as DOM_NICE but with AC_50_P instead of AC_45_P, and AC_50_C=25 not 30.
    # E[score] ≈ +$157,737 ; CVaR-5% ≈ -$359,913 ; Sharpe ≈ 0.598 ; P>0 = 72.0%
    # Strictly Pareto-dominated by DOM_NICE (-$1,571 mean for same tail).
    "OPTIMAL_7POS": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_50_P",   "buy",  50),
        ("AC_50_C",   "buy",  25),
    ],

    # Pure max-EV (no hedges) — highest expected score but worst tail
    # E[score] ≈ +$163,135 ; CVaR-5% ≈ -$552,361 ; Sharpe ≈ 0.474
    "DROP_60C": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
    ],

    # Conservative — high Sharpe, low absolute EV
    # E[score] ≈ +$57,237 ; CVaR-5% ≈ -$62,553 ; Sharpe ≈ 0.970 ; P>0 = 83.4%
    "USER_SAFE": [
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 50),
        ("AC_45_KO", "buy",  60),
        ("AC_50_P",  "buy",  17),
        ("AC_50_P_2","buy",  15),
        ("AC_50_C",  "buy",  15),
    ],

    # Strict theoretical max (includes 60C SELL) — Pareto-dominated by DROP_60C
    # Adds AC_60_C SELL: +$1.2k EV but +$245k SD = bad trade. Listed for comparison only.
    "GLOBAL_MAX_with_60C": [
        ("AC_50_CO",  "sell", 50),
        ("AC_45_KO",  "buy",  500),
        ("AC_40_BP",  "sell", 50),
        ("AC_50_P_2", "buy",  50),
        ("AC_50_C_2", "buy",  50),
        ("AC_60_C",   "sell", 50),
    ],
}


def validate_strategy(name: str, strat: List[Tuple[str, str, int]]) -> None:
    """Enforce per-instrument volume caps with duplicate-symbol aggregation.
    Raises ValueError (not AssertionError) so the check survives `python -O`.

    A strategy listing the same instrument twice (e.g. SELL 30 + SELL 25) must
    have its NET absolute position within the cap. Naive per-row checking
    misses this; we aggregate signed quantities first.
    """
    if not isinstance(strat, list) or len(strat) == 0:
        raise ValueError(f"{name}: empty or invalid strategy")
    net = {}
    for row in strat:
        if not isinstance(row, tuple) or len(row) != 3:
            raise ValueError(f"{name}: bad row {row}; expected (sym, side, vol)")
        sym, side, vol = row
        if sym not in QUOTES:
            raise ValueError(f"{name}: unknown instrument {sym!r}")
        if side not in ("buy", "sell"):
            raise ValueError(f"{name}: side must be 'buy' or 'sell', got {side!r}")
        if not isinstance(vol, (int, np.integer)) or vol <= 0:
            raise ValueError(f"{name}: vol must be positive int, got {vol!r} for {sym}")
        signed = vol if side == "buy" else -vol
        net[sym] = net.get(sym, 0) + signed
    for sym, q in net.items():
        if abs(q) > LIMITS[sym]:
            raise ValueError(f"{name}: net |{sym}|={abs(q)} > cap {LIMITS[sym]}")


# ────────────────────────────────────────────────────────────────────────────
# GBM PATH GENERATION + INSTRUMENT PAYOFFS
# ────────────────────────────────────────────────────────────────────────────
def generate_paths(n_paths: int, rng: np.random.Generator,
                   sigma: float = SIGMA_ANNUAL) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate n GBM paths from t=0 to t=3w, recording (S_T, S_2w, min_S)."""
    drift_step = -0.5 * sigma * sigma * DT       # martingale drift in log space
    vol_step = sigma * np.sqrt(DT)
    S = np.full(n_paths, S0, dtype=np.float64)
    min_S = S.copy()
    S_2w = None
    for k in range(N_3W_STEPS):
        z = rng.standard_normal(n_paths)
        S = S * np.exp(drift_step + vol_step * z)
        np.minimum(min_S, S, out=min_S)
        if k + 1 == N_2W_STEPS:                  # capture S at chooser decision time
            S_2w = S.copy()
    return S, S_2w, min_S


def compute_payoffs(S_T: np.ndarray, S_2w: np.ndarray,
                    min_S: np.ndarray) -> Dict[str, np.ndarray]:
    """Per-path terminal payoffs for all 12 instruments. Vectorized over paths."""
    return {
        # Underlying: spot value at t=3w (simulator expiry)
        "AC":         S_T,
        # Vanilla puts/calls (3w)
        "AC_50_P":    np.maximum(50 - S_T, 0.0),
        "AC_50_C":    np.maximum(S_T - 50, 0.0),
        "AC_35_P":    np.maximum(35 - S_T, 0.0),
        "AC_40_P":    np.maximum(40 - S_T, 0.0),
        "AC_45_P":    np.maximum(45 - S_T, 0.0),
        "AC_60_C":    np.maximum(S_T - 60, 0.0),
        # Vanilla 2w options (terminal value = at S_2w)
        "AC_50_P_2":  np.maximum(50 - S_2w, 0.0),
        "AC_50_C_2":  np.maximum(S_2w - 50, 0.0),
        # Chooser: at t=2w, becomes call if S_2w >= 50, else put. Pays at t=3w.
        # (Brief: "automatically converts to the side that is in the money".)
        "AC_50_CO":   np.where(S_2w >= 50,
                               np.maximum(S_T - 50, 0.0),    # ITM call
                               np.maximum(50 - S_T, 0.0)),   # ITM put
        # Binary put: pays 10 if S_T < 40 at expiry
        "AC_40_BP":   np.where(S_T < 40, 10.0, 0.0),
        # Knock-out put K=45 B=35: pays max(45 - S_T, 0) iff barrier never breached.
        # Brief: "If the value... ever falls below 35", strict < => survives at min_S >= 35.
        # 4-obs/day discrete monitoring (no continuous Brownian bridge).
        "AC_45_KO":   np.where(min_S >= 35, np.maximum(45 - S_T, 0.0), 0.0),
    }


def strategy_per_path_pnl(strategy: List[Tuple[str, str, int]],
                          payoffs: Dict[str, np.ndarray]) -> np.ndarray:
    """Per-path total PnL of a strategy (single GBM realization). Pre-multiplier."""
    pnl = np.zeros_like(next(iter(payoffs.values())))
    for sym, side, vol in strategy:
        bid, ask, _ = QUOTES[sym]
        p = payoffs[sym]
        if side == "buy":
            pnl += vol * (p - ask)               # pay ask now, receive payoff at expiry
        elif side == "sell":
            pnl += vol * (bid - p)               # receive bid now, owe payoff at expiry
    return pnl


# ────────────────────────────────────────────────────────────────────────────
# STATISTICS
# ────────────────────────────────────────────────────────────────────────────
def summarize(scores: np.ndarray, label: str) -> dict:
    """Compute headline stats and tail-risk metrics for a score distribution."""
    n = len(scores)
    mean = float(scores.mean())
    sd = float(scores.std(ddof=1))
    median = float(np.median(scores))
    pct_pos = float((scores > 0).mean() * 100)
    pcts = {p: float(np.percentile(scores, p)) for p in [0.1, 1, 2, 5, 10, 25, 50, 75, 90, 95, 99, 99.9]}
    cvar = {p: float(scores[scores <= pcts[p]].mean()) for p in [1, 2, 5, 10, 25]}
    sharpe = mean / sd if sd > 0 else 0.0
    return {
        "label": label, "n": n, "mean": mean, "sd": sd, "median": median,
        "sharpe": sharpe, "pct_positive": pct_pos,
        "percentiles": pcts, "cvar": cvar,
    }


def print_summary(s: dict) -> None:
    """Pretty-print a strategy's results."""
    print(f"\n  {'='*100}")
    print(f"  {s['label']}")
    print(f"  {'='*100}")
    print(f"  Trials:           {s['n']:,}")
    print(f"  Mean (E[score]):  ${s['mean']:>+15,.0f}")
    print(f"  Median:           ${s['median']:>+15,.0f}")
    print(f"  Std deviation:    ${s['sd']:>+15,.0f}")
    print(f"  Sharpe:           {s['sharpe']:>15.4f}")
    print(f"  P(score > 0):     {s['pct_positive']:>14.2f}%")
    print(f"\n  Tail percentiles (lower = worse):")
    for p in [0.1, 1, 2, 5, 10]:
        print(f"    q{p:>4.1f}%        ${s['percentiles'][p]:>+15,.0f}")
    print(f"\n  CVaR (mean of worst X% of trials):")
    for p in [1, 2, 5, 10, 25]:
        print(f"    CVaR-{p:>2d}%        ${s['cvar'][p]:>+15,.0f}")


# ────────────────────────────────────────────────────────────────────────────
# MAIN MONTE CARLO LOOP
# ────────────────────────────────────────────────────────────────────────────
def run_simulation(strategies: Dict[str, List[Tuple[str, str, int]]],
                   total_paths: int, chunk_size: int, seed: int,
                   sims_per_trial: int = SIMS_PER_TRIAL) -> dict:
    """
    Run total_paths GBM paths in chunks, group into trials of sims_per_trial,
    return per-strategy summary stats.

    Correctness guards (raise ValueError on violation):
      - chunk_size % sims_per_trial == 0  (each chunk fills whole trials)
      - total_paths % chunk_size == 0     (each chunk is fully consumed)
      - total_paths % sims_per_trial == 0 (no partial-trial tail)

    Without these, the pre-allocated trial_scores array would contain
    uninitialized memory (garbage) for the unfilled tail, and downstream
    statistics (Sharpe, CVaR) would silently include cosmic background bytes.
    """
    if total_paths <= 0 or chunk_size <= 0 or sims_per_trial <= 0:
        raise ValueError(
            f"all sizes must be positive: total_paths={total_paths}, "
            f"chunk_size={chunk_size}, sims_per_trial={sims_per_trial}")
    if chunk_size % sims_per_trial != 0:
        raise ValueError(
            f"chunk_size ({chunk_size:,}) must be divisible by "
            f"sims_per_trial ({sims_per_trial})")
    if total_paths % chunk_size != 0:
        raise ValueError(
            f"total_paths ({total_paths:,}) must be divisible by "
            f"chunk_size ({chunk_size:,}). Otherwise the final partial chunk "
            f"would leave {total_paths % chunk_size:,} paths "
            f"({(total_paths % chunk_size) // sims_per_trial:,} trials) "
            f"uninitialized in the output array.")
    if total_paths % sims_per_trial != 0:
        raise ValueError(
            f"total_paths ({total_paths:,}) must be divisible by "
            f"sims_per_trial ({sims_per_trial})")

    n_chunks = total_paths // chunk_size
    n_trials = total_paths // sims_per_trial
    n_trials_per_chunk = chunk_size // sims_per_trial

    # Validate all strategies first
    for name, strat in strategies.items():
        validate_strategy(name, strat)
    print(f"All {len(strategies)} strategies pass position-limit checks.")

    # Pre-allocate trial-score arrays per strategy
    trial_scores = {name: np.empty(n_trials, dtype=np.float64) for name in strategies}

    rng = np.random.default_rng(seed)
    t0 = time.time()
    print(f"\nGenerating {total_paths:,} paths in {n_chunks} chunks of {chunk_size:,}...")
    for ci in range(n_chunks):
        S_T, S_2w, min_S = generate_paths(chunk_size, rng)
        payoffs = compute_payoffs(S_T, S_2w, min_S)

        for name, strat in strategies.items():
            pnl_per_path = strategy_per_path_pnl(strat, payoffs)
            # Group paths into trials of 100, take row mean, scale by multiplier
            chunk_trials = (
                pnl_per_path[:n_trials_per_chunk * sims_per_trial]
                .reshape(n_trials_per_chunk, sims_per_trial)
                .mean(axis=1) * CONTRACT_MULTIPLIER
            )
            start = ci * n_trials_per_chunk
            trial_scores[name][start:start + n_trials_per_chunk] = chunk_trials

        # Free memory + show progress
        del payoffs, S_T, S_2w, min_S
        if (ci + 1) % max(1, n_chunks // 10) == 0:
            elapsed = time.time() - t0
            eta = elapsed * (n_chunks - ci - 1) / (ci + 1)
            print(f"  chunk {ci+1:>3}/{n_chunks}  elapsed {elapsed:>6.1f}s  ETA {eta:>6.0f}s")

    print(f"\nPath generation complete in {time.time()-t0:.0f}s")

    # Compute summary stats per strategy
    return {name: summarize(trial_scores[name], name) for name in strategies}


def main():
    parser = argparse.ArgumentParser(description="R4 Manual Challenge MC simulator")
    parser.add_argument("--paths", type=int, default=100_000_000,
                        help="Total paths (default 100M = 1M trials of 100)")
    parser.add_argument("--chunk", type=int, default=5_000_000,
                        help="Paths per chunk for memory management (default 5M)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed (default 42)")
    parser.add_argument("--strategies", type=str, default=None,
                        help="Comma-separated strategy names (default = all)")
    args = parser.parse_args()

    print("="*100)
    print(f"IMC R4 MANUAL CHALLENGE — Monte Carlo Simulator")
    print(f"S0={S0}  sigma={SIGMA_ANNUAL}  T_3w={T_3W_DAYS}td  T_2w={T_2W_DAYS}td  "
          f"DT=1/{int(1/DT)}  multiplier x{CONTRACT_MULTIPLIER}")
    print("="*100)

    if args.strategies:
        names = [n.strip() for n in args.strategies.split(",")]
        selected = {n: STRATEGIES[n] for n in names if n in STRATEGIES}
    else:
        selected = STRATEGIES

    results = run_simulation(selected, args.paths, args.chunk, args.seed)

    # Sort by mean and print
    sorted_names = sorted(results, key=lambda n: -results[n]["mean"])
    print("\n" + "="*100)
    print("RESULTS (sorted by E[score])")
    print("="*100)
    for name in sorted_names:
        print_summary(results[name])

    # Side-by-side comparison
    print("\n\n" + "="*120)
    print("SIDE-BY-SIDE")
    print("="*120)
    print(f"{'Strategy':<28} {'Mean':>14} {'Median':>14} {'SD':>13} {'Sharpe':>8} "
          f"{'P>0':>7} {'CVaR-5%':>14} {'CVaR-2%':>14}")
    for name in sorted_names:
        r = results[name]
        print(f"{name:<28} ${r['mean']:>+13,.0f} ${r['median']:>+13,.0f} ${r['sd']:>12,.0f} "
              f"{r['sharpe']:>8.4f} {r['pct_positive']:>6.1f}% "
              f"${r['cvar'][5]:>+13,.0f} ${r['cvar'][2]:>+13,.0f}")

    # Save JSON
    import json
    out_path = "r4_simulation_results.json"
    with open(out_path, "w") as f:
        json.dump({name: {k: v for k, v in r.items() if k != "label"}
                   for name, r in results.items()}, f, indent=2, default=float)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
