"""
Deep dive on the L2 Wall Mid phenomenon and combined signal strength analysis.
L2 Wall Mid shows 98% directional accuracy on narrow spread ticks -- why?
"""

import pandas as pd
import numpy as np

def load_day(day_num):
    path = f"prosperity4bt/resources/round0/prices_round_0_day_{day_num}.csv"
    df = pd.read_csv(path, sep=';')
    tom = df[df['product'] == 'TOMATOES'].copy().reset_index(drop=True)
    tom = tom.rename(columns={
        'bid_price_1': 'bp1', 'bid_volume_1': 'bv1',
        'bid_price_2': 'bp2', 'bid_volume_2': 'bv2',
        'bid_price_3': 'bp3', 'bid_volume_3': 'bv3',
        'ask_price_1': 'ap1', 'ask_volume_1': 'av1',
        'ask_price_2': 'ap2', 'ask_volume_2': 'av2',
        'ask_price_3': 'ap3', 'ask_volume_3': 'av3',
    })
    for col in ['bv1','bv2','bv3','av1','av2','av3','bp2','bp3','ap2','ap3']:
        tom[col] = tom[col].fillna(0)
    return tom

# ============================================================
# SECTION A: WHY IS L2 WALL MID SO ACCURATE?
# ============================================================

print("=" * 80)
print("DEEP DIVE: WHY L2 WALL MID HAS 98% DIRECTIONAL ACCURACY")
print("=" * 80)

for d in [0, -1, -2]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    narrow = spread <= 9

    print(f"\n{'='*60}")
    print(f"--- Day {d} ({n} ticks, {np.sum(narrow)} narrow) ---")

    # On narrow ticks, examine L2 volumes in detail
    narrow_idx = np.where(narrow & (np.arange(n) < n-1))[0]

    print(f"\nL2 volume analysis on narrow-spread ticks:")
    print(f"{'Spread':>8} {'Count':>8} {'bv2==av2':>10} {'bv2>av2':>10} {'av2>bv2':>10}")
    print("-" * 50)
    for s in sorted(np.unique(spread[narrow_idx])):
        mask = narrow_idx[spread[narrow_idx] == s]
        cnt = len(mask)
        eq = np.sum(bv2[mask] == av2[mask])
        bgt = np.sum(bv2[mask] > av2[mask])
        agt = np.sum(av2[mask] > bv2[mask])
        print(f"{s:>8.0f} {cnt:>8} {eq:>10} {bgt:>10} {agt:>10}")

    # For each L2 imbalance case, what happens next?
    print(f"\nL2 imbalance -> next dmid on narrow ticks:")
    for condition_name, condition in [
        ("bv2 > av2 (L2 bid heavy)", bv2[narrow_idx] > av2[narrow_idx]),
        ("av2 > bv2 (L2 ask heavy)", av2[narrow_idx] > bv2[narrow_idx]),
        ("bv2 == av2 (L2 balanced)", bv2[narrow_idx] == av2[narrow_idx]),
    ]:
        idx = narrow_idx[condition]
        if len(idx) == 0:
            print(f"  {condition_name:<30}: N=0")
            continue
        dm = dmid[idx]
        avg = np.mean(dm)
        up = np.sum(dm > 0)
        down = np.sum(dm < 0)
        flat = np.sum(dm == 0)
        acc_up = up / (up + down) if (up + down) > 0 else 0
        print(f"  {condition_name:<30}: N={len(idx):>5}  avg_dmid={avg:>7.3f}  up={up:>4} down={down:>4} flat={flat:>4}  dir_acc={acc_up:.3f}")

    # The key question: is L2 imbalance CAUSED by the spread narrowing event?
    # i.e., when spread narrows, does one side's L2 always become the "wall"?
    print(f"\nSpread TRANSITIONS into narrow (spread went from wide to narrow):")
    for i in narrow_idx:
        if i > 0 and spread[i-1] >= 13 and spread[i] <= 9:
            # This is a transition tick
            pass  # count below

    transitions = narrow_idx[(np.isin(narrow_idx - 1, np.where(spread >= 13)[0]))]
    if len(transitions) > 0:
        print(f"  {len(transitions)} ticks where previous spread >= 13 and current <= 9")
        bv2_gt = np.sum(bv2[transitions] > av2[transitions])
        av2_gt = np.sum(av2[transitions] > bv2[transitions])
        eq_v = np.sum(bv2[transitions] == av2[transitions])
        print(f"  bv2 > av2: {bv2_gt}  av2 > bv2: {av2_gt}  equal: {eq_v}")

        # And accuracy on these transition ticks
        dm_trans = dmid[transitions]
        l2_signal = np.sign(bv2[transitions] - av2[transitions])  # +1 = bid heavy = expect UP
        # But L2 Wall Mid says: bid heavy -> FV=ask -> expect UP, so signal = sign(bv2-av2) should predict UP
        active = (l2_signal != 0) & (np.sign(dm_trans) != 0)
        if np.sum(active) > 0:
            acc = np.mean(l2_signal[active] == np.sign(dm_trans[active]))
            print(f"  L2 signal accuracy on transitions: {acc:.3f} (N={np.sum(active)})")

    # Duration of narrow spread episodes
    print(f"\nNarrow spread episode durations:")
    in_narrow = False
    episodes = []
    start = 0
    for i in range(n):
        if narrow[i] and not in_narrow:
            in_narrow = True
            start = i
        elif not narrow[i] and in_narrow:
            in_narrow = False
            episodes.append((start, i - 1, i - start))
    if in_narrow:
        episodes.append((start, n-1, n - start))

    durations = [e[2] for e in episodes]
    print(f"  {len(episodes)} episodes, mean duration: {np.mean(durations):.1f} ticks, median: {np.median(durations):.1f}")
    print(f"  Distribution: {np.percentile(durations, [25,50,75,90,95])}")

    # On narrow ticks, what's the RELATIONSHIP between L1 and L2 imbalance?
    print(f"\nL1 vs L2 imbalance agreement on narrow ticks:")
    l1_sign = np.sign(bv1[narrow_idx] - av1[narrow_idx])
    l2_sign = np.sign(bv2[narrow_idx] - av2[narrow_idx])
    agree = np.sum((l1_sign == l2_sign) & (l1_sign != 0))
    disagree = np.sum((l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0))
    l1_only = np.sum((l1_sign != 0) & (l2_sign == 0))
    l2_only = np.sum((l1_sign == 0) & (l2_sign != 0))
    both_zero = np.sum((l1_sign == 0) & (l2_sign == 0))
    print(f"  Agree: {agree}  Disagree: {disagree}  L1-only: {l1_only}  L2-only: {l2_only}  Both zero: {both_zero}")

    # When they DISAGREE, who is right?
    if disagree > 0:
        disagree_idx = narrow_idx[(l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0)]
        dm_dis = dmid[disagree_idx]
        l1_right = np.sum(l1_sign[(l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0)] == np.sign(dm_dis))
        l2_right = np.sum(l2_sign[(l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0)] == np.sign(dm_dis))
        # Filter for non-zero dmid
        nz = np.sign(dm_dis) != 0
        if np.sum(nz) > 0:
            l1_acc = np.mean(l1_sign[(l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0)][nz] == np.sign(dm_dis[nz]))
            l2_acc = np.mean(l2_sign[(l1_sign != l2_sign) & (l1_sign != 0) & (l2_sign != 0)][nz] == np.sign(dm_dis[nz]))
            print(f"  When disagree (N={disagree}, nz={np.sum(nz)}): L1 acc={l1_acc:.3f}, L2 acc={l2_acc:.3f}")

# ============================================================
# SECTION B: WHAT DOES L2 IMBALANCE ACTUALLY ENCODE?
# ============================================================

print("\n" + "=" * 80)
print("SECTION B: WHAT IS L2 ENCODING? (spread=7 deep dive)")
print("=" * 80)

for d in [0, -1, -2]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    print(f"\n--- Day {d} ---")

    # Focus on spread=7 (most common narrow spread with clear L2 asymmetry)
    for target_spread in [5, 6, 7, 8, 9]:
        mask = (spread == target_spread) & (np.arange(n) < n-1)
        idx = np.where(mask)[0]
        if len(idx) == 0:
            continue

        # What does L2 look like?
        print(f"\n  Spread={target_spread}: N={len(idx)}")
        print(f"    L1: bv1 range [{bv1[idx].min():.0f}, {bv1[idx].max():.0f}], av1 range [{av1[idx].min():.0f}, {av1[idx].max():.0f}]")
        print(f"    L2: bv2 range [{bv2[idx].min():.0f}, {bv2[idx].max():.0f}], av2 range [{av2[idx].min():.0f}, {av2[idx].max():.0f}]")
        print(f"    L2 gap: bp1-bp2 = {np.unique(bp1[idx]-bp2[idx])}, ap2-ap1 = {np.unique(ap2[idx]-ap1[idx])}")

        # Key: look at actual L2 price levels
        print(f"    bp2 values: {np.unique(bp2[idx])[:10]}")
        print(f"    ap2 values: {np.unique(ap2[idx])[:10]}")

        # Examine L2 imbalance direction vs next move
        l2_dir = np.sign(bv2[idx] - av2[idx])
        dm = dmid[idx]
        for direction, label in [(1, "bv2>av2 (bid L2 heavy)"), (-1, "av2>bv2 (ask L2 heavy)"), (0, "balanced")]:
            sub = dm[l2_dir == direction]
            if len(sub) == 0:
                continue
            nz = sub[sub != 0]
            up = np.sum(sub > 0)
            down = np.sum(sub < 0)
            flat = np.sum(sub == 0)
            print(f"    {label}: N={len(sub)}, avg_dmid={np.mean(sub):.3f}, up={up} down={down} flat={flat}")

# ============================================================
# SECTION C: L2 WALL MID IN TRADING CONTEXT
# ============================================================

print("\n" + "=" * 80)
print("SECTION C: L2 WALL MID PRACTICAL TRADING VALUE")
print("=" * 80)

for d in [0, -1, -2]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    narrow = (spread <= 9) & (np.arange(n) < n-1)
    narrow_idx = np.where(narrow)[0]

    l2_signal = np.sign(bv2 - av2)

    print(f"\n--- Day {d} ---")

    # How many ticks does the prediction persist? (multi-tick returns)
    print(f"\nMulti-tick returns after L2 signal on narrow ticks:")
    for horizon in [1, 2, 3, 5, 10, 20]:
        returns = []
        for i in narrow_idx:
            if i + horizon < n:
                ret = mid[i + horizon] - mid[i]
                sig = l2_signal[i]
                if sig != 0:
                    returns.append(sig * ret)
        if returns:
            returns = np.array(returns)
            print(f"  +{horizon} ticks: avg signed return = {np.mean(returns):.3f}, "
                  f"hit rate = {np.mean(returns > 0):.3f}, N={len(returns)}")

    # Practical PnL: if we USE L2 signal to decide take direction
    # Buy at ask when L2 says UP, sell at bid when L2 says DOWN
    # vs. the alternative: post at best-1 when L2 fires
    print(f"\nPractical trading scenarios:")

    # Scenario 1: Take at best when L2 fires
    take_pnl = []
    for i in narrow_idx:
        if l2_signal[i] > 0 and i + 1 < n:
            # Buy at ask, mark to next mid
            take_pnl.append(mid[i+1] - ap1[i])
        elif l2_signal[i] < 0 and i + 1 < n:
            # Sell at bid, mark to next mid
            take_pnl.append(bp1[i] - mid[i+1])

    if take_pnl:
        take_pnl = np.array(take_pnl)
        print(f"  Take at best (L2-directed): avg={np.mean(take_pnl):.3f}, "
              f"total={np.sum(take_pnl):.1f}, win_rate={np.mean(take_pnl > 0):.3f}, N={len(take_pnl)}")

    # Scenario 2: Post at best-1 in signal direction (improve by 1 tick)
    post_pnl = []
    for i in narrow_idx:
        s = spread[i]
        if l2_signal[i] > 0 and i + 1 < n:
            # Post buy at ap1 - 1 (inside spread), expect fill + mid moves up
            entry = ap1[i] - 1
            # If we get filled: profit = mid[i+1] - entry
            post_pnl.append(mid[i+1] - entry)
        elif l2_signal[i] < 0 and i + 1 < n:
            # Post sell at bp1 + 1
            entry = bp1[i] + 1
            post_pnl.append(entry - mid[i+1])

    if post_pnl:
        post_pnl = np.array(post_pnl)
        print(f"  Post at best-1 (L2-directed): avg={np.mean(post_pnl):.3f}, "
              f"total={np.sum(post_pnl):.1f}, win_rate={np.mean(post_pnl > 0):.3f}, N={len(post_pnl)}")

    # Scenario 3: Use L2 to AVOID wrong-side takes
    # Count: how many narrow-tick takes would be on the WRONG side per L2?
    # (buying when L2 says DOWN, or selling when L2 says UP)
    wrong_side = 0
    right_side = 0
    for i in narrow_idx:
        if l2_signal[i] != 0:
            if l2_signal[i] > 0:
                right_side += 1  # should buy
            else:
                wrong_side += 1  # should sell (avoid buying)
    print(f"  L2 direction split: {right_side} should-buy vs {wrong_side} should-sell "
          f"(use to AVOID {wrong_side} wrong-side takes)")

# ============================================================
# SECTION D: COMBINED SIGNAL STRENGTH (L2 + OBI_shift from s36)
# ============================================================

print("\n" + "=" * 80)
print("SECTION D: L2 WALL MID vs OBI SHIFT (from s36_medallion)")
print("=" * 80)

for d in [0, -1, -2]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    # OBI shift as used in s36 (L1+L2 total OBI)
    total_bid = bv1 + bv2
    total_ask = av1 + av2
    obi = (total_bid - total_ask) / (total_bid + total_ask + 1e-10)
    obi_fires = np.abs(obi) > 0.01  # effectively whenever volumes differ

    # L2-only wall mid
    l2_signal = np.sign(bv2 - av2)
    l2_fires = l2_signal != 0

    # Are they the same signal?
    both = obi_fires & l2_fires & (np.arange(n) < n-1)
    both_idx = np.where(both)[0]

    print(f"\n--- Day {d} ---")
    print(f"OBI fires: {np.sum(obi_fires)}, L2 fires: {np.sum(l2_fires)}, Both: {np.sum(both)}")

    if len(both_idx) > 0:
        # Sign agreement
        obi_sign = np.sign(obi[both_idx])
        l2_sign_b = l2_signal[both_idx]
        agree = np.mean(obi_sign == l2_sign_b)
        print(f"  Sign agreement on both-fire ticks: {agree:.3f}")

        # Who is more accurate?
        dm = dmid[both_idx]
        nz = np.sign(dm) != 0

        if np.sum(nz) > 0:
            obi_acc = np.mean(obi_sign[nz] == np.sign(dm[nz]))
            l2_acc = np.mean(l2_sign_b[nz] == np.sign(dm[nz]))
            print(f"  OBI accuracy: {obi_acc:.3f}, L2 accuracy: {l2_acc:.3f} (N={np.sum(nz)})")

    # On ticks where they DISAGREE
    if len(both_idx) > 0:
        disagree = obi_sign != l2_sign_b
        if np.sum(disagree) > 0:
            dis_idx = both_idx[disagree]
            dm_dis = dmid[dis_idx]
            nz_dis = np.sign(dm_dis) != 0
            if np.sum(nz_dis) > 0:
                obi_wins = np.mean(np.sign(obi[dis_idx][nz_dis]) == np.sign(dm_dis[nz_dis]))
                l2_wins = np.mean(l2_signal[dis_idx][nz_dis] == np.sign(dm_dis[nz_dis]))
                print(f"  When they DISAGREE (N={np.sum(disagree)}, nz={np.sum(nz_dis)}): "
                      f"OBI acc={obi_wins:.3f}, L2 acc={l2_wins:.3f}")

# ============================================================
# SECTION E: WHY L2 WALL MID SCORES 2,600 DESPITE 98% ACCURACY
# ============================================================

print("\n" + "=" * 80)
print("SECTION E: WHY DOES L2 WALL MID SCORE ONLY ~2,600 ON WEBSITE?")
print("(Despite 98% directional accuracy on narrow ticks)")
print("=" * 80)

for d in [0]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    narrow = spread <= 9
    wide = spread >= 13

    print(f"\n--- Day {d} ---")
    print(f"\nThe problem breakdown:")
    print(f"  Total ticks: {n}")
    print(f"  Narrow ticks (signal exists): {np.sum(narrow)} ({np.sum(narrow)/n*100:.1f}%)")
    print(f"  Wide ticks (signal=0, just mid): {np.sum(wide)} ({np.sum(wide)/n*100:.1f}%)")

    # On wide ticks, L2 wall mid = mid. What does our CURRENT best strategy do on those?
    # It uses microprice regression. L2 wall mid would lose that edge.
    print(f"\n  On wide ticks, what does microprice regression give?")
    # Compute 4-lag microprice regression FV deviation from mid
    micro = bp1 + (bv1 / (bv1 + av1 + 1e-10)) * (ap1 - bp1)
    micro_dev = micro - mid

    wide_idx = np.where(wide & (np.arange(n) < n-1))[0]
    if np.std(micro_dev[wide_idx]) > 1e-10:
        corr_wide = np.corrcoef(micro_dev[wide_idx], dmid[wide_idx])[0, 1]
    else:
        corr_wide = 0
    print(f"  Microprice deviation corr with dmid on wide ticks: {corr_wide:.4f}")
    print(f"  (This is ZERO because L1 volumes are symmetric on wide ticks)")

    # So on 93% of ticks, BOTH L2 wall mid and microprice give ZERO signal
    print(f"\n  CRITICAL INSIGHT:")
    print(f"  On wide ticks (93%): L2 wall mid = mid = microprice (all give ZERO signal)")
    print(f"  On narrow ticks (7%): L2 wall mid has 98% accuracy, but so what?")
    print(f"  The narrow ticks already have naturally large moves (narrow spread = spread is about to revert)")

    narrow_idx = np.where(narrow & (np.arange(n) < n-1))[0]
    wide_idx = np.where(wide & (np.arange(n) < n-1))[0]
    avg_abs_dmid_narrow = np.mean(np.abs(dmid[narrow_idx]))
    avg_abs_dmid_wide = np.mean(np.abs(dmid[wide_idx]))
    print(f"\n  Avg |dmid| on narrow ticks: {avg_abs_dmid_narrow:.3f}")
    print(f"  Avg |dmid| on wide ticks:   {avg_abs_dmid_wide:.3f}")
    print(f"  Narrow ticks have {avg_abs_dmid_narrow/avg_abs_dmid_wide:.1f}x larger moves")

    # The real question: can L2 wall mid IMPROVE s36_medallion's FV on those 7% of ticks?
    print(f"\n  Hypothetical FV improvement:")
    print(f"  s36 uses microprice regression (lag-4) as FV. On narrow ticks:")

    # What does the regression FV do on narrow ticks vs L2 wall mid?
    # Regression uses lagged microprice deviations. On narrow ticks, current microprice
    # IS asymmetric, so it ALREADY captures some of the L2 signal.
    narrow_micro_dev = micro_dev[narrow_idx]
    narrow_l2_sign = np.sign(bv2[narrow_idx] - av2[narrow_idx])
    narrow_dm = dmid[narrow_idx]

    # Are microprice and L2 pointing same direction on narrow ticks?
    micro_sign = np.sign(narrow_micro_dev)
    agree = np.sum((micro_sign == narrow_l2_sign) & (micro_sign != 0))
    disagree = np.sum((micro_sign != narrow_l2_sign) & (micro_sign != 0) & (narrow_l2_sign != 0))
    print(f"  Microprice and L2 agree: {agree}, disagree: {disagree}")
    if disagree > 0:
        dis_mask = (micro_sign != narrow_l2_sign) & (micro_sign != 0) & (narrow_l2_sign != 0)
        dm_dis = narrow_dm[dis_mask]
        nz = np.sign(dm_dis) != 0
        if np.sum(nz) > 0:
            micro_right = np.mean(micro_sign[dis_mask][nz] == np.sign(dm_dis[nz]))
            l2_right = np.mean(narrow_l2_sign[dis_mask][nz] == np.sign(dm_dis[nz]))
            print(f"  When disagree: microprice acc={micro_right:.3f}, L2 acc={l2_right:.3f} (N={np.sum(nz)})")

    # L2/L1 volume ratio on narrow ticks
    l2_l1_ratio = (bv2 + av2) / (bv1 + av1 + 1e-10)
    print(f"\n  L2/L1 volume ratio on narrow ticks: mean={l2_l1_ratio[narrow_idx].mean():.2f}, "
          f"std={l2_l1_ratio[narrow_idx].std():.2f}")
    print(f"  L2/L1 volume ratio on wide ticks: mean={l2_l1_ratio[wide_idx].mean():.2f}, "
          f"std={l2_l1_ratio[wide_idx].std():.2f}")

# ============================================================
# SECTION F: THE REAL QUESTION -- SPREAD PREDICTION
# ============================================================

print("\n" + "=" * 80)
print("SECTION F: IS L2 WALL MID ACTUALLY PREDICTING SPREAD STATE CHANGES?")
print("=" * 80)

for d in [0, -1, -2]:
    df = load_day(d)
    n = len(df)

    bp1, bv1 = df['bp1'].values, df['bv1'].values.astype(float)
    bp2, bv2 = df['bp2'].values, df['bv2'].values.astype(float)
    ap1, av1 = df['ap1'].values, df['av1'].values.astype(float)
    ap2, av2 = df['ap2'].values, df['av2'].values.astype(float)
    mid = df['mid_price'].values
    spread = ap1 - bp1

    dmid = np.zeros(n)
    dmid[:-1] = mid[1:] - mid[:-1]

    # When spread is narrow, L2 imbalance predicts which way mid moves
    # But IS this because L2 imbalance predicts which SIDE of the book
    # the MM will widen FIRST?
    # i.e., if bv2 > av2 (bid L2 heavy), the ask side has less depth,
    # so the MM will widen the ask first -> ask goes up -> mid goes up
    # This would explain the near-perfect accuracy!

    narrow_idx = np.where((spread <= 9) & (np.arange(n) < n-1))[0]

    print(f"\n--- Day {d} ---")
    print(f"On narrow ticks, track which side widens FIRST:")

    l2_signal = np.sign(bv2[narrow_idx] - av2[narrow_idx])

    for sig_val, label in [(1, "bv2 > av2 (bid L2 heavy)"), (-1, "av2 > bv2 (ask L2 heavy)")]:
        sub_idx = narrow_idx[l2_signal == sig_val]
        if len(sub_idx) == 0:
            continue

        # Track next-tick changes in bid and ask
        dbp1 = bp1[sub_idx + 1] - bp1[sub_idx]
        dap1 = ap1[sub_idx + 1] - ap1[sub_idx]

        print(f"\n  {label} (N={len(sub_idx)}):")
        print(f"    Next dbid: mean={np.mean(dbp1):.3f}, next dask: mean={np.mean(dap1):.3f}")
        print(f"    Bid moves: up={np.sum(dbp1>0)}, dn={np.sum(dbp1<0)}, flat={np.sum(dbp1==0)}")
        print(f"    Ask moves: up={np.sum(dap1>0)}, dn={np.sum(dap1<0)}, flat={np.sum(dap1==0)}")

        # Next spread
        next_spread = spread[sub_idx + 1] if np.all(sub_idx + 1 < n) else np.zeros(len(sub_idx))
        ns_vals = ap1[sub_idx + 1] - bp1[sub_idx + 1]
        print(f"    Next spread: mean={np.mean(ns_vals):.1f}, "
              f"still_narrow={np.sum(ns_vals<=9)}, widened={np.sum(ns_vals>=13)}")

print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
