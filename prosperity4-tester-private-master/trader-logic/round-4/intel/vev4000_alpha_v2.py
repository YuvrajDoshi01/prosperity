"""VEV_4000 alpha hunt — DEEPER EDA:
- All counterparty profiling (not just M14/M38)
- Quote-level book inspection (where exactly do M14/M38 quote?)
- Cap-binding test: what if we bid AT intrinsic (offset=0) instead of intrinsic-1?
"""
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES = ROOT / "prosperity4bt" / "resources" / "round4"
K = 4000


def load_prices(day):
    rows = []
    with (RES / f"prices_round_4_day_{day}.csv").open() as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("product") == "VEV_4000":
                ts = int(r["timestamp"])
                bb = [float(r[f"bid_price_{i}"]) for i in (1,2,3) if r.get(f"bid_price_{i}")]
                ba = [float(r[f"ask_price_{i}"]) for i in (1,2,3) if r.get(f"ask_price_{i}")]
                bv = [int(r[f"bid_volume_{i}"]) for i in (1,2,3) if r.get(f"bid_volume_{i}")]
                av = [int(r[f"ask_volume_{i}"]) for i in (1,2,3) if r.get(f"ask_volume_{i}")]
                mp = float(r["mid_price"]) if r.get("mid_price") else None
                rows.append(dict(ts=ts, bb=bb, ba=ba, bv=bv, av=av, mid=mp))
    return rows


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
    if not p.exists(): return out
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


def main():
    print("=" * 90)
    print("VEV_4000 DEEP EDA — Quote book + counterparty profiling")
    print("=" * 90)

    for day in (1, 2, 3):
        prices = load_prices(day)
        trades = load_trades(day)
        vfe = load_vfe_mid(day)
        print(f"\n--- DAY {day} ({len(prices)} prices, {len(trades)} trades) ---")

        # 1) Quote book vs intrinsic — measure spread structure tick-by-tick
        spreads = []
        bid_edges = []  # bid - intrinsic
        ask_edges = []  # ask - intrinsic
        bid2_edges = []
        ask2_edges = []
        narrow_window_count = 0  # ticks where book has prices BETWEEN ±10.5
        for p in prices:
            v = vfe.get(p["ts"])
            if v is None or not p["bb"] or not p["ba"]: continue
            intrinsic = max(v - K, 0)
            bb1 = p["bb"][0]; ba1 = p["ba"][0]
            spreads.append(ba1 - bb1)
            bid_edges.append(bb1 - intrinsic)
            ask_edges.append(ba1 - intrinsic)
            if len(p["bb"]) > 1:
                bid2_edges.append(p["bb"][1] - intrinsic)
            if len(p["ba"]) > 1:
                ask2_edges.append(p["ba"][1] - intrinsic)
            # Narrow if best bid > intrinsic-10 OR best ask < intrinsic+10
            if bb1 > intrinsic - 10 or ba1 < intrinsic + 10:
                narrow_window_count += 1

        print(f"  Spread: mean={mean(spreads):.2f} median={median(spreads):.1f} "
              f"min={min(spreads):.0f} max={max(spreads):.0f}")
        print(f"  Best-bid edge vs intrinsic: mean={mean(bid_edges):+.2f} median={median(bid_edges):+.1f}")
        print(f"  Best-ask edge vs intrinsic: mean={mean(ask_edges):+.2f} median={median(ask_edges):+.1f}")
        print(f"  L2-bid edge: {'mean='+f'{mean(bid2_edges):+.2f}' if bid2_edges else 'none'}  "
              f"L2-ask edge: {'mean='+f'{mean(ask2_edges):+.2f}' if ask2_edges else 'none'}")
        print(f"  Narrow-spread ticks (book inside ±10): {narrow_window_count}/{len(prices)} "
              f"({100*narrow_window_count/len(prices):.1f}%)")

        # 2) Volume on Mark 14 / Mark 38 levels — which quote tier do they sit on?
        # Combine: at each tick, the bid/ask volume tells us implied taker capacity.
        bid_vols_l1 = [p["bv"][0] for p in prices if p["bv"]]
        ask_vols_l1 = [p["av"][0] for p in prices if p["av"]]
        print(f"  Best-bid L1 vol: mean={mean(bid_vols_l1):.1f} median={median(bid_vols_l1):.0f}")
        print(f"  Best-ask L1 vol: mean={mean(ask_vols_l1):.1f} median={median(ask_vols_l1):.0f}")

        # 3) All counterparties (not just M14/M38)
        cp = defaultdict(int)
        for t in trades:
            cp[t["buyer"]] += t["qty"]
            cp[t["seller"]] += t["qty"]
        print(f"  All counterparties (qty incl. dup):")
        for k, v in sorted(cp.items(), key=lambda x: -x[1])[:8]:
            print(f"    {k!r:20s}: {v}")

        # 4) NON-Mark14/38 trades — these are the "free money" trades
        non_mm_trades = [t for t in trades
                         if t["buyer"] not in ("Mark 14", "Mark 38", "")
                         and t["seller"] not in ("Mark 14", "Mark 38", "")]
        print(f"  Non-MM trades: {len(non_mm_trades)} ({100*len(non_mm_trades)/max(1,len(trades)):.1f}%)")

        # 5) PROFIT FROM AGGRESSIVE MID-CROSS QUOTING
        # Currently we bid intrinsic-1, ask intrinsic+1.
        # Test stepping: bid intrinsic-O, ask intrinsic+O for O ∈ {0,1,2,3,5}
        # For each Mark 38 SELL at intrinsic-10.5 (qty Q), if our ask <= intrinsic-10.5 ...
        # No, that doesn't make sense. M38 sells AT intrinsic-10.5 (we BUY from M38 at -10.5 below).
        # M14 buys AT intrinsic+10.5 (we SELL to M14 at +10.5 above).
        # So the "always-skim" PnL for stepping closer to intrinsic doesn't actually help — we're
        # already pricing inside their quotes.
        # The TRUE alpha: when M38/M14 cross our quotes (we sit at intrinsic±1 and they fill us
        # at THEIR price intrinsic∓10.5, paying us +9.5 instead of just +1).
        # Confirm: are trades happening AT our quote price (intrinsic±1) or AT M14/M38's price?
        edges_when_we_are_seller = []  # buyer=M14/M38 sells of ours
        edges_when_we_are_buyer = []
        for t in trades:
            v = vfe.get(t["ts"])
            if v is None: continue
            intr = max(v - K, 0)
            edge = t["px"] - intr
            edges_when_we_are_seller.append(edge if t["buyer"] in ("Mark 14",) else None)
        # Trade prices distribution
        trade_pxs = []
        for t in trades:
            v = vfe.get(t["ts"])
            if v is None: continue
            intr = max(v - K, 0)
            trade_pxs.append(t["px"] - intr)
        if trade_pxs:
            buckets = defaultdict(int)
            for e in trade_pxs:
                buckets[round(e)] += 1
            print(f"  Trade-price distribution (vs intrinsic, rounded):")
            for k, v in sorted(buckets.items()):
                print(f"    edge={k:+3d}: {v} trades")

    print("\n" + "=" * 90)
    print("INSIGHT: Mark 14 buys at intrinsic+10.5, Mark 38 sells at intrinsic-10.5.")
    print("Trade prices are AT THEIR quotes (±10.5), so when we bid intrinsic-1 / ask +1,")
    print("WE NEVER FILL — they fill EACH OTHER. We only fill via 'invisible taker'")
    print("mechanism when our price coincides with passive level inside ±10.5.")
    print("True alpha question: does our intrinsic-1 bid get hit by random takers, OR")
    print("can we step to intrinsic±0 (or even intrinsic+5/-5) to capture the FAT spread?")
    print("=" * 90)


if __name__ == "__main__":
    main()
