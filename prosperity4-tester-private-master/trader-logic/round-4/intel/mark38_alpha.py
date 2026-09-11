"""
Mark 38 reverse-engineering for R4 v6.

Goals:
  1. Quantify Mark 14 quote location around mid for HP / VEV_4000
     (where does the +8 / +10 spread cross actually happen?)
  2. Mark 38 trade timing: per-tick frequency, inter-arrival, regime split.
  3. Direction asymmetry: 745 sells vs 733 buys — does sell/buy cluster around
     up-vs-down mid moves? If Mark 38 is contrarian (taker into rises) we can
     skim differently than if he's momentum.
  4. Other-product: does Mark 38 trade anything besides HP and VEV_4000?
  5. Front-run feasibility: when only Mark 14 quotes the book, what is the
     implied "mid ± 8" in the public order book? Can we post inside (mid ± 7
     on HP, mid ± 9 on VEV_4000)?

Outputs: prints structured summary; saves CSV when asked.
"""
import os, csv, math, statistics
from collections import defaultdict, Counter

ROOT = "C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4"
DAYS = (1, 2, 3)


def load_trades():
    rows = []
    for d in DAYS:
        with open(os.path.join(ROOT, f"trades_round_4_day_{d}.csv"), newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                r["day"] = d
                r["timestamp"] = int(r["timestamp"])
                r["price"] = float(r["price"])
                r["quantity"] = int(r["quantity"])
                rows.append(r)
    return rows


def load_prices():
    """Return {(day, ts): {symbol: row}} where row has bid/ask levels + mid."""
    out = {}
    for d in DAYS:
        with open(os.path.join(ROOT, f"prices_round_4_day_{d}.csv"), newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                ts = int(r["timestamp"])
                sym = r["product"]
                key = (d, ts)
                out.setdefault(key, {})[sym] = r
    return out


def fnum(s):
    if s == "" or s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _bbo(row):
    """(best_bid, best_ask, bid_levels, ask_levels)."""
    bids = []
    asks = []
    for i in (1, 2, 3):
        bp = fnum(row.get(f"bid_price_{i}", ""))
        bv = fnum(row.get(f"bid_volume_{i}", ""))
        ap = fnum(row.get(f"ask_price_{i}", ""))
        av = fnum(row.get(f"ask_volume_{i}", ""))
        if bp is not None and bv is not None:
            bids.append((bp, bv))
        if ap is not None and av is not None:
            asks.append((ap, av))
    bbid = max(b[0] for b in bids) if bids else None
    bask = min(a[0] for a in asks) if asks else None
    return bbid, bask, bids, asks


# ---- 1. Mark 38 product universe ----
def mark38_products(trades):
    sym_counts = Counter()
    for t in trades:
        if t["buyer"] == "Mark 38" or t["seller"] == "Mark 38":
            sym_counts[t["symbol"]] += 1
    return sym_counts


# ---- 2. Per-tick / per-day Mark 38 trade frequency ----
def mark38_arrival_distribution(trades):
    """
    Distribution of trade arrivals on HP and VEV_4000.
    Per-day: ticks-with-trade vs total ticks (10000 per day).
    Inter-arrival: gaps between consecutive Mark 38 trades on same product.
    """
    by_prod_day = defaultdict(list)  # (prod, day) -> list of timestamps (sorted)
    for t in trades:
        if t["buyer"] == "Mark 38" or t["seller"] == "Mark 38":
            by_prod_day[(t["symbol"], t["day"])].append(t["timestamp"])

    out = {}
    for k, ts_list in by_prod_day.items():
        ts_list.sort()
        gaps = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        out[k] = {
            "n_trades": len(ts_list),
            "ticks_with_trade": len(set(ts_list)),
            "first_ts": ts_list[0] if ts_list else None,
            "last_ts": ts_list[-1] if ts_list else None,
            "mean_gap": statistics.mean(gaps) if gaps else None,
            "median_gap": statistics.median(gaps) if gaps else None,
            "p90_gap": (sorted(gaps)[int(len(gaps) * 0.9)] if gaps else None),
        }
    return out


# ---- 3. Direction asymmetry vs mid moves ----
def mark38_direction_vs_mid(trades, prices):
    """For each Mark 38 trade, compute mid_now and mid_h10 to test if direction predicts."""
    out = defaultdict(list)
    for t in trades:
        if not (t["buyer"] == "Mark 38" or t["seller"] == "Mark 38"):
            continue
        sym = t["symbol"]
        d = t["day"]
        ts = t["timestamp"]
        side = +1 if t["buyer"] == "Mark 38" else -1
        rows_now = prices.get((d, ts), {})
        if sym not in rows_now:
            continue
        mid_now = fnum(rows_now[sym].get("mid_price", ""))
        rows_h = prices.get((d, ts + 1000), {})  # 10 ticks = 1000 ms
        mid_h = fnum(rows_h.get(sym, {}).get("mid_price", "")) if sym in rows_h else None
        if mid_now is None:
            continue
        out[sym].append({
            "side": side,
            "trade_price": t["price"],
            "qty": t["quantity"],
            "mid_now": mid_now,
            "mid_h10": mid_h,
            "edge": (t["price"] - mid_now) * side,  # +ve = M38 paid spread
            "fwd": (mid_h - mid_now) * side if mid_h is not None else None,
        })
    return out


# ---- 4. Mark 14 quote-location empirical mid offset ----
def mark14_offset_distribution(trades, prices):
    """
    For Mark 14 trades on HP & VEV_4000, what is (mark14_price - mid_at_trade)
    signed by side? E.g. if M14 sells at price = mid+8, offset = +8.
    Tells us how far Mark 14 is from mid → confirms +8/+10 quote location.
    Also bucket by spread regime.
    """
    out = defaultdict(list)
    for t in trades:
        if not (t["buyer"] == "Mark 14" or t["seller"] == "Mark 14"):
            continue
        if t["symbol"] not in ("HYDROGEL_PACK", "VEV_4000"):
            continue
        rows_now = prices.get((t["day"], t["timestamp"]), {})
        if t["symbol"] not in rows_now:
            continue
        row = rows_now[t["symbol"]]
        mid = fnum(row.get("mid_price", ""))
        bbid, bask, _, _ = _bbo(row)
        if mid is None or bbid is None or bask is None:
            continue
        # Mark 14 was passive maker. If buyer=M14 he held a bid; if seller=M14 he held an ask.
        if t["buyer"] == "Mark 14":
            # Mark 14 bid filled at trade price (someone hit his bid)
            offset = mid - t["price"]  # positive = quote below mid
        else:
            # Mark 14 ask filled at trade price (someone lifted his ask)
            offset = t["price"] - mid  # positive = quote above mid
        spread = bask - bbid
        out[(t["symbol"], int(spread))].append(offset)
    return out


# ---- 5. Front-run feasibility: when only Mark 14 quotes ----
def book_population(prices):
    """
    For each (day, ts), describe HP and VEV_4000 book:
    - L1 only? L1+L2? L1+L2+L3?
    - approx range = best_ask - best_bid
    """
    out = defaultdict(lambda: Counter())
    for (d, ts), syms in prices.items():
        for sym in ("HYDROGEL_PACK", "VEV_4000"):
            if sym not in syms:
                continue
            row = syms[sym]
            bbid, bask, bids, asks = _bbo(row)
            if bbid is None or bask is None:
                continue
            n_bid_levels = len(bids)
            n_ask_levels = len(asks)
            spread = bask - bbid
            out[sym][(n_bid_levels, n_ask_levels, int(spread))] += 1
    return out


def main():
    print("Loading…", flush=True)
    trades = load_trades()
    prices = load_prices()
    print(f"  trades={len(trades):,}  price-rows={len(prices):,}\n", flush=True)

    # 1. M38 product universe
    print("=" * 72)
    print("1. Mark 38 product universe:")
    print("=" * 72)
    sym_counts = mark38_products(trades)
    for sym, n in sym_counts.most_common():
        print(f"  {sym:25s}  trades={n}")
    print()

    # 2. Arrivals
    print("=" * 72)
    print("2. Mark 38 arrival distribution (per product per day):")
    print("=" * 72)
    arrivals = mark38_arrival_distribution(trades)
    print(f"  {'sym':<16}{'day':>4}{'n':>6}{'ticks':>7}{'first':>9}{'last':>9}"
          f"{'mean_gap':>10}{'med_gap':>9}{'p90_gap':>9}")
    for (sym, d), s in sorted(arrivals.items()):
        mg = s["mean_gap"] if s["mean_gap"] is not None else float("nan")
        med = s["median_gap"] if s["median_gap"] is not None else float("nan")
        p90 = s["p90_gap"] if s["p90_gap"] is not None else float("nan")
        print(f"  {sym:<16}{d:>4}{s['n_trades']:>6}{s['ticks_with_trade']:>7}"
              f"{s['first_ts']:>9}{s['last_ts']:>9}{mg:>10.0f}"
              f"{med:>9.0f}{p90:>9.0f}")
    print()

    # 3. Direction asymmetry
    print("=" * 72)
    print("3. Mark 38 direction asymmetry (h10 forward mid):")
    print("=" * 72)
    by_sym = mark38_direction_vs_mid(trades, prices)
    for sym, recs in by_sym.items():
        if not recs:
            continue
        buys = [r for r in recs if r["side"] == +1]
        sells = [r for r in recs if r["side"] == -1]
        # Mid move conditional on buy/sell
        b_fwd = [r["fwd"] for r in buys if r["fwd"] is not None]
        s_fwd = [r["fwd"] for r in sells if r["fwd"] is not None]
        b_edge = [r["edge"] for r in buys]
        s_edge = [r["edge"] for r in sells]

        def _stats(vals):
            if not vals:
                return (0, 0.0, 0.0, 0.0)
            n = len(vals)
            mu = sum(vals) / n
            sd = (sum((x - mu) ** 2 for x in vals) / n) ** 0.5
            t = mu / (sd / max(1, n) ** 0.5) if sd > 0 else 0.0
            return (n, mu, sd, t)

        bn, bmu, bsd, bt = _stats(b_fwd)
        sn, smu, ssd, st = _stats(s_fwd)
        be_n, be_mu, _, _ = _stats(b_edge)
        se_n, se_mu, _, _ = _stats(s_edge)
        print(f"  {sym}")
        print(f"    BUYS  n={len(buys):4d}  edge_pad_avg=+{be_mu:5.2f}  "
              f"fwd_h10 mu=+{bmu:+5.2f}  sd={bsd:5.2f}  t={bt:+5.2f}  "
              f"(buys followed by mid {'UP' if bmu > 0 else 'DOWN'})")
        print(f"    SELLS n={len(sells):4d}  edge_pad_avg=+{se_mu:5.2f}  "
              f"fwd_h10 mu=+{smu:+5.2f}  sd={ssd:5.2f}  t={st:+5.2f}  "
              f"(after a M38 sell, mid went {'DOWN' if smu > 0 else 'UP'})")
    print()

    # 4. Mark 14 quote location vs mid
    print("=" * 72)
    print("4. Mark 14 quote offset from mid, by spread regime:")
    print("=" * 72)
    m14 = mark14_offset_distribution(trades, prices)
    print(f"  {'sym':<16}{'spread':>7}{'n':>6}{'mean':>8}{'median':>8}{'p10':>7}{'p90':>7}")
    for (sym, spread), offsets in sorted(m14.items()):
        if len(offsets) < 5:
            continue
        offsets_sorted = sorted(offsets)
        n = len(offsets)
        mu = sum(offsets) / n
        med = statistics.median(offsets)
        p10 = offsets_sorted[int(n * 0.1)]
        p90 = offsets_sorted[int(n * 0.9)]
        print(f"  {sym:<16}{spread:>7}{n:>6}{mu:>8.2f}{med:>8.2f}{p10:>7.1f}{p90:>7.1f}")
    print()

    # 5. Book population
    print("=" * 72)
    print("5. Book population (HP and VEV_4000): how many levels are quoted?")
    print("=" * 72)
    bpop = book_population(prices)
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        if sym not in bpop:
            continue
        total = sum(bpop[sym].values())
        print(f"  {sym}  total ticks observed = {total}")
        # top 8 most common (n_bid, n_ask, spread)
        for (nb, na, sp), c in bpop[sym].most_common(10):
            print(f"    bids={nb} asks={na} spread={sp:>3}  count={c:>5}  ({100*c/total:5.1f}%)")
    print()

    # 6. M38 trade-coincidence-with-mid-jump (do we see preceding signals?)
    print("=" * 72)
    print("6. Mid move 1 tick AFTER Mark 38 trade (signed by his side):")
    print("=" * 72)
    for sym in ("HYDROGEL_PACK", "VEV_4000"):
        recs = by_sym.get(sym, [])
        # Use 1-tick fwd
        fwds_1 = []
        for t in trades:
            if not (t["buyer"] == "Mark 38" or t["seller"] == "Mark 38"):
                continue
            if t["symbol"] != sym:
                continue
            d = t["day"]
            ts = t["timestamp"]
            side = +1 if t["buyer"] == "Mark 38" else -1
            row_now = prices.get((d, ts), {}).get(sym)
            row_nxt = prices.get((d, ts + 100), {}).get(sym)
            if row_now is None or row_nxt is None:
                continue
            mn = fnum(row_now.get("mid_price"))
            mnx = fnum(row_nxt.get("mid_price"))
            if mn is None or mnx is None:
                continue
            fwds_1.append((mnx - mn) * side)
        if not fwds_1:
            continue
        n = len(fwds_1)
        mu = sum(fwds_1) / n
        sd = (sum((x - mu) ** 2 for x in fwds_1) / n) ** 0.5
        t_stat = mu / (sd / max(1, n) ** 0.5) if sd > 0 else 0.0
        print(f"  {sym}  n={n:4d}  mu_h1=+{mu:+6.3f}  sd={sd:5.2f}  t={t_stat:+5.2f}")
    print()


if __name__ == "__main__":
    main()
