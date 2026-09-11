"""Voucher-pair stat arb investigation: vertical spreads, butterflies, smile kinks."""
import pandas as pd
import numpy as np
from pathlib import Path
from itertools import combinations

ROOT = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHERS = [f"VEV_{k}" for k in STRIKES]


def load_all():
    dfs = []
    for d in (1, 2, 3):
        df = pd.read_csv(ROOT / f"prices_round_4_day_{d}.csv", sep=";")
        df["day"] = d
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def pivot_books(df):
    """Pivot to wide: per (day, ts) -> bid1/ask1 per voucher."""
    sub = df[df["product"].isin(VOUCHERS)][["day", "timestamp", "product", "bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1", "mid_price"]]
    bid = sub.pivot_table(index=["day", "timestamp"], columns="product", values="bid_price_1")
    ask = sub.pivot_table(index=["day", "timestamp"], columns="product", values="ask_price_1")
    bvol = sub.pivot_table(index=["day", "timestamp"], columns="product", values="bid_volume_1")
    avol = sub.pivot_table(index=["day", "timestamp"], columns="product", values="ask_volume_1")
    mid = sub.pivot_table(index=["day", "timestamp"], columns="product", values="mid_price")
    return bid, ask, bvol, avol, mid


def vertical_arb(bid, ask, bvol, avol):
    """For each (lo, hi) with K_lo < K_hi: arb when ask_lo < bid_hi (buy lo cheap, sell hi rich)."""
    rows = []
    pairs = [(lo, hi) for lo, hi in combinations(STRIKES, 2)]
    n_total = len(bid)
    for klo, khi in pairs:
        lo, hi = f"VEV_{klo}", f"VEV_{khi}"
        if lo not in ask.columns or hi not in bid.columns:
            continue
        edge = bid[hi] - ask[lo]              # positive = arb (sell hi, buy lo)
        mask = (edge > 0) & ask[lo].notna() & bid[hi].notna()
        n_hits = int(mask.sum())
        if n_hits == 0:
            rows.append((klo, khi, 0, 0.0, 0, 0, 0))
            continue
        max_size = pd.concat([avol[lo][mask], bvol[hi][mask]], axis=1).min(axis=1)
        total_pnl = (edge[mask] * max_size).sum()
        avg_edge = edge[mask].mean()
        avg_size = max_size.mean()
        rows.append((klo, khi, n_hits, n_hits / n_total * 100, avg_edge, avg_size, total_pnl))
    return pd.DataFrame(rows, columns=["K_lo", "K_hi", "n_hits", "pct_ticks", "avg_edge", "avg_size", "total_pnl"])


def butterfly_arb(bid, ask, bvol, avol):
    """Asymmetric butterfly with NON-NEGATIVE PAYOFF construction.

    Long w1 of K1, short 1 of K2, long w3 of K3 (K1<K2<K3).
    Set w1=(K3-K2)/(K3-K1), w3=(K2-K1)/(K3-K1) so w1+w3=1 and weighted-avg strike = K2.
    Payoff at expiry: w1*(S-K1)+ - (S-K2)+ + w3*(S-K3)+ >= 0 always (convexity).
    Therefore initial cost should be >= 0. If <0, it's a free option = arb.

    LONG butterfly cost = w1*ask(K1) - bid(K2) + w3*ask(K3). Negative => arb (receive money for free option).
    SHORT butterfly proceeds = bid(K2) - w1*bid(K1) - w3*bid(K3) ... no, short = reverse.

    Actually: SHORT butterfly = -1 of long. Cost(short) = -Cost(long). For arb on the short side,
    we'd need the LONG butterfly to be expensive AND we sell it (sell w1 K1, buy 1 K2, sell w3 K3).
    Proceeds_short = w1*bid(K1) + w3*bid(K3) - ask(K2). If positive AND payoff <=0... but payoff <=0
    isn't guaranteed for short. So short-fly is risky, not free.

    Pure free-money arb is only the LONG side: cost < 0.
    """
    rows = []
    triples = [(STRIKES[i], STRIKES[j], STRIKES[k])
               for i in range(len(STRIKES))
               for j in range(i+1, len(STRIKES))
               for k in range(j+1, len(STRIKES))]
    n_total = len(bid)
    for k1, k2, k3 in triples:
        c1, c2, c3 = f"VEV_{k1}", f"VEV_{k2}", f"VEV_{k3}"
        if not all(c in bid.columns for c in (c1, c2, c3)):
            continue
        w1 = (k3 - k2) / (k3 - k1)
        w3 = (k2 - k1) / (k3 - k1)
        # LONG butterfly: pay w1*ask(K1), receive bid(K2), pay w3*ask(K3). Cost in voucher units.
        cost_long = w1 * ask[c1] - bid[c2] + w3 * ask[c3]
        m_long = (cost_long < 0) & ask[c1].notna() & bid[c2].notna() & ask[c3].notna()
        n_long = int(m_long.sum())
        # Capacity: bottleneck on integer multiples. To execute N flies need w1*N <= avol(K1), 1*N <= bvol(K2), w3*N <= avol(K3)
        if n_long > 0:
            cap = pd.concat([
                avol[c1][m_long] / max(w1, 1e-9),
                bvol[c2][m_long],
                avol[c3][m_long] / max(w3, 1e-9),
            ], axis=1).min(axis=1).clip(upper=300)  # voucher limit 300
            edge_long = (-cost_long[m_long]).mean()
            pnl_long = (-cost_long[m_long] * cap).sum()
        else:
            edge_long, pnl_long = 0, 0
        rows.append((k1, k2, k3, w1, w3, n_long, n_long / n_total * 100, edge_long, pnl_long))
    return pd.DataFrame(rows, columns=["K1", "K2", "K3", "w1", "w3", "n_arb", "pct", "avg_edge", "total_pnl"])


def smile_kinks(mid):
    """Detect monotonicity violations on mid: C(K_lo) >= C(K_hi) must hold."""
    rows = []
    n_total = len(mid)
    for klo, khi in combinations(STRIKES, 2):
        lo, hi = f"VEV_{klo}", f"VEV_{khi}"
        if lo not in mid.columns or hi not in mid.columns:
            continue
        mask = (mid[hi] > mid[lo]) & mid[hi].notna() & mid[lo].notna()
        rows.append((klo, khi, int(mask.sum()), mask.mean() * 100))
    return pd.DataFrame(rows, columns=["K_lo", "K_hi", "n_violations", "pct"])


if __name__ == "__main__":
    df = load_all()
    bid, ask, bvol, avol, mid = pivot_books(df)
    print(f"Total ticks (3 days): {len(bid)}")
    print(f"Strikes available: {[c for c in bid.columns if c.startswith('VEV_')]}")

    print("\n=== VERTICAL SPREAD ARB (ask_lo < bid_hi) ===")
    v = vertical_arb(bid, ask, bvol, avol)
    v_hits = v[v.n_hits > 0].sort_values("total_pnl", ascending=False)
    print(v_hits.to_string(index=False))
    print(f"\nTotal vertical arb opportunities: {v.n_hits.sum()} ticks across {(v.n_hits>0).sum()} pairs")
    print(f"Total theoretical PnL (if filled at displayed size, mid-only proxy): {v.total_pnl.sum():,.0f}")

    print("\n=== BUTTERFLY / CONVEXITY ARB ===")
    b = butterfly_arb(bid, ask, bvol, avol)
    if len(b):
        print(b.sort_values(["n_arb", "total_pnl"], ascending=False).head(15).to_string(index=False))
        print(f"\nTotal butterfly arb hits: {b.n_arb.sum()}, total theoretical PnL: {b.total_pnl.sum():,.0f}")
    else:
        print("No butterfly violations found.")

    print("\n=== SMILE MONOTONICITY (mid C(lo) < mid C(hi) violations) ===")
    s = smile_kinks(mid)
    print(s.sort_values("pct", ascending=False).head(10).to_string(index=False))

    # capacity: median displayed top-of-book size for each strike
    print("\n=== CAPACITY (median bid/ask L1 volume) ===")
    cap = pd.DataFrame({
        "median_bid_vol": bvol.median(),
        "median_ask_vol": avol.median(),
        "p25_bid": bvol.quantile(0.25),
        "p25_ask": avol.quantile(0.25),
    })
    print(cap.to_string())
