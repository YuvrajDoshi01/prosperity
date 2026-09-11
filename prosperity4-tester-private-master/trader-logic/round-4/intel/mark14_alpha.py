"""mark14_alpha.py - Mark 14 reverse engineering for R4 v6.

Goals:
  1. Mark 14 quote prediction: HP/VEV_4000 mid +/- 8 / mid +/- 10 - is this stable?
     Can we POST 1 tick AHEAD?
  2. HP/VEV_4000 spread skim: interpose between Mark 14 and Mark 38.
  3. Mark 14 directional drift signal.
  4. VFE Mark 14 fade.
  5. Cross-product Mark 14 correlation.
"""
from __future__ import annotations
import os
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

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


def build_mid_lookup(prices):
    """Index (day, ts, product) -> mid, bid1, ask1."""
    p = prices[["day", "timestamp", "product", "bid_price_1", "ask_price_1", "mid_price"]].copy()
    p = p.set_index(["day", "timestamp", "product"]).sort_index()
    return p


def mark14_offset_distribution(trades, mid_lookup):
    """For HP and VEV_4000, compute Mark14 trade price - mid_at_trade.
    Both as buyer (passive bid) and seller (passive ask)."""
    print("=" * 80)
    print("[1] Mark 14 quote offset distribution (HP, VEV_4000)")
    print("=" * 80)
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        sub = trades[(trades.symbol == sym) &
                     ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
        offsets_buy = []
        offsets_sell = []
        for _, r in sub.iterrows():
            try:
                mid = mid_lookup.loc[(r.day, r.timestamp, sym), "mid_price"]
            except KeyError:
                continue
            if r.buyer == "Mark 14":
                offsets_buy.append(r.price - mid)  # negative = below mid (passive bid)
            elif r.seller == "Mark 14":
                offsets_sell.append(r.price - mid)  # positive = above mid (passive ask)
        ob = np.array(offsets_buy)
        os_ = np.array(offsets_sell)
        print(f"\n{sym}:")
        print(f"  M14 BUYER  (passive bid): n={len(ob):4d} mean={ob.mean():+.2f} std={ob.std():.2f} "
              f"min={ob.min():+.1f} max={ob.max():+.1f}")
        print(f"  M14 SELLER (passive ask): n={len(os_):4d} mean={os_.mean():+.2f} std={os_.std():.2f} "
              f"min={os_.min():+.1f} max={os_.max():+.1f}")
        # frequency table of integer offsets
        print(f"  BUY  offset hist: {Counter([int(round(x)) for x in ob]).most_common(8)}")
        print(f"  SELL offset hist: {Counter([int(round(x)) for x in os_]).most_common(8)}")


def m14_offset_stationarity(trades, mid_lookup):
    """Does the offset drift across the day or across days? Test by day and quantile."""
    print("\n" + "=" * 80)
    print("[1b] Mark 14 offset stationarity by day")
    print("=" * 80)
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        for day in (1, 2, 3):
            sub = trades[(trades.symbol == sym) &
                         (trades.day == day) &
                         ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))]
            offs = []
            for _, r in sub.iterrows():
                try:
                    mid = mid_lookup.loc[(r.day, r.timestamp, sym), "mid_price"]
                except KeyError:
                    continue
                if r.buyer == "Mark 14":
                    offs.append(("BUY", r.price - mid))
                else:
                    offs.append(("SELL", r.price - mid))
            buy_offs = np.array([o for s, o in offs if s == "BUY"])
            sell_offs = np.array([o for s, o in offs if s == "SELL"])
            print(f"  {sym:13s} day {day}: buy mean={buy_offs.mean() if len(buy_offs) else float('nan'):+.2f} "
                  f"(n={len(buy_offs)})  sell mean={sell_offs.mean() if len(sell_offs) else float('nan'):+.2f} "
                  f"(n={len(sell_offs)})")


def m14_m38_pair_dynamics(trades, mid_lookup):
    """When does the M14<->M38 pair fire vs not? Conditional on spread."""
    print("\n" + "=" * 80)
    print("[2] Mark 14 <-> Mark 38 pair dynamics + spread context")
    print("=" * 80)
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        pair = trades[((trades.buyer == "Mark 14") & (trades.seller == "Mark 38")) |
                      ((trades.buyer == "Mark 38") & (trades.seller == "Mark 14"))]
        pair = pair[pair.symbol == sym].copy()
        spreads = []
        for _, r in pair.iterrows():
            try:
                row = mid_lookup.loc[(r.day, r.timestamp, sym)]
                spreads.append(row["ask_price_1"] - row["bid_price_1"])
            except KeyError:
                pass
        sp = np.array(spreads)
        print(f"\n{sym}: pair trades n={len(pair)}")
        print(f"  spread at fill: mean={sp.mean():.2f} std={sp.std():.2f} min={sp.min():.0f} max={sp.max():.0f}")
        print(f"  spread hist: {Counter(sp.astype(int)).most_common(10)}")


def m14_directional_shift(trades, mid_lookup):
    """Is there an alpha when Mark 14's net flow shifts?
    Compute rolling net qty (window N) and forward h-tick mid return."""
    print("\n" + "=" * 80)
    print("[3] Mark 14 directional drift: rolling net qty -> forward mid return")
    print("=" * 80)
    for sym in ("HYDROGEL_PACK", "VEV_4000", "VELVETFRUIT_EXTRACT"):
        sub = trades[(trades.symbol == sym) &
                     ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
        sub = sub.sort_values(["day", "timestamp"]).reset_index(drop=True)
        # M14's signed qty: +qty if he buys, -qty if he sells.
        sub["m14_signed"] = np.where(sub.buyer == "Mark 14", sub.quantity, -sub.quantity)
        for window in (10, 50, 200):
            sub[f"net_{window}"] = sub.groupby("day")["m14_signed"].transform(
                lambda s: s.rolling(window, min_periods=1).sum())
        # forward mid at h ticks
        for h in (10, 50, 100):
            fwd = []
            now = []
            for _, r in sub.iterrows():
                try:
                    mid_now = mid_lookup.loc[(r.day, r.timestamp, sym), "mid_price"]
                    fwd_ts = r.timestamp + 100 * h
                    if fwd_ts > 999900:
                        fwd.append(np.nan); now.append(np.nan); continue
                    mid_fwd = mid_lookup.loc[(r.day, fwd_ts, sym), "mid_price"]
                    fwd.append(mid_fwd - mid_now); now.append(mid_now)
                except KeyError:
                    fwd.append(np.nan); now.append(np.nan)
            sub[f"fwd_{h}"] = fwd
        # corr(net_w, fwd_h)
        line = f"  {sym:25s}"
        for w in (10, 50, 200):
            for h in (10, 50, 100):
                col_n = f"net_{w}"
                col_f = f"fwd_{h}"
                df = sub[[col_n, col_f]].dropna()
                if len(df) > 30:
                    c = df.corr().iloc[0, 1]
                    line += f"  w{w}h{h}={c:+.3f}"
        print(line)


def m14_vfe_fade(trades, mid_lookup):
    """For VFE specifically: does Mark 14 lose money? Can we fade individual trades?"""
    print("\n" + "=" * 80)
    print("[4] Mark 14 VFE fade analysis")
    print("=" * 80)
    sub = trades[(trades.symbol == "VELVETFRUIT_EXTRACT") &
                 ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
    print(f"  Mark 14 VFE trades: n={len(sub)}")
    # signed return: if M14 bought, fwd_return follows him. We FADE => we go opposite.
    # Edge for fade = -mean(fwd_return signed by M14 direction)
    for h in (10, 50, 100, 500):
        rets = []
        for _, r in sub.iterrows():
            try:
                mid_now = mid_lookup.loc[(r.day, r.timestamp, "VELVETFRUIT_EXTRACT"), "mid_price"]
                fwd_ts = r.timestamp + 100 * h
                if fwd_ts > 999900: continue
                mid_fwd = mid_lookup.loc[(r.day, fwd_ts, "VELVETFRUIT_EXTRACT"), "mid_price"]
                signed = (mid_fwd - mid_now) if r.buyer == "Mark 14" else -(mid_fwd - mid_now)
                rets.append(signed)
            except KeyError:
                continue
        a = np.array(rets)
        n = len(a)
        if n == 0:
            continue
        mean = a.mean()
        sd = a.std()
        t = mean / (sd / np.sqrt(n)) if sd > 0 else 0
        # Fade edge = -mean (if M14 loses, our anti-trade wins).
        print(f"  h={h:3d}: n={n:4d} mean(M14-direction return)={mean:+.3f} t={t:+.2f}  "
              f"-> FADE edge={-mean:+.3f}/trade")
    # by qty bucket
    print("\n  By qty bucket (h=50):")
    for qmin, qmax in [(1, 2), (3, 5), (6, 10), (11, 99)]:
        rets = []
        for _, r in sub.iterrows():
            if not (qmin <= r.quantity <= qmax): continue
            try:
                mid_now = mid_lookup.loc[(r.day, r.timestamp, "VELVETFRUIT_EXTRACT"), "mid_price"]
                fwd_ts = r.timestamp + 5000
                if fwd_ts > 999900: continue
                mid_fwd = mid_lookup.loc[(r.day, fwd_ts, "VELVETFRUIT_EXTRACT"), "mid_price"]
                signed = (mid_fwd - mid_now) if r.buyer == "Mark 14" else -(mid_fwd - mid_now)
                rets.append(signed)
            except KeyError:
                continue
        a = np.array(rets)
        if len(a) >= 10:
            print(f"    qty[{qmin:2d},{qmax:2d}]: n={len(a):4d} mean={a.mean():+.3f} fade_edge={-a.mean():+.3f}")


def m14_cross_product(trades, mid_lookup):
    """Does M14 HP activity correlate with VEV_4000 activity?"""
    print("\n" + "=" * 80)
    print("[5] Mark 14 cross-product flow correlation")
    print("=" * 80)
    out = {}
    for sym in ("HYDROGEL_PACK", "VEV_4000", "VELVETFRUIT_EXTRACT"):
        sub = trades[(trades.symbol == sym) &
                     ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
        sub["signed"] = np.where(sub.buyer == "Mark 14", sub.quantity, -sub.quantity)
        # bin into 1000-tick (100 timestamps) buckets per day
        sub["bucket"] = (sub.timestamp // 10000).astype(int)
        agg = sub.groupby(["day", "bucket"])["signed"].sum().reset_index()
        out[sym] = agg.set_index(["day", "bucket"])["signed"]
    # build joint frame
    df = pd.concat(out, axis=1).fillna(0)
    print("\n  M14 cross-product 10k-bucket flow correlations:")
    print(df.corr().to_string())


def m14_front_run_simulation(trades, prices):
    """Simulate: if we post 1 tick INSIDE M14's typical offset, do we get hit?
    Approximation: count pairs where price = mid +/- (M14_offset - 1)."""
    print("\n" + "=" * 80)
    print("[6] Front-run simulation — could WE post 1 tick inside M14?")
    print("=" * 80)
    # For each (day,ts) when M14 has a passive trade, what's the spread?
    # If spread allows mid +/- (8-1) = mid +/- 7 to be valid (still inside best opp),
    # we could post there.
    p_idx = prices.set_index(["day", "timestamp", "product"]).sort_index()
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        m14 = trades[(trades.symbol == sym) &
                     ((trades.buyer == "Mark 14") | (trades.seller == "Mark 14"))].copy()
        feasible = 0
        infeasible = 0
        ticks_seen = set()
        for _, r in m14.iterrows():
            key = (r.day, r.timestamp, sym)
            if key in ticks_seen: continue
            ticks_seen.add(key)
            try:
                row = p_idx.loc[key]
                mid = row["mid_price"]; b1 = row["bid_price_1"]; a1 = row["ask_price_1"]
            except KeyError:
                continue
            # If M14 bought (was passive bid at mid-7-ish), we'd post at mid - 6.
            # That has to still be > b1 (else we're outside).
            if r.buyer == "Mark 14":
                cand = mid - 7
                if cand > b1:
                    feasible += 1
                else:
                    infeasible += 1
            else:
                cand = mid + 7
                if cand < a1:
                    feasible += 1
                else:
                    infeasible += 1
        tot = feasible + infeasible
        if tot:
            print(f"  {sym}: feasible front-run posts = {feasible}/{tot} ({100*feasible/tot:.1f}%) "
                  f"[mid +/- 7 strictly inside best book]")


def main():
    print("Loading R4 trades + prices ...")
    trades, prices = load_all()
    print(f"  trades n={len(trades)}, prices n={len(prices)}")
    mid_lookup = build_mid_lookup(prices)

    mark14_offset_distribution(trades, mid_lookup)
    m14_offset_stationarity(trades, mid_lookup)
    m14_m38_pair_dynamics(trades, mid_lookup)
    m14_directional_shift(trades, mid_lookup)
    m14_vfe_fade(trades, mid_lookup)
    m14_cross_product(trades, mid_lookup)
    m14_front_run_simulation(trades, prices)


if __name__ == "__main__":
    main()
