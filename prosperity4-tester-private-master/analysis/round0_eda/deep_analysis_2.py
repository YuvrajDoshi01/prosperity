#!/usr/bin/env python3
"""
Deep analysis part 2: Focus on the most promising findings from part 1,
plus new analyses targeting actionable edge.
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

BASE = "prosperity4bt/resources/round0/"

days = {}
for d in [-2, -1, 0]:
    days[d] = pd.read_csv(f"{BASE}prices_round_0_day_{d}.csv", sep=";")

trades = {}
for d in [-2, -1, 0]:
    trades[d] = pd.read_csv(f"{BASE}trades_round_0_day_{d}.csv", sep=";")

def get_product(day_df, product):
    return day_df[day_df['product'] == product].copy().reset_index(drop=True)

# ============================================================================
# FINDING 1: VOLATILITY CLUSTERING (AC(1) of |change| = +0.44)
# The t+1 vol after big move is 2.5x unconditional but drops to 1x by t+2.
# This is a SINGLE-TICK effect. Can we exploit it?
# ============================================================================
print("=" * 80)
print("DEEP DIVE 1: VOLATILITY CLUSTERING - ACTIONABLE EDGE")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)
    df['next_spread'] = df['spread'].shift(-1)
    df['abs_change'] = df['mid_change'].abs()

    # After a big move, the NEXT move is ~2.5x. But what DIRECTION?
    # Mean reversion says opposite direction. Let's quantify.
    big_up = df[df['mid_change'] >= 3.0]
    big_dn = df[df['mid_change'] <= -3.0]

    print(f"\n  After mid_change >= +3.0 (n={len(big_up)}):")
    if len(big_up) > 0:
        next_mean = big_up['next_change'].mean()
        next_std = big_up['next_change'].std()
        p_down = (big_up['next_change'] < 0).mean()
        next_spread = big_up['next_spread'].mean()
        # If we sell at ask after big up move (mean reversion trade):
        # Expected PnL = half_spread - mean_reversion_amount
        # But we're already posting best+1. Can we be MORE aggressive?
        print(f"    next_change: mean={next_mean:+.3f}, std={next_std:.3f}")
        print(f"    P(next_move_down) = {p_down:.3f}")
        print(f"    next spread = {next_spread:.1f}")
        # What % of big-up are followed by spread narrowing (5-9)?
        p_narrow_next = (big_up['next_spread'] <= 9).mean()
        print(f"    P(next_tick_narrow) = {p_narrow_next:.3f}")

    print(f"\n  After mid_change <= -3.0 (n={len(big_dn)}):")
    if len(big_dn) > 0:
        next_mean = big_dn['next_change'].mean()
        next_std = big_dn['next_change'].std()
        p_up = (big_dn['next_change'] > 0).mean()
        next_spread = big_dn['next_spread'].mean()
        print(f"    next_change: mean={next_mean:+.3f}, std={next_std:.3f}")
        print(f"    P(next_move_up) = {p_up:.3f}")
        print(f"    next spread = {next_spread:.1f}")
        p_narrow_next = (big_dn['next_spread'] <= 9).mean()
        print(f"    P(next_tick_narrow) = {p_narrow_next:.3f}")

    # KEY QUESTION: After big move, is the REVERSAL big enough to cross spread?
    # Current spread is ~13. Half-spread = 6.5. Need reversal > 6.5 to profit from crossing.
    big_move = df[df['abs_change'] >= 3.0]
    reversal_size = -big_move['mid_change'] * np.sign(big_move['next_change'])  # positive if reversal
    print(f"\n  After |change| >= 3.0: avg reversal component = {reversal_size.mean():.3f}")
    print(f"  But half-spread = 6.5, so crossing to take is still -EV")

    # What about WIDENING the post on the continuation side?
    # After big up, post wider on buy side (we don't want to buy high)
    # This is what directional posting already does!
    # But can we also post TIGHTER on the reversal side?

    # What's the probability tree after big move?
    for thresh in [3.0, 3.5, 4.0]:
        big = df[df['abs_change'] >= thresh]
        if len(big) > 5:
            reversal_pct = (big['mid_change'] * big['next_change'] < 0).mean()
            avg_reversal = big[big['mid_change'] * big['next_change'] < 0]['next_change'].abs().mean() if reversal_pct > 0 else 0
            avg_continuation = big[big['mid_change'] * big['next_change'] > 0]['next_change'].abs().mean() if reversal_pct < 1 else 0
            print(f"\n  |change| >= {thresh} (n={len(big)}): P(reversal)={reversal_pct:.3f}, "
                  f"avg|reversal|={avg_reversal:.2f}, avg|continuation|={avg_continuation:.2f}")


# ============================================================================
# FINDING 2: SPREAD=5 ALWAYS MEANS UP, SPREAD=9 ALWAYS MEANS DOWN
# This was mentioned in CLAUDE.md. Let's verify and quantify more precisely.
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 2: NARROW SPREAD DIRECTION PREDICTION")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)
    df['prev_change'] = df['mid_change'].shift(1)

    for sp in [5, 6, 7, 8, 9]:
        mask = df['spread'] == sp
        n = mask.sum()
        if n > 0:
            next_up = (df.loc[mask, 'next_change'] > 0).mean()
            next_dn = (df.loc[mask, 'next_change'] < 0).mean()
            next_mean = df.loc[mask, 'next_change'].mean()
            # What was the PREVIOUS change before this narrow spread?
            prev_mean = df.loc[mask, 'prev_change'].mean()
            prev_pos = (df.loc[mask, 'prev_change'] > 0).mean()

            # What spread follows this?
            next_spread_mean = df.loc[mask, 'spread'].shift(-1).dropna().mean() if mask.any() else 0

            print(f"  spread={sp} (n={n}):")
            print(f"    next: up={next_up:.3f}, down={next_dn:.3f}, mean={next_mean:+.3f}")
            print(f"    prev_change: mean={prev_mean:+.3f}, P(prev>0)={prev_pos:.3f}")

    # CRITICAL: When spread=5, next change is ALWAYS positive.
    # Can we POST at best_ask - 1 (aggressive sell) knowing price will go UP?
    # NO - spread=5 means we SHOULD BUY. But the narrow spread only lasts 1 tick.
    # The question is: can we detect spread=5 and BUY at bid (which is now much closer to mid)?

    # What is the bid when spread=5?
    sp5 = df[df['spread'] == 5]
    if len(sp5) > 0:
        print(f"\n  When spread=5:")
        print(f"    bid_1 = {sp5['bid_price_1'].describe()}")
        print(f"    ask_1 = {sp5['ask_price_1'].describe()}")
        print(f"    mid = {sp5['mid_price'].describe()}")
        print(f"    The ask is only 5 above bid. If we buy at ask ({sp5['ask_price_1'].mean():.0f}), ")
        print(f"    and next mid goes up by {sp5['next_change'].mean():+.1f}, that's profitable!")

        # What's the 5-tick forward return from spread=5?
        for h in [1, 2, 3, 5, 10]:
            future_mid = df['mid_price'].shift(-h)
            ret = future_mid - df['mid_price']
            sp5_ret = ret[df['spread'] == 5]
            print(f"    {h}-tick forward return: {sp5_ret.mean():+.3f} (n={len(sp5_ret.dropna())})")


# ============================================================================
# FINDING 3: L2/L1 RATIO PREDICTS VOLATILITY
# Low L2/L1 -> high next |change| (0.89 vs 0.65 unconditional on day 0)
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 3: L2/L1 RATIO AS VOLATILITY PREDICTOR")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)
    df['l1_total'] = df['bid_volume_1'] + df['ask_volume_1']
    df['l2_total'] = df['bid_volume_2'].fillna(0) + df['ask_volume_2'].fillna(0)
    df['l2_l1_ratio'] = df['l2_total'] / df['l1_total'].replace(0, np.nan)

    # If low L2/L1 predicts bigger moves, can we widen our spread to capture more?
    # Or can we use this for DIRECTIONAL prediction?

    # Bucket L2/L1 and check directional bias
    df['l2_l1_bucket'] = pd.qcut(df['l2_l1_ratio'], 5, labels=['Q1','Q2','Q3','Q4','Q5'], duplicates='drop')

    print(f"  L2/L1 quintiles vs next change:")
    for q in ['Q1','Q2','Q3','Q4','Q5']:
        mask = df['l2_l1_bucket'] == q
        if mask.sum() > 0:
            next_mean = df.loc[mask, 'next_change'].mean()
            next_abs = df.loc[mask, 'next_change'].abs().mean()
            next_spread = df.loc[mask, 'spread'].shift(-1).mean()
            print(f"    {q}: next_change={next_mean:+.4f}, |next_change|={next_abs:.4f}, "
                  f"next_spread={next_spread:.1f}, n={mask.sum()}")

    # Does low L2/L1 predict NARROW spread?
    print(f"\n  L2/L1 vs P(narrow spread):")
    for q in ['Q1','Q2','Q3','Q4','Q5']:
        mask = df['l2_l1_bucket'] == q
        if mask.sum() > 0:
            p_narrow = (df.loc[mask, 'spread'] <= 9).mean()
            p_narrow_next = (df.loc[mask, 'spread'].shift(-1) <= 9).mean()
            print(f"    {q}: P(current_narrow)={p_narrow:.4f}, P(next_narrow)={p_narrow_next:.4f}")


# ============================================================================
# FINDING 4: VOLUME IMBALANCE (bid_vol > 2x ask_vol) IS HUGE SIGNAL
# Bid-heavy: next_change = +2.7, Ask-heavy: next_change = -2.3
# This was already noted as OBI in CLAUDE.md. But is there a TIMING component?
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 4: VOLUME IMBALANCE TIMING AND PERSISTENCE")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['vol_ratio'] = df['bid_volume_1'] / df['ask_volume_1'].replace(0, np.nan)

    # OBI already used with 0.5 shift. But what about MULTI-TICK persistence?
    # If vol_ratio > 2 at tick t, how long does it persist?
    # And is the CUMULATIVE return over persistence window larger?

    imb_events = df[df['vol_ratio'] > 2.0].index.tolist()

    persistence = []
    for idx in imb_events:
        count = 0
        for j in range(1, 20):
            if idx + j < len(df) and df.loc[idx + j, 'vol_ratio'] > 1.5:
                count += 1
            else:
                break
        persistence.append(count)

    if persistence:
        print(f"  OBI > 2.0 events: {len(imb_events)}")
        print(f"  Persistence (ticks where ratio stays > 1.5): mean={np.mean(persistence):.1f}, "
              f"max={max(persistence)}")

    # What about EMERALDS OBI?
    em = get_product(days[d], 'EMERALDS')
    em['spread'] = em['ask_price_1'] - em['bid_price_1']
    em['vol_ratio'] = em['bid_volume_1'] / em['ask_volume_1'].replace(0, np.nan)
    em['l1_imb'] = em['bid_volume_1'] - em['ask_volume_1']

    # EMERALDS has a KNOWN narrow spread when OBI is extreme.
    # Does EMERALDS OBI predict TOMATOES mid change?
    merged = pd.merge(df[['timestamp', 'mid_change', 'vol_ratio']],
                       em[['timestamp', 'vol_ratio', 'l1_imb', 'spread']].rename(
                           columns={'vol_ratio': 'em_vol_ratio', 'spread': 'em_spread', 'l1_imb': 'em_l1_imb'}),
                       on='timestamp')

    # Does EMERALDS extreme imbalance lead TOMATOES moves?
    for thresh in [1.5, 2.0, 3.0]:
        em_bid_heavy = merged[merged['em_vol_ratio'] > thresh]
        em_ask_heavy = merged[merged['em_vol_ratio'] < 1/thresh]
        if len(em_bid_heavy) > 0:
            print(f"  EM vol_ratio > {thresh} (n={len(em_bid_heavy)}): TOM next_change = {em_bid_heavy['mid_change'].shift(-1).mean():+.4f}")
        if len(em_ask_heavy) > 0:
            print(f"  EM vol_ratio < {1/thresh:.2f} (n={len(em_ask_heavy)}): TOM next_change = {em_ask_heavy['mid_change'].shift(-1).mean():+.4f}")


# ============================================================================
# FINDING 5: NON-LINEAR MEAN REVERSION STRENGTH
# Bigger moves have DISPROPORTIONATELY stronger mean reversion.
# change=-5 -> next=+3.27 (65% reversal) vs change=-1 -> next=+0.06 (6% reversal)
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 5: NON-LINEAR MEAN REVERSION - PIECEWISE STRATEGY")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)

    # The key insight: the regression FV uses a LINEAR function of lags.
    # But the actual relationship is CONVEX - big moves mean-revert FASTER.
    # A piece-wise or quadratic FV could capture this non-linearity.

    # Fit: next_change = a * change + b * change^2 * sign(change)
    from numpy.polynomial import polynomial as P
    valid = df.dropna(subset=['mid_change', 'next_change'])
    x = valid['mid_change'].values
    y = valid['next_change'].values

    # Linear fit
    linear_coef = np.polyfit(x, y, 1)
    linear_pred = np.polyval(linear_coef, x)
    linear_rmse = np.sqrt(np.mean((y - linear_pred)**2))

    # Quadratic fit
    quad_coef = np.polyfit(x, y, 2)
    quad_pred = np.polyval(quad_coef, x)
    quad_rmse = np.sqrt(np.mean((y - quad_pred)**2))

    # Cubic fit
    cubic_coef = np.polyfit(x, y, 3)
    cubic_pred = np.polyval(cubic_coef, x)
    cubic_rmse = np.sqrt(np.mean((y - cubic_pred)**2))

    print(f"  Linear RMSE: {linear_rmse:.4f}, coefs: {linear_coef}")
    print(f"  Quadratic RMSE: {quad_rmse:.4f}, coefs: {quad_coef}")
    print(f"  Cubic RMSE: {cubic_rmse:.4f}, coefs: {cubic_coef}")
    print(f"  Improvement quad vs linear: {(1 - quad_rmse/linear_rmse)*100:.2f}%")
    print(f"  Improvement cubic vs linear: {(1 - cubic_rmse/linear_rmse)*100:.2f}%")

    # What about piecewise? Stronger skew for |change| > 2 vs <= 2
    small = valid[valid['mid_change'].abs() <= 2]
    large = valid[valid['mid_change'].abs() > 2]
    if len(small) > 10 and len(large) > 10:
        small_coef = np.polyfit(small['mid_change'].values, small['next_change'].values, 1)
        large_coef = np.polyfit(large['mid_change'].values, large['next_change'].values, 1)
        print(f"\n  Piecewise linear:")
        print(f"    |change| <= 2: slope={small_coef[0]:.4f}, intercept={small_coef[1]:.4f}, n={len(small)}")
        print(f"    |change| > 2: slope={large_coef[0]:.4f}, intercept={large_coef[1]:.4f}, n={len(large)}")


# ============================================================================
# FINDING 6: SPREAD TRANSITION - NARROW ALWAYS FOLLOWED BY WIDE
# Can we exploit the 1-tick narrow window?
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 6: NARROW SPREAD EXPLOITATION WINDOW")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()

    narrow = df[df['spread'] <= 9]
    print(f"  Narrow spread ticks: {len(narrow)} ({len(narrow)/len(df)*100:.1f}%)")

    # For each narrow tick, what's the bid/ask and mid?
    if len(narrow) > 0:
        print(f"  Narrow spread details:")
        print(f"    avg bid_1: {narrow['bid_price_1'].mean():.1f}")
        print(f"    avg ask_1: {narrow['ask_price_1'].mean():.1f}")
        print(f"    avg mid: {narrow['mid_price'].mean():.1f}")

        # During narrow spread, our best+1 orders would be:
        # buy at bid+1, sell at ask-1
        # This is TIGHTER than the MM bot - we'd get first fill
        # But spread is only 5-9, so edge per fill is tiny

        # What matters: do we get MORE fills during narrow periods?
        # And what's the immediate P&L after a narrow-period fill?

        # Simulate: if we buy at ask during spread=5 (we know next move is UP)
        sp5 = df[df['spread'] == 5]
        if len(sp5) > 0:
            # Buy at ask = mid + 2.5
            # Sell at next tick's bid = next_mid - next_half_spread
            for h in [1, 2, 3, 5]:
                future_mid = df['mid_price'].shift(-h)
                future_spread = df['spread'].shift(-h)
                # PnL = future_bid - current_ask = (future_mid - future_spread/2) - (current_mid + current_spread/2)
                pnl = (future_mid - future_spread/2) - (df['mid_price'] + df['spread']/2)
                sp5_pnl = pnl[df['spread'] == 5]
                print(f"    spread=5 -> buy@ask, sell@bid+{h}: avg_pnl={sp5_pnl.mean():+.2f}, "
                      f"win_rate={( sp5_pnl > 0).mean():.2f}, n={len(sp5_pnl.dropna())}")

    # What about EMERALDS narrow spread?
    em = get_product(days[d], 'EMERALDS')
    em['spread'] = em['ask_price_1'] - em['bid_price_1']
    em_narrow = em[em['spread'] < 16]
    print(f"\n  EMERALDS narrow spread ticks: {len(em_narrow)} ({len(em_narrow)/len(em)*100:.1f}%)")

    if len(em_narrow) > 0:
        print(f"  EMERALDS narrow spread = {em_narrow['spread'].unique()}")
        # EMERALDS is always 10000. During narrow spread (8),
        # best ask = 10004, best bid = 9996
        # Normal: ask = 10008, bid = 9992
        # So during narrow, we can BUY at 9996 and the "fair" price is 10000
        # That's 4 ticks profit vs 8 ticks normally
        # But we ALREADY post at best+1 = 9993 normally. During narrow, best+1 = 9997
        # 9997 is CLOSER to fair value, so LESS edge per fill
        # However, we get fills at the taker's price = 9996 (their bid hit our ask at 9997? No...)

        # Actually: during narrow, MM posts bid=9996, ask=10004
        # Our best+1: buy at 9997, sell at 10003
        # If taker SELLS, they hit our 9997 bid (we buy at 9997, fair=10000, edge=3)
        # Normal: our buy at 9993, edge = 7
        # So narrow spread REDUCES our edge per EMERALDS fill
        # That's why "liquidation" fills at 10000 during narrow have zero spread


# ============================================================================
# FINDING 7: MULTI-LAG AUTOCORRELATION STRUCTURE
# AC(1) = -0.44, AC(2) near 0. But what about AC of SIGNED changes?
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 7: FULL AUTOCORRELATION STRUCTURE")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['mid_change'] = df['mid_price'].diff()
    df['abs_change'] = df['mid_change'].abs()
    df['sign_change'] = np.sign(df['mid_change'])

    print(f"  Autocorrelation of mid_change (signed):")
    for lag in range(1, 21):
        ac = df['mid_change'].autocorr(lag=lag)
        if abs(ac) > 0.02:
            print(f"    lag {lag}: {ac:+.4f} {'***' if abs(ac) > 0.05 else '*' if abs(ac) > 0.03 else ''}")

    print(f"\n  Autocorrelation of |mid_change|:")
    for lag in range(1, 21):
        ac = df['abs_change'].autocorr(lag=lag)
        if abs(ac) > 0.02:
            print(f"    lag {lag}: {ac:+.4f} {'***' if abs(ac) > 0.05 else '*' if abs(ac) > 0.03 else ''}")

    print(f"\n  Autocorrelation of sign(mid_change):")
    for lag in range(1, 21):
        ac = df['sign_change'].autocorr(lag=lag)
        if abs(ac) > 0.02:
            print(f"    lag {lag}: {ac:+.4f} {'***' if abs(ac) > 0.05 else '*' if abs(ac) > 0.03 else ''}")


# ============================================================================
# FINDING 8: CONDITIONAL STRATEGIES (combining signals)
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 8: COMBINED SIGNAL ANALYSIS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    df = get_product(days[d], 'TOMATOES')
    df['spread'] = df['ask_price_1'] - df['bid_price_1']
    df['mid_change'] = df['mid_price'].diff()
    df['next_change'] = df['mid_change'].shift(-1)
    df['abs_change'] = df['mid_change'].abs()
    df['l2_l1_ratio'] = (df['bid_volume_2'].fillna(0) + df['ask_volume_2'].fillna(0)) / \
                          (df['bid_volume_1'] + df['ask_volume_1']).replace(0, np.nan)
    df['vol_ratio'] = df['bid_volume_1'] / df['ask_volume_1'].replace(0, np.nan)
    df['obi'] = (df['bid_volume_1'] - df['ask_volume_1']) / (df['bid_volume_1'] + df['ask_volume_1'])

    # Signal 1: Low L2/L1 + big |change| (vol clustering + thin book)
    thin_book = df['l2_l1_ratio'] < df['l2_l1_ratio'].quantile(0.25)
    big_move = df['abs_change'] >= 2.0
    combined = thin_book & big_move

    if combined.sum() > 0:
        print(f"  Thin book + big move (n={combined.sum()}):")
        print(f"    next |change|: {df.loc[combined, 'next_change'].abs().mean():.3f} "
              f"(vs unconditional {df['next_change'].abs().mean():.3f})")
        print(f"    next change: {df.loc[combined, 'next_change'].mean():+.3f}")

    # Signal 2: OBI + vol clustering
    # After big move + OBI in reversal direction = stronger reversal
    big_up = df['mid_change'] >= 3.0
    obi_negative = df['obi'] < -0.2  # More ask volume = bearish
    reversal_combo = big_up & obi_negative

    if reversal_combo.sum() > 0:
        print(f"\n  Big up + bearish OBI (n={reversal_combo.sum()}):")
        print(f"    next change: {df.loc[reversal_combo, 'next_change'].mean():+.3f}")

    big_dn = df['mid_change'] <= -3.0
    obi_positive = df['obi'] > 0.2
    reversal_combo2 = big_dn & obi_positive

    if reversal_combo2.sum() > 0:
        print(f"  Big down + bullish OBI (n={reversal_combo2.sum()}):")
        print(f"    next change: {df.loc[reversal_combo2, 'next_change'].mean():+.3f}")

    # Signal 3: Position in daily range + OBI
    session_mean = df['mid_price'].mean()
    session_std = df['mid_price'].std()
    df['z_score'] = (df['mid_price'] - session_mean) / session_std

    # Extreme position + OBI opposing = strong reversal signal
    high_price = df['z_score'] > 1.0
    low_price = df['z_score'] < -1.0

    if (high_price & obi_negative).sum() > 0:
        print(f"\n  High price + bearish OBI (n={(high_price & obi_negative).sum()}):")
        print(f"    next change: {df.loc[high_price & obi_negative, 'next_change'].mean():+.3f}")

    if (low_price & obi_positive).sum() > 0:
        print(f"  Low price + bullish OBI (n={(low_price & obi_positive).sum()}):")
        print(f"    next change: {df.loc[low_price & obi_positive, 'next_change'].mean():+.3f}")


# ============================================================================
# FINDING 9: TAKER BOT INTER-ARRIVAL TIME DISTRIBUTION
# Can we predict WHEN the next trade will happen?
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 9: TAKER BOT TIMING ANALYSIS")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    for prod in ['TOMATOES', 'EMERALDS']:
        t = trades[d][trades[d]['symbol'] == prod].sort_values('timestamp')
        if len(t) < 5:
            continue

        intervals = np.diff(t['timestamp'].values)

        print(f"\n  {prod} inter-trade intervals (n={len(intervals)}):")
        print(f"    mean={intervals.mean():.0f}ms, median={np.median(intervals):.0f}ms, "
              f"std={intervals.std():.0f}ms")

        # Test for exponential distribution (memoryless)
        # If exponential: mean ≈ std
        cv = intervals.std() / intervals.mean()
        print(f"    CV (std/mean) = {cv:.3f} (exponential = 1.0)")

        # Conditional: is next interval predictable from current?
        if len(intervals) > 1:
            ac = np.corrcoef(intervals[:-1], intervals[1:])[0, 1]
            print(f"    Autocorrelation of intervals: {ac:.4f}")

        # Is there periodicity?
        if len(intervals) > 50:
            # Check if intervals cluster at certain values
            pctiles = np.percentile(intervals, [10, 25, 50, 75, 90])
            print(f"    Percentiles: {pctiles}")

            # Time since last trade → probability of trade this tick
            # Group by time-since-last and compute trade frequency
            prices = get_product(days[d], prod)
            trade_ts = set(t['timestamp'].values)
            prices['has_trade'] = prices['timestamp'].isin(trade_ts).astype(int)

            # Time since last trade for each tick
            prices['time_since_trade'] = np.nan
            last_trade = -999999
            for i in range(len(prices)):
                if prices.iloc[i]['has_trade']:
                    last_trade = prices.iloc[i]['timestamp']
                prices.iloc[i, prices.columns.get_loc('time_since_trade')] = prices.iloc[i]['timestamp'] - last_trade

            # Hazard rate: P(trade | time_since_last = t)
            print(f"    Hazard rate by time-since-last-trade:")
            for window in [0, 500, 1000, 2000, 3000, 5000, 10000, 20000]:
                window_end = window + 500
                mask = (prices['time_since_trade'] >= window) & (prices['time_since_trade'] < window_end)
                if mask.sum() > 0:
                    hazard = prices.loc[mask, 'has_trade'].mean()
                    # Only print if this is after the first trade
                    if prices.loc[mask, 'time_since_trade'].min() > 0:
                        print(f"      t_since=[{window},{window_end})ms: P(trade)={hazard:.4f}, n={mask.sum()}")


# ============================================================================
# FINDING 10: EMERALDS - EXACT NARROW SPREAD PATTERN
# ============================================================================
print("\n\n" + "=" * 80)
print("DEEP DIVE 10: EMERALDS NARROW SPREAD FULL CHARACTERIZATION")
print("=" * 80)

for d in [-2, -1, 0]:
    print(f"\n--- Day {d} ---")
    em = get_product(days[d], 'EMERALDS')
    em['spread'] = em['ask_price_1'] - em['bid_price_1']
    em['l1_imb'] = em['bid_volume_1'] - em['ask_volume_1']
    em['mid_change'] = em['mid_price'].diff()

    narrow = em[em['spread'] == 8]
    wide = em[em['spread'] == 16]

    print(f"  Narrow (spread=8): {len(narrow)} ticks ({len(narrow)/len(em)*100:.1f}%)")
    print(f"  Wide (spread=16): {len(wide)} ticks ({len(wide)/len(em)*100:.1f}%)")

    if len(narrow) > 0:
        # What L1 imbalance at narrow?
        print(f"\n  At narrow spread:")
        print(f"    L1 imbalance: {narrow['l1_imb'].describe()}")
        print(f"    bid_vol_1: {narrow['bid_volume_1'].describe()}")
        print(f"    ask_vol_1: {narrow['ask_volume_1'].describe()}")
        print(f"    mid_price: {narrow['mid_price'].describe()}")

        # Is narrow spread preceded by a specific pattern?
        narrow_idx = narrow.index
        for lookback in [1, 2, 3]:
            prev_mids = []
            prev_imbs = []
            for idx in narrow_idx:
                if idx - lookback >= 0:
                    prev_mids.append(em.loc[idx - lookback, 'mid_price'])
                    prev_imbs.append(em.loc[idx - lookback, 'l1_imb'])
            if prev_mids:
                print(f"    {lookback} tick before: mid={np.mean(prev_mids):.2f}, imb={np.mean(prev_imbs):.2f}")

        # Does mid_price at narrow tick predict direction?
        print(f"\n  Mid-price at narrow -> direction:")
        narrow_above = narrow[narrow['mid_price'] > 10000]
        narrow_below = narrow[narrow['mid_price'] < 10000]
        narrow_at = narrow[narrow['mid_price'] == 10000]

        for label, sub in [("above 10000", narrow_above), ("below 10000", narrow_below), ("at 10000", narrow_at)]:
            if len(sub) > 0:
                next_idx = sub.index + 1
                next_idx = next_idx[next_idx < len(em)]
                if len(next_idx) > 0:
                    next_change = em.loc[next_idx, 'mid_change'].mean()
                    print(f"    {label} (n={len(sub)}): next_change={next_change:+.4f}")


print("\n\n" + "=" * 80)
print("DEEP ANALYSIS PART 2 COMPLETE")
print("=" * 80)
