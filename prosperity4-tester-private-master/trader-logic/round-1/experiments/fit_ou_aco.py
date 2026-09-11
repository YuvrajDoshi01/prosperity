"""Fit OU parameters (alpha, beta) to ACO mid across all 4 CSV days.

OU in continuous time: dX_t = alpha * (mu - X_t) * dt + beta * dW_t
Discretized (Delta_t = 1 tick):
    X_{t+1} = X_t + alpha*(mu - X_t) + eps,   eps ~ N(0, beta^2)

We fit via AR(1) regression:
    X_{t+1} - X_t = a + b * X_t + eps
    => alpha = -b,  mu = -a/b,  beta = std(residuals)

Also computes wall-mid (deep-volume bid/ask) per Nancy's definition and fits to that.
Reports alpha, beta, mu, stationary std = beta/sqrt(2*alpha), R^2 of regression.
"""
import csv
import math
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prosperity4bt" / "resources" / "round1"
DAYS = [-2, -1, 0, 1]
PRODUCT = "ASH_COATED_OSMIUM"


def parse_float(s):
    return float(s) if s else None


def load_aco(day):
    path = DATA_DIR / f"prices_round_1_day_{day}.csv"
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            if r["product"] != PRODUCT:
                continue
            rows.append(r)
    return rows


def wall_mid(r):
    """Nancy's wall-mid: (max-volume bid + max-volume ask) / 2."""
    bids = []
    for i in (1, 2, 3):
        p = parse_float(r[f"bid_price_{i}"])
        v = parse_float(r[f"bid_volume_{i}"])
        if p is not None and v is not None:
            bids.append((v, p))
    asks = []
    for i in (1, 2, 3):
        p = parse_float(r[f"ask_price_{i}"])
        v = parse_float(r[f"ask_volume_{i}"])
        if p is not None and v is not None:
            asks.append((v, p))
    if not bids or not asks:
        return None
    deep_bid = max(bids)[1]
    deep_ask = min(asks, key=lambda x: -x[0])[1]
    return (deep_bid + deep_ask) / 2


def top_mid(r):
    bid = parse_float(r["bid_price_1"])
    ask = parse_float(r["ask_price_1"])
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def fit_ar1(series):
    """Fit X_{t+1} - X_t = a + b*X_t + eps. Returns (alpha, mu, beta, r2, n)."""
    x = series[:-1]
    dx = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    n = len(x)
    x_mean = sum(x) / n
    dx_mean = sum(dx) / n

    sxx = sum((xi - x_mean) ** 2 for xi in x)
    sxy = sum((x[i] - x_mean) * (dx[i] - dx_mean) for i in range(n))
    b = sxy / sxx
    a = dx_mean - b * x_mean

    resid = [dx[i] - (a + b * x[i]) for i in range(n)]
    ss_res = sum(r * r for r in resid)
    ss_tot = sum((d - dx_mean) ** 2 for d in dx)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    beta = math.sqrt(ss_res / (n - 2))

    alpha = -b
    mu = -a / b if b != 0 else float("nan")
    return alpha, mu, beta, r2, n


def summarize(label, series):
    alpha, mu, beta, r2, n = fit_ar1(series)
    if alpha > 0:
        stat_std = beta / math.sqrt(2 * alpha)
    else:
        stat_std = float("nan")
    half_life = math.log(2) / alpha if alpha > 0 else float("nan")
    print(f"  {label:14s}  n={n:5d}  alpha={alpha:+.6f}  mu={mu:10.3f}  beta={beta:.4f}  "
          f"stat_std={stat_std:.3f}  half_life={half_life:8.1f}  R2={r2:.4f}")
    return alpha, mu, beta, stat_std, r2


print(f"Fitting OU to {PRODUCT} across days {DAYS}\n")
print(f"Nancy's claimed: alpha=0.0294, beta=1.145, gamma=10000, stat_std = 1.145/sqrt(2*0.0294) = {1.145 / math.sqrt(2 * 0.0294):.3f}\n")

results_top = {}
results_wall = {}

for day in DAYS:
    rows = load_aco(day)
    tops = [top_mid(r) for r in rows]
    walls = [wall_mid(r) for r in rows]
    tops_clean = [m for m in tops if m is not None]
    walls_clean = [m for m in walls if m is not None]

    print(f"Day {day}  (rows={len(rows)}, top_mid_clean={len(tops_clean)}, wall_mid_clean={len(walls_clean)}):")
    results_top[day] = summarize("top_mid", tops_clean)
    results_wall[day] = summarize("wall_mid", walls_clean)
    print()

print("="*90)
print("STABILITY SUMMARY\n")


def show_stability(name, results):
    alphas = [v[0] for v in results.values()]
    mus = [v[1] for v in results.values()]
    betas = [v[2] for v in results.values()]
    stds = [v[3] for v in results.values()]
    a_mean = sum(alphas) / len(alphas)
    a_range = max(alphas) - min(alphas)
    b_mean = sum(betas) / len(betas)
    b_range = max(betas) - min(betas)
    std_mean = sum(stds) / len(stds)
    std_range = max(stds) - min(stds)
    print(f"  {name}:")
    print(f"    alpha: mean={a_mean:+.6f}  range={a_range:.6f}  rel_range={a_range / abs(a_mean):.2%}")
    print(f"    beta:  mean={b_mean:.4f}   range={b_range:.4f}   rel_range={b_range / b_mean:.2%}")
    print(f"    stat_std: mean={std_mean:.3f}  range={std_range:.3f}  rel_range={std_range / std_mean:.2%}")
    print(f"    days:   alpha={[f'{a:+.4f}' for a in alphas]}")
    print(f"            beta ={[f'{b:.3f}' for b in betas]}")
    print(f"            mu   ={[f'{m:.1f}' for m in mus]}")
    print()


show_stability("top_mid", results_top)
show_stability("wall_mid", results_wall)

print("Interpretation:")
print("  Nancy's alpha=0.0294 matches which day (if any)?")
for day in DAYS:
    for label, res in [("top", results_top[day]), ("wall", results_wall[day])]:
        diff_a = abs(res[0] - 0.0294) / 0.0294
        diff_b = abs(res[2] - 1.145) / 1.145
        print(f"  Day {day:2d} {label:4s}: alpha rel-diff vs 0.0294 = {diff_a:.1%}, beta rel-diff vs 1.145 = {diff_b:.1%}")
