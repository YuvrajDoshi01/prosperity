"""VEV_4000 alpha hunt — DEEP ITM call on VFE.

Questions:
  Q1: Theoretical PnL ceiling (perfect inventory at right level)
  Q2: Mark 38 spread skim — Mark 38 always pays +$10 vs Mark 14
  Q3: Position cap optimization (current 100 → 150/200/250)
  Q4: Theta vs intrinsic dynamics (does it match BS theta?)
  Q5: Concrete code recommendation
"""
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, mean, median, stdev

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES  = ROOT / "prosperity4bt" / "resources" / "round4"
ND = NormalDist()
K = 4000


def load_prices(day):
    rows = []
    with (RES / f"prices_round_4_day_{day}.csv").open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("product") == "VEV_4000":
                rows.append(r)
    out = []
    for r in rows:
        ts = int(r["timestamp"])
        bb = float(r["bid_price_1"]) if r.get("bid_price_1") else None
        ba = float(r["ask_price_1"]) if r.get("ask_price_1") else None
        bb2 = float(r["bid_price_2"]) if r.get("bid_price_2") else None
        ba2 = float(r["ask_price_2"]) if r.get("ask_price_2") else None
        bv = int(r["bid_volume_1"]) if r.get("bid_volume_1") else 0
        av = int(r["ask_volume_1"]) if r.get("ask_volume_1") else 0
        mp = float(r["mid_price"]) if r.get("mid_price") else None
        out.append(dict(ts=ts, bb=bb, ba=ba, bb2=bb2, ba2=ba2, bv=bv, av=av, mid=mp))
    return out


def load_vfe_mid(day):
    out = {}
    with (RES / f"prices_round_4_day_{day}.csv").open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("product") == "VELVETFRUIT_EXTRACT":
                ts = int(r["timestamp"])
                if r.get("mid_price"):
                    out[ts] = float(r["mid_price"])
    return out


def load_trades(day):
    out = []
    p = RES / f"trades_round_4_day_{day}.csv"
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("symbol") == "VEV_4000":
                out.append({
                    "ts": int(r["timestamp"]),
                    "px": float(r["price"]),
                    "qty": int(r["quantity"]),
                    "buyer": r.get("buyer", ""),
                    "seller": r.get("seller", ""),
                })
    return out


def bs_call(S, K, T, vol, r=0.0):
    if T <= 0 or vol <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * vol * vol * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return S * ND.cdf(d1) - K * math.exp(-r * T) * ND.cdf(d2)


def main():
    print("=" * 80)
    print("VEV_4000 ALPHA HUNT")
    print("=" * 80)

    all_pnl_ceiling = []
    all_mm_skim = []
    all_cap_curve = defaultdict(list)
    all_theta_obs = []

    for day in (1, 2, 3):
        prices = load_prices(day)
        trades = load_trades(day)
        vfe = load_vfe_mid(day)
        print(f"\n--- DAY {day} ({len(prices)} ticks, {len(trades)} trades) ---")

        # ----- Q1: PnL CEILING (perfect-foresight inventory at LIMIT=300) -----
        # Perfect: long when mid rises, short when mid falls; cap |pos|=300.
        # Greedy greedy walk-DP on midpath: capture every up-tick.
        mids = [p["mid"] for p in prices if p["mid"] is not None]
        # Profit = sum(|delta|) * 300 if cumulative perfect direction.
        # Simpler: perfect-foresight position carries through all ups → 300 * (max - min).
        # Walk-DP: at each tick choose pos∈{-300,0,+300}, transaction-cost-aware.
        if mids:
            dp = {-300: 0.0, 0: 0.0, 300: 0.0}
            for i in range(1, len(mids)):
                dm = mids[i] - mids[i-1]
                new_dp = {}
                for p_new in (-300, 0, 300):
                    best = -1e18
                    for p_prev, v in dp.items():
                        # MTM gain = p_prev * dm (we held p_prev across the move)
                        # No transaction cost in pure ceiling
                        candidate = v + p_prev * dm
                        if candidate > best:
                            best = candidate
                    new_dp[p_new] = best
                dp = new_dp
            ceiling = max(dp.values())
            buy_hold = 300 * (mids[-1] - mids[0])
            range_max = 300 * (max(mids) - min(mids))
            print(f"  Q1 PnL ceiling (DP, |pos|<=300): ${ceiling:,.0f}")
            print(f"     Buy & hold (300):          ${buy_hold:,.0f}")
            print(f"     Range × 300 (max-min):     ${range_max:,.0f}")
            all_pnl_ceiling.append((day, ceiling))

        # ----- Q2: Mark 38 spread skim — quote inside spread vs Mark 14 -----
        # Trade tape: identify Mark 14 ↔ Mark 38 dedicated MM pair.
        # For each trade, record buyer/seller pair.
        pair_count = defaultdict(int)
        pair_pnl = defaultdict(float)
        m38_trades = []
        for t in trades:
            key = (t["buyer"], t["seller"])
            pair_count[key] += t["qty"]
            if t["buyer"] == "Mark 38":
                m38_trades.append(("buy", t["px"], t["qty"], t["ts"]))
            elif t["seller"] == "Mark 38":
                m38_trades.append(("sell", t["px"], t["qty"], t["ts"]))
        # Top pairs
        top = sorted(pair_count.items(), key=lambda x: -x[1])[:5]
        print(f"  Q2 Top counterparty pairs (qty):")
        for (b, s), q in top:
            print(f"     {b!r:18s}->{s!r:18s} qty={q}")

        # Mark 38 buy-vs-sell px distribution
        m38_buys = [t[1] for t in m38_trades if t[0] == "buy"]
        m38_sells = [t[1] for t in m38_trades if t[0] == "sell"]
        if m38_buys and m38_sells:
            print(f"     Mark 38 buys: n={len(m38_buys)} mean_px={mean(m38_buys):.2f}")
            print(f"     Mark 38 sells: n={len(m38_sells)} mean_px={mean(m38_sells):.2f}")
            print(f"     Mark 38 implied skim per round trip: {mean(m38_sells)-mean(m38_buys):.2f}")

        # Mark 38 vs intrinsic
        m38_skim = []
        for t in trades:
            v = vfe.get(t["ts"])
            if v is None:
                continue
            intrinsic = max(v - K, 0)
            edge = t["px"] - intrinsic
            if t["buyer"] == "Mark 38":
                m38_skim.append(("Mark 38 buy", -edge, t["qty"]))   # buys below intrinsic = +edge
            elif t["seller"] == "Mark 38":
                m38_skim.append(("Mark 38 sell", edge, t["qty"]))   # sells above intrinsic = +edge
            if t["buyer"] == "Mark 14":
                m38_skim.append(("Mark 14 buy", -edge, t["qty"]))
            elif t["seller"] == "Mark 14":
                m38_skim.append(("Mark 14 sell", edge, t["qty"]))
        agg = defaultdict(list)
        for tag, edge, qty in m38_skim:
            agg[tag].append(edge)
        print("  Q2 Edge vs intrinsic (avg per trade):")
        for tag in sorted(agg):
            v = agg[tag]
            print(f"     {tag:18s}: n={len(v):3d}  avg_edge={mean(v):+.2f}  median={median(v):+.2f}")
        all_mm_skim.append((day, agg))

        # ----- Q3: Position cap optimization — simulate "always_at_cap" PnL -----
        # Approximation: assume strategy keeps avg position = cap × fill_rate.
        # PnL ∝ cap × edge_per_share × fills.
        # Use trade tape: each MM trade gives us +edge (we'd be on opposite side).
        # Compute total MTM PnL for "always able to take" trades within cap.
        # Treat each Mark 38/14 trade where price diverges from intrinsic ≥1 as fillable.
        for cap in (50, 100, 150, 200, 250, 300):
            pnl = 0.0
            pos = 0
            for t in trades:
                v = vfe.get(t["ts"])
                if v is None:
                    continue
                intrinsic = max(v - K, 0)
                edge = t["px"] - intrinsic
                # If Mark 38 sells at +edge above intrinsic, we'd buy from them at intrinsic+1
                # Treat this as fillable opportunity bounded by cap.
                if t["seller"] in ("Mark 38", "Mark 14") and edge >= 2:
                    qty = min(t["qty"], max(0, cap - pos))
                    pos += qty
                    pnl += qty * (edge - 1)   # we paid intrinsic+1, captured edge-1
                elif t["buyer"] in ("Mark 38", "Mark 14") and edge <= -2:
                    qty = min(t["qty"], max(0, cap + pos))
                    pos -= qty
                    pnl += qty * (-edge - 1)  # we sold at intrinsic-1, captured -edge-1
            all_cap_curve[cap].append((day, pnl))
            print(f"  Q3 cap={cap:3d}: simulated MM-skim PnL=${pnl:,.0f}  end_pos={pos}")

        # ----- Q4: Theta dynamics -----
        # BS theta on deep ITM call ≈ -K * r * exp(-rT) * N(d2). With r=0, theta≈0 except
        # very small from time decay near expiry. Empirically, does (mid - intrinsic) drop
        # systematically as TTE shrinks within day?
        # Compute time premium = mid - intrinsic over time.
        tte_premiums = []
        for p in prices:
            if p["mid"] is None:
                continue
            v = vfe.get(p["ts"])
            if v is None:
                continue
            intrinsic = max(v - K, 0)
            premium = p["mid"] - intrinsic
            tte_premiums.append((p["ts"], premium))
        if len(tte_premiums) > 100:
            first_avg = mean([t[1] for t in tte_premiums[:200]])
            last_avg = mean([t[1] for t in tte_premiums[-200:]])
            print(f"  Q4 Time premium: open={first_avg:+.2f}  close={last_avg:+.2f}  drift={last_avg-first_avg:+.2f}")
            all_theta_obs.append((day, first_avg, last_avg))

    # ----- AGGREGATES -----
    print("\n" + "=" * 80)
    print("AGGREGATES (3 days)")
    print("=" * 80)
    print(f"\nQ1 PnL ceilings:")
    for day, c in all_pnl_ceiling:
        print(f"  Day {day}: ${c:,.0f}")
    print(f"  TOTAL: ${sum(c for _,c in all_pnl_ceiling):,.0f}")
    print(f"\nQ3 Cap-curve totals (3-day MM-skim simulated):")
    for cap, vals in sorted(all_cap_curve.items()):
        tot = sum(p for _, p in vals)
        print(f"  cap={cap:3d}: ${tot:,.0f}")

    print(f"\nQ4 Theta observation (time premium open vs close):")
    for day, fst, lst in all_theta_obs:
        print(f"  Day {day}: {fst:+.2f} -> {lst:+.2f}  drift={lst-fst:+.2f}")


if __name__ == "__main__":
    main()
