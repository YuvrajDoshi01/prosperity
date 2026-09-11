#!/usr/bin/env python3
"""Generate charts for Round 3 VEV options analysis."""

import csv
import os
import math
from collections import defaultdict
from statistics import mean

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not found — generating ASCII-art charts instead.")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
DAYS = [0, 1, 2]
TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}
R = 0.0

def norm_cdf(x):
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def implied_vol(market_price, S, K, T, r, tol=1e-6, max_iter=200):
    if T <= 1e-10 or market_price <= max(0, S - K) + 1e-8:
        return None
    sigma = 0.3
    for _ in range(max_iter):
        if sigma <= 0.001: sigma = 0.001
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        vega = S * norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12: return None
        diff = price - market_price
        sigma -= diff / vega
        if abs(diff) < tol:
            return sigma if 0.001 < sigma < 5.0 else None
    return None

def load_prices(day):
    path = os.path.join(DATA_DIR, f'prices_round_3_day_{day}.csv')
    data = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product']
            ts = int(row['timestamp'])
            mid = float(row['mid_price']) if row['mid_price'] else None
            bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
            ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
            if mid is not None:
                data[product].append((ts, mid, bid1, ask1))
    return data

def load_trades(day):
    path = os.path.join(DATA_DIR, f'trades_round_3_day_{day}.csv')
    data = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            sym = row['symbol']
            ts = int(row['timestamp'])
            price = float(row['price'])
            qty = int(row['quantity'])
            data[sym].append((ts, price, qty))
    return data


def generate_charts():
    if not HAS_MPL:
        print("Skipping chart generation (no matplotlib).")
        return

    all_prices = {}
    all_trades = {}
    for d in DAYS:
        all_prices[d] = load_prices(d)
        all_trades[d] = load_trades(d)

    colors = plt.cm.tab10.colors

    # ── CHART 1: Underlying price + trades ─────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(18, 12), sharex=False)
    fig.suptitle('VELVETFRUIT_EXTRACT — Mid Price & Trades (Days 0-2)', fontsize=16, fontweight='bold')

    for d in DAYS:
        ax = axes[d]
        ve_data = all_prices[d].get('VELVETFRUIT_EXTRACT', [])
        ts = [x[0]/1000 for x in ve_data]  # convert to seconds
        mids = [x[1] for x in ve_data]
        bids = [x[2] for x in ve_data if x[2]]
        asks = [x[3] for x in ve_data if x[3]]

        ax.plot(ts, mids, color='steelblue', linewidth=0.5, alpha=0.8, label='Mid Price')
        ax.fill_between(ts, [x[2] if x[2] else x[1] for x in ve_data],
                        [x[3] if x[3] else x[1] for x in ve_data],
                        alpha=0.15, color='steelblue', label='Bid-Ask Spread')

        # Overlay trades
        trades = all_trades[d].get('VELVETFRUIT_EXTRACT', [])
        if trades:
            t_ts = [t[0]/1000 for t in trades]
            t_prices = [t[1] for t in trades]
            t_sizes = [t[2] for t in trades]
            ax.scatter(t_ts, t_prices, s=[max(3, q*2) for q in t_sizes],
                      c='red', alpha=0.4, zorder=5, label=f'Trades (n={len(trades)})')

        ax.set_title(f'Day {d} — TTE={TTE_MAP[d]*365:.0f}d', fontsize=12)
        ax.set_ylabel('Price')
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time (seconds)')
    plt.tight_layout()
    path1 = os.path.join(OUT_DIR, 'chart_underlying_prices.png')
    plt.savefig(path1, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path1}")
    plt.close()

    # ── CHART 2: Option mid prices by strike ───────────────────────────────────
    active_strikes = [5000, 5100, 5200, 5300, 5400, 5500]
    fig, axes = plt.subplots(3, 1, figsize=(18, 14), sharex=False)
    fig.suptitle('VEV Option Mid Prices by Strike (Days 0-2)', fontsize=16, fontweight='bold')

    for d in DAYS:
        ax = axes[d]
        for idx, k in enumerate(active_strikes):
            prod = f'VEV_{k}'
            entries = all_prices[d].get(prod, [])
            if entries:
                ts = [x[0]/1000 for x in entries]
                mids = [x[1] for x in entries]
                ax.plot(ts, mids, linewidth=0.8, alpha=0.8, color=colors[idx], label=f'K={k}')

        ax.set_title(f'Day {d} — TTE={TTE_MAP[d]*365:.0f}d', fontsize=12)
        ax.set_ylabel('Option Mid Price')
        ax.legend(loc='upper right', fontsize=8, ncol=3)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time (seconds)')
    plt.tight_layout()
    path2 = os.path.join(OUT_DIR, 'chart_option_prices.png')
    plt.savefig(path2, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path2}")
    plt.close()

    # ── CHART 3: Option trades scatter ─────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(18, 14), sharex=False)
    fig.suptitle('VEV Option Trades by Strike (Days 0-2)', fontsize=16, fontweight='bold')

    for d in DAYS:
        ax = axes[d]
        for idx, k in enumerate(active_strikes):
            prod = f'VEV_{k}'
            trades = all_trades[d].get(prod, [])
            if trades:
                t_ts = [t[0]/1000 for t in trades]
                t_prices = [t[1] for t in trades]
                t_sizes = [max(8, t[2]*4) for t in trades]
                ax.scatter(t_ts, t_prices, s=t_sizes, alpha=0.5,
                          color=colors[idx], label=f'K={k} (n={len(trades)})', edgecolors='black', linewidth=0.3)

        ax.set_title(f'Day {d}', fontsize=12)
        ax.set_ylabel('Trade Price')
        ax.legend(loc='upper right', fontsize=8, ncol=3)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time (seconds)')
    plt.tight_layout()
    path3 = os.path.join(OUT_DIR, 'chart_option_trades.png')
    plt.savefig(path3, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path3}")
    plt.close()

    # ── CHART 4: IV Smile across days ──────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.suptitle('Implied Volatility Smile (Days 0-2)', fontsize=16, fontweight='bold')

    day_colors = ['#2196F3', '#FF9800', '#4CAF50']
    for d in DAYS:
        T = TTE_MAP[d]
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000
        ts_to_S = {x[0]: x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])}

        plot_k, plot_iv = [], []
        for k in STRIKES:
            prod = f'VEV_{k}'
            ivs = []
            for x in all_prices[d].get(prod, []):
                S = ts_to_S.get(x[0], S_avg)
                if x[1] > 0.5:
                    iv = implied_vol(x[1], S, k, T, R)
                    if iv: ivs.append(iv)
            if ivs:
                plot_k.append(k)
                plot_iv.append(mean(ivs) * 100)

        ax.plot(plot_k, plot_iv, 'o-', color=day_colors[d], linewidth=2,
                markersize=8, label=f'Day {d} (TTE={T*365:.0f}d)')

    ax.axvline(x=5250, color='gray', linestyle='--', alpha=0.5, label='~ATM (S≈5250)')
    ax.set_xlabel('Strike Price', fontsize=12)
    ax.set_ylabel('Implied Volatility (%)', fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    path4 = os.path.join(OUT_DIR, 'chart_iv_smile.png')
    plt.savefig(path4, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path4}")
    plt.close()

    # ── CHART 5: BSM Mispricing (market - BSM flat vol) ────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
    fig.suptitle('BSM Mispricing: Market Mid − BSM(flat vol)', fontsize=16, fontweight='bold')

    for d in DAYS:
        ax = axes[d]
        T = TTE_MAP[d]
        ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
        S_avg = mean(ve_mids) if ve_mids else 5000
        ts_to_S = {x[0]: x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])}

        # Compute flat vol (ATM average)
        atm_ivs = []
        for k in STRIKES:
            if abs(k - S_avg) < 500:
                prod = f'VEV_{k}'
                for x in all_prices[d].get(prod, []):
                    S = ts_to_S.get(x[0], S_avg)
                    if x[1] > 0.5:
                        iv = implied_vol(x[1], S, k, T, R)
                        if iv: atm_ivs.append(iv)
        flat_vol = mean(atm_ivs) if atm_ivs else 0.22

        ks, diffs = [], []
        for k in STRIKES:
            prod = f'VEV_{k}'
            opt_mids = [x[1] for x in all_prices[d].get(prod, [])]
            if opt_mids:
                mkt_mid = mean(opt_mids)
                d1 = (math.log(S_avg / k) + 0.5 * flat_vol**2 * T) / (flat_vol * math.sqrt(T))
                d2 = d1 - flat_vol * math.sqrt(T)
                bsm_flat = S_avg * norm_cdf(d1) - k * norm_cdf(d2)
                ks.append(k)
                diffs.append(mkt_mid - bsm_flat)

        bar_colors = ['green' if d > 0 else 'red' for d in diffs]
        ax.bar(range(len(ks)), diffs, color=bar_colors, alpha=0.7, edgecolor='black', linewidth=0.5)
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels([str(k) for k in ks], rotation=45, fontsize=8)
        ax.set_title(f'Day {d} (flat vol={flat_vol*100:.1f}%)', fontsize=11)
        ax.axhline(0, color='black', linewidth=0.8)
        ax.grid(True, alpha=0.3, axis='y')

    axes[0].set_ylabel('Market Mid − BSM Fair Value')
    plt.tight_layout()
    path5 = os.path.join(OUT_DIR, 'chart_bsm_mispricing.png')
    plt.savefig(path5, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path5}")
    plt.close()

    # ── CHART 6: Greeks heatmap ────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Greeks Across Strikes (Day 1, TTE=7d)', fontsize=16, fontweight='bold')

    d = 1
    T = TTE_MAP[d]
    ve_mids = [x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])]
    S_avg = mean(ve_mids)
    ts_to_S = {x[0]: x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])}

    greek_data = {'delta': [], 'gamma': [], 'vega': [], 'theta': []}
    valid_strikes = []

    for k in STRIKES:
        prod = f'VEV_{k}'
        ivs = []
        for x in all_prices[d].get(prod, []):
            S = ts_to_S.get(x[0], S_avg)
            if x[1] > 0.5:
                iv = implied_vol(x[1], S, k, T, R)
                if iv: ivs.append(iv)
        if not ivs:
            continue
        sigma = mean(ivs)
        sqrtT = math.sqrt(T)
        d1 = (math.log(S_avg / k) + 0.5 * sigma**2 * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        valid_strikes.append(k)
        greek_data['delta'].append(norm_cdf(d1))
        greek_data['gamma'].append(norm_pdf(d1) / (S_avg * sigma * sqrtT))
        greek_data['vega'].append(S_avg * norm_pdf(d1) * sqrtT / 100)
        greek_data['theta'].append((-(S_avg * norm_pdf(d1) * sigma) / (2 * sqrtT)) / 365)

    for ax, (name, vals) in zip(axes.flat, greek_data.items()):
        color = {'delta': '#2196F3', 'gamma': '#FF5722', 'vega': '#4CAF50', 'theta': '#9C27B0'}[name]
        ax.bar(range(len(valid_strikes)), vals, color=color, alpha=0.7, edgecolor='black', linewidth=0.5)
        ax.set_xticks(range(len(valid_strikes)))
        ax.set_xticklabels([str(k) for k in valid_strikes], rotation=45, fontsize=9)
        ax.set_title(name.upper(), fontsize=13, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    path6 = os.path.join(OUT_DIR, 'chart_greeks.png')
    plt.savefig(path6, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path6}")
    plt.close()

    # ── CHART 7: Intrinsic value arb (VEV_4000) ───────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(18, 10))
    fig.suptitle('VEV_4000 Intrinsic Value Arbitrage: Bid vs Intrinsic (S − 4000)', fontsize=14, fontweight='bold')

    for d in DAYS:
        ax = axes[d]
        ve_ts = {x[0]: x[1] for x in all_prices[d].get('VELVETFRUIT_EXTRACT', [])}
        vev_data = all_prices[d].get('VEV_4000', [])

        ts_list, bid_list, intrinsic_list, gap_list = [], [], [], []
        for x in vev_data:
            S = ve_ts.get(x[0])
            if S and x[2]:
                intrinsic = max(0, S - 4000)
                ts_list.append(x[0] / 1000)
                bid_list.append(x[2])
                intrinsic_list.append(intrinsic)
                gap_list.append(intrinsic - x[2])

        ax.plot(ts_list, intrinsic_list, color='green', linewidth=0.7, alpha=0.8, label='Intrinsic (S−4000)')
        ax.plot(ts_list, bid_list, color='red', linewidth=0.7, alpha=0.8, label='VEV_4000 Bid')
        ax.fill_between(ts_list, bid_list, intrinsic_list, alpha=0.2, color='orange', label='Arb Gap')
        ax.set_title(f'Day {d}', fontsize=11)
        ax.set_ylabel('Price')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel('Time (seconds)')
    plt.tight_layout()
    path7 = os.path.join(OUT_DIR, 'chart_intrinsic_arb.png')
    plt.savefig(path7, dpi=150, bbox_inches='tight')
    print(f"  Saved: {path7}")
    plt.close()

    print(f"\n  All charts saved to: {OUT_DIR}/")


if __name__ == '__main__':
    generate_charts()
