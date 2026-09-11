"""Only EQUIDISTANT butterflies (K1+K3=2K2) and weighted convexity. Also test executable arb."""
import pickle, numpy as np, pandas as pd, os

DATA = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"
OUT = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\trader-logic\round-3\notes\alpha_hunt_2026-04-25\cross_product"

VOUCHERS = [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]

def load_book(day):
    p = pd.read_csv(os.path.join(DATA, f"prices_round_3_day_{day}.csv"), sep=";")
    bid = p.pivot(index="timestamp", columns="product", values="bid_price_1")
    ask = p.pivot(index="timestamp", columns="product", values="ask_price_1")
    return bid, ask

# Equidistant butterflies among VOUCHERS
equi_btfs = []
for i,k1 in enumerate(VOUCHERS):
    for j,k2 in enumerate(VOUCHERS[i+1:], i+1):
        for k3 in VOUCHERS[j+1:]:
            if k1+k3 == 2*k2:
                equi_btfs.append((k1,k2,k3))
print("Equidistant butterflies:", equi_btfs)

# General convexity: for any K1<K2<K3, the strike-normalized convexity
# (C(K1)-C(K2))/(K2-K1) >= (C(K2)-C(K3))/(K3-K2)
# Slope must be monotonically less negative.
# Tradeable convexity: lambda*C(K1) + (1-lambda)*C(K3) >= C(K2) where lambda*K1+(1-lambda)*K3=K2
# => lambda = (K3-K2)/(K3-K1)

print("\n=== EXECUTABLE convexity arb (weighted): lambda*ask(K1) + (1-lambda)*ask(K3) < bid(K2) ===")
print("Profit per replicating-K2-unit = bid(K2) - lambda*ask(K1) - (1-lambda)*ask(K3)\n")

for day in [0,1,2]:
    bid, ask = load_book(day)
    if day==2:
        bid=bid.iloc[:1000]; ask=ask.iloc[:1000]

    print(f"--- Day {day} ---")
    rec = []
    for i,k1 in enumerate(VOUCHERS):
        for j,k2 in enumerate(VOUCHERS[i+1:], i+1):
            for k3 in VOUCHERS[j+1:]:
                lam = (k3-k2)/(k3-k1)
                a1=f"VEV_{k1}"; a2=f"VEV_{k2}"; a3=f"VEV_{k3}"
                if not all(a in ask for a in [a1,a2,a3]): continue
                # SELL K2 (receive bid), BUY lam K1 + (1-lam) K3 (pay ask)
                profit_per_unit = bid[a2] - lam*ask[a1] - (1-lam)*ask[a3]
                # also reverse: BUY K2 sell weighted K1+K3
                rev_profit = lam*bid[a1] + (1-lam)*bid[a3] - ask[a2]
                fwd_n = (profit_per_unit>0).sum()
                rev_n = (rev_profit>0).sum()
                if fwd_n>0 or rev_n>0:
                    rec.append((f"{k1}/{k2}/{k3}",
                                fwd_n, profit_per_unit[profit_per_unit>0].mean() if fwd_n>0 else 0,
                                rev_n, rev_profit[rev_profit>0].mean() if rev_n>0 else 0,
                                round(lam,3)))
    df = pd.DataFrame(rec, columns=["k1/k2/k3","fwd_n","fwd_avg","rev_n","rev_avg","lambda"])
    df = df[df["fwd_n"]+df["rev_n"]>5].copy()
    if len(df)>0:
        df["best"] = df[["fwd_avg","rev_avg"]].max(axis=1)
        print(df.sort_values("best", ascending=False).head(10).to_string(index=False))
    else:
        print("  No executable convexity arb")
    print()

# Sanity: a single tick - print bid/ask all vouchers day 2 t=0
print("=== Day 2 t=0 sample book ===")
bid, ask = load_book(2)
b0 = bid.iloc[0]; a0 = ask.iloc[0]
for k in VOUCHERS:
    col = f"VEV_{k}"
    print(f"  {col}: bid={b0.get(col,np.nan)} ask={a0.get(col,np.nan)}")

# Now: structurally, what is C(4500)+C(6500) vs 2*C(5500)?
# We should expect LARGE positive numbers since K3>>K2 != midpoint. The "violation" is not a violation.
# Real arbs to look for: SAME structure but check execution edge with tight strike spacings.
print("\n=== Strike-adjacent convexity (5000/5100/5200, 5100/5200/5300, ...) ===")
adj_trios = [(5000,5100,5200),(5100,5200,5300),(5200,5300,5400),(5300,5400,5500),
             (4000,4500,5000),(4500,5000,5500),(5000,5500,6000)]
for day in [0,1,2]:
    bid, ask = load_book(day)
    if day==2: bid=bid.iloc[:1000]; ask=ask.iloc[:1000]
    print(f"--- Day {day} ---")
    for k1,k2,k3 in adj_trios:
        a1=f"VEV_{k1}"; a2=f"VEV_{k2}"; a3=f"VEV_{k3}"
        if not all(a in ask for a in [a1,a2,a3]): continue
        lam = (k3-k2)/(k3-k1)
        # BUY-butterfly: BUY K1, SELL 2*K2 wait no. Use weighted scheme.
        cost_buy_btf = lam*ask[a1] + (1-lam)*ask[a3] - bid[a2]
        # We BUY K1 units lam, BUY K3 units (1-lam), SELL K2 units 1. Receive bid(K2)-paid weighted asks.
        # Net cost. Negative cost = free butterfly.
        n = (cost_buy_btf<0).sum()
        if n>0:
            mean_p = -cost_buy_btf[cost_buy_btf<0].mean()
            # Capacity: limited by SMALLEST voucher position. 300 each * 1 = 300 butterflies/spread per leg.
            # But weights: lam=0.5 typically -> 600 K1 long, 600 K3 long, 1200 K2 short = limit 300 -> 100 butterflies
            # at most. Actually if lam=0.5, want 0.5 lots K1, 0.5 lots K3, 1 lot K2 short => max 300 K2 short -> 300 lots
            print(f"  {k1}/{k2}/{k3}: lam={lam:.2f} n={n} mean_edge_per_unit=${mean_p:.2f}")
