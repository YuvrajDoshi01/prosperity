"""Refined arb: only NEGATIVE butterflies (true arb), call-spread upper bound (C(K1)-C(K2) <= K2-K1),
and check tradeability (BID-ASK based, not mid-mid)."""
import pickle, numpy as np, pandas as pd, os

DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"
OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"

VOUCHERS = [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]

# Need bid/ask for each voucher and VFE
def load_book(day):
    p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_{day}.csv"), sep=";")
    bid = p.pivot(index="timestamp", columns="product", values="bid_price_1")
    ask = p.pivot(index="timestamp", columns="product", values="ask_price_1")
    bidv = p.pivot(index="timestamp", columns="product", values="bid_volume_1").fillna(0)
    askv = p.pivot(index="timestamp", columns="product", values="ask_volume_1").fillna(0)
    mid = p.pivot(index="timestamp", columns="product", values="mid_price")
    return bid, ask, bidv, askv, mid

print("=== TRUE arb (using bid/ask, not mid) ===\n")

for day in [0,1,2]:
    bid, ask, bidv, askv, mid = load_book(day)
    if day==2:
        bid=bid.iloc[:1000]; ask=ask.iloc[:1000]; bidv=bidv.iloc[:1000]; askv=askv.iloc[:1000]; mid=mid.iloc[:1000]

    # BUTTERFLY arb (executable): need C(k1) - 2*C(k2) + C(k3) < 0
    # To capture: BUY @ ask: C(k1), C(k3); SELL @ bid: C(k2)*2
    # Net cost = ask(k1) + ask(k3) - 2*bid(k2). Profit if cost < 0
    print(f"--- Day {day} (1k if day2) ---")
    bfly_results = []
    for i,k1 in enumerate(VOUCHERS):
        for j,k2 in enumerate(VOUCHERS[i+1:], i+1):
            for k3 in VOUCHERS[j+1:]:
                a1=f"VEV_{k1}"; a2=f"VEV_{k2}"; a3=f"VEV_{k3}"
                if not all(a in ask for a in [a1,a2,a3]): continue
                cost_btf = ask[a1] + ask[a3] - 2*bid[a2]
                profit_short_btf = 2*ask[a2] - bid[a1] - bid[a3]  # sell low, buy mid -> negative profit if convex
                # Convexity arb: butterfly mid >= 0 always. If we can BUY butterfly cheap (cost<0): free $
                cheap = (cost_btf<0).sum()
                if cheap>0:
                    bfly_results.append((f"buy_btf_{k1}_{k2}_{k3}", cheap, -cost_btf[cost_btf<0].mean()))

    df_b = pd.DataFrame(bfly_results, columns=["pair","n_arb","mean_profit"])
    df_b = df_b.sort_values("mean_profit", ascending=False)
    if len(df_b)>0:
        print("  BUTTERFLY arb (BUY butterfly @ negative cost):")
        print(df_b.head(10).to_string(index=False))

    # CALL-SPREAD upper bound: C(K1) - C(K2) <= K2-K1.
    # Tradeable: SELL@bid C(k1), BUY@ask C(k2). Receive bid(k1)-ask(k2). Spread max payoff = K2-K1.
    # Arb if bid(k1) - ask(k2) > K2-K1.
    cs_results = []
    for i,k1 in enumerate(VOUCHERS):
        for k2 in VOUCHERS[i+1:]:
            a1=f"VEV_{k1}"; a2=f"VEV_{k2}"
            if a1 not in ask or a2 not in ask: continue
            edge = bid[a1] - ask[a2] - (k2-k1)
            n = (edge>0).sum()
            if n>0:
                cs_results.append((f"sell_{k1}_buy_{k2}", n, edge[edge>0].mean()))

    df_cs = pd.DataFrame(cs_results, columns=["pair","n_arb","mean_edge"])
    df_cs = df_cs.sort_values("mean_edge", ascending=False)
    if len(df_cs)>0:
        print("  CALL-SPREAD upper-bound arb:")
        print(df_cs.head(10).to_string(index=False))

    # MONOTONICITY: C(K1) >= C(K2) for K1<K2. Tradeable: SELL C(K2)@bid, BUY C(K1)@ask. Profit if bid(K2)>ask(K1).
    mono_results = []
    for i,k1 in enumerate(VOUCHERS):
        for k2 in VOUCHERS[i+1:]:
            a1=f"VEV_{k1}"; a2=f"VEV_{k2}"
            if a1 not in ask or a2 not in ask: continue
            edge = bid[a2] - ask[a1]  # buy lower-K, sell higher-K
            n = (edge>0).sum()
            if n>0:
                mono_results.append((f"buy_{k1}_sell_{k2}", n, edge[edge>0].mean()))
    df_m = pd.DataFrame(mono_results, columns=["pair","n_arb","mean_edge"])
    df_m = df_m.sort_values("mean_edge", ascending=False)
    if len(df_m)>0:
        print("  MONOTONICITY arb:")
        print(df_m.head(10).to_string(index=False))
    print()

# DEEP-ITM intrinsic on day 2 1k
print("=== Deep-ITM intrinsic arb VEV_4000 on day 2 1k ===")
bid,ask,bidv,askv,mid = load_book(2)
bid=bid.iloc[:1000]; ask=ask.iloc[:1000]
S = mid.iloc[:1000]["VELVETFRUIT_EXTRACT"]
S_bid = bid.iloc[:1000]["VELVETFRUIT_EXTRACT"]
S_ask = ask.iloc[:1000]["VELVETFRUIT_EXTRACT"]
for k in [4000, 4500]:
    col=f"VEV_{k}"
    # Lower bound: C >= S - K (no rates). Tradeable: BUY C @ ask, SELL S @ bid. Profit if (S_bid-K) - C_ask > 0
    edge = S_bid - k - ask[col]
    n_long_C = (edge>0).sum()
    print(f"  K={k}: 'C cheaper than intrinsic' (BUY C SELL S): n={n_long_C} mean_edge={edge[edge>0].mean() if n_long_C>0 else 0:.2f}")
    # Reverse: SELL C @ bid, BUY S @ ask, premium > 0 always
