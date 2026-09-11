"""IV visualization for R3 vouchers — generates 4 PNGs.

Plots:
  1. smile_per_day.png       — IV vs log-moneyness scatter + quadratic fit per day.
  2. iv_timeseries.png       — IV(t) per strike per day.
  3. delta_iv_distribution.png — Hist of ΔIV + AR1 scatter (ΔIV_t vs ΔIV_{t-1}).
  4. smile_residuals.png     — Per-strike residual time series.

Run: `python -X utf8 trader-logic/round-3/notes/iv_visualization.py`
Output: trader-logic/round-3/notes/iv_plots/*.png
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import matplotlib.pyplot as plt
import numpy as np

_ND = NormalDist()

BASE = Path(__file__).resolve().parents[3] / "prosperity4bt" / "resources" / "round3"
OUT = Path(__file__).parent / "iv_plots"
OUT.mkdir(exist_ok=True)

DAYS = [0, 1, 2]
TTE_DAYS = {0: 8, 1: 7, 2: 6}
TTE_YEAR = 250.0
UNDERLYING = "VELVETFRUIT_EXTRACT"
STRIKES_IV = [5000, 5100, 5200, 5300, 5400]
SYM = {k: f"VEV_{k}" for k in STRIKES_IV}
DAY_COLOR = {0: "tab:blue", 1: "tab:orange", 2: "tab:green"}


def bs_call(spot, K, T, vol):
    if T <= 0 or vol <= 0:
        return max(spot - K, 0.0)
    d1 = (math.log(spot / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return spot * _ND.cdf(d1) - K * _ND.cdf(d2)


def implied_vol(mkt, spot, K, T, lo=1e-4, hi=5.0):
    intr = max(spot - K, 0.0)
    if mkt <= intr + 1e-6 or T <= 0 or mkt >= spot:
        return float("nan")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_call(spot, K, T, mid) < mkt:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def load_day(day):
    prices = defaultdict(list)
    with open(BASE / f"prices_round_3_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if not row["mid_price"]:
                continue
            try:
                prices[row["product"]].append((int(row["timestamp"]), float(row["mid_price"])))
            except ValueError:
                continue
    return prices


def compute_all_iv():
    """{(day, K): [(ts, iv, m), ...]} where m = log(K/spot)/sqrt(T)."""
    out = defaultdict(list)
    for day in DAYS:
        prices = load_day(day)
        und = dict(prices.get(UNDERLYING, []))
        for K in STRIKES_IV:
            for ts, mid in prices.get(SYM[K], []):
                spot = und.get(ts)
                if spot is None:
                    continue
                T = (TTE_DAYS[day] - ts / 1_000_000.0) / TTE_YEAR
                iv = implied_vol(mid, spot, K, T)
                if math.isnan(iv) or T <= 0:
                    continue
                m = math.log(K / spot) / math.sqrt(T)
                out[(day, K)].append((ts, iv, m))
    return out


# ─── Plot 1: smile per day ─────────────────────────────────────────────

def plot_smile_per_day(iv_data):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax, day in zip(axes, DAYS):
        # Sample every 100th tick to avoid 50k points
        ms_all, ivs_all = [], []
        for K in STRIKES_IV:
            data = iv_data.get((day, K), [])[::100]
            ms = [d[2] for d in data]
            ivs = [d[1] for d in data]
            ax.scatter(ms, ivs, s=8, alpha=0.5, label=f"K={K}")
            ms_all.extend(ms); ivs_all.extend(ivs)
        # Quadratic fit overlay
        if ms_all:
            ms_arr = np.array(ms_all)
            ivs_arr = np.array(ivs_all)
            coefs = np.polyfit(ms_arr, ivs_arr, 2)
            mx = np.linspace(ms_arr.min(), ms_arr.max(), 100)
            ax.plot(mx, np.polyval(coefs, mx), "k--", lw=2, alpha=0.7,
                    label=f"a={coefs[0]:.3f} b={coefs[1]:.3f} c={coefs[2]:.3f}")
        ax.set_title(f"Day {day} (TTE={TTE_DAYS[day]}d)")
        ax.set_xlabel("log-moneyness m = ln(K/S)/√T")
        if day == 0:
            ax.set_ylabel("Implied Volatility")
        ax.legend(loc="best", fontsize=8)
        ax.grid(alpha=0.3)
    fig.suptitle("R3 Voucher Smile — IV vs Moneyness (per day)")
    fig.tight_layout()
    fig.savefig(OUT / "smile_per_day.png", dpi=120)
    plt.close(fig)
    print(f"  saved {OUT / 'smile_per_day.png'}")


# ─── Plot 2: IV time series ────────────────────────────────────────────

def plot_iv_timeseries(iv_data):
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
    for ax, day in zip(axes, DAYS):
        for K in STRIKES_IV:
            data = iv_data.get((day, K), [])
            ts = [d[0] for d in data]
            ivs = [d[1] for d in data]
            ax.plot(ts, ivs, lw=0.6, alpha=0.75, label=f"K={K}")
        ax.set_title(f"Day {day} — IV time series (TTE={TTE_DAYS[day]}d)")
        ax.set_ylabel("IV")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("timestamp")
    fig.suptitle("R3 Voucher IV(t) — short half-life mean reversion visible")
    fig.tight_layout()
    fig.savefig(OUT / "iv_timeseries.png", dpi=120)
    plt.close(fig)
    print(f"  saved {OUT / 'iv_timeseries.png'}")


# ─── Plot 3: ΔIV alternation (AR1=-0.5) ────────────────────────────────

def plot_delta_iv_distribution(iv_data):
    fig, axes = plt.subplots(2, len(STRIKES_IV), figsize=(18, 8))
    # Top row: histogram of ΔIV per strike (pooled across days)
    # Bottom row: scatter ΔIV_{t-1} vs ΔIV_t per strike (AR1 visualization)
    for col, K in enumerate(STRIKES_IV):
        all_div = []
        scatter_x, scatter_y = [], []
        for day in DAYS:
            ivs = [d[1] for d in iv_data.get((day, K), [])]
            if len(ivs) < 3:
                continue
            div = [ivs[i + 1] - ivs[i] for i in range(len(ivs) - 1)]
            all_div.extend(div)
            for i in range(1, len(div)):
                scatter_x.append(div[i - 1])
                scatter_y.append(div[i])
        if all_div:
            axes[0, col].hist(all_div, bins=80, color=DAY_COLOR[0], alpha=0.7)
            axes[0, col].set_title(f"VEV_{K}\nΔIV histogram")
            axes[0, col].axvline(0, color="k", lw=0.5)
            axes[0, col].set_xlabel("ΔIV")
            axes[0, col].grid(alpha=0.3)
            # AR1 scatter
            axes[1, col].scatter(scatter_x, scatter_y, s=2, alpha=0.3)
            # Compute and plot regression line
            sx = np.array(scatter_x); sy = np.array(scatter_y)
            mx, my = sx.mean(), sy.mean()
            num = ((sx - mx) * (sy - my)).sum()
            den = ((sx - mx) ** 2).sum()
            if den > 1e-15:
                slope = num / den
                xs = np.linspace(sx.min(), sx.max(), 50)
                axes[1, col].plot(xs, slope * (xs - mx) + my, "r-", lw=1.5,
                                  label=f"AR1={slope:.3f}")
                axes[1, col].legend(fontsize=8, loc="upper right")
            axes[1, col].set_title(f"ΔIV(t-1) vs ΔIV(t)")
            axes[1, col].set_xlabel("ΔIV(t-1)")
            axes[1, col].axhline(0, color="k", lw=0.5)
            axes[1, col].axvline(0, color="k", lw=0.5)
            axes[1, col].grid(alpha=0.3)
        if col == 0:
            axes[0, col].set_ylabel("count")
            axes[1, col].set_ylabel("ΔIV(t)")
    fig.suptitle("R3 ΔIV distributions and AR1 alternation (expect AR1 ≈ −0.5)")
    fig.tight_layout()
    fig.savefig(OUT / "delta_iv_distribution.png", dpi=120)
    plt.close(fig)
    print(f"  saved {OUT / 'delta_iv_distribution.png'}")


# ─── Plot 4: smile residuals time series ───────────────────────────────

def plot_smile_residuals(iv_data):
    fig, axes = plt.subplots(len(STRIKES_IV), 1, figsize=(14, 10), sharex=True)
    for row, K in enumerate(STRIKES_IV):
        for day in DAYS:
            # Compute smile per tick using all 5 strikes simultaneously
            # Then residual per tick = iv_K - fit(m_K)
            day_data_by_strike = {Kk: dict([(d[0], (d[1], d[2])) for d in iv_data.get((day, Kk), [])])
                                  for Kk in STRIKES_IV}
            ts_list = sorted(day_data_by_strike[K].keys())
            residuals = []
            ts_used = []
            for ts in ts_list:
                ivs_per_strike = []
                ms_per_strike = []
                target_iv = None; target_m = None
                for Kk in STRIKES_IV:
                    if ts in day_data_by_strike[Kk]:
                        iv, m = day_data_by_strike[Kk][ts]
                        ivs_per_strike.append(iv); ms_per_strike.append(m)
                        if Kk == K:
                            target_iv = iv; target_m = m
                if target_iv is None or len(ivs_per_strike) < 4:
                    continue
                ms_arr = np.array(ms_per_strike)
                ivs_arr = np.array(ivs_per_strike)
                coefs = np.polyfit(ms_arr, ivs_arr, 2)
                fit = np.polyval(coefs, target_m)
                residuals.append(target_iv - fit)
                ts_used.append(ts)
            axes[row].plot(ts_used, residuals, lw=0.5, alpha=0.7,
                           color=DAY_COLOR[day], label=f"day {day}")
        axes[row].axhline(0, color="k", lw=0.5)
        axes[row].set_title(f"VEV_{K} — smile residual (IV − fit)")
        axes[row].set_ylabel("residual")
        axes[row].legend(loc="upper right", fontsize=8)
        axes[row].grid(alpha=0.3)
    axes[-1].set_xlabel("timestamp")
    fig.suptitle("R3 Smile Residuals per Strike (mean-reversion expected)")
    fig.tight_layout()
    fig.savefig(OUT / "smile_residuals.png", dpi=120)
    plt.close(fig)
    print(f"  saved {OUT / 'smile_residuals.png'}")


def main():
    print("Computing IV across all 3 days x 5 strikes...")
    iv_data = compute_all_iv()
    n_total = sum(len(v) for v in iv_data.values())
    print(f"  {n_total} IV points computed")
    print("Generating plots...")
    plot_smile_per_day(iv_data)
    plot_iv_timeseries(iv_data)
    plot_delta_iv_distribution(iv_data)
    plot_smile_residuals(iv_data)
    print(f"DONE. Plots in {OUT}")


if __name__ == "__main__":
    main()
