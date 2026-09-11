"""Round 4 Counterparty (Mark) Mining.

Profiles each unique buyer/seller across all 3 days, all 12 products.

Outputs:
  - counterparty_mining_results.md (summary tables + actionable rules)
  - prints diagnostics to stdout

Run:
  python trader-logic/round-4/notes/counterparty_mining.py
"""
from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[3]  # repo root
DATA = ROOT / "prosperity4bt" / "resources" / "round4"
OUT_DIR = ROOT / "trader-logic" / "round-4" / "notes"
OUT_MD = OUT_DIR / "counterparty_mining_results.md"
DAYS = (1, 2, 3)
TICKS_PER_DAY = 10_000  # timestamps 0..999_900 step 100

PRODUCTS_VEV = [f"VEV_{k}" for k in (4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500)]
ALL_PRODUCTS = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", *PRODUCTS_VEV]
HORIZONS = (100, 500, 1000)  # ticks (each tick = 100 ts units)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_prices(day: int):
    rows = []
    with open(DATA / f"prices_round_4_day_{day}.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            rows.append(r)
    return rows


def load_trades(day: int):
    rows = []
    with open(DATA / f"trades_round_4_day_{day}.csv") as f:
        for r in csv.DictReader(f, delimiter=";"):
            rows.append(r)
    return rows


def build_mid_lookup():
    """Returns lookup[product][day] -> dict ts->mid (timestamps step 100)."""
    look = defaultdict(lambda: defaultdict(dict))
    for d in DAYS:
        for r in load_prices(d):
            p = r["product"]
            ts = int(r["timestamp"])
            mid = float(r["mid_price"])
            look[p][d][ts] = mid
    return look


def build_ts_index(mid_lookup):
    """Returns sorted ts list per product/day for fast look-ahead."""
    idx = defaultdict(lambda: defaultdict(list))
    for p, days in mid_lookup.items():
        for d, ts_dict in days.items():
            idx[p][d] = sorted(ts_dict.keys())
    return idx


# ---------------------------------------------------------------------------
# Per-Mark accumulator
# ---------------------------------------------------------------------------
class MarkProfile:
    def __init__(self, name: str):
        self.name = name
        # totals
        self.n_buy = 0
        self.n_sell = 0
        self.vol_buy = 0
        self.vol_sell = 0
        # per product
        self.buys_per_prod = Counter()       # n trades
        self.sells_per_prod = Counter()
        self.bvol_per_prod = Counter()       # volume
        self.svol_per_prod = Counter()
        # qty distribution all products
        self.qtys = []
        # qty per product (modal qty detection)
        self.qtys_per_prod = defaultdict(list)
        # price-vs-mid (signed: positive = above mid)
        self.px_minus_mid_buy = []
        self.px_minus_mid_sell = []
        self.cross_count = 0   # buyer paying >= ask or seller hitting <= bid
        self.passive_count = 0 # buyer at <=bid or seller at >=ask
        self.inside_count = 0  # at mid
        # timestamps (for clustering analysis)
        self.timestamps_per_day = defaultdict(list)  # day -> list[ts]
        # trades for forward-mid analysis
        # list of (product, day, ts, side='buy'|'sell', price, qty)
        self.trades = []

    def record_trade(self, side: str, ts: int, day: int, prod: str, price: float, qty: int,
                     mid: Optional[float], best_bid: Optional[int], best_ask: Optional[int]):
        self.qtys.append(qty)
        self.qtys_per_prod[prod].append(qty)
        self.timestamps_per_day[day].append(ts)
        self.trades.append((prod, day, ts, side, price, qty))
        if side == "buy":
            self.n_buy += 1
            self.vol_buy += qty
            self.buys_per_prod[prod] += 1
            self.bvol_per_prod[prod] += qty
            if mid is not None:
                self.px_minus_mid_buy.append(price - mid)
        else:
            self.n_sell += 1
            self.vol_sell += qty
            self.sells_per_prod[prod] += 1
            self.svol_per_prod[prod] += qty
            if mid is not None:
                self.px_minus_mid_sell.append(price - mid)
        # aggressiveness classification
        if best_bid is not None and best_ask is not None:
            if side == "buy":
                if price >= best_ask:
                    self.cross_count += 1
                elif price <= best_bid:
                    self.passive_count += 1
                else:
                    self.inside_count += 1
            else:
                if price <= best_bid:
                    self.cross_count += 1
                elif price >= best_ask:
                    self.passive_count += 1
                else:
                    self.inside_count += 1


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    print("Loading prices and building mid lookup ...", flush=True)
    mid_lookup = build_mid_lookup()
    ts_index = build_ts_index(mid_lookup)

    # also need best_bid/ask at trade time for aggressiveness
    book_lookup = defaultdict(lambda: defaultdict(dict))  # prod -> day -> ts -> (bb, ba)
    for d in DAYS:
        for r in load_prices(d):
            p = r["product"]
            ts = int(r["timestamp"])
            bb = int(r["bid_price_1"]) if r["bid_price_1"] else None
            ba = int(r["ask_price_1"]) if r["ask_price_1"] else None
            book_lookup[p][d][ts] = (bb, ba)

    print("Loading trades and building Mark profiles ...", flush=True)
    profiles: dict[str, MarkProfile] = {}
    pair_counter = Counter()       # (buyer,seller,product) -> count
    pair_vol = Counter()           # (buyer,seller,product) -> volume
    all_trades = []                # for cross-Mark analysis
    for d in DAYS:
        for r in load_trades(d):
            ts = int(r["timestamp"])
            buyer = r["buyer"]
            seller = r["seller"]
            prod = r["symbol"]
            price = float(r["price"])
            qty = int(r["quantity"])
            mid = mid_lookup[prod][d].get(ts)
            bb, ba = book_lookup[prod][d].get(ts, (None, None))

            # buyer side
            p_b = profiles.setdefault(buyer, MarkProfile(buyer))
            p_b.record_trade("buy", ts, d, prod, price, qty, mid, bb, ba)
            # seller side
            p_s = profiles.setdefault(seller, MarkProfile(seller))
            p_s.record_trade("sell", ts, d, prod, price, qty, mid, bb, ba)

            pair_counter[(buyer, seller, prod)] += 1
            pair_vol[(buyer, seller, prod)] += qty
            all_trades.append((d, ts, buyer, seller, prod, price, qty, mid, bb, ba))

    print(f"  {len(profiles)} unique Marks: {sorted(profiles)}", flush=True)
    print(f"  {len(all_trades)} total trades across 3 days", flush=True)

    # ----------------------------------------------------------------------
    # Forward mid-move predictor analysis
    # For each (Mark, product, side): for each trade compute mid(ts+H) - mid(ts)
    # Then mean / std / sample size and approximate t-stat / R^2.
    # ----------------------------------------------------------------------
    print("Computing forward mid-move predictors ...", flush=True)
    # forward_stats[(mark, side, prod, H)] -> list of forward_returns
    forward_stats = defaultdict(list)
    # baseline (per product/day) forward returns for null distribution
    baseline_fwd = defaultdict(list)  # (prod, H) -> list of fwd returns sampled at every tick

    # Pre-compute baseline once per (product, day)
    for prod in mid_lookup:
        for day in DAYS:
            ts_sorted = ts_index[prod][day]
            mids = mid_lookup[prod][day]
            for ts in ts_sorted:
                m0 = mids[ts]
                for H in HORIZONS:
                    target_ts = ts + H * 100  # H ticks of 100 ts each
                    m1 = mids.get(target_ts)
                    if m1 is None:
                        # find nearest <= target_ts
                        # binary search for efficiency
                        lo, hi = 0, len(ts_sorted) - 1
                        idx = -1
                        while lo <= hi:
                            mm = (lo + hi) // 2
                            if ts_sorted[mm] <= target_ts:
                                idx = mm
                                lo = mm + 1
                            else:
                                hi = mm - 1
                        if idx < 0 or ts_sorted[idx] < ts:
                            continue
                        m1 = mids[ts_sorted[idx]]
                    baseline_fwd[(prod, H)].append(m1 - m0)

    # Now per-trade forward returns
    for (d, ts, buyer, seller, prod, price, qty, mid, bb, ba) in all_trades:
        ts_sorted = ts_index[prod][d]
        mids = mid_lookup[prod][d]
        m0 = mids.get(ts)
        if m0 is None:
            continue
        for H in HORIZONS:
            target_ts = ts + H * 100
            m1 = mids.get(target_ts)
            if m1 is None:
                # binary search for nearest <= target_ts >= ts
                lo, hi = 0, len(ts_sorted) - 1
                idx = -1
                while lo <= hi:
                    mm = (lo + hi) // 2
                    if ts_sorted[mm] <= target_ts:
                        idx = mm
                        lo = mm + 1
                    else:
                        hi = mm - 1
                if idx < 0 or ts_sorted[idx] < ts:
                    continue
                m1 = mids[ts_sorted[idx]]
            fwd = m1 - m0
            forward_stats[(buyer, "buy", prod, H)].append(fwd)
            forward_stats[(seller, "sell", prod, H)].append(fwd)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------
    def safe_mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def safe_std(xs):
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5

    def t_stat(xs):
        if len(xs) < 2:
            return 0.0
        m = safe_mean(xs)
        s = safe_std(xs)
        if s == 0:
            return 0.0
        return m / (s / (len(xs) ** 0.5))

    def archetype(prof: MarkProfile) -> str:
        """Classify a Mark."""
        n_total = prof.n_buy + prof.n_sell
        if n_total == 0:
            return "INACTIVE"
        side_ratio = prof.n_buy / n_total
        cross_ratio = prof.cross_count / n_total if n_total else 0
        passive_ratio = prof.passive_count / n_total if n_total else 0
        modal_qty, modal_freq = (Counter(prof.qtys).most_common(1) or [(0, 0)])[0]
        modal_share = modal_freq / n_total if n_total else 0

        # Olivia signature: rare, big quantity, ALWAYS one side per session
        if n_total < 100 and modal_qty >= 15 and (side_ratio < 0.05 or side_ratio > 0.95):
            return "OLIVIA/INSIDER"

        # Drift trader: heavily one-sided, large vol, slow build
        if (side_ratio < 0.10 or side_ratio > 0.90) and (prof.vol_buy + prof.vol_sell) > 200:
            return "DRIFT-TRADER"

        # MM bot: high freq, both sides (~50/50), at-spread or passive
        if n_total > 200 and 0.30 < side_ratio < 0.70 and passive_ratio + 0.4 > cross_ratio:
            # additionally check modal qty is small/modest
            if modal_qty <= 10:
                return "MM BOT"

        # Aggressive taker: cross-spread > passive
        if cross_ratio > 0.55:
            return "AGGRESSIVE TAKER"

        # Otherwise flow noise
        return "FLOW NOISE"

    # ----------------------------------------------------------------------
    # Build markdown report
    # ----------------------------------------------------------------------
    print("Building markdown report ...", flush=True)
    lines = []
    L = lines.append

    L("# Round 4 Counterparty (Mark) Mining Results\n")
    L(f"_Generated by `counterparty_mining.py` from `prosperity4bt/resources/round4/`._\n")
    L(f"- Days analysed: {DAYS}")
    L(f"- Unique Marks: **{len(profiles)}** ({', '.join(sorted(profiles))})")
    L(f"- Total trades: **{len(all_trades)}**")
    L(f"- Products: 12 ({len(ALL_PRODUCTS)} expected)\n")

    # Pair-frequency sanity
    L("## 1. Trading-pair frequency (top 20)\n")
    L("Identifies recurring counterparty relationships (e.g. dedicated MM pairs).\n")
    L("| Buyer | Seller | Product | # Trades | Total Volume |")
    L("|-------|--------|---------|---------:|-------------:|")
    for (b, s, prod), cnt in pair_counter.most_common(20):
        L(f"| {b} | {s} | {prod} | {cnt} | {pair_vol[(b, s, prod)]} |")
    L("")

    # ----------------------------------------------------------------------
    # 2. Per-Mark profile table
    # ----------------------------------------------------------------------
    L("## 2. Per-Mark archetype + headline stats\n")
    L("| Mark | Archetype | Trades | Vol(buy/sell) | Buy% | ModalQty (share) | x-spread% | passive% | inside% | Top product | # products |")
    L("|------|-----------|-------:|--------------:|-----:|-----------------:|----------:|---------:|--------:|-------------|----------:|")
    for name in sorted(profiles):
        prof = profiles[name]
        n_total = prof.n_buy + prof.n_sell
        side_ratio = prof.n_buy / n_total if n_total else 0
        cross_ratio = prof.cross_count / n_total if n_total else 0
        passive_ratio = prof.passive_count / n_total if n_total else 0
        inside_ratio = prof.inside_count / n_total if n_total else 0
        modal = (Counter(prof.qtys).most_common(1) or [(0, 0)])[0]
        modal_share = modal[1] / n_total if n_total else 0
        # top product by combined volume
        prod_combined = Counter()
        for p, v in prof.bvol_per_prod.items():
            prod_combined[p] += v
        for p, v in prof.svol_per_prod.items():
            prod_combined[p] += v
        top_prod, top_vol = prod_combined.most_common(1)[0] if prod_combined else ("-", 0)
        n_distinct = len(prod_combined)
        arch = archetype(prof)
        L(f"| {name} | **{arch}** | {n_total} | {prof.vol_buy}/{prof.vol_sell} | {side_ratio:.0%} | "
          f"{modal[0]} ({modal_share:.0%}) | {cross_ratio:.0%} | {passive_ratio:.0%} | "
          f"{inside_ratio:.0%} | {top_prod} ({top_vol}) | {n_distinct} |")
    L("")

    # ----------------------------------------------------------------------
    # 3. Per-Mark deep dive
    # ----------------------------------------------------------------------
    L("## 3. Per-Mark deep dive\n")
    for name in sorted(profiles):
        prof = profiles[name]
        n_total = prof.n_buy + prof.n_sell
        L(f"### {name} ({archetype(prof)})\n")
        # qty distribution
        qty_counter = Counter(prof.qtys)
        top_qtys = qty_counter.most_common(8)
        L(f"- Trades: {n_total}  |  buys {prof.n_buy} / sells {prof.n_sell}  |  "
          f"vol buy {prof.vol_buy} / sell {prof.vol_sell}")
        if prof.qtys:
            L(f"- Qty: min={min(prof.qtys)} max={max(prof.qtys)} mean={safe_mean(prof.qtys):.1f} "
              f"median={statistics.median(prof.qtys):.0f}")
            L(f"- Top qty bins: {dict(top_qtys)}")
        # price vs mid
        if prof.px_minus_mid_buy:
            L(f"- Buy price vs mid: mean={safe_mean(prof.px_minus_mid_buy):+.2f} "
              f"(>0 = paying above mid)")
        if prof.px_minus_mid_sell:
            L(f"- Sell price vs mid: mean={safe_mean(prof.px_minus_mid_sell):+.2f} "
              f"(>0 = receiving above mid)")
        if n_total:
            L(f"- Aggressiveness: {prof.cross_count} crossing / {prof.passive_count} passive / "
              f"{prof.inside_count} inside ({prof.cross_count*100/n_total:.0f}/"
              f"{prof.passive_count*100/n_total:.0f}/{prof.inside_count*100/n_total:.0f}%)")
        # product mix
        prod_combined = Counter()
        for p, v in prof.bvol_per_prod.items():
            prod_combined[p] += v
        for p, v in prof.svol_per_prod.items():
            prod_combined[p] += v
        top_prods = prod_combined.most_common(6)
        L(f"- Top products by volume: {dict(top_prods)}")
        # per-product side bias
        bias_lines = []
        for p in sorted(set(prof.buys_per_prod) | set(prof.sells_per_prod)):
            nb = prof.buys_per_prod.get(p, 0)
            ns = prof.sells_per_prod.get(p, 0)
            if nb + ns >= 5:
                bias_lines.append(f"{p}: {nb}b/{ns}s ({nb*100/(nb+ns):.0f}% buy)")
        if bias_lines:
            L(f"- Per-product side bias: {'; '.join(bias_lines[:8])}")
        # time-of-day clustering
        for d in DAYS:
            tss = prof.timestamps_per_day[d]
            if not tss:
                continue
            # Bucket into 10 deciles of the day (10k tick total = 1_000_000 ts)
            buckets = [0] * 10
            for t in tss:
                b = min(9, int(t // 100_000))
                buckets[b] += 1
            uniform = len(tss) / 10
            # chi-square statistic
            chi2 = sum((b - uniform) ** 2 / uniform for b in buckets) if uniform else 0
            L(f"- Day {d} time clustering (decile counts, n={len(tss)}): {buckets}  chi2={chi2:.0f}")
        L("")

    # ----------------------------------------------------------------------
    # 4. Forward-mid-move alpha screen
    # ----------------------------------------------------------------------
    L("## 4. Forward-mid-move alpha screen\n")
    L("For each (Mark, side, product) with >=10 trades, compute mean forward mid-move "
      "at H=100/500/1000 ticks. Compare against per-product baseline mean (random tick).\n")
    L("Sign convention: positive forward = mid went UP after the trade. "
      "If a Mark **buys** and forward is large positive -> good predictor. "
      "If a Mark **sells** and forward is large negative -> good predictor (right-side info).\n")
    L("| Mark | Side | Product | n | H | mean fwd | t-stat | baseline mean | edge vs base |")
    L("|------|------|---------|--:|--:|---------:|-------:|--------------:|-------------:|")
    actionable = []
    for (mark, side, prod, H), fwds in sorted(forward_stats.items()):
        if len(fwds) < 10:
            continue
        m_fwd = safe_mean(fwds)
        s_fwd = safe_std(fwds)
        ts_v = t_stat(fwds)
        base = baseline_fwd.get((prod, H), [])
        m_base = safe_mean(base) if base else 0.0
        edge = m_fwd - m_base
        # significance gate: |t| > 2 and edge sign aligned with side
        signed_edge = edge if side == "buy" else -edge  # for "sell" we want negative forward
        flag = ""
        if abs(ts_v) >= 2.0 and signed_edge > 0:
            flag = " ★"
            actionable.append((mark, side, prod, H, m_fwd, ts_v, m_base, edge, len(fwds)))
        L(f"| {mark} | {side} | {prod} | {len(fwds)} | {H} | {m_fwd:+.2f} | {ts_v:+.2f} | "
          f"{m_base:+.3f} | {edge:+.2f}{flag} |")
    L("")

    # ----------------------------------------------------------------------
    # 5. Actionable rules (top-ranked by signed t-stat)
    # ----------------------------------------------------------------------
    L("## 5. Actionable rules (statistically significant predictors)\n")
    if not actionable:
        L("_No (Mark, side, product, H) cell crossed |t|>=2 with sign-aligned forward move._\n")
    else:
        # Rank by |t| * sqrt(n) basically t-stat magnitude already encodes n
        actionable.sort(key=lambda x: abs(x[5]), reverse=True)
        L("| Rank | Mark | Side | Product | H | n | mean fwd | t-stat | edge vs base | suggested rule |")
        L("|-----:|------|------|---------|--:|--:|---------:|-------:|-------------:|----------------|")
        for i, (mark, side, prod, H, m_fwd, ts_v, m_base, edge, n) in enumerate(actionable[:25], 1):
            if side == "buy":
                action = f"FOLLOW: when {mark} buys {prod}, BUY within {H} ticks"
            else:
                action = f"FOLLOW: when {mark} sells {prod}, SELL within {H} ticks"
            L(f"| {i} | {mark} | {side} | {prod} | {H} | {n} | {m_fwd:+.2f} | {ts_v:+.2f} | "
              f"{edge:+.2f} | {action} |")
    L("")

    # ----------------------------------------------------------------------
    # 6. Cross-product / pair micro-analysis (Mark 01 vs Mark 22 etc.)
    # ----------------------------------------------------------------------
    L("## 6. Pair-cluster micro-analysis\n")
    L("Some Marks appear to be obligate counterparties (pre-arranged MM pairs). "
      "If Mark A & Mark B trade together >50% of A's volume, treat as a single MM bot pair.\n")
    L("| Mark | Counterparty | Pair-trade share of Mark's total |")
    L("|------|-------------|-----------------------------------:|")
    pair_share_rows = []
    for name, prof in profiles.items():
        n_total = prof.n_buy + prof.n_sell
        if n_total == 0:
            continue
        # collect counterparties
        cparty_count = Counter()
        for (b, s, _p), c in pair_counter.items():
            if b == name:
                cparty_count[s] += c
            elif s == name:
                cparty_count[b] += c
        for cp, cnt in cparty_count.most_common(3):
            pair_share_rows.append((name, cp, cnt, n_total))
    pair_share_rows.sort(key=lambda x: -x[2] / max(1, x[3]))
    for name, cp, cnt, n_total in pair_share_rows[:20]:
        L(f"| {name} | {cp} | {cnt}/{n_total} ({cnt*100/n_total:.0f}%) |")
    L("")

    # ----------------------------------------------------------------------
    # 7. Olivia hunt — explicit checks
    # ----------------------------------------------------------------------
    L("## 7. Olivia/insider explicit hunt\n")
    L("Round 0 'Olivia' signature: rare trades (<100 across day), modal qty=15, "
      "ALWAYS at one extreme (only buys at lows, only sells at highs).\n")
    olivia_lines = []
    # Build per-product min/max for each day to test 'extreme' bias
    per_prod_extremes = {}
    mid_lookup_l = mid_lookup
    for prod in ALL_PRODUCTS:
        per_prod_extremes[prod] = {}
        for d in DAYS:
            mids = list(mid_lookup_l[prod][d].values())
            if not mids:
                continue
            lo, hi = min(mids), max(mids)
            per_prod_extremes[prod][d] = (lo, hi)
    for name, prof in profiles.items():
        n_total = prof.n_buy + prof.n_sell
        if n_total > 200:
            continue
        # count trades at extreme (within 10% of range from side appropriate)
        extreme_buys = 0
        extreme_sells = 0
        for (prod, day, ts, side, price, qty) in prof.trades:
            ext = per_prod_extremes.get(prod, {}).get(day)
            if not ext:
                continue
            lo, hi = ext
            band = max(1.0, (hi - lo) * 0.10)
            mid_at = mid_lookup_l[prod][day].get(ts)
            if mid_at is None:
                continue
            if side == "buy" and mid_at <= lo + band:
                extreme_buys += 1
            elif side == "sell" and mid_at >= hi - band:
                extreme_sells += 1
        if extreme_buys + extreme_sells >= 3:
            olivia_lines.append(f"- **{name}**: {extreme_buys} extreme-low buys + "
                                f"{extreme_sells} extreme-high sells (out of {n_total} total)")
    if olivia_lines:
        for ln in olivia_lines:
            L(ln)
    else:
        L("_No Mark exhibits Olivia-style extreme-only trading._\n")
    L("")

    # ----------------------------------------------------------------------
    # 8. Summary archetype-key takeaways
    # ----------------------------------------------------------------------
    L("## 8. Strategic implications for our R4 trader\n")
    L("Bullet-point summary of the most actionable findings, derived from sections 1-7.\n")
    # Auto-derive a few generic implications
    archs = {n: archetype(p) for n, p in profiles.items()}
    mm_bots = [n for n, a in archs.items() if a == "MM BOT"]
    aggressors = [n for n, a in archs.items() if a == "AGGRESSIVE TAKER"]
    drifters = [n for n, a in archs.items() if a == "DRIFT-TRADER"]
    insiders = [n for n, a in archs.items() if a == "OLIVIA/INSIDER"]
    L(f"- **MM bots** (avoid adverse selection / use as quote anchor): {', '.join(mm_bots) or 'none'}")
    L(f"- **Aggressive takers** (their trades = noise; safe to be on the other side): "
      f"{', '.join(aggressors) or 'none'}")
    L(f"- **Drift traders / position builders**: {', '.join(drifters) or 'none'}")
    L(f"- **Olivia-style insiders**: {', '.join(insiders) or 'none — fall back on extreme-bias hunt'}")
    L("")
    L("### Manually curated qualitative insights\n")
    L("- **Mark 01 ↔ Mark 22 obligate pair on OTM vouchers (VEV_5300..6500).** "
      "Mark 01 always BUYS, Mark 22 always SELLS at fixed prices — Mark 22 sells deep-OTM premium "
      "(VEV_6000/6500 prints at 0.0 currency!). This is a pre-baked premium-decay loop — "
      "**ignore as alpha**, but **don't compete with their fixed quotes** on those strikes.")
    L("- **Mark 38 ↔ Mark 14 obligate pair on HYDROGEL_PACK (1003 trades, 98% of Mark 38's volume).** "
      "Mark 14 quotes passive at best±~6, Mark 38 always crosses. Together they account for "
      "~75% of HP volume. **If Mark 14 widens or stops quoting → liquidity vacuum, expect spread blow-out.** "
      "On VEV_4000 same dynamic.")
    L("- **Mark 55 is the dominant VFE aggressive taker (1198 trades, 100% crossing, 50/50 sides).** "
      "Predictive at H=100 for sells (-0.90 fwd, t=-2.48) — but signal washes out past 500 ticks. "
      "**Use as a short-term contrarian fade trigger** rather than directional signal.")
    L("- **Mark 67 is a one-sided VFE buyer (165 trades, 100% buy, modal qty 8-9).** "
      "Strong forward predictor: +1.57 mid at H=100 (t=+2.13). **Closest analog to an Olivia signal.** "
      "Trade alongside Mark 67's buys.")
    L("- **Mark 49 is a one-sided VFE seller (105 sells / 17 buys, modal qty 8-15).** "
      "98% passive (rests asks). Forward at H=100 = +1.92 (mid rises after he sells, the OPPOSITE "
      "of useful info — he's getting picked off). **Take liquidity from Mark 49 when his qty>=10 prints.**")
    L("- **No Olivia/insider in R4.** Modal qty ceiling is 15 only for Mark 49/67 — and neither shows "
      "the extreme-only trading pattern. R4 alpha must come from pair structure, not single-Mark hunts.")
    L("")
    if actionable:
        top3 = actionable[:3]
        L("- **Top 3 alpha rules** (from section 5):")
        for (mark, side, prod, H, m_fwd, ts_v, m_base, edge, n) in top3:
            if side == "buy":
                L(f"  - When **{mark}** buys **{prod}** -> BUY in next {H} ticks "
                  f"(mean +{m_fwd:.2f} fwd, t={ts_v:+.2f}, n={n})")
            else:
                L(f"  - When **{mark}** sells **{prod}** -> SELL in next {H} ticks "
                  f"(mean {m_fwd:+.2f} fwd, t={ts_v:+.2f}, n={n})")
    else:
        L("- No statistically significant single-Mark predictor (|t|>=2). "
          "Counterparty data may still help via *pair* signatures (section 6).")

    # write file
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote markdown report to {OUT_MD}", flush=True)
    print(f"  ({len(lines)} lines)")

    # also print headline summary to stdout
    print("\n=== HEADLINE ===")
    print(f"Marks identified: {sorted(profiles)}")
    for name in sorted(profiles):
        prof = profiles[name]
        n = prof.n_buy + prof.n_sell
        print(f"  {name}: {archetype(prof):>18}  trades={n:>4}  "
              f"buy%={prof.n_buy*100/max(1,n):>3.0f}  cross%={prof.cross_count*100/max(1,n):>3.0f}  "
              f"products={len(set(prof.buys_per_prod) | set(prof.sells_per_prod))}")
    if actionable:
        print(f"\nActionable rules found: {len(actionable)}")
        for (mark, side, prod, H, m_fwd, ts_v, m_base, edge, n) in actionable[:5]:
            print(f"  {mark:>8} {side:>4} {prod:>22} H={H:>4} n={n:>3} "
                  f"fwd={m_fwd:+.2f} t={ts_v:+.2f}")
    else:
        print("\nNo statistically significant alpha predictors at |t|>=2.")


if __name__ == "__main__":
    main()
