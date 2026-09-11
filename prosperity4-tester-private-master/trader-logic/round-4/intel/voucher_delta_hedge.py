"""voucher_delta_hedge.py — Aggregate voucher portfolio delta analysis for R4.

Reconstructs voucher positions and computes per-tick aggregate delta from
r4_final_v2.py BT log (proxy: simulate fills via wall-mid + BS_EDGE filter).
For analytical purposes we use mid-quote positions estimated by replaying
the day-3 CSV through a simplified delta tracker.

Outputs (printed):
  - Mean / std / |max| of net portfolio delta (in VFE shares)
  - Implied drift PnL from unhedged delta (delta * dVFE)
  - Hedge accuracy at threshold X = 30, 50, 80 (residual delta std)
  - Hedge cost estimate (VFE turnover * 1 tick of crossed half-spread)
"""
import csv
import math
from collections import defaultdict
from statistics import NormalDist, mean, stdev, median

ND = NormalDist()
DAY = 3
PRICES = f"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4/prices_round_4_day_{DAY}.csv"

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_SYMS = {k: f"VEV_{k}" for k in STRIKES}
VFE = "VELVETFRUIT_EXTRACT"
TTE_DAYS = 4.0
TTE_YEAR = 250.0


def bs_delta(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return ND.cdf(d1)


def main():
    rows_by_ts = defaultdict(dict)
    with open(PRICES) as f:
        rdr = csv.DictReader(f, delimiter=";")
        for r in rdr:
            ts = int(r["timestamp"])
            prod = r["product"]
            try:
                mid = float(r["mid_price"])
            except (TypeError, ValueError):
                continue
            try:
                bb = float(r["bid_price_1"])
                ba = float(r["ask_price_1"])
            except (TypeError, ValueError):
                bb, ba = mid - 1, mid + 1
            rows_by_ts[ts][prod] = (mid, bb, ba)

    timestamps = sorted(rows_by_ts.keys())[:1000]  # 1k tick

    # Simulate POSITIONS naively: assume MM gets filled to mid-spread and
    # voucher position drifts toward equilibrium ~ +50 per traded strike when
    # spot rises (calls bought at ask), ~-50 when spot falls. We use a
    # PROXY position = +V_BS_TRADE_SIZE per strike when (spot - K) > 0 and
    # spot has been rising; this is a loose upper bound but illustrates magnitude.
    # Actual sim requires full BT log; here we estimate from CSV alone.

    # Simpler proxy: assume static position = +30 per ITM strike (BT fill cap).
    # Scan delta over 1k ticks to bound exposure.
    deltas, vfe_mids, hp_mids, dvfe = [], [], [], []
    for i, ts in enumerate(timestamps):
        snap = rows_by_ts[ts]
        if VFE not in snap:
            continue
        spot = snap[VFE][0]
        T = max(TTE_DAYS - ts / 1_000_000.0, 0.01) / TTE_YEAR
        sigma = 0.18
        net_delta = 0.0
        for K, sym in VOUCHER_SYMS.items():
            if sym not in snap:
                continue
            d = bs_delta(spot, K, T, sigma)
            # Proxy position: BS taker accumulates when fair > mid, etc.
            # Use static long 30 for ITM (K<spot), 0 OTM.
            pos = 30 if K < spot else (10 if K < spot + 100 else 0)
            net_delta += pos * d
        deltas.append(net_delta)
        vfe_mids.append(spot)
        if i > 0:
            dvfe.append(spot - vfe_mids[-2])

    if not deltas:
        print("No data")
        return

    # Drift PnL from unhedged delta: sum(delta_t * dVFE_{t+1})
    drift_pnl = sum(deltas[i] * dvfe[i] for i in range(len(dvfe)))

    # Hedge simulation: when |net_delta| > X, take opposite VFE position
    for X in [30, 50, 80]:
        hedged = []
        vfe_pos = 0
        turnover = 0
        for i, d in enumerate(deltas):
            target = -d if abs(d) > X else 0
            target = max(-200, min(200, round(target)))
            change = target - vfe_pos
            turnover += abs(change)
            vfe_pos = target
            residual = d + vfe_pos
            hedged.append(residual)
        hedge_cost = turnover * 0.5  # half-spread per share traded
        hedged_pnl = sum(hedged[i] * dvfe[i] for i in range(len(dvfe))) - hedge_cost
        print(f"  X={X:>3}: residual_std={stdev(hedged):>6.1f}  "
              f"turnover={turnover:>6}  hedge_cost=${hedge_cost:>7.0f}  "
              f"net_drift_pnl=${hedged_pnl:>+8.0f}")

    print(f"\nUNHEDGED DELTA STATS (10 strikes, 1k day-3):")
    print(f"  mean delta:    {mean(deltas):+7.1f} VFE-share-equiv")
    print(f"  median delta:  {median(deltas):+7.1f}")
    print(f"  std delta:     {stdev(deltas):>7.1f}")
    print(f"  |max| delta:   {max(abs(d) for d in deltas):>7.1f}")
    print(f"  unhedged drift PnL ~ ${drift_pnl:+,.0f}")
    print(f"  VFE move (1k):  {vfe_mids[-1]-vfe_mids[0]:+.1f}")


if __name__ == "__main__":
    main()
