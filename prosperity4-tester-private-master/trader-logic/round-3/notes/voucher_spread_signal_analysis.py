"""
Voucher Spread Signal Analysis
================================
Hypothesis: When a voucher's bid-ask spread widens beyond its modal (most common)
value, VFE (the underlying) is at a local peak and will mean-revert downward.

This is the mechanism behind vev3.py's VEV_4000 spread=22 signal ($67k/3-day).
We systematically test whether similar signals exist across ALL voucher strikes.

Methodology:
  1. For each voucher strike on each day, compute spread distribution
  2. Define "spread-widen event" = spread > mode(spread)
  3. Compute forward VFE returns at horizons {5, 10, 20, 50, 100, 200} ticks
  4. Report: mean return, median return, hit rate (% negative returns), t-statistic
  5. Apply Bonferroni correction for multiple testing (10 strikes x 6 horizons = 60 tests)
  6. Cluster analysis: do widen events cluster in time? (consecutive count matters for vev3)
  7. Cross-strike correlation: do spread-widen events fire simultaneously?

Output: rank-ordered table of best strike/horizon combinations for VFE directional signals.
"""

import csv
import os
import sys
from collections import Counter, defaultdict
from math import sqrt
from statistics import median, stdev, mean

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
RESOURCE_DIR = os.path.join(PROJECT_ROOT, "prosperity4bt", "resources", "round3")

DAYS = [0, 1, 2]
VOUCHER_STRIKES = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500",
]
UNDERLYING = "VELVETFRUIT_EXTRACT"
HORIZONS = [5, 10, 20, 50, 100, 200]  # ticks ahead (each tick = 100ms)

# Minimum number of events required to consider a signal meaningful
MIN_EVENTS = 20

# Bonferroni correction: 10 strikes x 6 horizons = 60 tests
N_TESTS = len(VOUCHER_STRIKES) * len(HORIZONS)
ALPHA_BONFERRONI = 0.01 / N_TESTS  # per-test threshold for 1% family-wise error

# For consecutive-spread analysis (like vev3's s22_consec >= 3)
CONSEC_THRESHOLDS = [1, 2, 3, 5]


# ─────────────────────────────────────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────────────────────────────────────

def load_prices(day):
    """Load prices CSV and return dict of {product: [(timestamp, bid1, ask1, mid), ...]}."""
    fname = os.path.join(RESOURCE_DIR, f"prices_round_3_day_{day}.csv")
    data = defaultdict(list)

    with open(fname, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            product = row["product"]
            ts = int(row["timestamp"])
            bid1 = row.get("bid_price_1", "")
            ask1 = row.get("ask_price_1", "")

            if bid1 and ask1:
                bid1 = float(bid1)
                ask1 = float(ask1)
                mid = (bid1 + ask1) / 2.0
                spread = ask1 - bid1
            else:
                bid1 = None
                ask1 = None
                mid = None
                spread = None

            data[product].append({
                "ts": ts,
                "bid": bid1,
                "ask": ask1,
                "mid": mid,
                "spread": spread,
            })

    # Sort by timestamp within each product
    for product in data:
        data[product].sort(key=lambda x: x["ts"])

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Analysis Functions
# ─────────────────────────────────────────────────────────────────────────────

def compute_spread_distribution(records):
    """Compute spread distribution stats for a product's records."""
    spreads = [r["spread"] for r in records if r["spread"] is not None]
    if not spreads:
        return None

    counter = Counter(spreads)
    mode_spread = counter.most_common(1)[0][0]
    total = len(spreads)

    return {
        "mode": mode_spread,
        "mean": mean(spreads),
        "median": median(spreads),
        "min": min(spreads),
        "max": max(spreads),
        "std": stdev(spreads) if len(spreads) > 1 else 0,
        "n": total,
        "distribution": dict(counter.most_common(20)),  # top 20 spread values
        "pct_at_mode": counter[mode_spread] / total * 100,
        "pct_above_mode": sum(v for k, v in counter.items() if k > mode_spread) / total * 100,
    }


def find_widen_events(voucher_records, mode_spread):
    """Find timestamps where spread > mode."""
    events = []
    consec = 0
    for r in voucher_records:
        if r["spread"] is not None and r["spread"] > mode_spread:
            consec += 1
            events.append({
                "ts": r["ts"],
                "spread": r["spread"],
                "consec": consec,
            })
        else:
            consec = 0
    return events


def compute_forward_returns(events, underlying_records, horizons):
    """
    For each widen event, compute VFE forward returns at specified horizons.
    Returns dict: {horizon: [returns_list]}
    """
    # Build timestamp -> index mapping for underlying
    ts_to_idx = {}
    for i, r in enumerate(underlying_records):
        ts_to_idx[r["ts"]] = i

    results = {h: [] for h in horizons}

    for event in events:
        ts = event["ts"]
        if ts not in ts_to_idx:
            continue
        idx = ts_to_idx[ts]
        base_mid = underlying_records[idx]["mid"]
        if base_mid is None:
            continue

        for h in horizons:
            target_idx = idx + h
            if target_idx < len(underlying_records):
                future_mid = underlying_records[target_idx]["mid"]
                if future_mid is not None:
                    ret = future_mid - base_mid
                    results[h].append(ret)

    return results


def compute_signal_stats(returns_list):
    """Compute signal quality statistics for a list of forward returns."""
    n = len(returns_list)
    if n < MIN_EVENTS:
        return None

    avg = mean(returns_list)
    med = median(returns_list)
    sd = stdev(returns_list) if n > 1 else 0
    se = sd / sqrt(n) if n > 1 else float("inf")
    t_stat = avg / se if se > 0 else 0

    # Hit rate: what fraction of events are followed by negative returns (i.e., VFE declines)
    hit_rate_short = sum(1 for r in returns_list if r < 0) / n
    hit_rate_long = sum(1 for r in returns_list if r > 0) / n

    # Two-sided p-value approximation using normal CDF (valid for large N)
    # For |t| > 8 the p-value is effectively 0 from any practical standpoint.
    abs_t = abs(t_stat)
    # Mill's ratio approximation for the standard normal tail
    # P(Z > z) ~ phi(z)/z for large z, where phi is the standard normal pdf
    import math
    if abs_t > 37:
        p_approx = 1e-300  # underflow guard
    elif abs_t > 8:
        # Upper tail: phi(z)/z * 2 (two-sided)
        log_p = -0.5 * abs_t * abs_t - 0.5 * math.log(2 * math.pi) - math.log(abs_t)
        p_approx = 2.0 * math.exp(log_p)
    elif abs_t > 3.5:
        p_approx = 0.0005
    elif abs_t > 3.0:
        p_approx = 0.003
    elif abs_t > 2.58:
        p_approx = 0.01
    elif abs_t > 2.33:
        p_approx = 0.02
    elif abs_t > 1.96:
        p_approx = 0.05
    elif abs_t > 1.64:
        p_approx = 0.10
    else:
        p_approx = 0.50

    return {
        "n": n,
        "mean": avg,
        "median": med,
        "std": sd,
        "t_stat": t_stat,
        "p_approx": p_approx,
        "hit_rate_short": hit_rate_short,
        "hit_rate_long": hit_rate_long,
        "significant_bonferroni": p_approx < ALPHA_BONFERRONI,
        "max_adverse": max(returns_list) if returns_list else 0,
        "max_favorable": min(returns_list) if returns_list else 0,
        "p10": sorted(returns_list)[int(n * 0.10)] if n >= 10 else None,
        "p90": sorted(returns_list)[int(n * 0.90)] if n >= 10 else None,
    }


def compute_consecutive_signal(events, underlying_records, horizons, consec_thresh):
    """
    Like compute_forward_returns but only fires on ticks where
    consecutive widen count >= consec_thresh.
    """
    filtered = [e for e in events if e["consec"] >= consec_thresh]
    return compute_forward_returns(filtered, underlying_records, horizons), len(filtered)


def compute_cross_strike_correlation(all_widen_tss):
    """
    Check how correlated widen events are across strikes.
    Returns pairwise Jaccard similarity of event timestamp sets.
    """
    strikes = sorted(all_widen_tss.keys())
    results = {}
    for i, s1 in enumerate(strikes):
        for s2 in strikes[i + 1:]:
            set1 = set(all_widen_tss[s1])
            set2 = set(all_widen_tss[s2])
            if not set1 or not set2:
                continue
            jaccard = len(set1 & set2) / len(set1 | set2) if set1 | set2 else 0
            results[(s1, s2)] = {
                "jaccard": jaccard,
                "overlap_count": len(set1 & set2),
                "n1": len(set1),
                "n2": len(set2),
            }
    return results


def compute_directional_bias(events, underlying_records):
    """
    Compute what fraction of widen events occur when VFE is above/below
    its trailing 100-tick average (i.e., are widen events peak-biased?).
    """
    ts_to_idx = {}
    for i, r in enumerate(underlying_records):
        ts_to_idx[r["ts"]] = i

    above_avg = 0
    below_avg = 0
    total = 0
    for event in events:
        ts = event["ts"]
        if ts not in ts_to_idx:
            continue
        idx = ts_to_idx[ts]
        if idx < 100:
            continue
        current_mid = underlying_records[idx]["mid"]
        if current_mid is None:
            continue

        trailing_mids = [
            underlying_records[j]["mid"]
            for j in range(idx - 100, idx)
            if underlying_records[j]["mid"] is not None
        ]
        if not trailing_mids:
            continue

        trailing_avg = mean(trailing_mids)
        total += 1
        if current_mid > trailing_avg:
            above_avg += 1
        else:
            below_avg += 1

    return {
        "above_trailing_avg": above_avg,
        "below_trailing_avg": below_avg,
        "total": total,
        "pct_above": above_avg / total * 100 if total > 0 else 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# VFE Unconditional Stats (baseline for comparison)
# ─────────────────────────────────────────────────────────────────────────────

def compute_unconditional_returns(underlying_records, horizons):
    """Compute forward return distribution for ALL ticks (baseline)."""
    results = {h: [] for h in horizons}
    n = len(underlying_records)
    for i in range(n):
        base_mid = underlying_records[i]["mid"]
        if base_mid is None:
            continue
        for h in horizons:
            if i + h < n:
                future_mid = underlying_records[i + h]["mid"]
                if future_mid is not None:
                    results[h].append(future_mid - base_mid)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Spread Regime Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_spread_regimes(voucher_records, underlying_records):
    """
    For each unique spread value, compute the conditional mean forward return
    of VFE. This gives a complete picture of spread -> return mapping.
    """
    ts_to_idx = {}
    for i, r in enumerate(underlying_records):
        ts_to_idx[r["ts"]] = i

    # Group by spread value
    spread_returns = defaultdict(lambda: {h: [] for h in HORIZONS})

    for vr in voucher_records:
        if vr["spread"] is None:
            continue
        sp = vr["spread"]
        ts = vr["ts"]
        if ts not in ts_to_idx:
            continue
        idx = ts_to_idx[ts]
        base_mid = underlying_records[idx]["mid"]
        if base_mid is None:
            continue
        for h in HORIZONS:
            if idx + h < len(underlying_records):
                future_mid = underlying_records[idx + h]["mid"]
                if future_mid is not None:
                    spread_returns[sp][h].append(future_mid - base_mid)

    return spread_returns


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    output_lines = []

    def pr(s=""):
        output_lines.append(s)
        print(s)

    pr("=" * 100)
    pr("VOUCHER SPREAD SIGNAL ANALYSIS")
    pr(f"Testing {len(VOUCHER_STRIKES)} strikes x {len(HORIZONS)} horizons = {N_TESTS} hypotheses")
    pr(f"Bonferroni alpha per test: {ALPHA_BONFERRONI:.6f} (family-wise alpha=0.01)")
    pr(f"Days analyzed: {DAYS}")
    pr("=" * 100)

    # ── Load all data ────────────────────────────────────────────────────
    all_data = {}
    for day in DAYS:
        pr(f"\nLoading day {day}...")
        all_data[day] = load_prices(day)
        products = list(all_data[day].keys())
        pr(f"  Products: {sorted(products)}")
        pr(f"  Ticks per product: {len(all_data[day].get(UNDERLYING, []))}")

    # ── Section 1: Spread Distributions ──────────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 1: SPREAD DISTRIBUTIONS PER STRIKE PER DAY")
    pr("=" * 100)

    spread_modes = {}  # (strike, day) -> mode
    spread_modes_3day = {}  # strike -> 3-day mode

    for strike in VOUCHER_STRIKES:
        pr(f"\n{'─' * 80}")
        pr(f"  {strike}")
        pr(f"{'─' * 80}")

        all_spreads_3day = []

        for day in DAYS:
            records = all_data[day].get(strike, [])
            dist = compute_spread_distribution(records)

            if dist is None:
                pr(f"  Day {day}: NO DATA")
                continue

            spread_modes[(strike, day)] = dist["mode"]
            all_spreads_3day.extend([r["spread"] for r in records if r["spread"] is not None])

            pr(f"  Day {day}: N={dist['n']}, mode={dist['mode']}, "
               f"mean={dist['mean']:.2f}, std={dist['std']:.2f}, "
               f"range=[{dist['min']}, {dist['max']}]")
            pr(f"    %at_mode={dist['pct_at_mode']:.1f}%, "
               f"%above_mode={dist['pct_above_mode']:.1f}%")

            # Show top spread values
            top_spreads = sorted(dist["distribution"].items(), key=lambda x: -x[1])[:8]
            spread_str = ", ".join(f"{s:.0f}:{c}" for s, c in top_spreads)
            pr(f"    Distribution (top 8): {spread_str}")

        # 3-day mode
        if all_spreads_3day:
            counter_3d = Counter(all_spreads_3day)
            mode_3d = counter_3d.most_common(1)[0][0]
            spread_modes_3day[strike] = mode_3d
            pr(f"  3-DAY MODE: {mode_3d}")

    # ── Section 2: Forward Return Analysis (spread > mode) ───────────────
    pr("\n" + "=" * 100)
    pr("SECTION 2: VFE FORWARD RETURNS AFTER SPREAD-WIDEN EVENTS (spread > 3-day mode)")
    pr("=" * 100)

    # Aggregate across all 3 days for each strike
    all_results = {}  # (strike, horizon) -> stats
    all_widen_tss_by_strike = defaultdict(list)  # for cross-strike correlation

    for strike in VOUCHER_STRIKES:
        if strike not in spread_modes_3day:
            pr(f"\n{strike}: SKIPPED (no mode)")
            continue

        mode = spread_modes_3day[strike]
        pr(f"\n{'─' * 80}")
        pr(f"  {strike} (mode={mode:.0f}, widen threshold > {mode:.0f})")
        pr(f"{'─' * 80}")

        agg_forward = {h: [] for h in HORIZONS}
        total_events = 0

        for day in DAYS:
            voucher_recs = all_data[day].get(strike, [])
            underlying_recs = all_data[day].get(UNDERLYING, [])
            if not voucher_recs or not underlying_recs:
                continue

            events = find_widen_events(voucher_recs, mode)
            total_events += len(events)

            # Track timestamps for cross-strike analysis
            for e in events:
                all_widen_tss_by_strike[strike].append((day, e["ts"]))

            forward = compute_forward_returns(events, underlying_recs, HORIZONS)
            for h in HORIZONS:
                agg_forward[h].extend(forward[h])

        pr(f"  Total widen events (3-day): {total_events}")

        if total_events < MIN_EVENTS:
            pr(f"  INSUFFICIENT EVENTS (min={MIN_EVENTS})")
            continue

        pr(f"\n  {'Horizon':>8} {'N':>6} {'Mean':>8} {'Median':>8} {'Std':>8} "
           f"{'t-stat':>8} {'p≈':>8} {'HitShort':>9} {'HitLong':>8} "
           f"{'p10':>8} {'p90':>8} {'Bonf?':>6}")
        pr(f"  {'─' * 108}")

        for h in HORIZONS:
            stats = compute_signal_stats(agg_forward[h])
            if stats is None:
                pr(f"  {h:>8} {'N/A':>6}")
                continue

            all_results[(strike, h)] = stats

            bonf_flag = "***" if stats["significant_bonferroni"] else ""
            p10_str = f"{stats['p10']:.1f}" if stats["p10"] is not None else "N/A"
            p90_str = f"{stats['p90']:.1f}" if stats["p90"] is not None else "N/A"

            pr(f"  {h:>8} {stats['n']:>6} {stats['mean']:>8.2f} {stats['median']:>8.2f} "
               f"{stats['std']:>8.2f} {stats['t_stat']:>8.2f} {stats['p_approx']:>8.4f} "
               f"{stats['hit_rate_short']:>8.1%} {stats['hit_rate_long']:>8.1%} "
               f"{p10_str:>8} {p90_str:>8} {bonf_flag:>6}")

    # ── Section 3: Unconditional Baseline ────────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 3: VFE UNCONDITIONAL FORWARD RETURNS (BASELINE)")
    pr("=" * 100)

    agg_uncond = {h: [] for h in HORIZONS}
    for day in DAYS:
        underlying_recs = all_data[day].get(UNDERLYING, [])
        uncond = compute_unconditional_returns(underlying_recs, HORIZONS)
        for h in HORIZONS:
            agg_uncond[h].extend(uncond[h])

    pr(f"\n  {'Horizon':>8} {'N':>8} {'Mean':>8} {'Median':>8} {'Std':>8} "
       f"{'HitShort':>9} {'HitLong':>8}")
    pr(f"  {'─' * 70}")

    uncond_stats = {}
    for h in HORIZONS:
        rets = agg_uncond[h]
        if len(rets) < 2:
            continue
        avg = mean(rets)
        med = median(rets)
        sd = stdev(rets)
        hr_s = sum(1 for r in rets if r < 0) / len(rets)
        hr_l = sum(1 for r in rets if r > 0) / len(rets)
        uncond_stats[h] = {"mean": avg, "std": sd, "hit_rate_short": hr_s}

        pr(f"  {h:>8} {len(rets):>8} {avg:>8.2f} {med:>8.2f} {sd:>8.2f} "
           f"{hr_s:>8.1%} {hr_l:>8.1%}")

    # ── Section 4: Consecutive Spread-Widen (cluster signal) ─────────────
    pr("\n" + "=" * 100)
    pr("SECTION 4: CONSECUTIVE SPREAD-WIDEN SIGNAL (cluster = stronger)")
    pr("   vev3.py uses consec >= 3 for VEV_4000. Testing all strikes x thresholds.")
    pr("=" * 100)

    best_consec_signals = []

    for strike in VOUCHER_STRIKES:
        if strike not in spread_modes_3day:
            continue
        mode = spread_modes_3day[strike]

        pr(f"\n  {strike} (mode={mode:.0f}):")

        for ct in CONSEC_THRESHOLDS:
            agg_fwd = {h: [] for h in HORIZONS}
            total_events = 0

            for day in DAYS:
                voucher_recs = all_data[day].get(strike, [])
                underlying_recs = all_data[day].get(UNDERLYING, [])
                if not voucher_recs or not underlying_recs:
                    continue

                events = find_widen_events(voucher_recs, mode)
                fwd, n_evt = compute_consecutive_signal(events, underlying_recs, HORIZONS, ct)
                total_events += n_evt
                for h in HORIZONS:
                    agg_fwd[h].extend(fwd[h])

            if total_events < MIN_EVENTS:
                pr(f"    consec>={ct}: {total_events} events (insufficient)")
                continue

            # Show best horizon for this consec threshold
            best_h = None
            best_t = 0
            for h in HORIZONS:
                stats = compute_signal_stats(agg_fwd[h])
                if stats and abs(stats["t_stat"]) > abs(best_t):
                    best_t = stats["t_stat"]
                    best_h = h
                    best_stats = stats

            if best_h is not None:
                direction = "SHORT" if best_stats["mean"] < 0 else "LONG"
                pr(f"    consec>={ct}: {total_events:>5} events | "
                   f"best h={best_h:>3} mean={best_stats['mean']:>7.2f} "
                   f"t={best_stats['t_stat']:>6.2f} "
                   f"hit_{direction.lower()}={best_stats['hit_rate_short' if direction == 'SHORT' else 'hit_rate_long']:>5.1%} "
                   f"{'*** BONF' if best_stats['significant_bonferroni'] else ''}")

                best_consec_signals.append({
                    "strike": strike,
                    "consec": ct,
                    "horizon": best_h,
                    "n_events": total_events,
                    "mean_return": best_stats["mean"],
                    "t_stat": best_stats["t_stat"],
                    "direction": direction,
                    "hit_rate": best_stats["hit_rate_short"] if direction == "SHORT" else best_stats["hit_rate_long"],
                })

    # ── Section 5: Spread Regime Analysis ────────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 5: SPREAD REGIME ANALYSIS (VFE returns by exact spread value)")
    pr("   For each strike, what does each spread level predict?")
    pr("=" * 100)

    for strike in VOUCHER_STRIKES:
        pr(f"\n  {strike}:")

        all_regime_returns = defaultdict(lambda: {h: [] for h in HORIZONS})

        for day in DAYS:
            voucher_recs = all_data[day].get(strike, [])
            underlying_recs = all_data[day].get(UNDERLYING, [])
            if not voucher_recs or not underlying_recs:
                continue

            regime_rets = analyze_spread_regimes(voucher_recs, underlying_recs)
            for sp, h_rets in regime_rets.items():
                for h, rets in h_rets.items():
                    all_regime_returns[sp][h].extend(rets)

        if not all_regime_returns:
            pr("    NO DATA")
            continue

        # Pick reference horizon = 50 ticks for regime display
        ref_h = 50
        pr(f"    {'Spread':>8} {'N':>6} {'Mean@50':>8} {'Std@50':>8} {'t@50':>8} "
           f"{'Hit%short':>10} {'Mean@100':>9} {'t@100':>8}")
        pr(f"    {'─' * 80}")

        for sp in sorted(all_regime_returns.keys()):
            rets_50 = all_regime_returns[sp].get(ref_h, [])
            rets_100 = all_regime_returns[sp].get(100, [])
            n = len(rets_50)
            if n < 10:
                continue

            avg_50 = mean(rets_50)
            sd_50 = stdev(rets_50) if n > 1 else 0
            t_50 = avg_50 / (sd_50 / sqrt(n)) if sd_50 > 0 and n > 1 else 0
            hr_s = sum(1 for r in rets_50 if r < 0) / n

            avg_100 = mean(rets_100) if len(rets_100) >= 10 else float("nan")
            t_100 = 0
            if len(rets_100) >= 10:
                sd_100 = stdev(rets_100)
                t_100 = avg_100 / (sd_100 / sqrt(len(rets_100))) if sd_100 > 0 else 0

            pr(f"    {sp:>8.0f} {n:>6} {avg_50:>8.2f} {sd_50:>8.2f} {t_50:>8.2f} "
               f"{hr_s:>9.1%} {avg_100:>9.2f} {t_100:>8.2f}")

    # ── Section 6: Cross-Strike Correlation ──────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 6: CROSS-STRIKE WIDEN EVENT CORRELATION")
    pr("   Jaccard similarity of widen-event timestamp sets")
    pr("   High correlation = redundant signals. Low = potential diversification.")
    pr("=" * 100)

    cross_corr = compute_cross_strike_correlation(all_widen_tss_by_strike)

    # Show top 15 most correlated pairs
    sorted_pairs = sorted(cross_corr.items(), key=lambda x: -x[1]["jaccard"])
    pr(f"\n  {'Strike 1':>12} {'Strike 2':>12} {'Jaccard':>8} {'Overlap':>8} {'N1':>6} {'N2':>6}")
    pr(f"  {'─' * 60}")
    for (s1, s2), info in sorted_pairs[:20]:
        pr(f"  {s1:>12} {s2:>12} {info['jaccard']:>8.3f} {info['overlap_count']:>8} "
           f"{info['n1']:>6} {info['n2']:>6}")

    # ── Section 7: Directional Bias (are widen events peak-biased?) ──────
    pr("\n" + "=" * 100)
    pr("SECTION 7: DIRECTIONAL BIAS OF WIDEN EVENTS")
    pr("   What % of spread-widen events occur when VFE > trailing 100-tick avg?")
    pr("   If >60%, the signal is peak-biased (good for shorting).")
    pr("   If <40%, the signal is trough-biased (good for buying).")
    pr("=" * 100)

    for strike in VOUCHER_STRIKES:
        if strike not in spread_modes_3day:
            continue
        mode = spread_modes_3day[strike]

        agg_events = []
        agg_underlying = []

        for day in DAYS:
            voucher_recs = all_data[day].get(strike, [])
            underlying_recs = all_data[day].get(UNDERLYING, [])
            if not voucher_recs or not underlying_recs:
                continue

            events = find_widen_events(voucher_recs, mode)
            agg_events.extend(events)
            # For bias computation, use longest day's underlying
            if len(underlying_recs) > len(agg_underlying):
                agg_underlying = underlying_recs

        # Compute bias per day separately (timestamps reset per day)
        total_above = 0
        total_below = 0
        total_counted = 0

        for day in DAYS:
            voucher_recs = all_data[day].get(strike, [])
            underlying_recs = all_data[day].get(UNDERLYING, [])
            if not voucher_recs or not underlying_recs:
                continue

            events = find_widen_events(voucher_recs, mode)
            bias = compute_directional_bias(events, underlying_recs)
            total_above += bias["above_trailing_avg"]
            total_below += bias["below_trailing_avg"]
            total_counted += bias["total"]

        if total_counted > 0:
            pct_above = total_above / total_counted * 100
            label = "PEAK-BIASED (SHORT)" if pct_above > 55 else (
                "TROUGH-BIASED (LONG)" if pct_above < 45 else "NEUTRAL")
            pr(f"  {strike:>12}: {pct_above:>5.1f}% above trailing avg "
               f"({total_above}/{total_counted}) — {label}")
        else:
            pr(f"  {strike:>12}: NO DATA")

    # ── Section 8: Ranked Summary ────────────────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 8: RANKED SUMMARY — BEST SIGNALS")
    pr("   Ranked by |t-statistic| (strongest statistical evidence)")
    pr("=" * 100)

    ranked = sorted(all_results.items(), key=lambda x: abs(x[1]["t_stat"]), reverse=True)

    pr(f"\n  {'Rank':>4} {'Strike':>12} {'Horizon':>8} {'N':>6} {'Mean':>8} "
       f"{'t-stat':>8} {'p≈':>8} {'HitShort':>9} {'Direction':>10} {'Bonf?':>6}")
    pr(f"  {'─' * 100}")

    for i, ((strike, h), stats) in enumerate(ranked[:30]):
        direction = "SHORT" if stats["mean"] < 0 else "LONG"
        bonf = "***" if stats["significant_bonferroni"] else ""
        hit = stats["hit_rate_short"] if direction == "SHORT" else stats["hit_rate_long"]
        pr(f"  {i + 1:>4} {strike:>12} {h:>8} {stats['n']:>6} {stats['mean']:>8.2f} "
           f"{stats['t_stat']:>8.2f} {stats['p_approx']:>8.4f} {hit:>8.1%} "
           f"{direction:>10} {bonf:>6}")

    # ── Section 9: Consecutive Cluster Ranked ────────────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 9: BEST CONSECUTIVE-CLUSTER SIGNALS")
    pr("   Ranked by |t-statistic|")
    pr("=" * 100)

    best_consec_signals.sort(key=lambda x: abs(x["t_stat"]), reverse=True)

    pr(f"\n  {'Rank':>4} {'Strike':>12} {'Consec>=':>8} {'Horizon':>8} "
       f"{'N':>6} {'Mean':>8} {'t-stat':>8} {'Hit%':>6} {'Dir':>6}")
    pr(f"  {'─' * 80}")

    for i, sig in enumerate(best_consec_signals[:20]):
        pr(f"  {i + 1:>4} {sig['strike']:>12} {sig['consec']:>8} {sig['horizon']:>8} "
           f"{sig['n_events']:>6} {sig['mean_return']:>8.2f} {sig['t_stat']:>8.2f} "
           f"{sig['hit_rate']:>5.1%} {sig['direction']:>6}")

    # ── Section 10: Practical Trading Implications ───────────────────────
    pr("\n" + "=" * 100)
    pr("SECTION 10: PRACTICAL TRADING IMPLICATIONS")
    pr("=" * 100)

    pr("\nKey questions for implementation:")
    pr("  1. Which signals survive Bonferroni correction?")
    bonf_survivors = [(k, v) for k, v in all_results.items() if v["significant_bonferroni"]]
    if bonf_survivors:
        for (strike, h), stats in sorted(bonf_survivors, key=lambda x: abs(x[1]["t_stat"]), reverse=True):
            direction = "SHORT" if stats["mean"] < 0 else "LONG"
            pr(f"     {strike} h={h}: mean={stats['mean']:.2f}, t={stats['t_stat']:.2f}, "
               f"n={stats['n']}, direction={direction}")
    else:
        pr("     NONE survive strict Bonferroni (alpha_per_test={:.6f})".format(ALPHA_BONFERRONI))
        pr("     Using relaxed threshold (p < 0.05 per test):")
        relaxed = [(k, v) for k, v in all_results.items() if v["p_approx"] < 0.05]
        for (strike, h), stats in sorted(relaxed, key=lambda x: abs(x[1]["t_stat"]), reverse=True):
            direction = "SHORT" if stats["mean"] < 0 else "LONG"
            pr(f"     {strike} h={h}: mean={stats['mean']:.2f}, t={stats['t_stat']:.2f}, "
               f"n={stats['n']}, direction={direction}")

    pr("\n  2. Signal-to-noise comparison vs unconditional:")
    for (strike, h), stats in sorted(all_results.items(), key=lambda x: abs(x[1]["t_stat"]), reverse=True)[:10]:
        if h in uncond_stats:
            uncond_mean = uncond_stats[h]["mean"]
            signal_lift = stats["mean"] - uncond_mean
            pr(f"     {strike} h={h}: signal_mean={stats['mean']:.2f}, "
               f"uncond_mean={uncond_mean:.2f}, LIFT={signal_lift:+.2f}")

    pr("\n  3. Signal capacity estimate:")
    pr("     VFE limit = 200 contracts. At 200 units per trade:")
    for (strike, h), stats in sorted(all_results.items(), key=lambda x: abs(x[1]["t_stat"]), reverse=True)[:5]:
        pnl_per_event = abs(stats["mean"]) * 200  # units x avg move
        events_per_day = stats["n"] / len(DAYS)
        daily_pnl = pnl_per_event * events_per_day * stats.get(
            "hit_rate_short" if stats["mean"] < 0 else "hit_rate_long", 0.5)
        pr(f"     {strike} h={h}: ~{events_per_day:.0f} events/day x "
           f"{abs(stats['mean']):.1f} avg move x 200 = "
           f"${pnl_per_event:.0f}/event, ~${daily_pnl:.0f}/day est.")

    pr("\n  4. Additive value with VEV_4000 signal:")
    vev4000_ts = set(all_widen_tss_by_strike.get("VEV_4000", []))
    for strike in VOUCHER_STRIKES:
        if strike == "VEV_4000":
            continue
        other_ts = set(all_widen_tss_by_strike.get(strike, []))
        if not other_ts or not vev4000_ts:
            continue
        overlap = len(vev4000_ts & other_ts)
        unique = len(other_ts - vev4000_ts)
        pr(f"     {strike}: {len(other_ts)} total widen events, "
           f"{overlap} overlap with VEV_4000, {unique} UNIQUE "
           f"({unique / len(other_ts) * 100:.0f}% new information)")

    # ── Save output ──────────────────────────────────────────────────────
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "voucher_spread_signal_results.txt"
    )
    with open(output_path, "w") as f:
        f.write("\n".join(output_lines))
    pr(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
