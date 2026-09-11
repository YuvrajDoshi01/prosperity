"""Mark 01 alpha forensics.

Goals:
1. Per-day directional flow (net buy/sell per product).
2. Time-of-day clustering / burst frequency.
3. VEV_5300 negative h=1: when Mark 01 trades VEV_5300, fade?
4. Mark 01 + Mark 22 paired tick: predictable price impact?
5. VFE h=1 +0.22: passive bid posting after Mark 01 buys.

Run: python trader-logic/round-4/intel/mark01_alpha.py
"""
import csv
import os
from collections import defaultdict, Counter
from statistics import mean, stdev

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RES = os.path.join(ROOT, "prosperity4bt", "resources", "round4")

DAYS = [1, 2, 3]


def load_trades():
    trades = []
    for d in DAYS:
        with open(os.path.join(RES, f"trades_round_4_day_{d}.csv")) as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                trades.append({
                    "day": d,
                    "ts": int(row["timestamp"]),
                    "buyer": row["buyer"],
                    "seller": row["seller"],
                    "symbol": row["symbol"],
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
    return trades


def load_mids():
    """Returns {(day, ts, product): mid}."""
    mids = {}
    for d in DAYS:
        with open(os.path.join(RES, f"prices_round_4_day_{d}.csv")) as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                if row["mid_price"]:
                    mids[(d, int(row["timestamp"]), row["product"])] = float(row["mid_price"])
    return mids


def get_mid(mids, day, ts, product, default=None):
    """Return mid at (day,ts) or nearest earlier ts."""
    if (day, ts, product) in mids:
        return mids[(day, ts, product)]
    return default


def main():
    trades = load_trades()
    mids = load_mids()
    m01 = [t for t in trades if t["buyer"] == "Mark 01" or t["seller"] == "Mark 01"]
    print(f"Mark 01 total trades: {len(m01)}")

    # ---- 1. Per-day directional flow per product ----
    print("\n=== 1. PER-DAY NET FLOW (Mark 01) ===")
    print(f"{'product':<22} {'day':>3} {'n':>5} {'net_qty':>8} {'buy_share':>10} {'mean_qty':>9} {'day_drift':>10}")
    daily_drift = {}  # (day,product) -> close - open mid
    for d in DAYS:
        for product in set(t["symbol"] for t in m01):
            day_mids = [(ts, p) for (dd, ts, prod), p in mids.items() if dd == d and prod == product]
            if day_mids:
                day_mids.sort()
                daily_drift[(d, product)] = day_mids[-1][1] - day_mids[0][1]

    products = sorted(set(t["symbol"] for t in m01))
    for product in products:
        for d in DAYS:
            sub = [t for t in m01 if t["symbol"] == product and t["day"] == d]
            if not sub:
                continue
            net = sum(t["qty"] if t["buyer"] == "Mark 01" else -t["qty"] for t in sub)
            buy_share = sum(1 for t in sub if t["buyer"] == "Mark 01") / len(sub)
            mq = mean(t["qty"] for t in sub)
            drift = daily_drift.get((d, product), 0.0)
            print(f"{product:<22} {d:>3} {len(sub):>5} {net:>+8d} {buy_share:>10.2f} {mq:>9.2f} {drift:>+10.1f}")

    # Correlation: net buy direction vs day drift?
    print("\n--- Net direction vs day drift correlation ---")
    for product in products:
        nets = []
        drifts = []
        for d in DAYS:
            sub = [t for t in m01 if t["symbol"] == product and t["day"] == d]
            if not sub:
                continue
            net = sum(t["qty"] if t["buyer"] == "Mark 01" else -t["qty"] for t in sub)
            nets.append(net)
            drifts.append(daily_drift.get((d, product), 0.0))
        if len(nets) >= 2:
            sign_match = sum(1 for n, dr in zip(nets, drifts) if (n > 0 and dr > 0) or (n < 0 and dr < 0))
            print(f"{product:<22} sign_match: {sign_match}/{len(nets)} | nets={nets} drifts={[f'{x:+.0f}' for x in drifts]}")

    # ---- 2. Time-of-day clustering ----
    print("\n=== 2. TIME-OF-DAY CLUSTERING ===")
    # Bucket each ts into 10 buckets (each ~100k of 1M ticks)
    print("Trades per 100k tick bucket per day per product (top products):")
    for product in ["VELVETFRUIT_EXTRACT", "VEV_5300", "VEV_5200", "VEV_5400"]:
        for d in DAYS:
            sub = [t for t in m01 if t["symbol"] == product and t["day"] == d]
            if not sub:
                continue
            buckets = Counter(t["ts"] // 100000 for t in sub)
            counts = [buckets.get(i, 0) for i in range(10)]
            print(f"  {product:<22} day {d}: {counts}  (total={len(sub)})")

    # Burst frequency: histogram of consecutive-tick gaps
    print("\n--- Inter-trade gap (ticks) by product ---")
    for product in products:
        sub = sorted([t for t in m01 if t["symbol"] == product], key=lambda t: (t["day"], t["ts"]))
        gaps = []
        for i in range(1, len(sub)):
            if sub[i]["day"] == sub[i - 1]["day"]:
                gaps.append((sub[i]["ts"] - sub[i - 1]["ts"]) // 100)  # in ticks
        if gaps:
            short_pct = sum(1 for g in gaps if g <= 5) / len(gaps) * 100
            print(f"  {product:<22} n_gaps={len(gaps):>4} med={sorted(gaps)[len(gaps)//2]:>5} mean={mean(gaps):>7.1f} <=5tk={short_pct:>5.1f}%")

    # ---- 3. VEV_5300 fade signal ----
    print("\n=== 3. VEV_5300 FADE SIGNAL ===")
    sub = [t for t in m01 if t["symbol"] == "VEV_5300"]
    print(f"Mark 01 VEV_5300 trades: {len(sub)}")
    horizons = [1, 5, 10, 50, 100]
    print(f"{'horizon (ticks)':<20} {'n':>5} {'mean_signed_ret':>16} {'t_stat':>10}")
    for h in horizons:
        rets = []
        for t in sub:
            mid_now = get_mid(mids, t["day"], t["ts"], "VEV_5300")
            mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, "VEV_5300")
            if mid_now is None or mid_fwd is None:
                continue
            sign = 1 if t["buyer"] == "Mark 01" else -1
            rets.append(sign * (mid_fwd - mid_now))
        if len(rets) > 5:
            mu = mean(rets)
            sd = stdev(rets) if len(rets) > 1 else 1.0
            tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
            print(f"{h:<20} {len(rets):>5} {mu:>+16.4f} {tstat:>+10.2f}")

    # Conditional on size
    print("\n--- VEV_5300 by qty bucket (h=10) ---")
    for qmin in [1, 3, 5, 8]:
        rets = []
        for t in sub:
            if t["qty"] < qmin:
                continue
            mid_now = get_mid(mids, t["day"], t["ts"], "VEV_5300")
            mid_fwd = get_mid(mids, t["day"], t["ts"] + 1000, "VEV_5300")
            if mid_now is None or mid_fwd is None:
                continue
            sign = 1 if t["buyer"] == "Mark 01" else -1
            rets.append(sign * (mid_fwd - mid_now))
        if len(rets) > 5:
            mu = mean(rets)
            sd = stdev(rets) if len(rets) > 1 else 1.0
            tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
            print(f"  qty>={qmin}: n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f}")

    # ---- 4. Mark 01 + Mark 22 paired tick ----
    print("\n=== 4. MARK 01 + MARK 22 PAIRED TICK ANALYSIS ===")
    pair = [t for t in m01 if (t["buyer"] == "Mark 01" and t["seller"] == "Mark 22") or
            (t["buyer"] == "Mark 22" and t["seller"] == "Mark 01")]
    print(f"Mark 01 <-> Mark 22 trades: {len(pair)}")
    print(f"Symbols: {Counter(t['symbol'] for t in pair).most_common()}")

    # On VEV_5200/5300/5400/5500, mid impact (these are tradable strikes)
    print("\n--- Paired Mark01-buys-from-Mark22 mid impact at h=1,5,10 ---")
    for product in ["VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]:
        for action in ["m01_buy", "m01_sell"]:
            if action == "m01_buy":
                sub = [t for t in pair if t["symbol"] == product and t["buyer"] == "Mark 01"]
            else:
                sub = [t for t in pair if t["symbol"] == product and t["seller"] == "Mark 01"]
            if len(sub) < 5:
                continue
            for h in [1, 5, 10, 50]:
                rets = []
                for t in sub:
                    mid_now = get_mid(mids, t["day"], t["ts"], product)
                    mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, product)
                    if mid_now is None or mid_fwd is None:
                        continue
                    sign = 1 if action == "m01_buy" else -1
                    rets.append(sign * (mid_fwd - mid_now))
                if len(rets) > 5:
                    mu = mean(rets)
                    sd = stdev(rets) if len(rets) > 1 else 1.0
                    tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
                    star = " *" if abs(tstat) >= 2.0 else ""
                    print(f"  {product:<10} {action:<10} h={h:>3} n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f}{star}")

    # ---- 5. VFE h=1 +0.22 alpha — replicate signal ----
    print("\n=== 5. VFE h=1 PASSIVE-BID OPPORTUNITY ===")
    vfe = [t for t in m01 if t["symbol"] == "VELVETFRUIT_EXTRACT"]
    print(f"Mark 01 VFE trades: {len(vfe)}  buys={sum(1 for t in vfe if t['buyer']=='Mark 01')}")

    # h=1 forward return per side
    for action, label in [("buy", "Mark01 BUY"), ("sell", "Mark01 SELL")]:
        if action == "buy":
            sub = [t for t in vfe if t["buyer"] == "Mark 01"]
        else:
            sub = [t for t in vfe if t["seller"] == "Mark 01"]
        for h in [1, 3, 5, 10, 30, 100]:
            rets = []
            for t in sub:
                mid_now = get_mid(mids, t["day"], t["ts"], "VELVETFRUIT_EXTRACT")
                mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, "VELVETFRUIT_EXTRACT")
                if mid_now is None or mid_fwd is None:
                    continue
                sign = 1 if action == "buy" else -1
                rets.append(sign * (mid_fwd - mid_now))
            if len(rets) > 10:
                mu = mean(rets)
                sd = stdev(rets) if len(rets) > 1 else 1.0
                tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
                cum = sum(rets)
                star = " *" if abs(tstat) >= 2.0 else ""
                print(f"  {label} h={h:>3} n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f} sum={cum:>+.0f}{star}")
        print()

    # Capacity sizing: how often does Mark 01 buy VFE?
    vfe_buys = [t for t in vfe if t["buyer"] == "Mark 01"]
    print(f"VFE buy events / day:")
    for d in DAYS:
        n = sum(1 for t in vfe_buys if t["day"] == d)
        v = sum(t["qty"] for t in vfe_buys if t["day"] == d)
        print(f"  day {d}: n={n} vol={v}")

    # Aggression at trade time on VFE buys (average price - mid)
    print("\n--- Mark 01 VFE buy aggression vs mid ---")
    aggs = []
    for t in vfe_buys:
        mid_now = get_mid(mids, t["day"], t["ts"], "VELVETFRUIT_EXTRACT")
        if mid_now is not None:
            aggs.append(t["price"] - mid_now)
    if aggs:
        print(f"  mean={mean(aggs):+.2f}  pct_pays_thru_spread={sum(1 for a in aggs if a > 0)/len(aggs)*100:.1f}%")

    # CONDITIONAL: when Mark 01 buys at the ASK (taker, agg>0), does mid revert next 1-10 ticks?
    print("\n--- Mark 01 VFE BUY conditional on aggression sign ---")
    for cond_label, cond_fn in [
        ("agg <= -1 (Mark 01 passive buy)", lambda a: a <= -1),
        ("-1 < agg < +1 (mid)", lambda a: -1 < a < 1),
        ("agg >= +1 (Mark 01 takes ask)", lambda a: a >= 1),
    ]:
        for h in [1, 5, 10]:
            rets = []
            for t in vfe_buys:
                mid_now = get_mid(mids, t["day"], t["ts"], "VELVETFRUIT_EXTRACT")
                mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, "VELVETFRUIT_EXTRACT")
                if mid_now is None or mid_fwd is None:
                    continue
                if not cond_fn(t["price"] - mid_now):
                    continue
                rets.append(mid_fwd - mid_now)
            if len(rets) > 5:
                mu = mean(rets)
                sd = stdev(rets) if len(rets) > 1 else 1.0
                tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
                star = " *" if abs(tstat) >= 2.0 else ""
                print(f"  {cond_label:<32} h={h:>3} n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f}{star}")

    # Conditional on qty
    print("\n--- Mark 01 VFE BUY by qty bucket (h=1,5,10) ---")
    for qmin in [1, 3, 5, 8]:
        for h in [1, 5, 10]:
            rets = []
            for t in vfe_buys:
                if t["qty"] < qmin:
                    continue
                mid_now = get_mid(mids, t["day"], t["ts"], "VELVETFRUIT_EXTRACT")
                mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, "VELVETFRUIT_EXTRACT")
                if mid_now is None or mid_fwd is None:
                    continue
                rets.append(mid_fwd - mid_now)
            if len(rets) > 5:
                mu = mean(rets)
                sd = stdev(rets) if len(rets) > 1 else 1.0
                tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
                cum = sum(rets)
                star = " *" if abs(tstat) >= 2.0 else ""
                print(f"  qty>={qmin} h={h:>3} n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f} cum={cum:>+.0f}{star}")

    # ---- 6. Profile Mark 01 across all products with h=1 ----
    print("\n=== 6. ALL-PRODUCT Mark 01 h=1 SIGNED RETURN ===")
    for product in products:
        for action in ["buy", "sell"]:
            if action == "buy":
                sub = [t for t in m01 if t["symbol"] == product and t["buyer"] == "Mark 01"]
            else:
                sub = [t for t in m01 if t["symbol"] == product and t["seller"] == "Mark 01"]
            for h in [1, 5]:
                rets = []
                for t in sub:
                    mid_now = get_mid(mids, t["day"], t["ts"], product)
                    mid_fwd = get_mid(mids, t["day"], t["ts"] + h * 100, product)
                    if mid_now is None or mid_fwd is None:
                        continue
                    sign = 1 if action == "buy" else -1
                    rets.append(sign * (mid_fwd - mid_now))
                if len(rets) >= 30:
                    mu = mean(rets)
                    sd = stdev(rets) if len(rets) > 1 else 1.0
                    tstat = mu / (sd / (len(rets) ** 0.5)) if sd > 0 else 0.0
                    if abs(tstat) >= 2.0:
                        print(f"  {product:<22} {action:<5} h={h:>3} n={len(rets):>4} mean={mu:>+.4f} t={tstat:>+.2f} cum={sum(rets):>+.0f} *")


if __name__ == "__main__":
    main()
