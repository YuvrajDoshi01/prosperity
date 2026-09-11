#!/usr/bin/env python3
"""
Unconventional Signal Discovery for IMC Prosperity 4 - TOMATOES
Exhaustive search for nonlinear, conditional, sequence, and information-theoretic
predictors of future mid-price changes.

Target: dmid = mid(t+1) - mid(t) and sign(dmid) at horizons t+1, t+2, t+5, t+10, t+20
"""

import numpy as np
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# DATA LOADING
# ============================================================
BASE = Path("/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0")

PRICE_FILES = {
    "day-2": BASE / "prices_round_0_day_-2.csv",
    "day-1": BASE / "prices_round_0_day_-1.csv",
    "day0":  BASE / "prices_round_0_day_0.csv",
}

TRADE_FILES = {
    "day-2": BASE / "trades_round_0_day_-2.csv",
    "day-1": BASE / "trades_round_0_day_-1.csv",
    "day0":  BASE / "trades_round_0_day_0.csv",
}


def load_prices(path):
    df = pd.read_csv(path, sep=";")
    return df


def load_trades(path):
    df = pd.read_csv(path, sep=";")
    return df


def prepare_tomatoes(prices_df):
    """Filter TOMATOES, compute standard features."""
    tom = prices_df[prices_df["product"] == "TOMATOES"].copy()
    tom = tom.sort_values("timestamp").reset_index(drop=True)

    # Basic features
    tom["mid"] = tom["mid_price"]
    tom["dmid"] = tom["mid"].diff()
    tom["spread"] = tom["ask_price_1"] - tom["bid_price_1"]

    # L1 volumes
    tom["bv1"] = tom["bid_volume_1"].astype(float)
    tom["av1"] = tom["ask_volume_1"].astype(float)
    # L2 volumes (may be NaN)
    tom["bv2"] = pd.to_numeric(tom["bid_volume_2"], errors="coerce").fillna(0)
    tom["av2"] = pd.to_numeric(tom["ask_volume_2"], errors="coerce").fillna(0)
    # L2 prices
    tom["bp2"] = pd.to_numeric(tom["bid_price_2"], errors="coerce")
    tom["ap2"] = pd.to_numeric(tom["ask_price_2"], errors="coerce")

    # OBI L1
    tom["obi_l1"] = (tom["bv1"] - tom["av1"]) / (tom["bv1"] + tom["av1"])
    # OBI L2
    total_bid = tom["bv1"] + tom["bv2"]
    total_ask = tom["av1"] + tom["av2"]
    tom["obi_l2"] = (total_bid - total_ask) / (total_bid + total_ask)

    # Gap asymmetry: (bid1 - bid2) - (ask2 - ask1)
    tom["gap_bid"] = tom["bid_price_1"] - tom["bp2"]
    tom["gap_ask"] = tom["ap2"] - tom["ask_price_1"]
    tom["gap_asym"] = tom["gap_bid"] - tom["gap_ask"]

    # Microprice
    tom["microprice"] = (tom["bid_price_1"] * tom["av1"] + tom["ask_price_1"] * tom["bv1"]) / (tom["bv1"] + tom["av1"])
    tom["mp_dev"] = tom["microprice"] - tom["mid"]

    # Lagged dmid
    for lag in range(1, 6):
        tom[f"dmid_lag{lag}"] = tom["dmid"].shift(lag)

    # Spread change
    tom["dspread"] = tom["spread"].diff()

    # Future targets
    for h in [1, 2, 5, 10, 20]:
        tom[f"dmid_t{h}"] = tom["mid"].shift(-h) - tom["mid"]
        tom[f"sign_t{h}"] = np.sign(tom[f"dmid_t{h}"])

    return tom


def prepare_emeralds(prices_df):
    """Filter EMERALDS for cross-product analysis."""
    em = prices_df[prices_df["product"] == "EMERALDS"].copy()
    em = em.sort_values("timestamp").reset_index(drop=True)
    em["mid"] = em["mid_price"]
    em["dmid"] = em["mid"].diff()
    em["spread"] = em["ask_price_1"] - em["bid_price_1"]
    em["bv1"] = em["bid_volume_1"].astype(float)
    em["av1"] = em["ask_volume_1"].astype(float)
    em["obi_l1"] = (em["bv1"] - em["av1"]) / (em["bv1"] + em["av1"])
    return em


# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================
def mi_histogram(x, y, bins=20):
    """Mutual information via histogram (2D)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 50:
        return 0.0
    c_xy, _, _ = np.histogram2d(x, y, bins=bins)
    c_xy = c_xy / c_xy.sum()
    c_x = c_xy.sum(axis=1)
    c_y = c_xy.sum(axis=0)
    # MI = sum p(x,y) * log(p(x,y) / (p(x)*p(y)))
    mi = 0.0
    for i in range(bins):
        for j in range(bins):
            if c_xy[i, j] > 0 and c_x[i] > 0 and c_y[j] > 0:
                mi += c_xy[i, j] * np.log(c_xy[i, j] / (c_x[i] * c_y[j]))
    return mi


def conditional_accuracy(condition_mask, dmid_future, label=""):
    """Given a boolean mask (condition ticks), compute accuracy of sign prediction."""
    n = condition_mask.sum()
    if n < 10:
        return None
    future = dmid_future[condition_mask]
    future = future[np.isfinite(future)]
    if len(future) < 10:
        return None
    n_pos = (future > 0).sum()
    n_neg = (future < 0).sum()
    n_zero = (future == 0).sum()
    n_nonzero = n_pos + n_neg
    if n_nonzero == 0:
        return None
    majority = max(n_pos, n_neg)
    acc = majority / n_nonzero
    direction = "UP" if n_pos > n_neg else "DOWN"
    return {
        "label": label,
        "n_total": int(n),
        "n_nonzero": int(n_nonzero),
        "n_pos": int(n_pos),
        "n_neg": int(n_neg),
        "accuracy": acc,
        "direction": direction,
        "mean_dmid": float(future.mean()),
        "std_dmid": float(future.std()) if len(future) > 1 else 0,
    }


# ============================================================
# MAIN ANALYSIS
# ============================================================
all_findings = []

for day_label, price_path in PRICE_FILES.items():
    print(f"\n{'='*80}")
    print(f"  ANALYZING {day_label}")
    print(f"{'='*80}")

    prices = load_prices(price_path)
    tom = prepare_tomatoes(prices)
    em = prepare_emeralds(prices)
    n_ticks = len(tom)
    print(f"  TOMATOES ticks: {n_ticks}")

    # Load trades
    trade_path = TRADE_FILES[day_label]
    trades_df = load_trades(trade_path)
    tom_trades = trades_df[trades_df["symbol"] == "TOMATOES"].copy()
    print(f"  TOMATOES trades: {len(tom_trades)}")

    findings_day = []

    # ----------------------------------------------------------
    # 1. NONLINEAR TRANSFORMS
    # ----------------------------------------------------------
    print("\n--- 1. NONLINEAR TRANSFORMS ---")

    base_features = {
        "obi_l1": tom["obi_l1"].values,
        "obi_l2": tom["obi_l2"].values,
        "gap_asym": tom["gap_asym"].values,
        "spread": tom["spread"].values,
        "dmid": tom["dmid"].values,
        "mp_dev": tom["mp_dev"].values,
        "dspread": tom["dspread"].values,
    }

    # Nonlinear transforms of each feature
    for fname, fvals in base_features.items():
        fv = fvals.copy()
        transforms = {
            f"{fname}_sq": fv ** 2,
            f"{fname}_cube": fv ** 3,
            f"{fname}_sqrt": np.sqrt(np.abs(fv)) * np.sign(fv),
            f"{fname}_log": np.log1p(np.abs(fv)) * np.sign(fv),
            f"{fname}_abs": np.abs(fv),
        }
        for tname, tvals in transforms.items():
            for h in [1, 2, 5, 10, 20]:
                target = tom[f"dmid_t{h}"].values
                mask = np.isfinite(tvals) & np.isfinite(target)
                if mask.sum() < 50:
                    continue
                r = np.corrcoef(tvals[mask], target[mask])[0, 1]
                if abs(r) > 0.08:
                    findings_day.append({
                        "category": "1_nonlinear",
                        "feature": tname,
                        "horizon": h,
                        "corr": r,
                        "n": int(mask.sum()),
                        "day": day_label,
                    })

    # Interaction terms
    interaction_pairs = [
        ("obi_l1", "spread"), ("obi_l1", "dmid"), ("gap_asym", "spread"),
        ("gap_asym", "dmid"), ("obi_l1", "gap_asym"), ("spread", "dmid"),
        ("mp_dev", "spread"), ("obi_l2", "spread"), ("dspread", "obi_l1"),
        ("dspread", "dmid"), ("mp_dev", "dmid"),
    ]
    for f1, f2 in interaction_pairs:
        v1 = base_features[f1]
        v2 = base_features[f2]
        interact = v1 * v2
        for h in [1, 2, 5, 10, 20]:
            target = tom[f"dmid_t{h}"].values
            mask = np.isfinite(interact) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(interact[mask], target[mask])[0, 1]
            if abs(r) > 0.08:
                findings_day.append({
                    "category": "1_interaction",
                    "feature": f"{f1}*{f2}",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # Momentum ratio: dmid(t) / dmid(t-1)
    dmid_prev = tom["dmid"].shift(1).values
    mom_ratio = np.where(np.abs(dmid_prev) > 0.01, tom["dmid"].values / dmid_prev, np.nan)
    for h in [1, 2, 5, 10, 20]:
        target = tom[f"dmid_t{h}"].values
        mask = np.isfinite(mom_ratio) & np.isfinite(target)
        if mask.sum() < 50:
            r = np.corrcoef(mom_ratio[mask], target[mask])[0, 1] if mask.sum() > 2 else 0
            if abs(r) > 0.08:
                findings_day.append({
                    "category": "1_nonlinear",
                    "feature": "momentum_ratio",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # |dmid| predicting future direction
    abs_dmid = np.abs(tom["dmid"].values)
    for h in [1, 2, 5, 10, 20]:
        target = tom[f"dmid_t{h}"].values
        mask = np.isfinite(abs_dmid) & np.isfinite(target) & (abs_dmid > 0)
        if mask.sum() < 50:
            continue
        r = np.corrcoef(abs_dmid[mask], target[mask])[0, 1]
        if abs(r) > 0.05:
            findings_day.append({
                "category": "1_nonlinear",
                "feature": "|dmid|_predicts_future",
                "horizon": h,
                "corr": r,
                "n": int(mask.sum()),
                "day": day_label,
            })

    n_nl = sum(1 for f in findings_day if f["category"].startswith("1_"))
    print(f"  Found {n_nl} nonlinear signals with |r| > 0.08")

    # ----------------------------------------------------------
    # 2. CONDITIONAL PATTERNS
    # ----------------------------------------------------------
    print("\n--- 2. CONDITIONAL PATTERNS ---")

    spread = tom["spread"].values
    dmid = tom["dmid"].values

    # After spread change
    spread_changed = tom["dspread"].values != 0
    for h in [1, 2, 5]:
        res = conditional_accuracy(
            spread_changed & np.isfinite(tom[f"dmid_t{h}"].values),
            tom[f"dmid_t{h}"].values,
            f"after_spread_change_t{h}"
        )
        if res and (res["accuracy"] > 0.52 or abs(res["mean_dmid"]) > 0.05):
            findings_day.append({
                "category": "2_conditional",
                "feature": res["label"],
                "horizon": h,
                "accuracy": res["accuracy"],
                "direction": res["direction"],
                "mean_dmid": res["mean_dmid"],
                "n": res["n_nonzero"],
                "day": day_label,
            })

    # Wide -> narrow spread transition
    prev_spread = pd.Series(spread).shift(1).values
    wide_to_narrow = (prev_spread >= 13) & (spread <= 9)
    narrow_to_wide = (prev_spread <= 9) & (spread >= 13)

    for h in [1, 2, 5, 10]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(wide_to_narrow, "wide_to_narrow"), (narrow_to_wide, "narrow_to_wide")]:
            mask = cond & np.isfinite(target)
            res = conditional_accuracy(mask, target, f"{cname}_t{h}")
            if res and (res["accuracy"] > 0.52):
                findings_day.append({
                    "category": "2_conditional",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # After 2+ consecutive same-direction moves
    dmid_sign = np.sign(dmid)
    consec_same = np.zeros(n_ticks)
    for i in range(2, n_ticks):
        if dmid_sign[i] == dmid_sign[i - 1] and dmid_sign[i] != 0:
            consec_same[i] = consec_same[i - 1] + 1
        else:
            consec_same[i] = 0

    for streak_min in [2, 3, 5]:
        for h in [1, 2, 5]:
            mask = (consec_same >= streak_min)
            # Separate by direction
            for direction, dsign in [("up_streak", 1), ("down_streak", -1)]:
                cond = mask & (dmid_sign == dsign) & np.isfinite(tom[f"dmid_t{h}"].values)
                res = conditional_accuracy(cond, tom[f"dmid_t{h}"].values,
                                           f"{direction}_{streak_min}+_t{h}")
                if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.1):
                    findings_day.append({
                        "category": "2_conditional",
                        "feature": res["label"],
                        "horizon": h,
                        "accuracy": res["accuracy"],
                        "direction": res["direction"],
                        "mean_dmid": res["mean_dmid"],
                        "n": res["n_nonzero"],
                        "day": day_label,
                    })

    # After big move (|dmid| >= 2)
    for thresh in [1.5, 2.0, 2.5, 3.0]:
        big_up = dmid >= thresh
        big_down = dmid <= -thresh
        for h in [1, 2, 5, 10]:
            target = tom[f"dmid_t{h}"].values
            for cond, cname in [(big_up, f"after_big_up_{thresh}"), (big_down, f"after_big_down_{thresh}")]:
                res = conditional_accuracy(cond & np.isfinite(target), target, f"{cname}_t{h}")
                if res and (res["accuracy"] > 0.52 or abs(res["mean_dmid"]) > 0.1):
                    findings_day.append({
                        "category": "2_conditional",
                        "feature": res["label"],
                        "horizon": h,
                        "accuracy": res["accuracy"],
                        "direction": res["direction"],
                        "mean_dmid": res["mean_dmid"],
                        "n": res["n_nonzero"],
                        "day": day_label,
                    })

    # Asymmetric L1 quote
    vol_asym = tom["bv1"].values != tom["av1"].values
    bid_heavy = (tom["bv1"].values > tom["av1"].values) & vol_asym
    ask_heavy = (tom["av1"].values > tom["bv1"].values) & vol_asym
    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(bid_heavy, f"bid_heavy_l1_t{h}"), (ask_heavy, f"ask_heavy_l1_t{h}")]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and res["accuracy"] > 0.52:
                findings_day.append({
                    "category": "2_conditional",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    n_cond = sum(1 for f in findings_day if f["category"].startswith("2_"))
    print(f"  Found {n_cond} conditional signals")

    # ----------------------------------------------------------
    # 3. SEQUENCE PATTERNS (Hidden Markov-like)
    # ----------------------------------------------------------
    print("\n--- 3. SEQUENCE PATTERNS ---")

    # Encode last 3 dmid signs as pattern
    s0 = np.sign(tom["dmid"].values)
    s1 = np.sign(tom["dmid"].shift(1).values)
    s2 = np.sign(tom["dmid"].shift(2).values)

    # Map sign to char
    def sign_char(s):
        return np.where(s > 0, "+", np.where(s < 0, "-", "0"))

    sc0 = sign_char(s0)
    sc1 = sign_char(s1)
    sc2 = sign_char(s2)
    pattern_3 = np.char.add(np.char.add(sc2, sc1), sc0)

    unique_patterns = np.unique(pattern_3[3:])  # skip first 3 NaN-derived
    print(f"  Unique 3-tick sign patterns: {len(unique_patterns)}")

    for pat in unique_patterns:
        mask = (pattern_3 == pat)
        if mask.sum() < 20:
            continue
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            cond = mask & np.isfinite(target)
            res = conditional_accuracy(cond, target, f"sign_pattern_{pat}_t{h}")
            if res and res["accuracy"] > 0.58:
                findings_day.append({
                    "category": "3_sequence",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Encode last 3 spread states: bucket into "narrow" (<10) and "wide" (>=10)
    spread_state = np.where(spread < 10, "N", "W")
    ss0 = spread_state
    ss1 = np.roll(spread_state, 1)
    ss2 = np.roll(spread_state, 2)
    spread_pattern = np.char.add(np.char.add(ss2, ss1), ss0)

    for pat in np.unique(spread_pattern[3:]):
        mask = (spread_pattern == pat)
        if mask.sum() < 20:
            continue
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            cond = mask & np.isfinite(target)
            res = conditional_accuracy(cond, target, f"spread_pattern_{pat}_t{h}")
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.2):
                findings_day.append({
                    "category": "3_sequence",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Run length analysis
    run_lengths = np.zeros(n_ticks)
    for i in range(1, n_ticks):
        if s0[i] != 0 and s0[i] == s0[i - 1]:
            run_lengths[i] = run_lengths[i - 1] + 1

    for rl_min in [3, 5, 7, 10]:
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            # After long UP run
            cond_up = (run_lengths >= rl_min) & (s0 > 0) & np.isfinite(target)
            res = conditional_accuracy(cond_up, target, f"run_up_{rl_min}+_t{h}")
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.1):
                findings_day.append({
                    "category": "3_sequence",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })
            # After long DOWN run
            cond_down = (run_lengths >= rl_min) & (s0 < 0) & np.isfinite(target)
            res = conditional_accuracy(cond_down, target, f"run_down_{rl_min}+_t{h}")
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.1):
                findings_day.append({
                    "category": "3_sequence",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Combined pattern: (dspread_sign, dmid_sign) transitions
    dspread_sign = np.sign(tom["dspread"].values)
    combo = np.char.add(
        np.char.add(sign_char(dspread_sign), "_"),
        sign_char(s0)
    )
    for pat in np.unique(combo[2:]):
        mask = (combo == pat)
        if mask.sum() < 20:
            continue
        for h in [1, 2]:
            target = tom[f"dmid_t{h}"].values
            cond = mask & np.isfinite(target)
            res = conditional_accuracy(cond, target, f"dspread_dmid_{pat}_t{h}")
            if res and res["accuracy"] > 0.55:
                findings_day.append({
                    "category": "3_sequence",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    n_seq = sum(1 for f in findings_day if f["category"].startswith("3_"))
    print(f"  Found {n_seq} sequence signals")

    # ----------------------------------------------------------
    # 4. VOLUME PATTERN ANALYSIS
    # ----------------------------------------------------------
    print("\n--- 4. VOLUME PATTERNS ---")

    # Volume changes
    tom["dbv1"] = tom["bv1"].diff()
    tom["dav1"] = tom["av1"].diff()
    tom["dbv2"] = tom["bv2"].diff()
    tom["dav2"] = tom["av2"].diff()
    tom["total_vol"] = tom["bv1"] + tom["av1"] + tom["bv2"] + tom["av2"]
    tom["dtotal_vol"] = tom["total_vol"].diff()

    # Volume acceleration (second difference)
    tom["vol_accel"] = tom["dtotal_vol"].diff()

    # L2/L1 ratio change
    tom["l2l1_ratio_bid"] = tom["bv2"] / tom["bv1"].replace(0, np.nan)
    tom["l2l1_ratio_ask"] = tom["av2"] / tom["av1"].replace(0, np.nan)
    tom["dl2l1_bid"] = tom["l2l1_ratio_bid"].diff()
    tom["dl2l1_ask"] = tom["l2l1_ratio_ask"].diff()

    # Bid volume lead: did bid volume change when ask didn't?
    tom["bid_vol_lead"] = (tom["dbv1"].abs() > 0) & (tom["dav1"].abs() == 0)
    tom["ask_vol_lead"] = (tom["dav1"].abs() > 0) & (tom["dbv1"].abs() == 0)

    vol_features = {
        "dbv1": tom["dbv1"].values,
        "dav1": tom["dav1"].values,
        "dtotal_vol": tom["dtotal_vol"].values,
        "vol_accel": tom["vol_accel"].values,
        "dl2l1_bid": tom["dl2l1_bid"].values,
        "dl2l1_ask": tom["dl2l1_ask"].values,
        "dbv1-dav1": (tom["dbv1"] - tom["dav1"]).values,
    }

    for fname, fvals in vol_features.items():
        for h in [1, 2, 5, 10]:
            target = tom[f"dmid_t{h}"].values
            mask = np.isfinite(fvals) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(fvals[mask], target[mask])[0, 1]
            if abs(r) > 0.06:
                findings_day.append({
                    "category": "4_volume",
                    "feature": fname,
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # Consecutive volume increases (3 ticks)
    bv1_up3 = (tom["dbv1"].values > 0) & (tom["dbv1"].shift(1).values > 0) & (tom["dbv1"].shift(2).values > 0)
    av1_up3 = (tom["dav1"].values > 0) & (tom["dav1"].shift(1).values > 0) & (tom["dav1"].shift(2).values > 0)
    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(bv1_up3, f"bv1_up_3x_t{h}"), (av1_up3, f"av1_up_3x_t{h}")]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and res["accuracy"] > 0.52:
                findings_day.append({
                    "category": "4_volume",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Bid volume lead predicts direction?
    for h in [1, 2]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(tom["bid_vol_lead"].values, f"bid_vol_lead_t{h}"),
                            (tom["ask_vol_lead"].values, f"ask_vol_lead_t{h}")]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and res["accuracy"] > 0.52:
                findings_day.append({
                    "category": "4_volume",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    n_vol = sum(1 for f in findings_day if f["category"].startswith("4_"))
    print(f"  Found {n_vol} volume pattern signals")

    # ----------------------------------------------------------
    # 5. CROSS-PRODUCT (EMERALDS <-> TOMATOES)
    # ----------------------------------------------------------
    print("\n--- 5. CROSS-PRODUCT ANALYSIS ---")

    # Merge on timestamp
    merged = pd.merge(
        tom[["timestamp", "mid", "dmid", "spread", "obi_l1"] + [f"dmid_t{h}" for h in [1, 2, 5, 10, 20]]],
        em[["timestamp", "mid", "dmid", "spread", "obi_l1"]].rename(
            columns={"mid": "em_mid", "dmid": "em_dmid", "spread": "em_spread", "obi_l1": "em_obi_l1"}
        ),
        on="timestamp",
        how="inner"
    )

    # Unconditional cross-correlation
    for h in [1, 2, 5]:
        target = merged[f"dmid_t{h}"].values
        for feat, fname in [("em_dmid", "em_dmid"), ("em_obi_l1", "em_obi_l1")]:
            fvals = merged[feat].values
            mask = np.isfinite(fvals) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(fvals[mask], target[mask])[0, 1]
            if abs(r) > 0.05:
                findings_day.append({
                    "category": "5_cross",
                    "feature": f"{fname}_predicts_tom_t{h}",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # Conditional: when EM spread narrows, does TOM move?
    em_spread_narrow = merged["em_spread"].values <= 18  # EM narrow = 16
    for h in [1, 2, 5]:
        target = merged[f"dmid_t{h}"].values
        cond = em_spread_narrow & np.isfinite(target)
        res = conditional_accuracy(cond, target, f"em_narrow_spread_tom_t{h}")
        if res and (res["accuracy"] > 0.52 or abs(res["mean_dmid"]) > 0.05):
            findings_day.append({
                "category": "5_cross",
                "feature": res["label"],
                "horizon": h,
                "accuracy": res["accuracy"],
                "direction": res["direction"],
                "mean_dmid": res["mean_dmid"],
                "n": res["n_nonzero"],
                "day": day_label,
            })

    # EM dmid conditional on EM spread state
    for em_state, em_cond in [("em_narrow", merged["em_spread"].values <= 18),
                               ("em_wide", merged["em_spread"].values > 18)]:
        em_dmid_cond = merged["em_dmid"].values
        for h in [1, 2]:
            target = merged[f"dmid_t{h}"].values
            mask = em_cond & np.isfinite(em_dmid_cond) & np.isfinite(target) & (em_dmid_cond != 0)
            if mask.sum() < 20:
                continue
            r = np.corrcoef(em_dmid_cond[mask], target[mask])[0, 1]
            if abs(r) > 0.08:
                findings_day.append({
                    "category": "5_cross",
                    "feature": f"em_dmid_given_{em_state}_tom_t{h}",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    n_cross = sum(1 for f in findings_day if f["category"].startswith("5_"))
    print(f"  Found {n_cross} cross-product signals")

    # ----------------------------------------------------------
    # 6. TIME-OF-DAY / TICK POSITION
    # ----------------------------------------------------------
    print("\n--- 6. TIME-OF-DAY PATTERNS ---")

    tom["tick_idx"] = np.arange(n_ticks)
    tom["decile"] = pd.qcut(tom["tick_idx"], 10, labels=False)

    # Average dmid per decile
    decile_stats = tom.groupby("decile")["dmid"].agg(["mean", "std", "count"])
    print(f"  Decile drift stats:")
    for dec, row in decile_stats.iterrows():
        if abs(row["mean"]) > 0.01:
            print(f"    Decile {dec}: mean_dmid={row['mean']:.4f}, n={int(row['count'])}")

    # Cumulative drift: first half vs second half
    half = n_ticks // 2
    first_half_drift = tom["dmid"].iloc[1:half].mean()
    second_half_drift = tom["dmid"].iloc[half:].mean()
    print(f"  First half drift: {first_half_drift:.4f}, Second half drift: {second_half_drift:.4f}")

    # Tick position as linear feature
    tick_norm = tom["tick_idx"].values / n_ticks
    for h in [1, 5, 20]:
        target = tom[f"dmid_t{h}"].values
        mask = np.isfinite(target)
        if mask.sum() < 50:
            continue
        r = np.corrcoef(tick_norm[mask], target[mask])[0, 1]
        if abs(r) > 0.03:
            findings_day.append({
                "category": "6_time",
                "feature": f"tick_position_t{h}",
                "horizon": h,
                "corr": r,
                "n": int(mask.sum()),
                "day": day_label,
            })

    # Volatility clustering: autocorrelation of |dmid|
    abs_dmid_series = pd.Series(np.abs(tom["dmid"].values))
    vol_ac = [abs_dmid_series.autocorr(lag=i) for i in range(1, 11)]
    print(f"  |dmid| autocorrelation (lags 1-10): {[f'{v:.3f}' for v in vol_ac]}")

    # High volatility regime: |dmid| EMA
    tom["vol_ema5"] = abs_dmid_series.ewm(span=5).mean().values
    tom["vol_ema10"] = abs_dmid_series.ewm(span=10).mean().values

    for vname in ["vol_ema5", "vol_ema10"]:
        for h in [1, 2, 5, 10]:
            target = tom[f"dmid_t{h}"].values
            fvals = tom[vname].values
            mask = np.isfinite(fvals) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(fvals[mask], target[mask])[0, 1]
            if abs(r) > 0.05:
                findings_day.append({
                    "category": "6_time",
                    "feature": f"{vname}_predicts_dmid_t{h}",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # After low-vol periods (5 ticks of |dmid|<=0.25)
    low_vol_5 = np.zeros(n_ticks, dtype=bool)
    abs_dm = np.abs(tom["dmid"].values)
    for i in range(5, n_ticks):
        if np.all(abs_dm[i - 4:i + 1] <= 0.25):
            low_vol_5[i] = True

    for h in [1, 2, 5, 10]:
        target = tom[f"dmid_t{h}"].values
        cond = low_vol_5 & np.isfinite(target)
        if cond.sum() < 10:
            continue
        # Check if low-vol predicts BIGGER absolute move
        future_abs = np.abs(target[cond])
        baseline_abs = np.abs(target[np.isfinite(target)])
        if len(future_abs) > 0 and len(baseline_abs) > 0:
            ratio = future_abs.mean() / baseline_abs.mean() if baseline_abs.mean() > 0 else 1
            if abs(ratio - 1) > 0.1:
                findings_day.append({
                    "category": "6_time",
                    "feature": f"low_vol_5tick_abs_ratio_t{h}",
                    "horizon": h,
                    "vol_ratio": ratio,
                    "n": int(cond.sum()),
                    "mean_abs_future": float(future_abs.mean()),
                    "baseline_abs": float(baseline_abs.mean()),
                    "day": day_label,
                })

    n_time = sum(1 for f in findings_day if f["category"].startswith("6_"))
    print(f"  Found {n_time} time/volatility signals")

    # ----------------------------------------------------------
    # 7. BOOK PRESSURE DYNAMICS
    # ----------------------------------------------------------
    print("\n--- 7. BOOK PRESSURE DYNAMICS ---")

    # Rate of change of OBI
    tom["dobi_l1"] = tom["obi_l1"].diff()
    tom["dobi_l2"] = tom["obi_l2"].diff()

    # OBI acceleration
    tom["obi_accel"] = tom["dobi_l1"].diff()

    # Persistent OBI: same sign for N ticks
    obi_sign = np.sign(tom["obi_l1"].values)
    obi_streak = np.zeros(n_ticks)
    for i in range(1, n_ticks):
        if obi_sign[i] != 0 and obi_sign[i] == obi_sign[i - 1]:
            obi_streak[i] = obi_streak[i - 1] + 1
        else:
            obi_streak[i] = 0
    tom["obi_streak"] = obi_streak

    book_features = {
        "dobi_l1": tom["dobi_l1"].values,
        "dobi_l2": tom["dobi_l2"].values,
        "obi_accel": tom["obi_accel"].values,
        "obi_streak": tom["obi_streak"].values,
        "obi_streak_signed": tom["obi_streak"].values * obi_sign,
    }

    for fname, fvals in book_features.items():
        for h in [1, 2, 5, 10]:
            target = tom[f"dmid_t{h}"].values
            mask = np.isfinite(fvals) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(fvals[mask], target[mask])[0, 1]
            if abs(r) > 0.06:
                findings_day.append({
                    "category": "7_book_pressure",
                    "feature": fname,
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # Persistent OBI (streak >= 5) conditional accuracy
    for streak_thresh in [3, 5, 7]:
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            cond_pos = (obi_streak >= streak_thresh) & (obi_sign > 0) & np.isfinite(target)
            res = conditional_accuracy(cond_pos, target, f"obi_pos_streak_{streak_thresh}+_t{h}")
            if res and res["accuracy"] > 0.55:
                findings_day.append({
                    "category": "7_book_pressure",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })
            cond_neg = (obi_streak >= streak_thresh) & (obi_sign < 0) & np.isfinite(target)
            res = conditional_accuracy(cond_neg, target, f"obi_neg_streak_{streak_thresh}+_t{h}")
            if res and res["accuracy"] > 0.55:
                findings_day.append({
                    "category": "7_book_pressure",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Book thickness: does L2 appearing/disappearing predict?
    has_l2_bid = tom["bv2"].values > 0
    has_l2_ask = tom["av2"].values > 0
    l2_bid_appears = (~np.roll(has_l2_bid, 1)) & has_l2_bid
    l2_bid_disappears = np.roll(has_l2_bid, 1) & (~has_l2_bid)
    l2_ask_appears = (~np.roll(has_l2_ask, 1)) & has_l2_ask
    l2_ask_disappears = np.roll(has_l2_ask, 1) & (~has_l2_ask)

    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [
            (l2_bid_appears, f"l2_bid_appears_t{h}"),
            (l2_bid_disappears, f"l2_bid_disappears_t{h}"),
            (l2_ask_appears, f"l2_ask_appears_t{h}"),
            (l2_ask_disappears, f"l2_ask_disappears_t{h}"),
        ]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and res["accuracy"] > 0.52:
                findings_day.append({
                    "category": "7_book_pressure",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Price level clustering / support-resistance
    mid_vals = tom["mid"].values
    mid_rounded = np.round(mid_vals).astype(int)
    from collections import Counter
    level_counts = Counter(mid_rounded)
    top_levels = [lv for lv, cnt in level_counts.most_common(10)]
    print(f"  Top 10 mid-price levels: {top_levels}")

    # At frequently visited levels, is there mean reversion?
    for lv in top_levels[:5]:
        at_level = (np.abs(mid_vals - lv) <= 0.5)
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            cond = at_level & np.isfinite(target)
            res = conditional_accuracy(cond, target, f"at_level_{lv}_t{h}")
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.1):
                findings_day.append({
                    "category": "7_book_pressure",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    n_book = sum(1 for f in findings_day if f["category"].startswith("7_"))
    print(f"  Found {n_book} book pressure signals")

    # ----------------------------------------------------------
    # 8. MUTUAL INFORMATION
    # ----------------------------------------------------------
    print("\n--- 8. MUTUAL INFORMATION ---")

    mi_features = {
        "obi_l1": tom["obi_l1"].values,
        "obi_l2": tom["obi_l2"].values,
        "gap_asym": tom["gap_asym"].values,
        "spread": tom["spread"].values,
        "dmid": tom["dmid"].values,
        "mp_dev": tom["mp_dev"].values,
        "dobi_l1": tom["dobi_l1"].values,
        "obi_streak_signed": tom["obi_streak"].values * obi_sign,
        "vol_ema5": tom["vol_ema5"].values,
        "abs_dmid": np.abs(tom["dmid"].values),
    }

    target_t1 = tom["dmid_t1"].values
    mi_results = {}
    for fname, fvals in mi_features.items():
        mask = np.isfinite(fvals) & np.isfinite(target_t1)
        if mask.sum() < 100:
            continue
        mi_val = mi_histogram(fvals[mask], target_t1[mask], bins=30)
        mi_results[fname] = mi_val
        pearson_r = np.corrcoef(fvals[mask], target_t1[mask])[0, 1]
        findings_day.append({
            "category": "8_mutual_info",
            "feature": fname,
            "horizon": 1,
            "mi": mi_val,
            "pearson_r": pearson_r,
            "n": int(mask.sum()),
            "day": day_label,
        })

    mi_sorted = sorted(mi_results.items(), key=lambda x: -x[1])
    print(f"  MI ranking (t+1):")
    for fname, miv in mi_sorted[:10]:
        print(f"    {fname}: MI={miv:.4f}")

    # Also compute MI for nonlinear transforms to see if they add info
    nl_mi = {}
    for fname in ["obi_l1", "gap_asym", "spread"]:
        fvals = mi_features[fname]
        for tname, tfunc in [("sq", lambda x: x**2), ("abs", np.abs), ("cube", lambda x: x**3)]:
            tvals = tfunc(fvals)
            mask = np.isfinite(tvals) & np.isfinite(target_t1)
            if mask.sum() < 100:
                continue
            mi_val = mi_histogram(tvals[mask], target_t1[mask], bins=30)
            nl_mi[f"{fname}_{tname}"] = mi_val

    print(f"  MI for nonlinear transforms:")
    for fname, miv in sorted(nl_mi.items(), key=lambda x: -x[1])[:5]:
        print(f"    {fname}: MI={miv:.4f}")

    # ----------------------------------------------------------
    # 9. RUNS AND STREAKS
    # ----------------------------------------------------------
    print("\n--- 9. RUNS AND STREAKS ---")

    # OBI streak length predicting continuation
    for streak_thresh in [3, 5, 8, 10]:
        cond = (obi_streak >= streak_thresh) & np.isfinite(tom["dmid_t1"].values)
        if cond.sum() < 10:
            continue
        # Does the OBI direction predict next dmid?
        obi_dir = obi_sign[cond]
        next_dm = tom["dmid_t1"].values[cond]
        mask2 = np.isfinite(next_dm) & (obi_dir != 0)
        if mask2.sum() < 10:
            continue
        correct = (np.sign(next_dm[mask2]) == obi_dir[mask2]).sum()
        acc = correct / mask2.sum()
        findings_day.append({
            "category": "9_streaks",
            "feature": f"obi_streak_{streak_thresh}+_direction",
            "horizon": 1,
            "accuracy": acc,
            "n": int(mask2.sum()),
            "day": day_label,
        })
        if acc > 0.5:
            print(f"  OBI streak >= {streak_thresh}: {acc:.1%} direction accuracy (n={mask2.sum()})")

    # Consecutive same spread
    spread_streak = np.zeros(n_ticks)
    for i in range(1, n_ticks):
        if spread[i] == spread[i - 1]:
            spread_streak[i] = spread_streak[i - 1] + 1

    # Does spread streak BREAK predict dmid?
    spread_break = (spread_streak == 0) & (np.roll(spread_streak, 1) >= 3)
    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        cond = spread_break & np.isfinite(target)
        res = conditional_accuracy(cond, target, f"spread_streak_break_t{h}")
        if res and res["accuracy"] > 0.52:
            findings_day.append({
                "category": "9_streaks",
                "feature": res["label"],
                "horizon": h,
                "accuracy": res["accuracy"],
                "direction": res["direction"],
                "mean_dmid": res["mean_dmid"],
                "n": res["n_nonzero"],
                "day": day_label,
            })

    # Time since last spread change
    time_since_spread_change = np.zeros(n_ticks)
    for i in range(1, n_ticks):
        if tom["dspread"].values[i] != 0:
            time_since_spread_change[i] = 0
        else:
            time_since_spread_change[i] = time_since_spread_change[i - 1] + 1

    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        mask = np.isfinite(target) & (time_since_spread_change > 0)
        if mask.sum() < 50:
            continue
        r = np.corrcoef(time_since_spread_change[mask], target[mask])[0, 1]
        if abs(r) > 0.05:
            findings_day.append({
                "category": "9_streaks",
                "feature": f"time_since_spread_change_t{h}",
                "horizon": h,
                "corr": r,
                "n": int(mask.sum()),
                "day": day_label,
            })

    n_streak = sum(1 for f in findings_day if f["category"].startswith("9_"))
    print(f"  Found {n_streak} streak signals")

    # ----------------------------------------------------------
    # 10. MARKET TRADES ANALYSIS
    # ----------------------------------------------------------
    print("\n--- 10. MARKET TRADES ---")

    if len(tom_trades) > 0:
        print(f"  Total TOMATOES trades: {len(tom_trades)}")
        print(f"  Trade columns: {list(tom_trades.columns)}")
        print(f"  Price range: {tom_trades['price'].min()} - {tom_trades['price'].max()}")

        # Merge trade info onto price ticks
        # For each tick, find the most recent trade
        trade_ts = tom_trades["timestamp"].values
        trade_prices = tom_trades["price"].values
        trade_qtys = tom_trades["quantity"].values

        tom_ts = tom["timestamp"].values
        tom_mid = tom["mid"].values

        # Last trade info for each tick
        last_trade_side = np.full(n_ticks, np.nan)  # +1 if at ask, -1 if at bid
        last_trade_qty = np.full(n_ticks, np.nan)
        time_since_trade = np.full(n_ticks, np.nan)

        trade_idx = 0
        for i in range(n_ticks):
            while trade_idx < len(trade_ts) and trade_ts[trade_idx] <= tom_ts[i]:
                # Determine side: trade at ask = buy (aggressor), at bid = sell
                mid_at_trade = tom_mid[i]
                if trade_prices[trade_idx] >= mid_at_trade:
                    last_trade_side[i] = 1  # bought at/above mid
                else:
                    last_trade_side[i] = -1  # sold at/below mid
                last_trade_qty[i] = trade_qtys[trade_idx]
                time_since_trade[i] = 0
                trade_idx += 1
            if i > 0 and np.isfinite(time_since_trade[i - 1]):
                if np.isnan(time_since_trade[i]) or time_since_trade[i] != 0:
                    time_since_trade[i] = time_since_trade[i - 1] + 1
                    last_trade_side[i] = last_trade_side[i - 1] if np.isnan(last_trade_side[i]) else last_trade_side[i]
                    last_trade_qty[i] = last_trade_qty[i - 1] if np.isnan(last_trade_qty[i]) else last_trade_qty[i]

        tom["last_trade_side"] = last_trade_side
        tom["last_trade_qty"] = last_trade_qty
        tom["time_since_trade"] = time_since_trade

        trade_features = {
            "last_trade_side": last_trade_side,
            "last_trade_qty": last_trade_qty,
            "time_since_trade": time_since_trade,
            "trade_side_x_qty": last_trade_side * last_trade_qty,
        }

        for fname, fvals in trade_features.items():
            for h in [1, 2, 5, 10]:
                target = tom[f"dmid_t{h}"].values
                mask = np.isfinite(fvals) & np.isfinite(target)
                if mask.sum() < 30:
                    continue
                r = np.corrcoef(fvals[mask], target[mask])[0, 1]
                if abs(r) > 0.05:
                    findings_day.append({
                        "category": "10_trades",
                        "feature": fname,
                        "horizon": h,
                        "corr": r,
                        "n": int(mask.sum()),
                        "day": day_label,
                    })

        # Trade at bid vs ask: conditional next move
        at_bid = (last_trade_side == -1) & (time_since_trade <= 2)
        at_ask = (last_trade_side == 1) & (time_since_trade <= 2)
        for h in [1, 2, 5, 10]:
            target = tom[f"dmid_t{h}"].values
            for cond, cname in [(at_bid, f"trade_at_bid_t{h}"), (at_ask, f"trade_at_ask_t{h}")]:
                res = conditional_accuracy(cond & np.isfinite(target), target, cname)
                if res and res["accuracy"] > 0.52:
                    findings_day.append({
                        "category": "10_trades",
                        "feature": res["label"],
                        "horizon": h,
                        "accuracy": res["accuracy"],
                        "direction": res["direction"],
                        "mean_dmid": res["mean_dmid"],
                        "n": res["n_nonzero"],
                        "day": day_label,
                    })

        # Large trade size predicts bigger move?
        big_trade = (last_trade_qty >= 4) & (time_since_trade <= 2)
        small_trade = (last_trade_qty <= 2) & (time_since_trade <= 2)
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            for cond, cname in [(big_trade, f"big_trade_t{h}"), (small_trade, f"small_trade_t{h}")]:
                future_abs = np.abs(target[cond & np.isfinite(target)])
                baseline_abs = np.abs(target[np.isfinite(target)])
                if len(future_abs) > 10 and baseline_abs.mean() > 0:
                    ratio = future_abs.mean() / baseline_abs.mean()
                    if abs(ratio - 1) > 0.1:
                        findings_day.append({
                            "category": "10_trades",
                            "feature": f"{cname}_vol_ratio",
                            "horizon": h,
                            "vol_ratio": ratio,
                            "n": int(len(future_abs)),
                            "day": day_label,
                        })
    else:
        print("  No TOMATOES trades found!")

    n_trades = sum(1 for f in findings_day if f["category"].startswith("10_"))
    print(f"  Found {n_trades} trade signals")

    # ----------------------------------------------------------
    # BONUS: COMBINED SIGNALS
    # ----------------------------------------------------------
    print("\n--- BONUS: COMBINED/REGIME SIGNALS ---")

    # OBI + spread state interaction
    obi_positive = tom["obi_l1"].values > 0.1
    obi_negative = tom["obi_l1"].values < -0.1
    spread_narrow = tom["spread"].values <= 9
    spread_wide = tom["spread"].values >= 13

    combos = {
        "obi_pos+narrow": obi_positive & spread_narrow,
        "obi_neg+narrow": obi_negative & spread_narrow,
        "obi_pos+wide": obi_positive & spread_wide,
        "obi_neg+wide": obi_negative & spread_wide,
    }

    for cname, cond in combos.items():
        for h in [1, 2, 5]:
            target = tom[f"dmid_t{h}"].values
            res = conditional_accuracy(cond & np.isfinite(target), target, f"{cname}_t{h}")
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.15):
                findings_day.append({
                    "category": "bonus_combined",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # Price deviation from EMA as mean-reversion signal
    mid_ema20 = pd.Series(tom["mid"].values).ewm(span=20).mean().values
    mid_ema50 = pd.Series(tom["mid"].values).ewm(span=50).mean().values
    tom["dev_ema20"] = tom["mid"].values - mid_ema20
    tom["dev_ema50"] = tom["mid"].values - mid_ema50

    for ema_name in ["dev_ema20", "dev_ema50"]:
        fvals = tom[ema_name].values
        for h in [1, 2, 5, 10, 20]:
            target = tom[f"dmid_t{h}"].values
            mask = np.isfinite(fvals) & np.isfinite(target)
            if mask.sum() < 50:
                continue
            r = np.corrcoef(fvals[mask], target[mask])[0, 1]
            if abs(r) > 0.05:
                findings_day.append({
                    "category": "bonus_combined",
                    "feature": f"{ema_name}_t{h}",
                    "horizon": h,
                    "corr": r,
                    "n": int(mask.sum()),
                    "day": day_label,
                })

    # Bollinger-like: is price at extreme of recent range?
    rolling_high = pd.Series(tom["mid"].values).rolling(20).max().values
    rolling_low = pd.Series(tom["mid"].values).rolling(20).min().values
    rolling_range = rolling_high - rolling_low
    mid_in_range = np.where(rolling_range > 0,
                            (tom["mid"].values - rolling_low) / rolling_range,
                            0.5)
    tom["mid_in_range"] = mid_in_range

    for h in [1, 2, 5, 10, 20]:
        target = tom[f"dmid_t{h}"].values
        mask = np.isfinite(mid_in_range) & np.isfinite(target) & (rolling_range > 0)
        if mask.sum() < 50:
            continue
        r = np.corrcoef(mid_in_range[mask], target[mask])[0, 1]
        if abs(r) > 0.05:
            findings_day.append({
                "category": "bonus_combined",
                "feature": f"mid_in_range20_t{h}",
                "horizon": h,
                "corr": r,
                "n": int(mask.sum()),
                "day": day_label,
            })

    # Extremes: at top or bottom of range
    at_top = mid_in_range > 0.9
    at_bottom = mid_in_range < 0.1
    for h in [1, 2, 5, 10]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(at_top, f"at_range_top_t{h}"), (at_bottom, f"at_range_bottom_t{h}")]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and (res["accuracy"] > 0.52 or abs(res["mean_dmid"]) > 0.1):
                findings_day.append({
                    "category": "bonus_combined",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    # SIGNED dmid * obi interaction: when move agrees with OBI, continuation stronger?
    dmid_obi_agree = (np.sign(tom["dmid"].values) == np.sign(tom["obi_l1"].values)) & (tom["dmid"].values != 0)
    dmid_obi_disagree = (np.sign(tom["dmid"].values) != np.sign(tom["obi_l1"].values)) & (tom["dmid"].values != 0) & (tom["obi_l1"].values != 0)

    for h in [1, 2, 5]:
        target = tom[f"dmid_t{h}"].values
        for cond, cname in [(dmid_obi_agree, f"dmid_obi_agree_t{h}"),
                            (dmid_obi_disagree, f"dmid_obi_disagree_t{h}")]:
            res = conditional_accuracy(cond & np.isfinite(target), target, cname)
            if res and (res["accuracy"] > 0.55 or abs(res["mean_dmid"]) > 0.1):
                findings_day.append({
                    "category": "bonus_combined",
                    "feature": res["label"],
                    "horizon": h,
                    "accuracy": res["accuracy"],
                    "direction": res["direction"],
                    "mean_dmid": res["mean_dmid"],
                    "n": res["n_nonzero"],
                    "day": day_label,
                })

    n_bonus = sum(1 for f in findings_day if f["category"].startswith("bonus_"))
    print(f"  Found {n_bonus} combined/regime signals")

    # Accumulate
    all_findings.extend(findings_day)
    print(f"\n  TOTAL signals for {day_label}: {len(findings_day)}")

# ============================================================
# CROSS-DAY STABILITY ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("  CROSS-DAY STABILITY ANALYSIS")
print("=" * 80)

findings_df = pd.DataFrame(all_findings)
if len(findings_df) == 0:
    print("  No findings to analyze!")
    exit()

# Separate correlation-based and accuracy-based findings
corr_findings = findings_df[findings_df["corr"].notna()].copy() if "corr" in findings_df.columns else pd.DataFrame()
acc_findings = findings_df[findings_df["accuracy"].notna()].copy() if "accuracy" in findings_df.columns else pd.DataFrame()
mi_findings = findings_df[findings_df["category"] == "8_mutual_info"].copy()

# ----------------------------------------------------------
# CORRELATION-BASED SIGNALS: stable across 3 days
# ----------------------------------------------------------
print("\n--- STABLE CORRELATION SIGNALS (present all 3 days, |r| > 0.08) ---")
if len(corr_findings) > 0:
    grouped = corr_findings.groupby(["category", "feature", "horizon"])
    stable_corr = []
    for (cat, feat, h), grp in grouped:
        if len(grp) < 3:
            continue
        corrs = grp["corr"].values
        # Check same sign across all days
        if not (np.all(corrs > 0) or np.all(corrs < 0)):
            continue
        mean_corr = corrs.mean()
        min_abs = np.min(np.abs(corrs))
        if min_abs < 0.06:
            continue
        stable_corr.append({
            "category": cat,
            "feature": feat,
            "horizon": h,
            "mean_corr": mean_corr,
            "min_abs_corr": min_abs,
            "max_abs_corr": np.max(np.abs(corrs)),
            "corr_per_day": {row["day"]: row["corr"] for _, row in grp.iterrows()},
            "avg_n": grp["n"].mean(),
        })

    stable_corr_df = pd.DataFrame(stable_corr)
    if len(stable_corr_df) > 0:
        stable_corr_df = stable_corr_df.sort_values("min_abs_corr", ascending=False)
        print(f"\n  {len(stable_corr_df)} stable correlation signals:")
        for _, row in stable_corr_df.head(40).iterrows():
            print(f"  [{row['category']}] {row['feature']} (h={row['horizon']}): "
                  f"mean_r={row['mean_corr']:.3f}, range=[{row['min_abs_corr']:.3f}, {row['max_abs_corr']:.3f}], "
                  f"n={int(row['avg_n'])}")
            for day, r in row["corr_per_day"].items():
                print(f"      {day}: r={r:.4f}")
    else:
        print("  No stable correlation signals found!")
else:
    stable_corr_df = pd.DataFrame()
    print("  No correlation findings!")

# ----------------------------------------------------------
# ACCURACY-BASED SIGNALS: stable across 3 days
# ----------------------------------------------------------
print("\n--- STABLE ACCURACY SIGNALS (present all 3 days, acc > 0.55) ---")
if len(acc_findings) > 0:
    grouped = acc_findings.groupby(["category", "feature"])
    stable_acc = []
    for (cat, feat), grp in grouped:
        if len(grp) < 3:
            continue
        accs = grp["accuracy"].values
        mean_acc = accs.mean()
        min_acc = accs.min()
        # Check same direction
        directions = grp["direction"].values
        if len(set(directions)) > 1:
            continue
        avg_n = grp["n"].mean()
        if min_acc < 0.52:
            continue
        mean_dmid_vals = grp["mean_dmid"].values
        stable_acc.append({
            "category": cat,
            "feature": feat,
            "direction": directions[0],
            "mean_acc": mean_acc,
            "min_acc": min_acc,
            "max_acc": accs.max(),
            "mean_dmid": mean_dmid_vals.mean(),
            "avg_n": avg_n,
            "acc_per_day": {row["day"]: row["accuracy"] for _, row in grp.iterrows()},
        })

    stable_acc_df = pd.DataFrame(stable_acc)
    if len(stable_acc_df) > 0:
        stable_acc_df = stable_acc_df.sort_values("min_acc", ascending=False)
        print(f"\n  {len(stable_acc_df)} stable accuracy signals:")
        for _, row in stable_acc_df.head(30).iterrows():
            print(f"  [{row['category']}] {row['feature']} -> {row['direction']}: "
                  f"mean_acc={row['mean_acc']:.1%}, range=[{row['min_acc']:.1%}, {row['max_acc']:.1%}], "
                  f"mean_dmid={row['mean_dmid']:.3f}, n={int(row['avg_n'])}")
            for day, a in row["acc_per_day"].items():
                print(f"      {day}: acc={a:.1%}")
    else:
        print("  No stable accuracy signals found!")
else:
    stable_acc_df = pd.DataFrame()
    print("  No accuracy findings!")

# ----------------------------------------------------------
# MUTUAL INFORMATION: stable rankings
# ----------------------------------------------------------
print("\n--- MUTUAL INFORMATION RANKINGS ---")
if len(mi_findings) > 0:
    mi_pivot = mi_findings.pivot_table(index="feature", columns="day", values="mi", aggfunc="first")
    mi_pivot["mean_mi"] = mi_pivot.mean(axis=1)
    mi_pivot = mi_pivot.sort_values("mean_mi", ascending=False)
    print(mi_pivot.to_string())

    # Compare MI with Pearson r
    print("\n  MI vs Pearson r comparison:")
    mi_pearson = mi_findings.groupby("feature").agg(
        mean_mi=("mi", "mean"),
        mean_pearson=("pearson_r", lambda x: np.mean(np.abs(x)))
    ).sort_values("mean_mi", ascending=False)
    print(mi_pearson.to_string())

# ============================================================
# FINAL SUMMARY: RANKED BY EXPECTED PNL
# ============================================================
print("\n" + "=" * 80)
print("  FINAL RANKINGS: ALL STABLE SIGNALS BY EXPECTED PNL CONTRIBUTION")
print("=" * 80)

# Estimate PnL contribution:
# For correlation: expected PnL ~ |r| * frequency * avg_spread_half
# For accuracy: expected PnL ~ (2*acc - 1) * frequency * avg_spread_half
# avg_spread_half ~ 6.5, frequency = n/10000 per day
# Assume 2000 ticks per day for website

AVG_HALF_SPREAD = 6.5
TICKS_PER_DAY = 2000  # website tutorial

all_ranked = []

if len(stable_corr_df) > 0:
    for _, row in stable_corr_df.iterrows():
        freq_per_day = row["avg_n"] / 10000 * TICKS_PER_DAY  # scale
        # For linear signals, edge ~ |r| * sigma_dmid * signal_std
        # Simplify: proportional edge ~ |r|
        edge_per_trigger = abs(row["mean_corr"]) * 0.5 * AVG_HALF_SPREAD
        expected_pnl = edge_per_trigger * freq_per_day
        all_ranked.append({
            "type": "correlation",
            "category": row["category"],
            "feature": row["feature"],
            "horizon": row["horizon"],
            "strength": row["mean_corr"],
            "stability": row["min_abs_corr"],
            "freq_per_day": freq_per_day,
            "expected_pnl_per_day": expected_pnl,
        })

if len(stable_acc_df) > 0:
    for _, row in stable_acc_df.iterrows():
        freq_per_day = row["avg_n"] / 10000 * TICKS_PER_DAY
        edge_per_trigger = (2 * row["mean_acc"] - 1) * AVG_HALF_SPREAD
        expected_pnl = edge_per_trigger * freq_per_day
        all_ranked.append({
            "type": "accuracy",
            "category": row["category"],
            "feature": row["feature"],
            "horizon": 0,
            "strength": row["mean_acc"],
            "stability": row["min_acc"],
            "direction": row.get("direction", ""),
            "mean_dmid": row.get("mean_dmid", 0),
            "freq_per_day": freq_per_day,
            "expected_pnl_per_day": expected_pnl,
        })

ranked_df = pd.DataFrame(all_ranked)
if len(ranked_df) > 0:
    ranked_df = ranked_df.sort_values("expected_pnl_per_day", ascending=False)
    print(f"\n  TOP 50 SIGNALS BY EXPECTED PNL:")
    print("-" * 120)
    for i, (_, row) in enumerate(ranked_df.head(50).iterrows()):
        if row["type"] == "correlation":
            print(f"  #{i+1:2d} [{row['category']:20s}] {row['feature']:40s} h={int(row['horizon']):2d} | "
                  f"r={row['strength']:+.3f} min|r|={row['stability']:.3f} | "
                  f"freq={row['freq_per_day']:.0f}/day | est_pnl={row['expected_pnl_per_day']:.1f}")
        else:
            print(f"  #{i+1:2d} [{row['category']:20s}] {row['feature']:40s}       | "
                  f"acc={row['strength']:.1%} min={row['stability']:.1%} dmid={row.get('mean_dmid',0):+.3f} | "
                  f"freq={row['freq_per_day']:.0f}/day | est_pnl={row['expected_pnl_per_day']:.1f}")
else:
    print("  No ranked signals found!")

# ============================================================
# ACTIONABLE INSIGHTS
# ============================================================
print("\n" + "=" * 80)
print("  ACTIONABLE INSIGHTS")
print("=" * 80)

print("""
KEY QUESTIONS ANSWERED:
1. Do nonlinear transforms beat linear? (Compare MI of x^2, x^3 vs x)
2. Do conditional patterns have >55% accuracy stable across days?
3. Do sequence patterns (HMM-like) reveal exploitable structure?
4. Do volume dynamics add information beyond OBI level?
5. Is there ANY cross-product signal (conditional or not)?
6. Is there a time-of-day drift we can exploit?
7. Does OBI acceleration beat OBI level?
8. Does MI reveal hidden nonlinear structure missed by Pearson r?
9. Do run lengths / streaks add predictive value?
10. Do market trade characteristics predict future moves?

REMINDER: Even if a signal is statistically significant in CSV data,
it may NOT transfer to the website if it depends on L2 volume levels
(which differ 98.5% between CSV and website).

SAFE signals (volume-independent): spread state, dmid patterns,
  price level, time-of-day, sign sequences, run lengths.
UNSAFE signals (volume-dependent): OBI level, vol ratios,
  gap asymmetry, microprice deviation.
""")

# Print total unique features found
print(f"\nTotal findings across all days: {len(all_findings)}")
if len(stable_corr_df) > 0:
    print(f"Stable correlation signals: {len(stable_corr_df)}")
if len(stable_acc_df) > 0:
    print(f"Stable accuracy signals: {len(stable_acc_df)}")
if len(ranked_df) > 0:
    print(f"Ranked signals by expected PnL: {len(ranked_df)}")
