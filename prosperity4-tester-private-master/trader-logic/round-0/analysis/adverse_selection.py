"""
Module 3: Adverse Selection Classifier (Offline)

Labels historical fills as "toxic" or "benign" based on post-trade price movement.
When multiple bots exist (Round 1+), correlates toxicity with bot identity.

Run offline: python analysis/adverse_selection.py
Outputs: analysis/outputs/toxicity_analysis.json

For the tutorial round (single random taker), this establishes baseline toxicity rates.
For Round 1+, this identifies WHICH bots to avoid and which to seek.
"""

import csv
import json
import os
import sys
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                        "prosperity4bt", "resources", "round0")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


def load_prices(day):
    """Load mid prices indexed by (product, timestamp)."""
    mids = {}
    fname = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    with open(fname) as f:
        for row in csv.DictReader(f, delimiter=';'):
            mids[(row['product'], int(row['timestamp']))] = float(row['mid_price'])
    return mids


def load_trades(day):
    """Load all trades."""
    trades = []
    fname = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    with open(fname) as f:
        for row in csv.DictReader(f, delimiter=';'):
            trades.append({
                'timestamp': int(row['timestamp']),
                'product': row['symbol'],
                'price': float(row['price']),
                'quantity': int(row['quantity']),
                'buyer': row.get('buyer', ''),
                'seller': row.get('seller', ''),
            })
    return trades


def classify_fills(trades, mids, lookback_windows=[500, 1000, 2000]):
    """
    For each trade, compute post-trade price movement at various horizons.
    Label as toxic if price moves against the passive side.
    """
    results = defaultdict(lambda: defaultdict(list))  # product -> window -> list of dicts

    for trade in trades:
        product = trade['product']
        ts = trade['timestamp']
        price = trade['price']
        mid_now = mids.get((product, ts))
        if mid_now is None:
            continue

        # Determine taker side
        is_taker_buy = price >= mid_now  # taker bought (hit ask)

        for window in lookback_windows:
            future_ts = ts + window
            # Find closest future mid
            future_mid = None
            for offset in range(0, window + 200, 100):
                future_mid = mids.get((product, ts + offset))
                if future_mid is not None and offset >= window:
                    break
            if future_mid is None:
                continue

            # PnL impact for the PASSIVE side (us as market maker)
            if is_taker_buy:
                # We sold to the taker. Adverse if price goes UP after (we sold too cheap)
                passive_pnl = price - future_mid
            else:
                # We bought from the taker. Adverse if price goes DOWN after (we bought too high)
                passive_pnl = future_mid - price

            is_toxic = passive_pnl < -0.5  # threshold: half a tick adverse

            results[product][window].append({
                'timestamp': ts,
                'price': price,
                'quantity': trade['quantity'],
                'taker_side': 'BUY' if is_taker_buy else 'SELL',
                'future_mid': future_mid,
                'passive_pnl': passive_pnl,
                'is_toxic': is_toxic,
                'buyer': trade['buyer'],
                'seller': trade['seller'],
            })

    return results


def summarize(results):
    """Compute toxicity rates per product per window."""
    summary = {}
    for product, windows in results.items():
        summary[product] = {}
        for window, fills in windows.items():
            n = len(fills)
            toxic = sum(1 for f in fills if f['is_toxic'])
            benign = n - toxic
            mean_pnl = sum(f['passive_pnl'] for f in fills) / n if n else 0
            toxic_mean = sum(f['passive_pnl'] for f in fills if f['is_toxic']) / toxic if toxic else 0
            benign_mean = sum(f['passive_pnl'] for f in fills if not f['is_toxic']) / benign if benign else 0

            # Break down by taker side
            buy_fills = [f for f in fills if f['taker_side'] == 'BUY']
            sell_fills = [f for f in fills if f['taker_side'] == 'SELL']

            summary[product][str(window)] = {
                'n_fills': n,
                'toxicity_rate': toxic / n if n else 0,
                'mean_passive_pnl': mean_pnl,
                'toxic_mean_pnl': toxic_mean,
                'benign_mean_pnl': benign_mean,
                'buy_taker_toxicity': sum(1 for f in buy_fills if f['is_toxic']) / len(buy_fills) if buy_fills else 0,
                'sell_taker_toxicity': sum(1 for f in sell_fills if f['is_toxic']) / len(sell_fills) if sell_fills else 0,
            }
    return summary


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_summaries = {}
    for day in [-2, -1]:
        print(f"\n=== Day {day} ===")
        mids = load_prices(day)
        trades = load_trades(day)
        results = classify_fills(trades, mids)
        day_summary = summarize(results)
        all_summaries[f"day_{day}"] = day_summary

        for product, windows in day_summary.items():
            print(f"\n  {product}:")
            for window, stats in sorted(windows.items(), key=lambda x: int(x[0])):
                print(f"    {window}ms: n={stats['n_fills']}, "
                      f"toxic={stats['toxicity_rate']:.1%}, "
                      f"mean_pnl={stats['mean_passive_pnl']:+.2f}, "
                      f"buy_toxic={stats['buy_taker_toxicity']:.1%}, "
                      f"sell_toxic={stats['sell_taker_toxicity']:.1%}")

    # Save results
    output_path = os.path.join(OUTPUT_DIR, "toxicity_analysis.json")
    with open(output_path, 'w') as f:
        json.dump(all_summaries, f, indent=2)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
