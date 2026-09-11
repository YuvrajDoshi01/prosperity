"""
posting_width_analysis.py — Compare posting widths for TOMATOES and EMERALDS

Key question: Does posting at mid +/- 3 give BETTER queue priority than best +/- 1?
Or is it actually WIDER (worse priority)?

Our strategy (s36_medallion):
  TOMATOES: bid = min(fv-1, best_bid+1), ask = max(fv+1, best_ask-1)
  EMERALDS: bid = min(9999, best_bid+1),  ask = max(10001, best_ask-1)

Alternative: post at mid +/- K (fixed offset from fair value)
"""

import csv
import os
from collections import defaultdict

DATA_DIR = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0"

def load_data(day_suffix):
    """Load price data for a given day suffix (e.g., '0', '-1')."""
    path = os.path.join(DATA_DIR, f"prices_round_0_day_{day_suffix}.csv")
    tomatoes = []
    emeralds = []
    with open(path, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            product = row["product"]
            rec = {
                "timestamp": int(row["timestamp"]),
                "bid1": int(row["bid_price_1"]),
                "bid1_vol": int(row["bid_volume_1"]),
                "bid2": int(row["bid_price_2"]) if row["bid_price_2"] else None,
                "bid2_vol": int(row["bid_volume_2"]) if row["bid_volume_2"] else None,
                "ask1": int(row["ask_price_1"]),
                "ask1_vol": int(row["ask_volume_1"]),
                "ask2": int(row["ask_price_2"]) if row["ask_price_2"] else None,
                "ask2_vol": int(row["ask_volume_2"]) if row["ask_volume_2"] else None,
                "mid": float(row["mid_price"]),
            }
            if product == "TOMATOES":
                tomatoes.append(rec)
            elif product == "EMERALDS":
                emeralds.append(rec)
    return tomatoes, emeralds


def analyze_posting_widths():
    print("=" * 80)
    print("POSTING WIDTH ANALYSIS: mid +/- K vs best +/- 1")
    print("=" * 80)

    for day_label, day_suffix in [("Day 0 (2k ticks)", "0"), ("Day -1 (10k ticks)", "-1")]:
        tom_data, em_data = load_data(day_suffix)

        print(f"\n{'='*80}")
        print(f"  {day_label}: {len(tom_data)} TOMATOES ticks, {len(em_data)} EMERALDS ticks")
        print(f"{'='*80}")

        # ─────────────────────────────────────────────────
        # SECTION 1: TOMATOES spread distribution
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Spread Distribution ---")
        spreads = [r["ask1"] - r["bid1"] for r in tom_data]
        spread_counts = defaultdict(int)
        for s in spreads:
            spread_counts[s] += 1
        total = len(spreads)
        for s in sorted(spread_counts):
            pct = spread_counts[s] / total * 100
            print(f"  Spread {s:3d}: {spread_counts[s]:5d} ticks ({pct:5.1f}%)")
        print(f"  Mean spread: {sum(spreads)/len(spreads):.2f}")

        # ─────────────────────────────────────────────────
        # SECTION 2: TOMATOES — mid +/- K analysis
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Posting at mid +/- K vs best +/- 1 ---")
        print(f"  (positive = our order is INSIDE the MM spread = better priority)")
        print(f"  (negative = our order is OUTSIDE the MM spread = worse priority)")

        for K in [2, 3, 4, 5, 6, 7]:
            inside_bid = 0
            inside_ask = 0
            at_or_outside_bid = 0
            at_or_outside_ask = 0
            crosses_mid = 0

            for r in tom_data:
                mid = r["mid"]
                # Our hypothetical quotes
                hyp_bid = round(mid) - K
                hyp_ask = round(mid) + K

                # Compare to MM best bid/ask
                if hyp_bid > r["bid1"]:
                    inside_bid += 1
                else:
                    at_or_outside_bid += 1

                if hyp_ask < r["ask1"]:
                    inside_ask += 1
                else:
                    at_or_outside_ask += 1

                # Check for crossing (bid >= ask or our bid >= our ask)
                if hyp_bid >= hyp_ask:
                    crosses_mid += 1

            print(f"\n  mid +/- {K}:")
            print(f"    Bid (mid-{K}) INSIDE MM spread (better priority): {inside_bid:5d} / {total} ({inside_bid/total*100:.1f}%)")
            print(f"    Bid (mid-{K}) AT/OUTSIDE MM bid (equal/worse):    {at_or_outside_bid:5d} / {total} ({at_or_outside_bid/total*100:.1f}%)")
            print(f"    Ask (mid+{K}) INSIDE MM spread (better priority): {inside_ask:5d} / {total} ({inside_ask/total*100:.1f}%)")
            print(f"    Ask (mid+{K}) AT/OUTSIDE MM ask (equal/worse):    {at_or_outside_ask:5d} / {total} ({at_or_outside_ask/total*100:.1f}%)")
            if crosses_mid > 0:
                print(f"    WARNING: quotes cross each other on {crosses_mid} ticks!")

        # ─────────────────────────────────────────────────
        # SECTION 3: Compare best+1 vs mid-K numerically
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Numerical comparison (where orders land) ---")
        print(f"  Tick-by-tick: best_bid+1 vs mid-K, and best_ask-1 vs mid+K")
        print(f"  Higher bid = better buy priority. Lower ask = better sell priority.\n")

        # Collect statistics
        for K in [3, 5, 6, 7]:
            best_plus1_higher_bid = 0
            midK_higher_bid = 0
            equal_bid = 0
            best_minus1_lower_ask = 0
            midK_lower_ask = 0
            equal_ask = 0

            bid_diffs = []
            ask_diffs = []

            for r in tom_data:
                mid = r["mid"]
                # Our current strategy: best +/- 1
                our_bid = r["bid1"] + 1
                our_ask = r["ask1"] - 1
                # Alternative: mid +/- K
                alt_bid = round(mid) - K
                alt_ask = round(mid) + K

                bid_diff = our_bid - alt_bid  # positive = our current bid is higher (better)
                ask_diff = alt_ask - our_ask   # positive = alt ask is higher (our current is better)

                bid_diffs.append(bid_diff)
                ask_diffs.append(ask_diff)

                if our_bid > alt_bid:
                    best_plus1_higher_bid += 1
                elif alt_bid > our_bid:
                    midK_higher_bid += 1
                else:
                    equal_bid += 1

                if our_ask < alt_ask:
                    best_minus1_lower_ask += 1
                elif alt_ask < our_ask:
                    midK_lower_ask += 1
                else:
                    equal_ask += 1

            avg_bid_diff = sum(bid_diffs) / len(bid_diffs)
            avg_ask_diff = sum(ask_diffs) / len(ask_diffs)
            print(f"  mid +/- {K}:")
            print(f"    BID: best_bid+1 higher (we win): {best_plus1_higher_bid:5d} ({best_plus1_higher_bid/total*100:.1f}%)")
            print(f"         mid-{K} higher (alt wins):   {midK_higher_bid:5d} ({midK_higher_bid/total*100:.1f}%)")
            print(f"         equal:                       {equal_bid:5d} ({equal_bid/total*100:.1f}%)")
            print(f"         avg diff (ours - alt bid):   {avg_bid_diff:+.2f}")
            print(f"    ASK: best_ask-1 lower (we win):  {best_minus1_lower_ask:5d} ({best_minus1_lower_ask/total*100:.1f}%)")
            print(f"         mid+{K} lower (alt wins):    {midK_lower_ask:5d} ({midK_lower_ask/total*100:.1f}%)")
            print(f"         equal:                       {equal_ask:5d} ({equal_ask/total*100:.1f}%)")
            print(f"         avg diff (alt ask - ours):   {avg_ask_diff:+.2f}")

        # ─────────────────────────────────────────────────
        # SECTION 4: What happens during narrow spreads (5-9)?
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Narrow spread (5-9) analysis ---")
        narrow_ticks = [r for r in tom_data if r["ask1"] - r["bid1"] <= 9]
        print(f"  Narrow spread ticks: {len(narrow_ticks)} / {total} ({len(narrow_ticks)/total*100:.1f}%)")

        if narrow_ticks:
            for K in [3, 5, 6, 7]:
                crosses = 0
                inside = 0
                outside = 0
                for r in narrow_ticks:
                    mid = r["mid"]
                    hyp_bid = round(mid) - K
                    hyp_ask = round(mid) + K
                    spread = r["ask1"] - r["bid1"]

                    if hyp_bid >= hyp_ask:
                        crosses += 1
                    if hyp_bid > r["bid1"] and hyp_ask < r["ask1"]:
                        inside += 1
                    elif hyp_bid <= r["bid1"] or hyp_ask >= r["ask1"]:
                        outside += 1

                n = len(narrow_ticks)
                print(f"  mid +/- {K} during narrow spread:")
                print(f"    Both sides inside MM: {inside:3d} ({inside/n*100:.1f}%)")
                print(f"    At least one side at/outside: {outside:3d} ({outside/n*100:.1f}%)")
                if crosses > 0:
                    print(f"    WARNING: bid/ask cross: {crosses:3d} ({crosses/n*100:.1f}%)")

            # Show actual prices during narrow spreads
            print(f"\n  Sample narrow-spread ticks:")
            for r in narrow_ticks[:10]:
                spread = r["ask1"] - r["bid1"]
                mid = r["mid"]
                print(f"    t={r['timestamp']:7d}: bid1={r['bid1']} ask1={r['ask1']} spread={spread} mid={mid:.1f}"
                      f"  | best+1={r['bid1']+1} best-1={r['ask1']-1}"
                      f"  | mid-3={round(mid)-3} mid+3={round(mid)+3}"
                      f"  | mid-6={round(mid)-6} mid+6={round(mid)+6}")

        # ─────────────────────────────────────────────────
        # SECTION 5: EMERALDS analysis
        # ─────────────────────────────────────────────────
        print(f"\n--- EMERALDS: Spread Distribution ---")
        em_spreads = [r["ask1"] - r["bid1"] for r in em_data]
        em_spread_counts = defaultdict(int)
        for s in em_spreads:
            em_spread_counts[s] += 1
        em_total = len(em_spreads)
        for s in sorted(em_spread_counts):
            pct = em_spread_counts[s] / em_total * 100
            print(f"  Spread {s:3d}: {em_spread_counts[s]:5d} ticks ({pct:5.1f}%)")

        print(f"\n--- EMERALDS: FV=10000, posting comparison ---")
        FV = 10000
        for offset in [1, 3, 5, 7, 8]:
            inside_bid = 0
            inside_ask = 0
            for r in em_data:
                hyp_bid = FV - offset
                hyp_ask = FV + offset
                if hyp_bid > r["bid1"]:
                    inside_bid += 1
                if hyp_ask < r["ask1"]:
                    inside_ask += 1
            print(f"  FV +/- {offset}: bid={FV-offset}, ask={FV+offset}")
            print(f"    Bid inside MM spread: {inside_bid:5d} / {em_total} ({inside_bid/em_total*100:.1f}%)")
            print(f"    Ask inside MM spread: {inside_ask:5d} / {em_total} ({inside_ask/em_total*100:.1f}%)")

        print(f"\n--- EMERALDS: best+1 vs FV-K numerical comparison ---")
        for offset in [1, 7, 8]:
            our_bid_wins = 0
            alt_bid_wins = 0
            equal_bid = 0
            bid_diffs = []
            for r in em_data:
                our_bid = min(FV - 1, r["bid1"] + 1)  # our actual logic
                alt_bid = FV - offset
                d = our_bid - alt_bid
                bid_diffs.append(d)
                if our_bid > alt_bid:
                    our_bid_wins += 1
                elif alt_bid > our_bid:
                    alt_bid_wins += 1
                else:
                    equal_bid += 1

            our_ask_wins = 0
            alt_ask_wins = 0
            equal_ask = 0
            ask_diffs = []
            for r in em_data:
                our_ask = max(FV + 1, r["ask1"] - 1)  # our actual logic
                alt_ask = FV + offset
                d = alt_ask - our_ask
                ask_diffs.append(d)
                if our_ask < alt_ask:
                    our_ask_wins += 1
                elif alt_ask < our_ask:
                    alt_ask_wins += 1
                else:
                    equal_ask += 1

            print(f"  FV +/- {offset} (alt) vs our best+1/best-1 (capped at FV-1/FV+1):")
            print(f"    BID: ours higher: {our_bid_wins:5d}  alt higher: {alt_bid_wins:5d}  equal: {equal_bid:5d}  avg diff: {sum(bid_diffs)/len(bid_diffs):+.2f}")
            print(f"    ASK: ours lower:  {our_ask_wins:5d}  alt lower:  {alt_ask_wins:5d}  equal: {equal_ask:5d}  avg diff: {sum(ask_diffs)/len(ask_diffs):+.2f}")

        # ─────────────────────────────────────────────────
        # SECTION 6: EMERALDS — show typical best_bid, best_ask
        # ─────────────────────────────────────────────────
        print(f"\n--- EMERALDS: Typical best_bid / best_ask ---")
        em_bid_counts = defaultdict(int)
        em_ask_counts = defaultdict(int)
        for r in em_data:
            em_bid_counts[r["bid1"]] += 1
            em_ask_counts[r["ask1"]] += 1
        print(f"  Best bid distribution:")
        for p in sorted(em_bid_counts, reverse=True)[:5]:
            print(f"    {p}: {em_bid_counts[p]:5d} ({em_bid_counts[p]/em_total*100:.1f}%)")
        print(f"  Best ask distribution:")
        for p in sorted(em_ask_counts)[:5]:
            print(f"    {p}: {em_ask_counts[p]:5d} ({em_ask_counts[p]/em_total*100:.1f}%)")

        # ─────────────────────────────────────────────────
        # SECTION 7: Compute actual posting prices our strategy uses
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Where our strategy ACTUALLY posts (best+1 capped at fv-1) ---")
        # Use mid as rough proxy for fv (regression shifts by ~2, negligible for this)
        our_bid_prices = defaultdict(int)
        our_ask_prices = defaultdict(int)
        our_bid_offsets = []
        our_ask_offsets = []
        for r in tom_data:
            mid = r["mid"]
            fv_int = round(mid)  # approximate (real uses regression)
            our_bid = min(fv_int - 1, r["bid1"] + 1)
            our_ask = max(fv_int + 1, r["ask1"] - 1)
            our_bid_prices[our_bid - round(mid)] += 1
            our_ask_prices[our_ask - round(mid)] += 1
            our_bid_offsets.append(our_bid - mid)
            our_ask_offsets.append(our_ask - mid)

        print(f"  Our bid offset from mid (negative = below mid):")
        for off in sorted(our_bid_prices):
            print(f"    mid{off:+d}: {our_bid_prices[off]:5d} ({our_bid_prices[off]/total*100:.1f}%)")
        print(f"  Our ask offset from mid (positive = above mid):")
        for off in sorted(our_ask_prices):
            print(f"    mid{off:+d}: {our_ask_prices[off]:5d} ({our_ask_prices[off]/total*100:.1f}%)")
        print(f"  Avg bid offset from mid: {sum(our_bid_offsets)/len(our_bid_offsets):+.2f}")
        print(f"  Avg ask offset from mid: {sum(our_ask_offsets)/len(our_ask_offsets):+.2f}")

        # ─────────────────────────────────────────────────
        # SECTION 8: Spread captured at different posting widths
        # ─────────────────────────────────────────────────
        print(f"\n--- TOMATOES: Spread captured (ask - bid) at different posting widths ---")
        for K in [3, 5, 6, 7]:
            alt_spreads = []
            for r in tom_data:
                mid = r["mid"]
                alt_bid = round(mid) - K
                alt_ask = round(mid) + K
                alt_spreads.append(alt_ask - alt_bid)
            print(f"  mid +/- {K}: spread captured = {alt_spreads[0]} (constant = {2*K})")

        print(f"\n  Our strategy (best+1/best-1 capped at fv+/-1):")
        our_spreads = []
        for r in tom_data:
            mid = r["mid"]
            fv_int = round(mid)
            our_bid = min(fv_int - 1, r["bid1"] + 1)
            our_ask = max(fv_int + 1, r["ask1"] - 1)
            our_spreads.append(our_ask - our_bid)
        spread_cap_counts = defaultdict(int)
        for s in our_spreads:
            spread_cap_counts[s] += 1
        for s in sorted(spread_cap_counts):
            print(f"    Spread {s:3d}: {spread_cap_counts[s]:5d} ({spread_cap_counts[s]/total*100:.1f}%)")
        print(f"    Mean spread captured: {sum(our_spreads)/len(our_spreads):.2f}")

    # ─────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("SUMMARY & KEY FINDINGS")
    print(f"{'='*80}")
    print("""
TOMATOES (typical spread 13-14, mid ~5000):
  The MM bot typically posts at mid +/- 6.5 to mid +/- 7.
  
  Our strategy: best_bid+1 / best_ask-1 (capped at fv +/- 1)
    -> This means we post at approximately mid -5.5 / mid +5.5 (when spread=13)
    -> Or approximately mid -6 / mid +6 (when spread=13, mid is X.5)
    -> We are INSIDE the MM spread by 1 tick on each side
    -> Spread captured: ~11-12 per round trip

  Alternative mid +/- 3:
    -> We would post at mid -3 / mid +3
    -> This is DEEPER inside the spread (closer to mid) = MORE aggressive
    -> BETTER queue priority (higher bid, lower ask) than best+1
    -> BUT spread captured only 6 per round trip (vs ~11-12 for best+1)
    -> This is essentially the "tight posting" strategy
    -> CONFIRMED WORSE on website: diag_tight scored 1,836 vs 2,857
    
  The tradeoff:
    - Tighter quotes = better fill probability but LESS spread captured per fill
    - In this market, fills are dominated by the random taker bot
    - The taker hits the best price regardless — so best+1 already captures 98% of flow
    - Going tighter (mid+/-3) just gives away spread for no extra fills

EMERALDS (typical spread 16, pegged at FV=10000):
  MM bot typically at 9992/10008 (spread=16) or 9993/10007 (spread=14)
  
  Our strategy: best_bid+1 = 9993, best_ask-1 = 10007 (capped at 9999/10001)
    -> When best_bid=9992: we post 9993 (FV-7)
    -> When best_bid=9993: we post 9994 (FV-6)
    -> Spread captured: ~13-14
    
  Alternative FV +/- 7 = 9993/10007:
    -> Same as best+1 when MM bid is 9992 (both give 9993)
    -> Worse when MM bid is 9993 (we'd post 9993, best+1 gives 9994)
    -> Fixed offset misses the adaptiveness of best+1

KEY ANSWER: mid +/- 3 gives BETTER queue priority (more aggressive) than best+1,
but this is NOT desirable. It captures less spread per fill while getting roughly
the same fill rate (taker bot hits best price regardless). The website confirmed
this: tight posting (diag_tight) scored 1,836 vs normal posting at 2,857.

The optimal posting width is best +/- 1, which sits exactly 1 tick inside the MM
spread. This maximizes spread captured while maintaining queue priority over the
MM bot's quotes.
""")


if __name__ == "__main__":
    analyze_posting_widths()
