"""
Deep dive into the most promising patterns from log_analysis.py:

1. SPREAD STATE → NEXT MID CHANGE (HUGE signal):
   - spread=5: +3.83 mean, 22/23 UP (96% directional)
   - spread=6: -1.48 mean, 14/20 DOWN (70%)
   - spread=7: +1.19 mean, 26/36 UP (72%)
   - spread=8: -1.32 mean, 29/39 DOWN (74%)
   - spread=9: -2.43 mean, 7/7 DOWN (100%)

   PATTERN: ODD spreads → UP, EVEN spreads → DOWN ???
   Let's verify on all 3 days.

2. 3-LEVEL BOOKS: 58 bid, 67 ask (out of 2000). What happens when we see 3 levels?

3. ASYMMETRIC L1 volumes: 5.5% of ticks. What's the signal?

4. EMERALDS: 71% same-direction trade runs. Can we predict next side?

5. TOMATOES trade runs: 55% same-direction. Run of 10 exists!
"""
import csv
import os
from collections import Counter, defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "prosperity4bt", "resources", "round0")


def load_prices(day):
    path = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def load_trades(day):
    path = os.path.join(DATA_DIR, f"trades_round_0_day_{day}.csv")
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            rows.append(row)
    return rows


def analyze_spread_signal(day, max_ticks=2000):
    """THE BIG ONE: spread state predicts next mid change"""
    prices = load_prices(day)
    tom = [r for r in prices if r['product'] == 'TOMATOES'][:max_ticks]

    print(f"\n{'='*80}")
    print(f"  SPREAD → NEXT DMID SIGNAL — day={day} ({len(tom)} ticks)")
    print(f"{'='*80}")

    mids = []
    spreads_list = []
    for r in tom:
        b1 = int(r['bid_price_1'])
        a1 = int(r['ask_price_1'])
        mids.append(float(r['mid_price']))
        spreads_list.append(a1 - b1)

    # Spread → next N-tick mid change
    for lookahead in [1, 2, 3, 5]:
        print(f"\n--- Spread → mid change {lookahead} ticks ahead ---")
        spd_dmid = defaultdict(list)
        for i in range(len(tom) - lookahead):
            spd = spreads_list[i]
            dm = mids[i + lookahead] - mids[i]
            spd_dmid[spd].append(dm)

        for spd in sorted(spd_dmid):
            vals = spd_dmid[spd]
            if len(vals) >= 3:
                mean_dm = sum(vals) / len(vals)
                up = sum(1 for v in vals if v > 0.25)
                dn = sum(1 for v in vals if v < -0.25)
                flat = len(vals) - up - dn
                # Theoretical edge: if we can get a fill at best±1 and mid moves mean_dm
                edge = abs(mean_dm)
                hit_rate = max(up, dn) / len(vals) * 100 if len(vals) > 0 else 0
                print(f"  spread={spd:>3}: n={len(vals):>5}  mean_dmid={mean_dm:>+6.3f}  "
                      f"up={up:>3} dn={dn:>3} flat={flat:>3}  "
                      f"hit={hit_rate:>5.1f}%  edge={edge:.2f}")


def analyze_3level_books(day, max_ticks=2000):
    """What happens when we see 3 price levels?"""
    prices = load_prices(day)
    tom = [r for r in prices if r['product'] == 'TOMATOES'][:max_ticks]

    print(f"\n{'='*80}")
    print(f"  3-LEVEL BOOK ANALYSIS — TOMATOES day={day}")
    print(f"{'='*80}")

    mids = [float(r['mid_price']) for r in tom]

    for i, r in enumerate(tom):
        bv3 = int(r['bid_volume_3']) if r['bid_volume_3'] else 0
        av3 = int(r['ask_volume_3']) if r['ask_volume_3'] else 0

        if bv3 > 0 or av3 > 0:
            b1 = int(r['bid_price_1'])
            a1 = int(r['ask_price_1'])
            b2 = int(r['bid_price_2']) if r['bid_price_2'] else None
            a2 = int(r['ask_price_2']) if r['ask_price_2'] else None
            b3 = int(r['bid_price_3']) if r['bid_price_3'] else None
            a3 = int(r['ask_price_3']) if r['ask_price_3'] else None
            bv1 = int(r['bid_volume_1'])
            av1 = int(r['ask_volume_1'])
            bv2 = int(r['bid_volume_2']) if r['bid_volume_2'] else 0
            av2 = int(r['ask_volume_2']) if r['ask_volume_2'] else 0
            spd = a1 - b1
            ts = int(r['timestamp'])

            # Next dmid
            dm1 = mids[i+1] - mids[i] if i+1 < len(mids) else None
            dm3 = mids[i+3] - mids[i] if i+3 < len(mids) else None

            side = "BID3" if bv3 > 0 else "ASK3"
            print(f"  t={ts:>6} spd={spd:>2} "
                  f"bids=[{b1}x{bv1},{b2}x{bv2},{b3}x{bv3}] "
                  f"asks=[{a1}x{av1},{a2}x{av2},{a3}x{av3}] "
                  f"dm1={dm1:>+5.1f} dm3={dm3 if dm3 is not None else '?':>+5} [{side}]")


def analyze_asymmetric_volumes(day, max_ticks=2000):
    """What happens when L1 bid vol != L1 ask vol?"""
    prices = load_prices(day)
    tom = [r for r in prices if r['product'] == 'TOMATOES'][:max_ticks]

    print(f"\n{'='*80}")
    print(f"  ASYMMETRIC L1 VOLUME ANALYSIS — TOMATOES day={day}")
    print(f"{'='*80}")

    mids = [float(r['mid_price']) for r in tom]
    asym_events = []

    for i, r in enumerate(tom):
        bv1 = int(r['bid_volume_1'])
        av1 = int(r['ask_volume_1'])
        if bv1 != av1:
            b1 = int(r['bid_price_1'])
            a1 = int(r['ask_price_1'])
            spd = a1 - b1
            imb = bv1 - av1  # positive = more bids
            ts = int(r['timestamp'])

            dm1 = mids[i+1] - mids[i] if i+1 < len(mids) else 0
            dm3 = mids[min(i+3, len(mids)-1)] - mids[i]
            dm5 = mids[min(i+5, len(mids)-1)] - mids[i]

            asym_events.append({
                'ts': ts, 'spd': spd, 'bv1': bv1, 'av1': av1,
                'imb': imb, 'dm1': dm1, 'dm3': dm3, 'dm5': dm5
            })

    print(f"  Total asymmetric ticks: {len(asym_events)}")

    # Imbalance sign → next dmid direction
    pos_imb = [e for e in asym_events if e['imb'] > 0]
    neg_imb = [e for e in asym_events if e['imb'] < 0]

    print(f"\n  Positive imbalance (more bids, expect UP):")
    print(f"    n={len(pos_imb)}")
    if pos_imb:
        print(f"    dm1: mean={sum(e['dm1'] for e in pos_imb)/len(pos_imb):+.3f}")
        print(f"    dm3: mean={sum(e['dm3'] for e in pos_imb)/len(pos_imb):+.3f}")
        print(f"    dm5: mean={sum(e['dm5'] for e in pos_imb)/len(pos_imb):+.3f}")
        up1 = sum(1 for e in pos_imb if e['dm1'] > 0)
        print(f"    dm1 up: {up1}/{len(pos_imb)} ({up1/len(pos_imb)*100:.0f}%)")

    print(f"\n  Negative imbalance (more asks, expect DOWN):")
    print(f"    n={len(neg_imb)}")
    if neg_imb:
        print(f"    dm1: mean={sum(e['dm1'] for e in neg_imb)/len(neg_imb):+.3f}")
        print(f"    dm3: mean={sum(e['dm3'] for e in neg_imb)/len(neg_imb):+.3f}")
        print(f"    dm5: mean={sum(e['dm5'] for e in neg_imb)/len(neg_imb):+.3f}")
        dn1 = sum(1 for e in neg_imb if e['dm1'] < 0)
        print(f"    dm1 dn: {dn1}/{len(neg_imb)} ({dn1/len(neg_imb)*100:.0f}%)")

    # Spread state of asymmetric ticks
    print(f"\n  Spread distribution of asymmetric ticks:")
    spd_counter = Counter(e['spd'] for e in asym_events)
    for s in sorted(spd_counter):
        print(f"    spread={s}: {spd_counter[s]}")


def analyze_narrow_spread_microstructure(day, max_ticks=2000):
    """Deep dive into narrow spread events: what happens BEFORE and AFTER?"""
    prices = load_prices(day)
    tom = [r for r in prices if r['product'] == 'TOMATOES'][:max_ticks]

    print(f"\n{'='*80}")
    print(f"  NARROW SPREAD MICROSTRUCTURE — TOMATOES day={day}")
    print(f"{'='*80}")

    mids = [float(r['mid_price']) for r in tom]
    spreads_list = []
    for r in tom:
        b1 = int(r['bid_price_1'])
        a1 = int(r['ask_price_1'])
        spreads_list.append(a1 - b1)

    # Before narrow: what was the dmid?
    narrow_events = []
    for i in range(1, len(tom)):
        if spreads_list[i] < 13:
            prev_spd = spreads_list[i-1]
            dm_into = mids[i] - mids[i-1]
            dm_after1 = mids[i+1] - mids[i] if i+1 < len(mids) else 0
            dm_after3 = mids[min(i+3, len(mids)-1)] - mids[i]
            narrow_events.append({
                'tick': i,
                'spd': spreads_list[i],
                'prev_spd': prev_spd,
                'dm_into': dm_into,
                'dm_after1': dm_after1,
                'dm_after3': dm_after3,
                'mid': mids[i]
            })

    print(f"  Total narrow events: {len(narrow_events)}")

    # Was there a big move INTO the narrow spread?
    print(f"\n  dmid INTO narrow spread:")
    dm_into_counter = Counter()
    for e in narrow_events:
        dm_into_counter[round(e['dm_into'], 1)] += 1
    for d in sorted(dm_into_counter):
        print(f"    dm_into={d:>+5.1f}: {dm_into_counter[d]:>3}")

    # Predictability of post-narrow direction
    print(f"\n  Narrow spread → post-narrow direction (1 tick):")
    for spd in sorted(set(e['spd'] for e in narrow_events)):
        subset = [e for e in narrow_events if e['spd'] == spd]
        up = sum(1 for e in subset if e['dm_after1'] > 0.25)
        dn = sum(1 for e in subset if e['dm_after1'] < -0.25)
        flat = len(subset) - up - dn
        mean_dm = sum(e['dm_after1'] for e in subset) / len(subset)
        print(f"    spread={spd}: n={len(subset):>3}  up={up:>2} dn={dn:>2} flat={flat:>2}  "
              f"mean_dm_after={mean_dm:>+5.2f}")

    # Does dm_into predict dm_after? (continuation vs reversal)
    print(f"\n  dm_into → dm_after correlation:")
    big_up_into = [e for e in narrow_events if e['dm_into'] > 2.0]
    big_dn_into = [e for e in narrow_events if e['dm_into'] < -2.0]

    if big_up_into:
        mean_after = sum(e['dm_after1'] for e in big_up_into) / len(big_up_into)
        dn_after = sum(1 for e in big_up_into if e['dm_after1'] < -0.25)
        print(f"    Big move UP into narrow (n={len(big_up_into)}): "
              f"mean_after={mean_after:+.2f}, reversal={dn_after}/{len(big_up_into)}")

    if big_dn_into:
        mean_after = sum(e['dm_after1'] for e in big_dn_into) / len(big_dn_into)
        up_after = sum(1 for e in big_dn_into if e['dm_after1'] > 0.25)
        print(f"    Big move DN into narrow (n={len(big_dn_into)}): "
              f"mean_after={mean_after:+.2f}, reversal={up_after}/{len(big_dn_into)}")


def analyze_emeralds_deep(day, max_ticks=2000):
    """EMERALDS: narrow spread timing and volume patterns"""
    prices = load_prices(day)
    em = [r for r in prices if r['product'] == 'EMERALDS'][:max_ticks]
    trades = load_trades(day)
    em_trades = [t for t in trades if t['symbol'] == 'EMERALDS']

    print(f"\n{'='*80}")
    print(f"  EMERALDS DEEP DIVE — day={day}")
    print(f"{'='*80}")

    # When do narrow spreads happen?
    print(f"\n--- Narrow spread (8) timing ---")
    narrow_ticks = []
    for i, r in enumerate(em):
        b1 = int(r['bid_price_1'])
        a1 = int(r['ask_price_1'])
        if a1 - b1 == 8:
            ts = int(r['timestamp'])
            bv1 = int(r['bid_volume_1'])
            av1 = int(r['ask_volume_1'])
            # Which side has the extra level?
            bv3 = int(r['bid_volume_3']) if r['bid_volume_3'] else 0
            av3 = int(r['ask_volume_3']) if r['ask_volume_3'] else 0
            side = "BID_AT_10000" if b1 == 10000 else "ASK_AT_10000"
            narrow_ticks.append(ts)
            print(f"  t={ts:>6} b1={b1} a1={a1} bv1={bv1:>2} av1={av1:>2} [{side}]")

    # Inter-arrival of narrow spreads
    if len(narrow_ticks) > 1:
        ias = [narrow_ticks[i+1] - narrow_ticks[i] for i in range(len(narrow_ticks)-1)]
        print(f"\n  Narrow spread inter-arrival: min={min(ias)} max={max(ias)} "
              f"mean={sum(ias)/len(ias):.0f}")

    # EMERALDS volume patterns during narrow
    print(f"\n--- Volume during narrow vs wide ---")
    narrow_bv1 = []
    narrow_av1 = []
    wide_bv1 = []
    wide_av1 = []
    for r in em:
        b1 = int(r['bid_price_1'])
        a1 = int(r['ask_price_1'])
        bv1 = int(r['bid_volume_1'])
        av1 = int(r['ask_volume_1'])
        if a1 - b1 == 8:
            narrow_bv1.append(bv1)
            narrow_av1.append(av1)
        else:
            wide_bv1.append(bv1)
            wide_av1.append(av1)

    if narrow_bv1:
        print(f"  Narrow: bid_vol mean={sum(narrow_bv1)/len(narrow_bv1):.1f} "
              f"ask_vol mean={sum(narrow_av1)/len(narrow_av1):.1f}")
    if wide_bv1:
        print(f"  Wide:   bid_vol mean={sum(wide_bv1)/len(wide_bv1):.1f} "
              f"ask_vol mean={sum(wide_av1)/len(wide_av1):.1f}")

    # Trade timing relative to narrow spreads
    print(f"\n--- Trades relative to narrow spread events ---")
    trade_timestamps = [int(t['timestamp']) for t in em_trades]
    for tt in trade_timestamps:
        # Find nearest narrow spread
        dists = [abs(tt - nt) for nt in narrow_ticks]
        nearest = min(dists) if dists else 999999
        tp = float([t for t in em_trades if int(t['timestamp']) == tt][0]['price'])
        tq = int([t for t in em_trades if int(t['timestamp']) == tt][0]['quantity'])
        side = "BUY@ask" if tp > 10000 else "SELL@bid"
        print(f"  t={tt:>6} {side} price={tp:.0f} qty={tq} nearest_narrow={nearest}ms")


if __name__ == "__main__":
    for day in [0, -1, -2]:
        analyze_spread_signal(day)

    analyze_3level_books(0)
    analyze_asymmetric_volumes(0)
    analyze_narrow_spread_microstructure(0)
    analyze_emeralds_deep(0)
