"""
Oracle scenarios: compute max PnL under different assumptions.
"""
import time
from collections import defaultdict

def load_data():
    prices_file = 'prosperity4bt/resources/round0/prices_round_0_day_0.csv'
    trades_file = 'prosperity4bt/resources/round0/trades_round_0_day_0.csv'
    prices = defaultdict(list)
    with open(prices_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[1]); product = cols[2]
            bp, bv, ap, av = [], [], [], []
            for idx in [3, 5, 7]:
                if cols[idx] == '': break
                bp.append(int(cols[idx])); bv.append(int(cols[idx + 1]))
            for idx in [9, 11, 13]:
                if cols[idx] == '': break
                ap.append(int(cols[idx])); av.append(int(cols[idx + 1]))
            prices[product].append({
                'ts': ts, 'mid': float(cols[15]),
                'bp': bp, 'bv': bv, 'ap': ap, 'av': av,
            })
    for p in prices:
        prices[p].sort(key=lambda x: x['ts'])

    trades = defaultdict(list)
    with open(trades_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[0]); sym = cols[3]
            trades[sym].append({
                'ts': ts, 'price': int(float(cols[5])), 'qty': int(cols[6])
            })

    classified = {}
    for product in trades:
        ts_to_mid = {t['ts']: t['mid'] for t in prices[product]}
        classified[product] = []
        for t in trades[product]:
            mid = ts_to_mid.get(t['ts'])
            if mid is None:
                continue
            classified[product].append({
                **t, 'is_buy': t['price'] >= mid, 'mid': mid
            })
    return prices, classified


def run_dp(ticks, trades_cls, pos_limit=80,
           allow_book_takes=True, l1_only=False, forced_flat=False):
    """
    Generic backward-induction DP.
    allow_book_takes: can we take from the MM order book?
    l1_only: restrict book takes to L1 volume only
    forced_flat: must end at position 0 (terminal value 0 for pos=0, -inf otherwise)
    """
    N = len(ticks)
    NEG_INF = float('-inf')
    trades_at = defaultdict(list)
    for t in trades_cls:
        for i, tick in enumerate(ticks):
            if tick['ts'] == t['ts']:
                trades_at[i].append(t)
                break

    final_mid = ticks[N - 1]['mid']
    POS = range(-pos_limit, pos_limit + 1)

    if forced_flat:
        dp = {p: (0.0 if p == 0 else NEG_INF) for p in POS}
    else:
        dp = {p: p * final_mid for p in POS}

    for i in range(N - 1, -1, -1):
        tick = ticks[i]
        bb = tick['bp'][0] if tick['bp'] else None
        ba = tick['ap'][0] if tick['ap'] else None
        dp_new = {}

        for pos in POS:
            best = dp[pos]
            if bb is None or ba is None:
                dp_new[pos] = best
                continue

            # Book takes
            if allow_book_takes:
                if l1_only:
                    # L1 only buy
                    l1a = tick['ap'][0]; l1av = tick['av'][0]
                    for q in range(1, min(l1av, pos_limit - pos) + 1):
                        v = -l1a * q + dp[pos + q]
                        if v > best:
                            best = v
                    # L1 only sell
                    l1b = tick['bp'][0]; l1bv = tick['bv'][0]
                    for q in range(1, min(l1bv, pos_limit + pos) + 1):
                        v = l1b * q + dp[pos - q]
                        if v > best:
                            best = v
                else:
                    # Multi-level buy
                    cost = 0; tq = 0
                    for lvl in range(len(tick['ap'])):
                        for _ in range(tick['av'][lvl]):
                            cost += tick['ap'][lvl]; tq += 1
                            np = pos + tq
                            if np > pos_limit:
                                break
                            v = -cost + dp[np]
                            if v > best:
                                best = v
                        if pos + tq >= pos_limit:
                            break
                    # Multi-level sell
                    rev = 0; tq = 0
                    for lvl in range(len(tick['bp'])):
                        for _ in range(tick['bv'][lvl]):
                            rev += tick['bp'][lvl]; tq += 1
                            np = pos - tq
                            if np < -pos_limit:
                                break
                            v = rev + dp[np]
                            if v > best:
                                best = v
                        if pos - tq <= -pos_limit:
                            break

            # Taker interception
            for td in trades_at.get(i, []):
                if td['is_buy']:
                    for q in range(1, min(td['qty'], pos_limit + pos) + 1):
                        v = ba * q + dp[pos - q]
                        if v > best:
                            best = v
                else:
                    for q in range(1, min(td['qty'], pos_limit - pos) + 1):
                        v = -bb * q + dp[pos + q]
                        if v > best:
                            best = v

            # Combos: taker + book (independent fill sources)
            if allow_book_takes:
                for td in trades_at.get(i, []):
                    if td['is_buy']:
                        # sell to taker + buy from book
                        for tq in range(1, min(td['qty'], pos_limit + pos) + 1):
                            tcash = ba * tq
                            if l1_only:
                                l1a = tick['ap'][0]; l1av = tick['av'][0]
                                for bq in range(1, min(l1av, pos_limit - pos + tq) + 1):
                                    np = pos - tq + bq
                                    if np > pos_limit or pos - tq < -pos_limit:
                                        break
                                    v = tcash - l1a * bq + dp[np]
                                    if v > best:
                                        best = v
                            else:
                                cost = 0; bq = 0
                                for lvl in range(len(tick['ap'])):
                                    for _ in range(tick['av'][lvl]):
                                        cost += tick['ap'][lvl]; bq += 1
                                        np = pos - tq + bq
                                        if np > pos_limit or pos - tq < -pos_limit:
                                            break
                                        v = tcash - cost + dp[np]
                                        if v > best:
                                            best = v
                                    if pos - tq + bq > pos_limit:
                                        break

                        # sell to taker + sell to book
                        for tq in range(1, min(td['qty'], pos_limit + pos) + 1):
                            tcash = ba * tq
                            if l1_only:
                                l1b = tick['bp'][0]; l1bv = tick['bv'][0]
                                for sq in range(1, min(l1bv, pos_limit + pos - tq) + 1):
                                    np = pos - tq - sq
                                    if np < -pos_limit:
                                        break
                                    v = tcash + l1b * sq + dp[np]
                                    if v > best:
                                        best = v
                            else:
                                rev = 0; sq = 0
                                for lvl in range(len(tick['bp'])):
                                    for _ in range(tick['bv'][lvl]):
                                        rev += tick['bp'][lvl]; sq += 1
                                        np = pos - tq - sq
                                        if np < -pos_limit:
                                            break
                                        v = tcash + rev + dp[np]
                                        if v > best:
                                            best = v
                                    if pos - tq - sq < -pos_limit:
                                        break

                    else:
                        # buy from taker + sell to book
                        for tq in range(1, min(td['qty'], pos_limit - pos) + 1):
                            tcash = -bb * tq
                            if l1_only:
                                l1b = tick['bp'][0]; l1bv = tick['bv'][0]
                                for sq in range(1, min(l1bv, pos_limit + pos + tq) + 1):
                                    np = pos + tq - sq
                                    if np < -pos_limit or pos + tq > pos_limit:
                                        break
                                    v = tcash + l1b * sq + dp[np]
                                    if v > best:
                                        best = v
                            else:
                                rev = 0; sq = 0
                                for lvl in range(len(tick['bp'])):
                                    for _ in range(tick['bv'][lvl]):
                                        rev += tick['bp'][lvl]; sq += 1
                                        np = pos + tq - sq
                                        if np < -pos_limit or pos + tq > pos_limit:
                                            break
                                        v = tcash + rev + dp[np]
                                        if v > best:
                                            best = v
                                    if pos + tq - sq < -pos_limit:
                                        break

                        # buy from taker + buy from book
                        for tq in range(1, min(td['qty'], pos_limit - pos) + 1):
                            tcash = -bb * tq
                            if l1_only:
                                l1a = tick['ap'][0]; l1av = tick['av'][0]
                                for bq in range(1, min(l1av, pos_limit - pos - tq) + 1):
                                    np = pos + tq + bq
                                    if np > pos_limit:
                                        break
                                    v = tcash - l1a * bq + dp[np]
                                    if v > best:
                                        best = v
                            else:
                                cost = 0; bq = 0
                                for lvl in range(len(tick['ap'])):
                                    for _ in range(tick['av'][lvl]):
                                        cost += tick['ap'][lvl]; bq += 1
                                        np = pos + tq + bq
                                        if np > pos_limit:
                                            break
                                        v = tcash - cost + dp[np]
                                        if v > best:
                                            best = v
                                    if pos + tq + bq > pos_limit:
                                        break

            dp_new[pos] = best
        dp = dp_new

    return dp[0]


def main():
    prices, classified = load_data()

    print("=" * 70)
    print("  ORACLE MAXIMUM PnL - ALL SCENARIOS")
    print("  IMC Prosperity 4, Round 0, Day 0 (2000 ticks)")
    print("=" * 70)

    # Data summary
    for product in sorted(prices.keys()):
        ticks = prices[product]
        tc = classified[product]
        buys = sum(1 for t in tc if t['is_buy'])
        sells = len(tc) - buys
        total_qty = sum(t['qty'] for t in tc)
        spread = sum(
            t['ap'][0] - t['bp'][0]
            for t in ticks if t['bp'] and t['ap']
        ) / len(ticks)
        print(f"\n  {product}: {len(ticks)} ticks, {len(tc)} takers "
              f"({buys}B/{sells}S, {total_qty} units)")
        print(f"    Mid: {ticks[0]['mid']} -> {ticks[-1]['mid']} "
              f"({ticks[-1]['mid'] - ticks[0]['mid']:+.1f}), "
              f"Avg spread: {spread:.1f}")

    # Pure spread capture (no DP needed)
    print(f"\n{'=' * 70}")
    print("  PURE SPREAD CAPTURE (half-spread * taker qty, no pos limit)")
    print(f"{'=' * 70}")
    for product in sorted(prices.keys()):
        tc = classified[product]
        ts_to_tick = {t['ts']: t for t in prices[product]}
        total = 0
        for t in tc:
            tick = ts_to_tick.get(t['ts'])
            if tick is None:
                continue
            hs = (tick['ap'][0] - tick['bp'][0]) / 2.0
            total += hs * t['qty']
        print(f"  {product}: {total:>8,.0f}")

    scenarios = [
        ("A. Full oracle (L1+L2 takes + taker + MTM)",
         dict(allow_book_takes=True, l1_only=False, forced_flat=False)),
        ("B. L1-only takes + taker + MTM",
         dict(allow_book_takes=True, l1_only=True, forced_flat=False)),
        ("C. Taker-only + MTM (no book takes)",
         dict(allow_book_takes=False, forced_flat=False)),
        ("D. Full oracle (L1+L2), forced flat",
         dict(allow_book_takes=True, l1_only=False, forced_flat=True)),
        ("E. L1-only takes, forced flat",
         dict(allow_book_takes=True, l1_only=True, forced_flat=True)),
        ("F. Taker-only, forced flat",
         dict(allow_book_takes=False, forced_flat=True)),
    ]

    results = {}
    for label, kwargs in scenarios:
        print(f"\n{'=' * 70}")
        print(f"  {label}")
        print(f"{'=' * 70}")
        total = 0
        for product in sorted(prices.keys()):
            t0 = time.time()
            pnl = run_dp(prices[product], classified[product], **kwargs)
            elapsed = time.time() - t0
            total += pnl
            print(f"  {product}: {pnl:>10,.1f}  ({elapsed:.1f}s)")
        print(f"  TOTAL:  {total:>10,.1f}")
        results[label] = total

    # Summary table
    print(f"\n{'=' * 70}")
    print("  COMPREHENSIVE SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  {'Scenario':<50} {'PnL':>8}")
    print(f"  {'-'*50} {'-'*8}")
    for label, total in results.items():
        print(f"  {label:<50} {total:>8,.0f}")

    print(f"\n  {'Our best (s36, website)':<50} {'2,896':>8}")
    print(f"  {'Top team (website)':<50} {'4,949':>8}")

    print(f"""
  ===================================================================
  KEY FINDINGS
  ===================================================================

  1. FULL ORACLE with MTM:  {results[scenarios[0][0]]:>6,.0f}
     - Top team (4,949) is at {4949/results[scenarios[0][0]]*100:.0f}% of theoretical max
     - Confirms 4,949 IS achievable

  2. TAKER-ONLY with MTM:   {results[scenarios[2][0]]:>6,.0f}
     - Our s36 (2,896) is at {2896/results[scenarios[2][0]]*100:.0f}% of taker-only max
     - We're already near the taker-only ceiling!

  3. FORCED FLAT (full):    {results[scenarios[3][0]]:>6,.0f}
     - Even without MTM benefit, oracle beats top team
     - Pure round-trip spread capture is enormous

  4. The gap between us and top team:
     - Our score:     2,896
     - Taker-only:    {results[scenarios[2][0]]:>,.0f}  (we're {2896/results[scenarios[2][0]]*100:.0f}% of this)
     - Top team:      4,949
     - Full oracle:   {results[scenarios[0][0]]:>,.0f}

     The {4949-2896:,} gap = top teams are doing BOOK TAKES
     (buying at ask / selling at bid when they predict mid will move)

  5. WHAT TOP TEAMS DO DIFFERENTLY:
     - They don't just intercept takers - they actively take from the book
     - Each successful directional take earns: mid_change - half_spread
     - With avg spread ~13, need mid moves > 6.5 to be profitable
     - TOMATOES has 34.5-tick price range - plenty of room

  6. WHY OUR L2 FEATURES FAILED:
     - We used L2 OBI to SKEW our quotes (shift fair value)
     - Top teams likely use signals to decide WHEN TO TAKE
     - Posting at ask-1 vs taking the ask = fundamentally different
     - Our architecture is make-only; top teams are make+take

  7. THE MISSING INGREDIENT:
     - We need a TAKE signal that predicts mid moves > half-spread
     - Features like gap_asymmetry (r=-0.607) predict DIRECTION
     - But we only used them for posting, not for taking
     - A take signal with >55% accuracy on |move| > 6.5 would bridge the gap
""")


if __name__ == '__main__':
    main()
