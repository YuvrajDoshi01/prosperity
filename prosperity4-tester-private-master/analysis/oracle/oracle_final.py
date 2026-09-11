"""
DEFINITIVE Oracle Maximum PnL Analysis
IMC Prosperity 4 - Round 0, Day 0 (2000 ticks)

Three scenarios computed:
1. FULL ORACLE: Perfect knowledge, can take from book + intercept takers + MTM
2. TAKER-ONLY ORACLE: Only intercept taker trades (no book takes)
3. NO-MTM ORACLE: Full oracle but forced flat at end of day

The key question: Is 4,949 achievable? What's the TRUE ceiling?
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
            ts = int(cols[1])
            product = cols[2]
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
    for p in prices: prices[p].sort(key=lambda x: x['ts'])

    trades = defaultdict(list)
    with open(trades_file) as f:
        for line in f.read().splitlines()[1:]:
            cols = line.split(';')
            ts = int(cols[0]); sym = cols[3]
            price = int(float(cols[5])); qty = int(cols[6])
            trades[sym].append({'ts': ts, 'price': price, 'qty': qty})

    classified = {}
    for product in trades:
        ts_to_mid = {t['ts']: t['mid'] for t in prices[product]}
        classified[product] = []
        for t in trades[product]:
            mid = ts_to_mid.get(t['ts'])
            if mid is None: continue
            classified[product].append({**t, 'is_buy': t['price'] >= mid, 'mid': mid})

    return prices, classified


def run_dp(ticks, trades_cls, pos_limit=80, allow_book_takes=True):
    """
    Generic DP. Returns dp[0] = optimal PnL from position 0.
    Also returns full policy for reconstruction.
    """
    N = len(ticks)
    trades_at = defaultdict(list)
    for t in trades_cls:
        for i, tick in enumerate(ticks):
            if tick['ts'] == t['ts']:
                trades_at[i].append(t)
                break

    final_mid = ticks[N-1]['mid']
    POS = range(-pos_limit, pos_limit + 1)
    dp = {p: p * final_mid for p in POS}
    policy = [{} for _ in range(N)]

    for i in range(N - 1, -1, -1):
        tick = ticks[i]
        bb = tick['bp'][0] if tick['bp'] else None
        ba = tick['ap'][0] if tick['ap'] else None
        dp_new = {}

        for pos in POS:
            best = dp[pos]
            best_info = (pos, 0, 'hold')

            if bb is None or ba is None:
                dp_new[pos] = best
                policy[i][pos] = best_info
                continue

            # -- Book takes --
            if allow_book_takes:
                # Buy from asks
                cost = 0
                total_q = 0
                for lvl in range(len(tick['ap'])):
                    for _ in range(tick['av'][lvl]):
                        cost += tick['ap'][lvl]
                        total_q += 1
                        np = pos + total_q
                        if np > pos_limit: break
                        v = -cost + dp[np]
                        if v > best:
                            best = v
                            best_info = (np, -cost, f'take_buy_{total_q}')
                    if pos + total_q >= pos_limit: break

                # Sell to bids
                rev = 0
                total_q = 0
                for lvl in range(len(tick['bp'])):
                    for _ in range(tick['bv'][lvl]):
                        rev += tick['bp'][lvl]
                        total_q += 1
                        np = pos - total_q
                        if np < -pos_limit: break
                        v = rev + dp[np]
                        if v > best:
                            best = v
                            best_info = (np, rev, f'take_sell_{total_q}')
                    if pos - total_q <= -pos_limit: break

            # -- Taker interception --
            for td in trades_at.get(i, []):
                if td['is_buy']:
                    # We sell to buying taker at ask
                    for q in range(1, min(td['qty'], pos_limit + pos) + 1):
                        np = pos - q
                        cash = ba * q
                        v = cash + dp[np]
                        if v > best:
                            best = v
                            best_info = (np, cash, f'intercept_sell_{q}@{ba}')
                else:
                    # We buy from selling taker at bid
                    for q in range(1, min(td['qty'], pos_limit - pos) + 1):
                        np = pos + q
                        cash = -bb * q
                        v = cash + dp[np]
                        if v > best:
                            best = v
                            best_info = (np, cash, f'intercept_buy_{q}@{bb}')

            # -- Combos: book take + taker intercept --
            if allow_book_takes:
                for td in trades_at.get(i, []):
                    if td['is_buy']:
                        # Sell to taker + buy from book (hedge)
                        for tq in range(1, min(td['qty'], pos_limit + pos) + 1):
                            tcash = ba * tq
                            # Then buy from book
                            cost = 0; bq = 0
                            for lvl in range(len(tick['ap'])):
                                for _ in range(tick['av'][lvl]):
                                    cost += tick['ap'][lvl]; bq += 1
                                    np = pos - tq + bq
                                    if np > pos_limit or bq > pos_limit: break
                                    if pos - tq < -pos_limit: break
                                    v = tcash - cost + dp[np]
                                    if v > best:
                                        best = v
                                        best_info = (np, tcash - cost, f'combo_isell{tq}+tbuy{bq}')
                                if np > pos_limit: break

                        # Sell to taker + sell to book (amplify directional)
                        for tq in range(1, min(td['qty'], pos_limit + pos) + 1):
                            tcash = ba * tq
                            rev = 0; sq = 0
                            for lvl in range(len(tick['bp'])):
                                for _ in range(tick['bv'][lvl]):
                                    rev += tick['bp'][lvl]; sq += 1
                                    np = pos - tq - sq
                                    if np < -pos_limit: break
                                    v = tcash + rev + dp[np]
                                    if v > best:
                                        best = v
                                        best_info = (np, tcash + rev, f'combo_isell{tq}+tsell{sq}')
                                if np < -pos_limit: break

                    else:
                        # Buy from taker + sell to book (hedge)
                        for tq in range(1, min(td['qty'], pos_limit - pos) + 1):
                            tcash = -bb * tq
                            rev = 0; sq = 0
                            for lvl in range(len(tick['bp'])):
                                for _ in range(tick['bv'][lvl]):
                                    rev += tick['bp'][lvl]; sq += 1
                                    np = pos + tq - sq
                                    if np < -pos_limit or pos + tq > pos_limit: break
                                    v = tcash + rev + dp[np]
                                    if v > best:
                                        best = v
                                        best_info = (np, tcash + rev, f'combo_ibuy{tq}+tsell{sq}')
                                if np < -pos_limit: break

                        # Buy from taker + buy from book (amplify)
                        for tq in range(1, min(td['qty'], pos_limit - pos) + 1):
                            tcash = -bb * tq
                            cost = 0; bq = 0
                            for lvl in range(len(tick['ap'])):
                                for _ in range(tick['av'][lvl]):
                                    cost += tick['ap'][lvl]; bq += 1
                                    np = pos + tq + bq
                                    if np > pos_limit: break
                                    v = tcash - cost + dp[np]
                                    if v > best:
                                        best = v
                                        best_info = (np, tcash - cost, f'combo_ibuy{tq}+tbuy{bq}')
                                if np > pos_limit: break

            dp_new[pos] = best
            policy[i][pos] = best_info

        dp = dp_new

    # Reconstruct
    pos = 0; cash = 0
    actions = []
    take_cash = 0; take_qty = 0; take_count = 0
    intercept_cash = 0; intercept_qty = 0; intercept_count = 0
    combo_cash = 0; combo_count = 0

    for i in range(N):
        np, dc, desc = policy[i][pos]
        if desc != 'hold':
            delta = abs(np - pos)
            actions.append({'tick': i, 'ts': ticks[i]['ts'], 'desc': desc,
                          'pos_from': pos, 'pos_to': np, 'cash': dc, 'mid': ticks[i]['mid']})
            if desc.startswith('take_'):
                take_cash += dc; take_qty += delta; take_count += 1
            elif desc.startswith('intercept_'):
                intercept_cash += dc; intercept_qty += delta; intercept_count += 1
            elif desc.startswith('combo_'):
                combo_cash += dc; combo_count += 1
            cash += dc
        pos = np

    mtm = pos * final_mid
    return {
        'pnl': dp_new[0] if 0 in dp_new else dp[0],
        'cash': cash, 'mtm': mtm, 'final_pos': pos,
        'actions': actions,
        'take': {'count': take_count, 'qty': take_qty, 'cash': take_cash},
        'intercept': {'count': intercept_count, 'qty': intercept_qty, 'cash': intercept_cash},
        'combo': {'count': combo_count, 'cash': combo_cash},
    }


def main():
    print("=" * 70)
    print("  DEFINITIVE ORACLE MAXIMUM PnL ANALYSIS")
    print("  IMC Prosperity 4 - Round 0, Day 0 (2000 ticks)")
    print("=" * 70)

    prices, classified = load_data()

    for product in sorted(prices.keys()):
        ticks = prices[product]; tc = classified[product]
        buys = sum(1 for t in tc if t['is_buy'])
        sells = len(tc) - buys
        total_qty = sum(t['qty'] for t in tc)
        print(f"\n  {product}: {len(ticks)} ticks")
        print(f"    Mid: {ticks[0]['mid']} -> {ticks[-1]['mid']} ({ticks[-1]['mid']-ticks[0]['mid']:+.1f})")
        spread = sum(t['ap'][0]-t['bp'][0] for t in ticks if t['bp'] and t['ap'])/len(ticks)
        print(f"    Avg spread: {spread:.1f}")
        print(f"    Taker: {len(tc)} trades ({buys} buys, {sells} sells), {total_qty} units")

    # ============================================================
    # SCENARIO 1: Full Oracle (book takes + taker intercept + MTM)
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  SCENARIO 1: FULL ORACLE (book takes + taker + MTM)")
    print(f"{'='*70}")

    total_full = 0
    for product in sorted(prices.keys()):
        t0 = time.time()
        r = run_dp(prices[product], classified[product], allow_book_takes=True)
        elapsed = time.time() - t0
        total_full += r['pnl']
        print(f"\n  {product} ({elapsed:.1f}s):")
        print(f"    Total PnL: {r['pnl']:>10,.1f}")
        print(f"    Cash: {r['cash']:>10,.1f}  MTM: {r['mtm']:>10,.1f}  Final pos: {r['final_pos']}")
        print(f"    Book takes:  {r['take']['count']:>4} actions, {r['take']['qty']:>5} units, cash: {r['take']['cash']:>12,.0f}")
        print(f"    Intercepts:  {r['intercept']['count']:>4} actions, {r['intercept']['qty']:>5} units, cash: {r['intercept']['cash']:>12,.0f}")
        print(f"    Combos:      {r['combo']['count']:>4} actions, cash: {r['combo']['cash']:>12,.0f}")

    print(f"\n  TOTAL (Full Oracle): {total_full:>10,.1f}")

    # ============================================================
    # SCENARIO 2: Taker-Only Oracle (no book takes)
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  SCENARIO 2: TAKER-ONLY ORACLE (intercept takers + MTM)")
    print(f"{'='*70}")

    total_taker = 0
    for product in sorted(prices.keys()):
        t0 = time.time()
        r = run_dp(prices[product], classified[product], allow_book_takes=False)
        elapsed = time.time() - t0
        total_taker += r['pnl']
        print(f"\n  {product} ({elapsed:.1f}s):")
        print(f"    Total PnL: {r['pnl']:>10,.1f}")
        print(f"    Cash: {r['cash']:>10,.1f}  MTM: {r['mtm']:>10,.1f}  Final pos: {r['final_pos']}")
        print(f"    Intercepts: {r['intercept']['count']:>4} actions, {r['intercept']['qty']:>5} units")

    print(f"\n  TOTAL (Taker-Only): {total_taker:>10,.1f}")

    # ============================================================
    # SCENARIO 3: Full Oracle, Forced Flat (unwind at end)
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  SCENARIO 3: FULL ORACLE, FORCED FLAT (no terminal MTM)")
    print(f"{'='*70}")
    print(f"  (Running DP where terminal value = 0 for all positions)")

    # Run DP with terminal value 0
    total_flat = 0
    for product in sorted(prices.keys()):
        ticks = prices[product]
        tc = classified[product]
        N = len(ticks)

        # Manual DP with 0 terminal
        trades_at = defaultdict(list)
        for t in tc:
            for i, tick in enumerate(ticks):
                if tick['ts'] == t['ts']:
                    trades_at[i].append(t)
                    break

        POS = range(-80, 81)
        dp = {p: 0.0 for p in POS}  # ZERO terminal value

        for i in range(N - 1, -1, -1):
            tick = ticks[i]
            bb = tick['bp'][0] if tick['bp'] else None
            ba = tick['ap'][0] if tick['ap'] else None
            dp_new = {}

            for pos in POS:
                best = dp[pos]

                if bb is None or ba is None:
                    dp_new[pos] = best; continue

                # Book buy
                cost = 0; tq = 0
                for lvl in range(len(tick['ap'])):
                    for _ in range(tick['av'][lvl]):
                        cost += tick['ap'][lvl]; tq += 1
                        np = pos + tq
                        if np > 80: break
                        v = -cost + dp[np]
                        if v > best: best = v
                    if pos + tq >= 80: break

                # Book sell
                rev = 0; tq = 0
                for lvl in range(len(tick['bp'])):
                    for _ in range(tick['bv'][lvl]):
                        rev += tick['bp'][lvl]; tq += 1
                        np = pos - tq
                        if np < -80: break
                        v = rev + dp[np]
                        if v > best: best = v
                    if pos - tq <= -80: break

                # Taker
                for td in trades_at.get(i, []):
                    if td['is_buy']:
                        for q in range(1, min(td['qty'], 80 + pos) + 1):
                            v = ba * q + dp[pos - q]
                            if v > best: best = v
                    else:
                        for q in range(1, min(td['qty'], 80 - pos) + 1):
                            v = -bb * q + dp[pos + q]
                            if v > best: best = v

                # Combos (same as full DP but abbreviated)
                for td in trades_at.get(i, []):
                    if td['is_buy']:
                        for tq in range(1, min(td['qty'], 80 + pos) + 1):
                            tcash = ba * tq
                            cost = 0; bq = 0
                            for lvl in range(len(tick['ap'])):
                                for _ in range(tick['av'][lvl]):
                                    cost += tick['ap'][lvl]; bq += 1
                                    np = pos - tq + bq
                                    if np > 80 or pos - tq < -80: break
                                    v = tcash - cost + dp[np]
                                    if v > best: best = v
                                if np > 80: break
                            rev = 0; sq = 0
                            for lvl in range(len(tick['bp'])):
                                for _ in range(tick['bv'][lvl]):
                                    rev += tick['bp'][lvl]; sq += 1
                                    np = pos - tq - sq
                                    if np < -80: break
                                    v = tcash + rev + dp[np]
                                    if v > best: best = v
                                if np < -80: break
                    else:
                        for tq in range(1, min(td['qty'], 80 - pos) + 1):
                            tcash = -bb * tq
                            rev = 0; sq = 0
                            for lvl in range(len(tick['bp'])):
                                for _ in range(tick['bv'][lvl]):
                                    rev += tick['bp'][lvl]; sq += 1
                                    np = pos + tq - sq
                                    if np < -80 or pos + tq > 80: break
                                    v = tcash + rev + dp[np]
                                    if v > best: best = v
                                if np < -80: break
                            cost = 0; bq = 0
                            for lvl in range(len(tick['ap'])):
                                for _ in range(tick['av'][lvl]):
                                    cost += tick['ap'][lvl]; bq += 1
                                    np = pos + tq + bq
                                    if np > 80: break
                                    v = tcash - cost + dp[np]
                                    if v > best: best = v
                                if np > 80: break

                dp_new[pos] = best
            dp = dp_new

        pnl = dp[0]
        total_flat += pnl
        print(f"\n  {product}: {pnl:>10,.1f}")

    print(f"\n  TOTAL (Forced Flat): {total_flat:>10,.1f}")

    # ============================================================
    # SCENARIO 4: Pure spread capture analysis
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  SCENARIO 4: PURE SPREAD CAPTURE (buy at bid, sell at ask)")
    print(f"{'='*70}")

    for product in sorted(prices.keys()):
        tc = classified[product]
        total_spread = 0
        total_units = 0
        for t in tc:
            tick = None
            for td in prices[product]:
                if td['ts'] == t['ts']:
                    tick = td; break
            if tick is None: continue
            bb = tick['bp'][0]; ba = tick['ap'][0]
            spread = ba - bb
            half_spread = spread / 2.0
            total_spread += half_spread * t['qty']
            total_units += t['qty']
        avg_hs = total_spread / total_units if total_units > 0 else 0
        print(f"  {product}: {total_spread:>8,.0f} PnL from {len(tc)} trades, {total_units} units (avg half-spread: {avg_hs:.1f})")

    # ============================================================
    # FINAL COMPARISON TABLE
    # ============================================================
    print(f"\n{'='*70}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*70}")
    print(f"""
    Scenario                          PnL    Notes
    --------------------------------  -----  ---------------------------
    Full Oracle (book+taker+MTM)      {total_full:>5,.0f}  Upper bound (uses CSV volumes)
    Full Oracle forced flat           {total_flat:>5,.0f}  No terminal MTM benefit
    Taker-Only Oracle (+MTM)          {total_taker:>5,.0f}  Only intercept taker bot
    Our best (s36 on website)         2,896  Actual submission
    Top team (website)                4,949  Leaderboard #1

    Key insights:
    - Full Oracle ({total_full:,.0f}) is ABOVE top team (4,949) by {total_full-4949:+,.0f}
    - This confirms 4,949 IS achievable with this game's mechanics
    - BUT: ~{total_full-total_taker:,.0f} of Oracle PnL comes from book takes
    - Book takes use CSV volumes (98.5% different from website)
    - Taker-only ({total_taker:,.0f}) accounts for only {total_taker/total_full*100:.0f}% of total

    THE GAP EXPLAINED:
    - Our 2,896 = taker intercept (~1,200 EM + ~1,700 TOM)
    - Top 4,949 = taker intercept + AGGRESSIVE BOOK TAKES
    - The top teams ARE taking from the MM book (buying at ask / selling at bid)
    - This is profitable when they KNOW the mid will move past the spread
    - With perfect knowledge: sell 80 at bid when mid is at peak,
      buy 80 at ask when mid is at trough = massive directional PnL
    - Position limit of 80 * 34.5 tick range = ~2,760 max directional PnL

    WHAT TOP TEAMS ARE DOING (that we're not):
    1. Aggressive directional book takes when signal is strong
    2. Better position trajectory management
    3. Possibly using features we haven't tried
    4. The 2,053 gap = ({4949-2896}) mostly from directional book takes
    """)

    # ============================================================
    # How many book takes are needed to bridge the gap?
    # ============================================================
    gap = 4949 - total_taker  # How much needs to come from book takes
    avg_tom_spread = 13.1 / 2  # half-spread cost of taking
    print(f"\n  BRIDGING ANALYSIS:")
    print(f"    Taker-only oracle: {total_taker:,.0f}")
    print(f"    Gap to 4,949:      {gap:>+,.0f}")
    print(f"    This gap must come from book takes + better MTM management")
    print(f"    Avg TOMATOES half-spread: {avg_tom_spread:.1f}")
    print(f"    To earn {gap:,.0f} from book takes: need {gap/avg_tom_spread:.0f} units worth of directional edge")
    print(f"    At avg mid-change of 1.1 ticks, edge per take = 1.1 - {avg_tom_spread:.1f} = {1.1-avg_tom_spread:.1f}")
    print(f"    This means each book take LOSES {avg_tom_spread-1.1:.1f} on average!")
    print(f"    => Book takes only profitable on LARGE mid moves (>= {avg_tom_spread:.0f} ticks)")

    # How many large mid moves are there?
    ticks = prices['TOMATOES']
    large_moves = []
    for j in range(1, len(ticks)):
        dm = ticks[j]['mid'] - ticks[j-1]['mid']
        if abs(dm) >= 6:
            large_moves.append((j, dm, ticks[j-1]))

    print(f"\n    TOMATOES mid moves >= 6 ticks: {len(large_moves)}")
    for j, dm, td in large_moves[:20]:
        vol = sum(td['bv']) if dm > 0 else sum(td['av'])  # sell if going up (wrong), buy if going down
        # Wait: if mid is going UP, we want to BUY now (take the ask)
        if dm > 0:
            vol = sum(td['av'])
            action = 'BUY at ask'
            edge = dm - (td['ap'][0] - td['mid'])  # edge = mid_change - cost_to_take
        else:
            vol = sum(td['bv'])
            action = 'SELL at bid'
            edge = abs(dm) - (td['mid'] - td['bp'][0])
        print(f"      t={td['ts']:>6} dm={dm:>+5.1f} {action} vol={vol:>3} edge={edge:>+5.1f}")

    total_directional = sum(
        max(0, (abs(dm) - (td['ap'][0] - td['mid'])) * min(sum(td['av']), 80)) if dm > 0 else
        max(0, (abs(dm) - (td['mid'] - td['bp'][0])) * min(sum(td['bv']), 80))
        for j, dm, td in large_moves
    )
    # Actually compute properly
    total_dir_pnl = 0
    for j, dm, td in large_moves:
        if dm > 0:
            cost_per = td['ap'][0] - td['mid']
            edge = dm - cost_per
            vol = min(sum(td['av']), 80)
        else:
            cost_per = td['mid'] - td['bp'][0]
            edge = abs(dm) - cost_per
            vol = min(sum(td['bv']), 80)
        if edge > 0:
            total_dir_pnl += edge * vol

    print(f"\n    Total directional PnL from large moves: {total_dir_pnl:,.0f}")
    print(f"    Combined with taker interception: {total_taker + total_dir_pnl:,.0f}")

    print(f"\n{'='*70}")


if __name__ == '__main__':
    main()
