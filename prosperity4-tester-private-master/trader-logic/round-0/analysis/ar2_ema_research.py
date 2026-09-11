"""
AR(2) + EMA + VWAP + Quote Skew + L2 OBI Research Script
=========================================================
Analyzes TOMATOES data from all 3 CSV days to calibrate FV estimation parameters.

Outputs:
  1. AR(2) coefficients and R² per day
  2. EMA deviation predictive power (spans 5,10,20,50)
  3. VWAP-mid deviation predictive power
  4. Blended FV weight optimization
  5. Quote skew ramp analysis (gamma sweep)
  6. L2 OBI correlation with next dmid
"""

import pandas as pd
import numpy as np

# ============================================================
# DATA LOADING
# ============================================================
BASE = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round0"
FILES = {
    -2: f"{BASE}/prices_round_0_day_-2.csv",
    -1: f"{BASE}/prices_round_0_day_-1.csv",
    0:  f"{BASE}/prices_round_0_day_0.csv",
}

def load_tomatoes(path):
    df = pd.read_csv(path, sep=";")
    tom = df[df["product"] == "TOMATOES"].copy()
    tom = tom.sort_values("timestamp").reset_index(drop=True)
    return tom

days_data = {}
for day, path in FILES.items():
    days_data[day] = load_tomatoes(path)
    print(f"Day {day:+d}: {len(days_data[day])} TOMATOES ticks loaded")

print("\n" + "="*80)
print("1. AR(2) MODEL ON MID PRICE CHANGES")
print("="*80)

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)  # dmid[t] = mid[t+1] - mid[t]
    
    # AR(2): dmid[t] = a1*dmid[t-1] + a2*dmid[t-2] + intercept
    Y = dmid[2:]
    X1 = dmid[1:-1]
    X2 = dmid[:-2]
    
    X = np.column_stack([X1, X2, np.ones(len(Y))])
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    Y_hat = X @ beta
    
    ss_res = np.sum((Y - Y_hat)**2)
    ss_tot = np.sum((Y - Y.mean())**2)
    r2 = 1 - ss_res / ss_tot
    
    rmse = np.sqrt(np.mean((Y - Y_hat)**2))
    
    print(f"\nDay {day:+d}:")
    print(f"  a1 (lag-1) = {beta[0]:.6f}")
    print(f"  a2 (lag-2) = {beta[1]:.6f}")
    print(f"  intercept  = {beta[2]:.6f}")
    print(f"  R²         = {r2:.6f}")
    print(f"  RMSE       = {rmse:.4f}")
    print(f"  dmid std   = {dmid.std():.4f}")
    print(f"  dmid mean  = {dmid.mean():.6f}")

# Also fit AR(4) for comparison (used in s36)
print("\n" + "-"*40)
print("AR(4) comparison (used in s36_medallion):")
for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    
    Y = dmid[4:]
    Xs = [dmid[4-i-1:len(dmid)-i-1] for i in range(4)]
    X = np.column_stack(Xs + [np.ones(len(Y))])
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    Y_hat = X @ beta
    
    ss_res = np.sum((Y - Y_hat)**2)
    ss_tot = np.sum((Y - Y.mean())**2)
    r2 = 1 - ss_res / ss_tot
    
    print(f"\nDay {day:+d}: coefs = [{', '.join(f'{b:.4f}' for b in beta[:4])}], "
          f"intercept = {beta[4]:.4f}, R² = {r2:.6f}")


print("\n" + "="*80)
print("2. EMA DEVIATION AS PREDICTOR OF NEXT dmid")
print("="*80)

ema_spans = [5, 10, 20, 50]

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    print(f"\nDay {day:+d}:")
    
    for span in ema_spans:
        alpha = 2.0 / (span + 1)
        ema = np.zeros(len(mid))
        ema[0] = mid[0]
        for i in range(1, len(mid)):
            ema[i] = alpha * mid[i] + (1 - alpha) * ema[i-1]
        
        signal = ema[:-1] - mid[:-1]
        target = dmid
        
        corr = np.corrcoef(signal, target)[0, 1]
        
        X = np.column_stack([signal, np.ones(len(signal))])
        beta = np.linalg.lstsq(X, target, rcond=None)[0]
        pred = X @ beta
        ss_res = np.sum((target - pred)**2)
        ss_tot = np.sum((target - target.mean())**2)
        r2 = 1 - ss_res / ss_tot
        
        print(f"  EMA({span:2d}): corr = {corr:+.4f}, R² = {r2:.6f}, "
              f"beta = {beta[0]:+.6f}, signal_std = {signal.std():.4f}")


print("\n" + "="*80)
print("3. VWAP FROM ORDER BOOK AS PREDICTOR")
print("="*80)

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    
    vwap = np.zeros(len(df))
    for idx in range(len(df)):
        row = df.iloc[idx]
        total_pv = 0.0
        total_v = 0.0
        for level in [1, 2, 3]:
            bp = row.get(f"bid_price_{level}", np.nan)
            bv = row.get(f"bid_volume_{level}", np.nan)
            ap = row.get(f"ask_price_{level}", np.nan)
            av = row.get(f"ask_volume_{level}", np.nan)
            
            if pd.notna(bp) and pd.notna(bv) and bv > 0:
                total_pv += bp * bv
                total_v += bv
            if pd.notna(ap) and pd.notna(av) and av > 0:
                total_pv += ap * av
                total_v += av
        
        vwap[idx] = total_pv / total_v if total_v > 0 else mid[idx]
    
    dmid = np.diff(mid)
    signal = vwap[:-1] - mid[:-1]
    target = dmid
    
    corr = np.corrcoef(signal, target)[0, 1]
    
    X = np.column_stack([signal, np.ones(len(signal))])
    beta = np.linalg.lstsq(X, target, rcond=None)[0]
    pred = X @ beta
    ss_res = np.sum((target - pred)**2)
    ss_tot = np.sum((target - target.mean())**2)
    r2 = 1 - ss_res / ss_tot
    
    print(f"\nDay {day:+d}:")
    print(f"  VWAP-mid corr = {corr:+.4f}, R² = {r2:.6f}")
    print(f"  beta = {beta[0]:+.6f}, intercept = {beta[1]:+.6f}")
    print(f"  signal mean = {signal.mean():.4f}, std = {signal.std():.4f}")
    
    # Also test microprice (L1 only)
    bp1 = df["bid_price_1"].values.astype(float)
    bv1 = df["bid_volume_1"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    microprice = (bp1 * av1 + ap1 * bv1) / (bv1 + av1)
    
    mp_signal = microprice[:-1] - mid[:-1]
    mp_corr = np.corrcoef(mp_signal, target)[0, 1]
    
    X_mp = np.column_stack([mp_signal, np.ones(len(mp_signal))])
    beta_mp = np.linalg.lstsq(X_mp, target, rcond=None)[0]
    pred_mp = X_mp @ beta_mp
    ss_res_mp = np.sum((target - pred_mp)**2)
    r2_mp = 1 - ss_res_mp / ss_tot
    
    print(f"  Microprice-mid corr = {mp_corr:+.4f}, R² = {r2_mp:.6f}")


print("\n" + "="*80)
print("4. BLENDED FV WEIGHT OPTIMIZATION")
print("="*80)

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    
    # AR(2) signal
    ar2_pred = np.zeros(len(dmid))
    Y_ar = dmid[2:]
    X1_ar = dmid[1:-1]
    X2_ar = dmid[:-2]
    X_ar = np.column_stack([X1_ar, X2_ar, np.ones(len(Y_ar))])
    beta_ar = np.linalg.lstsq(X_ar, Y_ar, rcond=None)[0]
    for t in range(2, len(dmid)):
        ar2_pred[t] = beta_ar[0] * dmid[t-1] + beta_ar[1] * dmid[t-2] + beta_ar[2]
    
    # EMA(10) signal
    alpha_ema = 2.0 / 11
    ema = np.zeros(len(mid))
    ema[0] = mid[0]
    for i in range(1, len(mid)):
        ema[i] = alpha_ema * mid[i] + (1 - alpha_ema) * ema[i-1]
    ema_signal = ema[:-1] - mid[:-1]
    
    # VWAP signal
    vwap = np.zeros(len(df))
    for idx in range(len(df)):
        row = df.iloc[idx]
        total_pv, total_v = 0.0, 0.0
        for level in [1, 2, 3]:
            for side in ["bid", "ask"]:
                p = row.get(f"{side}_price_{level}", np.nan)
                v = row.get(f"{side}_volume_{level}", np.nan)
                if pd.notna(p) and pd.notna(v) and v > 0:
                    total_pv += p * v
                    total_v += v
        vwap[idx] = total_pv / total_v if total_v > 0 else mid[idx]
    vwap_signal = vwap[:-1] - mid[:-1]
    
    # Microprice signal
    bp1 = df["bid_price_1"].values.astype(float)
    bv1 = df["bid_volume_1"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    mp = (bp1 * av1 + ap1 * bv1) / (bv1 + av1)
    mp_signal = mp[:-1] - mid[:-1]
    
    start = 4
    target = dmid[start:]
    
    # Joint regression: all 4 signals
    X_all = np.column_stack([
        ar2_pred[start:],
        ema_signal[start:],
        vwap_signal[start:],
        mp_signal[start:],
        np.ones(len(target))
    ])
    beta_all = np.linalg.lstsq(X_all, target, rcond=None)[0]
    pred_all = X_all @ beta_all
    ss_res_all = np.sum((target - pred_all)**2)
    ss_tot_all = np.sum((target - target.mean())**2)
    r2_all = 1 - ss_res_all / ss_tot_all
    
    print(f"\nDay {day:+d} -- Joint regression (AR2 + EMA10 + VWAP + Microprice):")
    print(f"  w_AR2        = {beta_all[0]:+.6f}")
    print(f"  w_EMA10      = {beta_all[1]:+.6f}")
    print(f"  w_VWAP       = {beta_all[2]:+.6f}")
    print(f"  w_Microprice = {beta_all[3]:+.6f}")
    print(f"  intercept    = {beta_all[4]:+.6f}")
    print(f"  Joint R²     = {r2_all:.6f}")
    
    # AR2 + Microprice only
    X_am = np.column_stack([ar2_pred[start:], mp_signal[start:], np.ones(len(target))])
    beta_am = np.linalg.lstsq(X_am, target, rcond=None)[0]
    pred_am = X_am @ beta_am
    ss_res_am = np.sum((target - pred_am)**2)
    r2_am = 1 - ss_res_am / ss_tot_all
    print(f"  AR2 + Microprice R² = {r2_am:.6f} (w_AR2={beta_am[0]:+.4f}, w_MP={beta_am[1]:+.4f})")
    
    # Microprice-only
    X_mo = np.column_stack([mp_signal[start:], np.ones(len(target))])
    beta_mo = np.linalg.lstsq(X_mo, target, rcond=None)[0]
    pred_mo = X_mo @ beta_mo
    ss_res_mo = np.sum((target - pred_mo)**2)
    r2_mo = 1 - ss_res_mo / ss_tot_all
    print(f"  Microprice-only R²  = {r2_mo:.6f}")


print("\n" + "="*80)
print("5. QUOTE SKEW RAMP (POSITION-DEPENDENT GAMMA)")
print("="*80)
print("Effect of skew: skewed_mid = FV - pos * gamma")
print("Positive gamma = when long, lower FV (widen buy, tighten sell) = mean-revert faster")
print()

gammas = [0.0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2]

print("Deterministic analysis: quote adjustment at various position levels")
print("(Shift applied to BOTH bid and ask symmetrically)\n")
print(f"  {'Pos':>5s}", end="")
for gamma in gammas:
    print(f"  g={gamma:.2f}", end="")
print()
print(f"  {'':>5s}", end="")
for gamma in gammas:
    print(f"  {'shift':>6s}", end="")
print()
print("  " + "-" * (5 + len(gammas) * 8))

for pos_val in [0, 10, 20, 30, 40, 50, 60, 70, 80]:
    print(f"  {pos_val:5d}", end="")
    for gamma in gammas:
        shift = pos_val * gamma
        print(f"  {shift:6.2f}", end="")
    print()

print("\nInterpretation: shift = how many ticks FV drops when long (raises when short)")
print("  At pos=40, gamma=0.05: shift=2.0 (our ask drops 2 ticks, bid drops 2 ticks)")
print("  At pos=80, gamma=0.10: shift=8.0 (very aggressive mean reversion)")

# Now simulate how gamma affects realized PnL with a simple MM model
print("\n\nSimulated MM with gamma (fixed spread=13, random taker ~4%/tick):")
print("(Average of 20 runs per setting for noise reduction)\n")

np.random.seed(42)
N_RUNS = 20

for day in sorted(days_data.keys()):
    df = days_data[day]
    mid = df["mid_price"].values
    N = len(mid)
    
    print(f"Day {day:+d}:")
    print(f"  {'gamma':>8s}  {'Avg PnL':>10s}  {'Std PnL':>10s}  {'Avg Fills':>10s}  "
          f"{'Avg |EndPos|':>12s}  {'Avg MaxPos':>10s}")
    
    for gamma in gammas:
        pnls = []
        fills_list = []
        end_pos_list = []
        max_pos_list = []
        
        for run in range(N_RUNS):
            pos = 0
            pnl = 0.0
            fills = 0
            max_abs_pos = 0
            
            for t in range(N - 1):
                # Skewed FV: when long (pos>0), lower FV to encourage selling
                skewed_fv = mid[t] - pos * gamma
                half_spread = 6.5
                
                our_bid = int(np.floor(skewed_fv - half_spread))
                our_ask = int(np.ceil(skewed_fv + half_spread))
                
                # MM bot at mid +/- 6.5
                mm_bid = int(np.floor(mid[t] - half_spread))
                mm_ask = int(np.ceil(mid[t] + half_spread))
                
                # Taker arrives ~4% per tick, randomly buys or sells
                if np.random.random() < 0.04:
                    if np.random.random() < 0.5:
                        # Taker buys (hits asks). We fill if our_ask <= mm_ask
                        if our_ask <= mm_ask and pos > -80:
                            pos -= 1
                            pnl += our_ask
                            fills += 1
                    else:
                        # Taker sells (hits bids). We fill if our_bid >= mm_bid
                        if our_bid >= mm_bid and pos < 80:
                            pos += 1
                            pnl -= our_bid
                            fills += 1
                
                max_abs_pos = max(max_abs_pos, abs(pos))
            
            final_pnl = pnl + pos * mid[-1]
            pnls.append(final_pnl)
            fills_list.append(fills)
            end_pos_list.append(abs(pos))
            max_pos_list.append(max_abs_pos)
        
        print(f"  {gamma:8.3f}  {np.mean(pnls):10.1f}  {np.std(pnls):10.1f}  "
              f"{np.mean(fills_list):10.1f}  {np.mean(end_pos_list):12.1f}  "
              f"{np.mean(max_pos_list):10.1f}")
    print()


print("\n" + "="*80)
print("6. L2 OBI CORRELATION WITH NEXT dmid")
print("="*80)

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    
    bv1 = df["bid_volume_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    bv2 = df["bid_volume_2"].values.astype(float)
    av2 = df["ask_volume_2"].values.astype(float)
    
    bp1 = df["bid_price_1"].values.astype(float)
    ap1 = df["ask_price_1"].values.astype(float)
    bp2 = df["bid_price_2"].values.astype(float)
    ap2 = df["ask_price_2"].values.astype(float)
    
    # L1 OBI
    l1_obi = (bv1 - av1) / (bv1 + av1)
    
    # L2 OBI
    l2_obi = (bv2 - av2) / (bv2 + av2)
    
    # Combined L1+L2 OBI
    total_bv = bv1 + bv2
    total_av = av1 + av2
    combined_obi = (total_bv - total_av) / (total_bv + total_av)
    
    # Distance-weighted OBI
    dist_b1 = mid - bp1
    dist_a1 = ap1 - mid
    dist_b2 = mid - bp2
    dist_a2 = ap2 - mid
    
    wb1 = bv1 / np.maximum(dist_b1, 0.5)
    wa1 = av1 / np.maximum(dist_a1, 0.5)
    wb2 = bv2 / np.maximum(dist_b2, 0.5)
    wa2 = av2 / np.maximum(dist_a2, 0.5)
    
    dw_obi = (wb1 + wb2 - wa1 - wa2) / (wb1 + wb2 + wa1 + wa2)
    
    print(f"\nDay {day:+d}:")
    print(f"  {'Signal':30s} {'corr(sig, next_dmid)':>22s} {'R²':>10s}")
    
    for name, signal in [("L1 OBI", l1_obi), ("L2 OBI", l2_obi),
                          ("Combined L1+L2 OBI", combined_obi),
                          ("Dist-weighted OBI", dw_obi)]:
        sig = signal[:-1]
        tgt = dmid
        
        mask = ~(np.isnan(sig) | np.isnan(tgt))
        sig_clean = sig[mask]
        tgt_clean = tgt[mask]
        
        corr = np.corrcoef(sig_clean, tgt_clean)[0, 1]
        
        X = np.column_stack([sig_clean, np.ones(len(sig_clean))])
        beta = np.linalg.lstsq(X, tgt_clean, rcond=None)[0]
        pred = X @ beta
        ss_res = np.sum((tgt_clean - pred)**2)
        ss_tot = np.sum((tgt_clean - tgt_clean.mean())**2)
        r2 = 1 - ss_res / ss_tot
        
        print(f"  {name:30s} {corr:+22.4f} {r2:10.6f}")
    
    # Directional accuracy
    print(f"\n  Directional accuracy (OBI > 0 => dmid > 0):")
    for name, signal in [("L1 OBI", l1_obi), ("L2 OBI", l2_obi),
                          ("Combined L1+L2 OBI", combined_obi)]:
        sig = signal[:-1]
        tgt = dmid
        mask = (sig != 0) & (tgt != 0)
        if mask.sum() > 0:
            correct = np.sum((sig[mask] > 0) == (tgt[mask] > 0))
            total = mask.sum()
            print(f"    {name:30s}: {correct}/{total} = {correct/total:.1%} "
                  f"(fires on {total} of {len(sig)} ticks)")


print("\n" + "="*80)
print("7. OBI CONDITIONED ON MAGNITUDE (threshold analysis)")
print("="*80)

for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    
    bv1 = df["bid_volume_1"].values.astype(float)
    av1 = df["ask_volume_1"].values.astype(float)
    bv2 = df["bid_volume_2"].values.astype(float)
    av2 = df["ask_volume_2"].values.astype(float)
    
    total_bv = bv1 + bv2
    total_av = av1 + av2
    obi = (total_bv - total_av) / (total_bv + total_av)
    
    print(f"\nDay {day:+d}:")
    print(f"  {'Threshold':>10s}  {'Count':>6s}  {'Avg signed dmid':>16s}  "
          f"{'Std':>8s}  {'Dir Acc':>8s}  {'Avg |OBI|':>10s}")
    
    for thresh in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
        sig = obi[:-1]
        tgt = dmid
        
        mask = np.abs(sig) > thresh
        if mask.sum() == 0:
            continue
        
        signed_tgt = tgt[mask] * np.sign(sig[mask])
        no_move = np.sum(tgt[mask] == 0)
        denom = mask.sum() - no_move
        
        correct = 0
        if denom > 0:
            move_mask = mask & (tgt != 0)
            sig_m = sig[move_mask]
            tgt_m = tgt[move_mask]
            correct = np.sum((sig_m > 0) == (tgt_m > 0))
            acc = correct / denom
        else:
            acc = 0.0
        
        print(f"  {thresh:10.2f}  {mask.sum():6d}  {signed_tgt.mean():+16.4f}  "
              f"{signed_tgt.std():8.4f}  {acc:8.1%}  "
              f"{np.abs(sig[mask]).mean():10.4f}")


print("\n" + "="*80)
print("8. AR(2) OUT-OF-SAMPLE VALIDATION")
print("="*80)
print("Fit on one day, predict on others\n")

ar2_models = {}
for day, df in sorted(days_data.items()):
    mid = df["mid_price"].values
    dmid = np.diff(mid)
    Y = dmid[2:]
    X = np.column_stack([dmid[1:-1], dmid[:-2], np.ones(len(Y))])
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    ar2_models[day] = beta

print(f"  {'Train':>8s}  {'Test':>8s}  {'IS R²':>10s}  {'OOS R²':>10s}  {'R² drop':>10s}")
for train_day in sorted(days_data.keys()):
    beta = ar2_models[train_day]
    
    mid_tr = days_data[train_day]["mid_price"].values
    dmid_tr = np.diff(mid_tr)
    Y_tr = dmid_tr[2:]
    X_tr = np.column_stack([dmid_tr[1:-1], dmid_tr[:-2], np.ones(len(Y_tr))])
    pred_tr = X_tr @ beta
    ss_res_tr = np.sum((Y_tr - pred_tr)**2)
    ss_tot_tr = np.sum((Y_tr - Y_tr.mean())**2)
    r2_is = 1 - ss_res_tr / ss_tot_tr
    
    for test_day in sorted(days_data.keys()):
        mid = days_data[test_day]["mid_price"].values
        dmid = np.diff(mid)
        Y = dmid[2:]
        X = np.column_stack([dmid[1:-1], dmid[:-2], np.ones(len(Y))])
        pred = X @ beta
        ss_res = np.sum((Y - pred)**2)
        ss_tot = np.sum((Y - Y.mean())**2)
        r2 = 1 - ss_res / ss_tot
        
        drop = r2_is - r2
        label = " <-- IS" if train_day == test_day else ""
        print(f"  {train_day:+8d}  {test_day:+8d}  {r2_is:10.6f}  {r2:10.6f}  {drop:+10.6f}{label}")
    print()


print("\n" + "="*80)
print("9. COMPREHENSIVE SIGNAL COMPARISON TABLE")
print("="*80)
print("All signals, all days -- correlation with next dmid\n")

header = f"  {'Signal':35s}"
for day in sorted(days_data.keys()):
    header += f"  Day{day:+d} corr"
    header += f"   Day{day:+d} R²"
print(header)
print("  " + "-" * 130)

signal_names = [
    "AR(2) predicted dmid",
    "EMA(5) - mid",
    "EMA(10) - mid",
    "EMA(20) - mid",
    "EMA(50) - mid",
    "Microprice - mid",
    "VWAP - mid",
    "L1 OBI",
    "L2 OBI",
    "Combined L1+L2 OBI",
    "Dist-weighted OBI",
]

for sig_name in signal_names:
    row = f"  {sig_name:35s}"
    for day in sorted(days_data.keys()):
        df = days_data[day]
        mid = df["mid_price"].values
        dmid = np.diff(mid)
        
        bp1 = df["bid_price_1"].values.astype(float)
        bv1 = df["bid_volume_1"].values.astype(float)
        ap1 = df["ask_price_1"].values.astype(float)
        av1 = df["ask_volume_1"].values.astype(float)
        bp2 = df["bid_price_2"].values.astype(float)
        bv2 = df["bid_volume_2"].values.astype(float)
        ap2 = df["ask_price_2"].values.astype(float)
        av2 = df["ask_volume_2"].values.astype(float)
        
        mp = (bp1 * av1 + ap1 * bv1) / (bv1 + av1)
        
        start = 4
        target = dmid[start:]
        
        if sig_name == "AR(2) predicted dmid":
            Y_ar = dmid[2:]
            X_ar = np.column_stack([dmid[1:-1], dmid[:-2], np.ones(len(Y_ar))])
            beta_ar = np.linalg.lstsq(X_ar, Y_ar, rcond=None)[0]
            sig_arr = np.zeros(len(dmid))
            for t in range(2, len(dmid)):
                sig_arr[t] = beta_ar[0] * dmid[t-1] + beta_ar[1] * dmid[t-2] + beta_ar[2]
            signal = sig_arr[start:]
        elif sig_name.startswith("EMA("):
            span = int(sig_name.split("(")[1].split(")")[0])
            alpha = 2.0 / (span + 1)
            ema = np.zeros(len(mid))
            ema[0] = mid[0]
            for i in range(1, len(mid)):
                ema[i] = alpha * mid[i] + (1 - alpha) * ema[i-1]
            signal = (ema[:-1] - mid[:-1])[start:]
        elif sig_name == "Microprice - mid":
            signal = (mp[:-1] - mid[:-1])[start:]
        elif sig_name == "VWAP - mid":
            vwap = np.zeros(len(df))
            for idx in range(len(df)):
                r = df.iloc[idx]
                tpv, tv = 0.0, 0.0
                for lv in [1, 2, 3]:
                    for side in ["bid", "ask"]:
                        p = r.get(f"{side}_price_{lv}", np.nan)
                        v = r.get(f"{side}_volume_{lv}", np.nan)
                        if pd.notna(p) and pd.notna(v) and v > 0:
                            tpv += p * v
                            tv += v
                vwap[idx] = tpv / tv if tv > 0 else mid[idx]
            signal = (vwap[:-1] - mid[:-1])[start:]
        elif sig_name == "L1 OBI":
            signal = ((bv1 - av1) / (bv1 + av1))[:-1][start:]
        elif sig_name == "L2 OBI":
            signal = ((bv2 - av2) / (bv2 + av2))[:-1][start:]
        elif sig_name == "Combined L1+L2 OBI":
            tb = bv1 + bv2
            ta = av1 + av2
            signal = ((tb - ta) / (tb + ta))[:-1][start:]
        elif sig_name == "Dist-weighted OBI":
            db1 = mid - bp1
            da1 = ap1 - mid
            db2 = mid - bp2
            da2 = ap2 - mid
            wb1 = bv1 / np.maximum(db1, 0.5)
            wa1 = av1 / np.maximum(da1, 0.5)
            wb2 = bv2 / np.maximum(db2, 0.5)
            wa2 = av2 / np.maximum(da2, 0.5)
            signal = ((wb1 + wb2 - wa1 - wa2) / (wb1 + wb2 + wa1 + wa2))[:-1][start:]
        else:
            continue
        
        mask = ~np.isnan(signal) & ~np.isnan(target)
        sig_c = signal[mask]
        tgt_c = target[mask]
        
        corr = np.corrcoef(sig_c, tgt_c)[0, 1]
        X = np.column_stack([sig_c, np.ones(len(sig_c))])
        b = np.linalg.lstsq(X, tgt_c, rcond=None)[0]
        pred = X @ b
        ss_res = np.sum((tgt_c - pred)**2)
        ss_tot = np.sum((tgt_c - tgt_c.mean())**2)
        r2 = 1 - ss_res / ss_tot
        
        row += f"  {corr:+10.4f}  {r2:9.6f}"
    
    print(row)


print("\n" + "="*80)
print("10. PRACTICAL IMPLICATIONS SUMMARY")
print("="*80)
print("""
Key findings:

1. AR(2) vs AR(4):
   Compare R² values -- does adding lags 3-4 help beyond lags 1-2?
   If AR(2) R² ~= AR(4) R², extra lags are noise.

2. EMA as predictor:
   If all EMA correlations are near zero, EMA is useless for this mean-reverting market.
   EMA is a TREND follower -- this market mean-reverts (lag-1 AC = -0.44).

3. VWAP vs Microprice:
   Check which has higher R². Microprice uses L1 only (cleaner).
   VWAP includes L2 which is ~2.77x L1 vol -- may dilute signal.

4. Blended FV:
   If joint R² barely exceeds microprice-only R², blending adds complexity not value.
   Check if AR(2) weight is significant in the joint regression.

5. Gamma for quote skew:
   Higher gamma = faster mean reversion = less inventory risk but wider effective spread.
   Optimal gamma depends on how much the spread income vs inventory PnL tradeoff.

6. L2 OBI:
   Already confirmed in CLAUDE.md that OBI fires on 7% of ticks with 97-99% accuracy.
   This validates the s36_medallion +0.5 FV shift.

7. OOS stability:
   If AR(2) coefficients are stable across days (small R² drop), signal is robust.
   If large drop, coefficients are overfit to specific day's dynamics.
""")
