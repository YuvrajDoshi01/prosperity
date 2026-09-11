"""Render plots and ASCII tables from sigma_sensitivity_v2.json."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

JSON_PATH = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/manual/sigma_sensitivity_v2.json"
PNG_PATH = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/manual/sigma_sensitivity_v2.png"
CONTRACT_MULT = 3000

with open(JSON_PATH) as f:
    data = json.load(f)

sigmas = sorted(float(s) for s in data["grid_results"].keys())
strategies = list(next(iter(data["grid_results"].values())).keys())

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
axes = axes.flatten()

# 1. E[score] vs sigma (USD/trial)
ax = axes[0]
for name in strategies:
    ys = [data["grid_results"][f"{s}"][name]["mean_usd"] for s in sigmas]
    ax.plot(sigmas, ys, "-o", label=name, lw=1.5, markersize=4)
ax.axvline(2.51, color="k", linestyle="--", alpha=0.4, label="brief sigma=2.51")
ax.set_xlabel("sigma")
ax.set_ylabel("E[score] (USD per trial)")
ax.set_title("E[score] vs sigma")
ax.grid(True, alpha=0.3)
ax.legend(fontsize=8, loc="best")

# 2. Differential E[7POS] - E[5POS]
ax = axes[1]
diffs = [data["grid_results"][f"{s}"]["OPTIMAL_7POS"]["mean_usd"] -
         data["grid_results"][f"{s}"]["DROP_60C"]["mean_usd"] for s in sigmas]
ax.plot(sigmas, diffs, "-o", color="purple", lw=2)
ax.axhline(0, color="k", linewidth=0.8)
ax.axvline(2.51, color="k", linestyle="--", alpha=0.4)
if "crossover_sigma" in data:
    ax.axvline(data["crossover_sigma"], color="red", linestyle=":", lw=1.5,
               label=f"crossover sigma~{data['crossover_sigma']:.4f}")
    ax.legend()
ax.set_xlabel("sigma")
ax.set_ylabel("E[7POS] - E[5POS] (USD per trial)")
ax.set_title("Sigma break-even: 7POS overtakes 5POS where curve crosses 0")
ax.grid(True, alpha=0.3)

# 3. Sharpe vs sigma
ax = axes[2]
for name in strategies:
    ys = [data["grid_results"][f"{s}"][name]["sharpe_trial"] for s in sigmas]
    ax.plot(sigmas, ys, "-o", label=name, lw=1.5, markersize=4)
ax.axvline(2.51, color="k", linestyle="--", alpha=0.4)
ax.set_xlabel("sigma")
ax.set_ylabel("Sharpe (per 100-path trial)")
ax.set_title("Sharpe vs sigma")
ax.grid(True, alpha=0.3)
ax.legend(fontsize=8, loc="best")

# 4. CVaR-5% vs sigma (USD/trial)
ax = axes[3]
for name in strategies:
    ys = [data["grid_results"][f"{s}"][name]["cvar5_trial_usd"] for s in sigmas]
    ax.plot(sigmas, ys, "-o", label=name, lw=1.5, markersize=4)
ax.axvline(2.51, color="k", linestyle="--", alpha=0.4)
ax.set_xlabel("sigma")
ax.set_ylabel("CVaR-5% per trial (USD)")
ax.set_title("CVaR-5% vs sigma (left tail of trial mean)")
ax.grid(True, alpha=0.3)
ax.legend(fontsize=8, loc="best")

plt.tight_layout()
plt.savefig(PNG_PATH, dpi=120)
print(f"Saved plot to {PNG_PATH}")

# ASCII table dumps
print()
print("E[score] in USD per trial:")
print(f"  {'sigma':>6}  " + "  ".join(f"{n:>14}" for n in strategies))
for s in sigmas:
    row = f"  {s:>6.3f}  " + "  ".join(
        f"{data['grid_results'][f'{s}'][n]['mean_usd']:>+14,.0f}" for n in strategies
    )
    print(row)

print()
print("E[7POS] - E[5POS] vs sigma:")
print(f"  {'sigma':>6} {'gap (USD)':>13}")
for s, d in zip(sigmas, diffs):
    print(f"  {s:>6.3f} {d:>+13,.0f}")
