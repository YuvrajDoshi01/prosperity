"""mark14_alpha_v2.py - Deeper validation: spread structure + front-run simulation
in the IMC engine matching model.

KEY question: in the IMC matcher, market_trades print at PRICE = trade price (not our
order price). When Mark 38 takes through book, our resting order at mid +/- 7 will be
hit IF AND ONLY IF mid +/- 7 is the best bid/ask after our post.

The taker hits ALL price levels on his side (per CLAUDE.md tick sequence). So if Mark 38
crosses to mid + 10 (Mark 14's ask), but we post mid + 7 (one inside Mark 14), we are
the BEST ask -> Mark 38 hits us first at price = mid + 7 (we capture +7 vs Mark 14's +8).
We get -1 per fill but bigger fill probability.

Wait: with passive 2-sided MM, M14 posts mid +/- 8. If we post inside at mid +/- 7, we
become best, M38 hits us at +7 instead of M14 at +8. So we GAIN +7 spread (vs not posting
= 0). Mark 14 captures nothing that tick.

But: by stepping inside, we narrow the book M38 sees. He still pays his "+8" target?
Or does the bot react to the new quote?

Per CLAUDE.md: "Bots are NOT reactive to our spread (confirmed zero-delta god-logger)".
So Mark 38 will still cross. He hits OUR quote at mid +/- 7.

Risk: what if Mark 38's order is at price = mid + 10 (his typical aggressive)? Then he'd
sweep through mid + 7, mid + 8, etc. Our edge is +7 (still better than mid + 0).

Question to validate: when our backtester replays trades at mid +/- 7, do we GET filled?
The market_trades csv contains M14<->M38 trades at price = mid + 8. If we post inside,
the IMC matcher in `imc` mode will replay the market trade through OUR best.
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
from collections import Counter

DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round4"


def load_all():
    trades = []
    prices = []
    for d in (1, 2, 3):
        t = pd.read_csv(os.path.join(DATA, f"trades_round_4_day_{d}.csv"), sep=";")
        t["day"] = d
        trades.append(t)
        p = pd.read_csv(os.path.join(DATA, f"prices_round_4_day_{d}.csv"), sep=";")
        p["day"] = d
        prices.append(p)
    return pd.concat(trades, ignore_index=True), pd.concat(prices, ignore_index=True)


def m14_m38_per_trade_economics(trades, prices):
    """For each M14<->M38 trade, compute the price the buyer paid vs ideal mid +/- 7."""
    print("=" * 80)
    print("Mark 14 <-> Mark 38 trade economics + frontrun PnL projection")
    print("=" * 80)
    p_idx = prices.set_index(["day", "timestamp", "product"]).sort_index()
    for sym, want_offset in [("HYDROGEL_PACK", 7), ("VEV_4000", 9)]:
        pair = trades[((trades.buyer == "Mark 14") & (trades.seller == "Mark 38")) |
                      ((trades.buyer == "Mark 38") & (trades.seller == "Mark 14"))]
        pair = pair[pair.symbol == sym].copy()
        records = []
        for _, r in pair.iterrows():
            try:
                row = p_idx.loc[(r.day, r.timestamp, sym)]
            except KeyError:
                continue
            mid = row["mid_price"]; b1 = row["bid_price_1"]; a1 = row["ask_price_1"]
            spread = a1 - b1
            # M38 is taker. If M38 BUYS (he is buyer), we want to SELL inside at mid + want_offset.
            # That ask must be < a1 to be best.
            if r.buyer == "Mark 38":
                cand_ask = mid + want_offset
                feasible = cand_ask < a1
                # Our profit if filled at cand_ask: cand_ask - mid (per share)
                edge = cand_ask - mid if feasible else 0
            else:  # M38 is seller -> sells aggressively. We want to BID inside at mid - want_offset.
                cand_bid = mid - want_offset
                feasible = cand_bid > b1
                edge = mid - cand_bid if feasible else 0
            records.append({
                "day": r.day, "ts": r.timestamp, "qty": r.quantity, "price": r.price,
                "mid": mid, "spread": spread,
                "side": "M38_BUY" if r.buyer == "Mark 38" else "M38_SELL",
                "feasible": feasible, "edge": edge,
            })
        df = pd.DataFrame(records)
        feas = df[df.feasible]
        print(f"\n{sym}: pair trades n={len(df)}, feasible front-run n={len(feas)} ({100*len(feas)/max(len(df),1):.1f}%)")
        print(f"  total qty available: {feas.qty.sum()} | mean qty/trade={feas.qty.mean():.2f}")
        print(f"  per-trade edge mean (paid to us): {feas.edge.mean():.2f}")
        print(f"  TOTAL theoretical edge if we capture all: {(feas.qty * feas.edge).sum():.0f} XIRECs over 3 days")
        # Per day
        for day in (1, 2, 3):
            d = feas[feas.day == day]
            if len(d):
                print(f"    day {day}: n={len(d):4d} qty={d.qty.sum():4d} edge_total={(d.qty*d.edge).sum():.0f}")


def m14_quote_lifetime(trades, prices):
    """Mark 14 posts effectively at every tick. Verify: how often is M14 the best bid/ask?
    We have no order-book attribution but can infer by: when spread=16 on HP, and M14 is
    actively trading, M14 is probably at best bid AND best ask.

    Simpler: count fraction of timestamps where spread is 16 (HP) or 21 (VEV_4000).
    These are 'M14-active' ticks where front-run is feasible.
    """
    print("\n" + "=" * 80)
    print("Mark 14 active-quote ticks (spread structure)")
    print("=" * 80)
    for sym, target_spread in [("HYDROGEL_PACK", 16), ("VEV_4000", 21)]:
        sub = prices[prices["product"] == sym].copy()
        sub["spread"] = sub["ask_price_1"] - sub["bid_price_1"]
        active = (sub["spread"] >= target_spread - 1).sum()
        total = len(sub)
        print(f"  {sym}: spread>={target_spread-1} on {active}/{total} ticks ({100*active/total:.1f}%)")
        # spread histogram
        print(f"    spread hist: {Counter(sub['spread'].astype(int)).most_common(8)}")


def vfe_fade_simulation(trades, prices):
    """Simulate the VFE fade: when M14 trades VFE qty>=N, take opposite at mid +/- 1
    for h=50 ticks. Realistic: bracket the trade timestamp."""
    print("\n" + "=" * 80)
    print("VFE Mark-14 fade simulation (mark-to-mid h-tick later)")
    print("=" * 80)
    p_idx = prices.set_index(["day", "timestamp", "product"]).sort_index()
    sub = trades[(trades.symbol == "VELVETFRUIT_EXTRACT") &
                 ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
    for qty_min in (1, 3, 5, 8):
        for h in (10, 50, 100):
            edges = []
            for _, r in sub.iterrows():
                if r.quantity < qty_min: continue
                # Fade direction: if M14 buys, we sell; we profit if price falls.
                try:
                    mid_now = p_idx.loc[(r.day, r.timestamp, "VELVETFRUIT_EXTRACT"), "mid_price"]
                    fwd_ts = r.timestamp + 100 * h
                    if fwd_ts > 999900: continue
                    mid_fwd = p_idx.loc[(r.day, fwd_ts, "VELVETFRUIT_EXTRACT"), "mid_price"]
                except KeyError:
                    continue
                # If we fade (we sell when M14 buys), our PnL per unit = mid_now - mid_fwd
                if r.buyer == "Mark 14":
                    pnl = mid_now - mid_fwd  # we sold @ mid_now, mark-to-mid_fwd
                else:
                    pnl = mid_fwd - mid_now  # we bought @ mid_now
                edges.append(pnl * r.quantity)
            a = np.array(edges)
            if len(a) >= 20:
                print(f"  qty_min={qty_min}, h={h}: n={len(a):3d}, total_pnl={a.sum():+.0f}, "
                      f"mean_pnl/trade={a.mean():+.2f}")


def main():
    print("Loading R4 trades + prices...")
    trades, prices = load_all()
    m14_m38_per_trade_economics(trades, prices)
    m14_quote_lifetime(trades, prices)
    vfe_fade_simulation(trades, prices)


if __name__ == "__main__":
    main()
