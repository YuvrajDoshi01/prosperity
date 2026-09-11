"""
IMC Prosperity 4 — Round 4 Manual Challenge
Position-vector optimization across 12 derivatives on AC.

Score = average of 100 simulations of  sum_i  q_i * (S_T_payoff_i - trade_price_i)
where:
    q_i > 0   => bought at ask
    q_i < 0   => sold  at bid
    payoff_i  = realised value of instrument at expiry under the simulated path

So per-unit edge under the *true* model is:
    buy : fv_i - ask_i
    sell: bid_i - fv_i
But the realised PnL has variance from the path.

We:
  (1) Build EV oracle  ev(q, fv, quotes)
  (2) Build variance / CVaR oracle via 1M MC paths of S
  (3) Enumerate ~150+ candidate position vectors and rank under
      EV / Sharpe / CVaR / robust-EV objectives
  (4) Print Pareto frontier and final recommendation
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

S0    = 50.0
SIGMA = 2.51                    # ANNUALIZED lognormal vol  (~251%)
T_3w  = 15 / 252
T_2w  = 10 / 252

# Sanity:  ATM BS call value ~= 0.4 * S0 * sigma * sqrt(T)
#                            ~= 0.4 * 50 * 2.51 * sqrt(15/252)
#                            ~= 12.25   matches FV[AC_50_C] = 12.027
SIGMA_ANN = SIGMA

FV: Dict[str, float] = {
    "AC":          50.000,
    "AC_50_P":     12.027,
    "AC_50_C":     12.027,
    "AC_35_P":      4.336,
    "AC_40_P":      6.510,
    "AC_45_P":      9.089,
    "AC_60_C":      8.792,
    "AC_50_P_2":    9.871,
    "AC_50_C_2":    9.871,
    "AC_50_CO":    21.898,
    "AC_40_BP":     4.768,
    "AC_45_KO":     0.207,
}

# (bid, ask, vol_cap)
QUOTES: Dict[str, Tuple[float, float, int]] = {
    "AC":          (49.975, 50.025, 200),
    "AC_50_P":     (12.00,  12.05,  50),
    "AC_50_C":     (12.00,  12.05,  50),
    "AC_35_P":     ( 4.33,   4.35,  50),
    "AC_40_P":     ( 6.50,   6.55,  50),
    "AC_45_P":     ( 9.05,   9.10,  50),
    "AC_60_C":     ( 8.80,   8.85,  50),
    "AC_50_P_2":   ( 9.70,   9.75,  50),
    "AC_50_C_2":   ( 9.70,   9.75,  50),
    "AC_50_CO":    (22.20,  22.30,  50),
    "AC_40_BP":    ( 5.00,   5.10,  50),
    "AC_45_KO":    ( 0.15,   0.175, 500),
}

INSTRUMENTS = list(FV.keys())

# ---------------------------------------------------------------------------
# (1) EV Oracle
# ---------------------------------------------------------------------------

def edges(fv: Dict[str, float], quotes: Dict[str, Tuple[float, float, int]]):
    """Per-unit buy and sell edges."""
    buy_edge  = {k: fv[k] - quotes[k][1] for k in fv}   # positive => good buy
    sell_edge = {k: quotes[k][0] - fv[k] for k in fv}   # positive => good sell
    caps      = {k: quotes[k][2] for k in fv}
    return buy_edge, sell_edge, caps


def ev(positions: Dict[str, int],
       fv: Dict[str, float] = FV,
       quotes: Dict[str, Tuple[float, float, int]] = QUOTES) -> float:
    """Expected value of position vector."""
    total = 0.0
    for k, q in positions.items():
        bid, ask, _ = quotes[k]
        if q > 0:
            total += q * (fv[k] - ask)
        elif q < 0:
            total += (-q) * (bid - fv[k])
    return total

# ---------------------------------------------------------------------------
# (2) Monte Carlo paths of S — discrete daily monitoring for the KO put
# ---------------------------------------------------------------------------

N_PATHS    = 1_000_000
N_STEPS_3W = 15            # 15 trading days
KO_BARRIER = 45.0
KO_STRIKE  = 45.0
RNG_SEED   = 12345


def simulate_paths(n_paths: int = N_PATHS, seed: int = RNG_SEED) -> np.ndarray:
    """
    Simulate GBM under risk-neutral (r=0) lognormal:
        S_{t+dt} = S_t * exp(-0.5*sig^2*dt + sig*sqrt(dt)*Z)
    Returns shape (n_paths, N_STEPS_3W+1) with column 0 = S0.
    For 2-week instruments we slice S[:, :11] (10 steps -> day 10).
    """
    rng = np.random.default_rng(seed)
    dt   = 1.0 / 252.0
    sig  = SIGMA_ANN
    Z    = rng.standard_normal(size=(n_paths, N_STEPS_3W))
    incr = np.exp(-0.5 * sig * sig * dt + sig * math.sqrt(dt) * Z)
    S    = np.empty((n_paths, N_STEPS_3W + 1), dtype=np.float64)
    S[:, 0] = S0
    np.cumprod(incr, axis=1, out=S[:, 1:])
    S[:, 1:] *= S0
    return S


def realized_payoffs(S: np.ndarray) -> Dict[str, np.ndarray]:
    """Per-path realised payoff per unit for every instrument."""
    S_T3  = S[:, -1]                # day 15
    S_T2  = S[:, 10]                # day 10
    out: Dict[str, np.ndarray] = {}
    out["AC"]         = S_T3
    out["AC_50_P"]    = np.maximum(50.0 - S_T3, 0.0)
    out["AC_50_C"]    = np.maximum(S_T3 - 50.0, 0.0)
    out["AC_35_P"]    = np.maximum(35.0 - S_T3, 0.0)
    out["AC_40_P"]    = np.maximum(40.0 - S_T3, 0.0)
    out["AC_45_P"]    = np.maximum(45.0 - S_T3, 0.0)
    out["AC_60_C"]    = np.maximum(S_T3 - 60.0, 0.0)
    out["AC_50_P_2"]  = np.maximum(50.0 - S_T2, 0.0)
    out["AC_50_C_2"]  = np.maximum(S_T2 - 50.0, 0.0)
    # Chooser at t=2w: max(call_3w(S_T2), put_3w(S_T2)).  But chooser pays
    # at expiry; standard chooser value at choose-date with same K=50 and
    # remaining 1w = max(C_1w, P_1w).  The realised "payoff at 3w" is
    # whichever option you chose.  We model: at t=2w, agent picks the
    # higher Black-Scholes value of the 1w call vs put, then receives that
    # option's terminal payoff at t=3w.
    one_week_T = 5 / 252.0
    sig = SIGMA_ANN
    d1 = (np.log(S_T2 / 50.0) + 0.5 * sig * sig * one_week_T) / (sig * math.sqrt(one_week_T))
    d2 = d1 - sig * math.sqrt(one_week_T)
    # Standard normal CDF
    from math import erf, sqrt
    Phi = lambda x: 0.5 * (1.0 + np.vectorize(erf)(x / np.sqrt(2.0)))
    call_1w = S_T2 * Phi(d1) - 50.0 * Phi(d2)
    put_1w  = 50.0 * Phi(-d2) - S_T2 * Phi(-d1)
    chose_call = call_1w >= put_1w
    payoff_call_at_T3 = np.maximum(S_T3 - 50.0, 0.0)
    payoff_put_at_T3  = np.maximum(50.0 - S_T3, 0.0)
    out["AC_50_CO"] = np.where(chose_call, payoff_call_at_T3, payoff_put_at_T3)
    # Binary put K=40 — pays $10 if S_T3 < 40 else 0
    out["AC_40_BP"] = np.where(S_T3 < 40.0, 10.0, 0.0)
    # KO put K=45, barrier 45, discrete daily monitoring (barrier in/out):
    # standard "down-and-out" put — knocks out if any monitored S <= 45.
    # The fv ($0.207) was given as discrete-monitoring KO put; we replicate.
    monitored = S[:, 1:]                 # daily closes day1..day15
    knocked   = (monitored <= KO_BARRIER).any(axis=1)
    payoff_p  = np.maximum(KO_STRIKE - S_T3, 0.0)
    out["AC_45_KO"] = np.where(knocked, 0.0, payoff_p)
    return out


def trade_pnl_per_path(positions: Dict[str, int],
                       payoffs: Dict[str, np.ndarray],
                       quotes: Dict[str, Tuple[float, float, int]] = QUOTES
                       ) -> np.ndarray:
    """Per-path realised PnL of a position vector."""
    n = next(iter(payoffs.values())).shape[0]
    pnl = np.zeros(n, dtype=np.float64)
    for k, q in positions.items():
        if q == 0:
            continue
        bid, ask, _ = quotes[k]
        if q > 0:
            pnl += q * (payoffs[k] - ask)
        else:
            pnl += (-q) * (bid - payoffs[k])
    return pnl


def stats_of(positions, payoffs, quotes=QUOTES, alpha_cvar=0.05):
    pnl = trade_pnl_per_path(positions, payoffs, quotes)
    mean = pnl.mean()
    std  = pnl.std()
    # Empirical CVaR_alpha (left tail, average of worst alpha fraction)
    k = max(1, int(alpha_cvar * pnl.size))
    cvar = np.partition(pnl, k - 1)[:k].mean()
    sharpe = mean / std if std > 0 else float("inf")
    return mean, std, cvar, sharpe, pnl

# ---------------------------------------------------------------------------
# (3) Candidate position vectors
# ---------------------------------------------------------------------------

def zero_vec() -> Dict[str, int]:
    return {k: 0 for k in INSTRUMENTS}


def from_dict(**kw) -> Dict[str, int]:
    v = zero_vec()
    for k, q in kw.items():
        v[k] = int(q)
    return v


def positive_edge_max(fv=FV, quotes=QUOTES) -> Dict[str, int]:
    """All instruments at max size on whichever side has positive edge."""
    v = zero_vec()
    for k in INSTRUMENTS:
        bid, ask, cap = quotes[k]
        be = fv[k] - ask
        se = bid - fv[k]
        if be > 0 and be >= se:
            v[k] =  cap
        elif se > 0 and se > be:
            v[k] = -cap
    return v


def build_candidates() -> Dict[str, Dict[str, int]]:
    cands: Dict[str, Dict[str, int]] = {}

    # Baselines ---------------------------------------------------------
    cands["zero"] = zero_vec()
    cands["all_pos_edge_max"] = positive_edge_max()

    # KO scaled down ----------------------------------------------------
    base = positive_edge_max()
    for ko_q in (500, 400, 300, 250, 200, 150, 100, 50, 25, 0):
        v = dict(base); v["AC_45_KO"] = ko_q
        cands[f"pos_edge_KO{ko_q}"] = v

    # User reference ----------------------------------------------------
    cands["user_ref"] = from_dict(
        AC_50_CO=-15, AC_40_BP=-50, AC_50_P=17,
        AC_50_P_2=15, AC_50_C=15, AC=150,
    )

    # Sparse: only top-edge buys / sells -------------------------------
    be, se, caps = edges(FV, QUOTES)
    ranked = sorted(INSTRUMENTS, key=lambda k: -max(be[k], se[k]))
    for top_k in (1, 2, 3, 5, 7):
        v = zero_vec()
        for k in ranked[:top_k]:
            v[k] = caps[k] if be[k] >= se[k] else -caps[k]
        cands[f"top{top_k}_edges"] = v

    # Hedged variants: SELL chooser + BUY straddle ---------------------
    for n_choo in (10, 15, 20, 25, 30, 40, 50):
        # one chooser ~ value of straddle in spirit; offset 1:1 hedge
        for n_strad in (n_choo, n_choo // 2, n_choo // 3):
            v = positive_edge_max()
            v["AC_50_CO"] = -n_choo
            v["AC_50_P"]  = +n_strad
            v["AC_50_C"]  = +n_strad
            cands[f"hedged_choo{n_choo}_strad{n_strad}"] = v

    # Sweep KO position with everything else off (pure KO bet)
    for ko_q in (-500, -300, -100, 0, 100, 300, 500):
        v = zero_vec(); v["AC_45_KO"] = ko_q
        cands[f"ko_only_{ko_q}"] = v

    # Spot scaled
    for ac_q in (-200, -100, 0, 100, 200):
        v = positive_edge_max(); v["AC"] = ac_q
        cands[f"pos_edge_AC{ac_q}"] = v

    # Variants killing the binary put short (high left tail risk)
    base = positive_edge_max()
    v = dict(base); v["AC_40_BP"] = 0
    cands["pos_edge_no_BP"] = v
    v = dict(base); v["AC_40_BP"] = -25
    cands["pos_edge_BP-25"] = v

    # Variants killing chooser short
    v = dict(base); v["AC_50_CO"] = 0
    cands["pos_edge_no_CO"] = v

    # Random LP-style mixes (mostly KO-light)
    rng = np.random.default_rng(7)
    for i in range(80):
        v = zero_vec()
        for k in INSTRUMENTS:
            cap = QUOTES[k][2]
            be_k = FV[k] - QUOTES[k][1]
            se_k = QUOTES[k][0] - FV[k]
            if be_k <= 0 and se_k <= 0:
                continue
            sign = 1 if be_k >= se_k else -1
            frac = rng.random()                # 0..1 of cap
            v[k] = int(round(sign * frac * cap))
        # cap KO to 200
        v["AC_45_KO"] = int(np.clip(v["AC_45_KO"], -200, 200))
        cands[f"rand_{i:02d}"] = v

    return cands


# ---------------------------------------------------------------------------
# (4) Robust optimization & Pareto frontier
# ---------------------------------------------------------------------------

def evaluate_all(cands: Dict[str, Dict[str, int]], payoffs):
    rows = []
    for name, v in cands.items():
        m, s, cv, sh, _ = stats_of(v, payoffs)
        rows.append({
            "name": name,
            "ev_model": ev(v),
            "ev_mc":    m,
            "sigma":    s,
            "cvar5":    cv,
            "sharpe":   sh,
            "vec":      v,
        })
    return rows


def pareto_front(rows):
    """Maximize EV, minimize sigma."""
    pts = sorted(rows, key=lambda r: (-r["ev_mc"], r["sigma"]))
    front, best_sigma = [], math.inf
    for r in pts:
        if r["sigma"] < best_sigma:
            front.append(r)
            best_sigma = r["sigma"]
    return front


def kelly_score(pnl: np.ndarray, alpha: float) -> float:
    """E[log(1 + alpha*PnL)], clipped to avoid log of negatives."""
    x = 1.0 + alpha * pnl
    x = np.clip(x, 1e-9, None)
    return float(np.log(x).mean())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 78)
    print(" IMC Prosperity R4 Manual — Position Vector Optimizer")
    print("=" * 78)

    be, se, caps = edges(FV, QUOTES)
    print("\nPer-unit edges  (positive => take that side):")
    print(f"{'instr':12s} {'buy_edge':>10s} {'sell_edge':>10s} {'cap':>6s} {'best_side':>10s}")
    for k in INSTRUMENTS:
        side = "BUY " if be[k] > se[k] and be[k] > 0 else (
               "SELL" if se[k] > 0 else "----")
        print(f"{k:12s} {be[k]:10.4f} {se[k]:10.4f} {caps[k]:6d}   {side}")

    print(f"\nSimulating {N_PATHS:,} GBM paths (sigma_ann = {SIGMA_ANN:.4f}) ...")
    S = simulate_paths()
    payoffs = realized_payoffs(S)

    # Sanity: empirical means vs FV inputs
    print("\nMC-mean payoff vs supplied FV (sanity check):")
    print(f"{'instr':12s} {'fv':>10s} {'mc_mean':>10s} {'diff':>10s}")
    for k in INSTRUMENTS:
        m = float(payoffs[k].mean())
        print(f"{k:12s} {FV[k]:10.4f} {m:10.4f} {m - FV[k]:+10.4f}")

    cands = build_candidates()
    print(f"\nEvaluating {len(cands)} candidate vectors ...")
    rows = evaluate_all(cands, payoffs)

    # ---- Sort tables ------------------------------------------------
    def show(rows, key, n=15, reverse=True, label=""):
        print(f"\n--- Top {n} by {label or key} ---")
        rs = sorted(rows, key=lambda r: r[key], reverse=reverse)[:n]
        print(f"{'name':30s} {'EV':>9s} {'EV_mc':>9s} {'sigma':>8s} "
              f"{'CVaR5%':>9s} {'Sharpe':>7s}")
        for r in rs:
            print(f"{r['name']:30s} {r['ev_model']:9.1f} {r['ev_mc']:9.1f} "
                  f"{r['sigma']:8.1f} {r['cvar5']:9.1f} {r['sharpe']:7.3f}")

    show(rows, "ev_mc",  n=15, label="EV (MC)")
    show(rows, "sharpe", n=15, label="Sharpe")
    show(rows, "cvar5",  n=15, label="CVaR_5% (least bad)")

    # ---- Constrained: sigma <= 1500 --------------------------------
    csig = [r for r in rows if r["sigma"] <= 1500]
    print(f"\nCandidates with sigma <= 1500: {len(csig)}")
    show(csig, "ev_mc", n=10, label="EV s.t. sigma<=1500")

    # ---- Constrained: CVaR_5% >= -3000 -----------------------------
    ccvar = [r for r in rows if r["cvar5"] >= -3000]
    print(f"\nCandidates with CVaR_5% >= -3000: {len(ccvar)}")
    show(ccvar, "ev_mc", n=10, label="EV s.t. CVaR>=-3000")

    # ---- Kelly (small alpha) ---------------------------------------
    print("\nKelly E[log(1 + alpha*PnL)] for alpha = 1e-4 (top 10):")
    for r in rows:
        _, _, _, _, pnl = stats_of(r["vec"], payoffs)
        r["kelly"] = kelly_score(pnl, 1e-4)
    show(rows, "kelly", n=10, label="Kelly (alpha=1e-4)")

    # ---- Pareto frontier --------------------------------------------
    front = pareto_front(rows)
    print(f"\nPareto frontier (EV vs sigma):  {len(front)} pts")
    print(f"{'name':30s} {'EV_mc':>9s} {'sigma':>8s} {'CVaR5%':>9s}")
    for r in front:
        print(f"{r['name']:30s} {r['ev_mc']:9.1f} {r['sigma']:8.1f} "
              f"{r['cvar5']:9.1f}")

    # ---- Robust EV: stay positive under +/-10% sigma shock ---------
    print("\nRobust EV (model EV unchanged; sigma shock +/-10% on MC):")
    rng = np.random.default_rng(99)
    Z   = rng.standard_normal(size=(200_000, N_STEPS_3W))
    def shocked_payoffs(scale: float):
        sig = SIGMA_ANN * scale
        dt = 1.0 / 252.0
        incr = np.exp(-0.5 * sig * sig * dt + sig * math.sqrt(dt) * Z)
        S_s  = np.empty((Z.shape[0], N_STEPS_3W + 1))
        S_s[:, 0] = S0
        np.cumprod(incr, axis=1, out=S_s[:, 1:]); S_s[:, 1:] *= S0
        return realized_payoffs(S_s)
    pay_lo = shocked_payoffs(0.9)
    pay_hi = shocked_payoffs(1.1)
    robust = []
    for r in rows:
        m_lo = trade_pnl_per_path(r["vec"], pay_lo).mean()
        m_hi = trade_pnl_per_path(r["vec"], pay_hi).mean()
        worst = min(r["ev_mc"], m_lo, m_hi)
        robust.append((worst, r))
    robust.sort(key=lambda x: -x[0])
    print(f"{'name':30s} {'EV_base':>9s} {'EV_lo':>9s} {'EV_hi':>9s} {'min':>9s}")
    for worst, r in robust[:12]:
        m_lo = trade_pnl_per_path(r["vec"], pay_lo).mean()
        m_hi = trade_pnl_per_path(r["vec"], pay_hi).mean()
        print(f"{r['name']:30s} {r['ev_mc']:9.1f} {m_lo:9.1f} {m_hi:9.1f} "
              f"{worst:9.1f}")

    # ---- Final recommendation ---------------------------------------
    # Pick highest Sharpe among those with sigma<=1500 AND CVaR>=-3000
    finalists = [r for r in rows
                 if r["sigma"] <= 1500 and r["cvar5"] >= -3000]
    finalists.sort(key=lambda r: -r["ev_mc"])
    print(f"\nFinalists (sigma<=1500, CVaR5%>=-3000): {len(finalists)}")
    show(finalists, "ev_mc", n=10, label="Finalists EV")

    if finalists:
        rec = finalists[0]
    else:
        rec = sorted(rows, key=lambda r: -r["ev_mc"])[0]

    print("\n" + "=" * 78)
    print("FINAL RECOMMENDATION")
    print("=" * 78)
    print(f"Name:    {rec['name']}")
    print(f"EV:      {rec['ev_mc']:.1f}")
    print(f"Sigma:   {rec['sigma']:.1f}")
    print(f"CVaR5%:  {rec['cvar5']:.1f}")
    print(f"Sharpe:  {rec['sharpe']:.3f}")
    print("Position vector:")
    for k in INSTRUMENTS:
        if rec["vec"][k] != 0:
            print(f"  {k:12s} {rec['vec'][k]:+6d}")

    out_path = ("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/"
                "trader-logic/round-4/manual/cp_optimal_recommendation.json")
    with open(out_path, "w") as f:
        json.dump({
            "recommendation":  rec["name"],
            "vec":             rec["vec"],
            "ev_mc":           rec["ev_mc"],
            "sigma":           rec["sigma"],
            "cvar5":           rec["cvar5"],
            "sharpe":          rec["sharpe"],
            "all_top10_by_ev": [
                {"name": r["name"], "vec": r["vec"], "ev_mc": r["ev_mc"],
                 "sigma": r["sigma"], "cvar5": r["cvar5"]}
                for r in sorted(rows, key=lambda r: -r["ev_mc"])[:10]
            ],
        }, f, indent=2)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
