import os
import csv
import math
from collections import defaultdict
import numpy as np

DATA_DIR = "/home/mmaliar/prosperity4-tester-private/prosperity4bt/resources/round3"
DAYS = [0, 1, 2]

def load_mid_and_obi(day, product):
    path = os.path.join(DATA_DIR, f'prices_round_3_day_{day}.csv')
    ts_list = []
    mid_list = []
    obi_list = []
    spread_list = []
    if not os.path.exists(path):
        return [], [], [], []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == product:
                ts = int(row['timestamp'])
                bp1 = float(row['bid_price_1']) if row['bid_price_1'] else None
                ap1 = float(row['ask_price_1']) if row['ask_price_1'] else None
                bv1 = int(row['bid_volume_1']) if row['bid_volume_1'] else 0
                av1 = int(row['ask_volume_1']) if row['ask_volume_1'] else 0
                
                if bp1 and ap1:
                    mid = (bp1 + ap1) / 2
                    obi = (bv1 - av1) / (bv1 + av1) if (bv1 + av1) > 0 else 0
                    spread = ap1 - bp1
                    ts_list.append(ts)
                    mid_list.append(mid)
                    obi_list.append(obi)
                    spread_list.append(spread)
    return ts_list, mid_list, obi_list, spread_list

def lead_lag_analysis(ts1, val1, ts2, val2, max_lag=5):
    # align
    v1_dict = dict(zip(ts1, val1))
    v2_dict = dict(zip(ts2, val2))
    common_ts = sorted(list(set(v1_dict.keys()) & set(v2_dict.keys())))
    if len(common_ts) < 10:
        return {}
        
    y1 = np.diff([v1_dict[t] for t in common_ts])
    y2 = np.diff([v2_dict[t] for t in common_ts])
    
    if len(y1) <= max_lag:
        return {}
        
    corrs = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            a = y1[:lag]
            b = y2[-lag:]
        elif lag > 0:
            a = y1[lag:]
            b = y2[:-lag]
        else:
            a = y1
            b = y2
        if np.std(a) > 0 and np.std(b) > 0:
            corrs[lag] = np.corrcoef(a, b)[0, 1]
    return corrs

def analyze_obi_prediction(mid_list, obi_list, future_ticks=[1, 3, 5]):
    results = {}
    obi_arr = np.array(obi_list)
    mid_arr = np.array(mid_list)
    return_arrs = {k: np.roll(mid_arr, -k) - mid_arr for k in future_ticks}
    
    # Exclude tail elements
    obi_valid = obi_arr[:-max(future_ticks)]
    
    try:
        # 5 buckets of OBI
        q_bins = np.percentile(obi_valid, [20, 40, 60, 80])
        for tick in future_ticks:
            ret_valid = return_arrs[tick][:-max(future_ticks)]
            means = []
            
            # Buckets
            means.append(np.mean(ret_valid[obi_valid <= q_bins[0]]))
            means.append(np.mean(ret_valid[(obi_valid > q_bins[0]) & (obi_valid <= q_bins[1])]))
            means.append(np.mean(ret_valid[(obi_valid > q_bins[1]) & (obi_valid <= q_bins[2])]))
            means.append(np.mean(ret_valid[(obi_valid > q_bins[2]) & (obi_valid <= q_bins[3])]))
            means.append(np.mean(ret_valid[obi_valid > q_bins[3]]))
            
            results[tick] = means
    except Exception as e:
        return None
    return results

print("=== DEEP MICROSTRUCTURE ANALYSIS ===")
for day in DAYS:
    print(f"\\n--- DAY {day} ---")
    
    # 1. Lead-lag VELVETFRUIT vs VEV_5000
    ts_vfe, mid_vfe, obi_vfe, spread_vfe = load_mid_and_obi(day, "VELVETFRUIT_EXTRACT")
    ts_vev, mid_vev, obi_vev, spread_vev = load_mid_and_obi(day, "VEV_5000")
    
    corrs = lead_lag_analysis(ts_vfe, mid_vfe, ts_vev, mid_vev, max_lag=5)
    print("\\n1. Lead-Lag Correlation (VELVETFRUIT Returns vs VEV_5000 Returns)")
    if corrs:
        best_lag = max(corrs.items(), key=lambda x: abs(x[1]))
        print(f"   Best correlation at lag {best_lag[0]} (corr = {best_lag[1]:.4f})")
        for lag in range(-2, 3):
            print(f"   Lag {lag:>2}: {corrs.get(lag, 0):.4f}")
    else:
        print("   Insufficient data for correlation.")
        
    # 2. OBI Predictive Power on VELVETFRUIT
    obi_pred = analyze_obi_prediction(mid_vfe, obi_vfe, future_ticks=[1, 3, 5])
    print("\\n2. Order Book Imbalance (OBI) Predictive Power (VELVETFRUIT)")
    if obi_pred:
        print("   Average Future Returns by OBI Quintile (Q1=strong sell, Q5=strong buy):")
        print("   Tick |      Q1 |      Q2 |      Q3 |      Q4 |      Q5 |")
        for tick, means in obi_pred.items():
            print(f"     {tick:>2} | " + " | ".join([f"{m:>7.3f}" for m in means]) + " |")
    
    # 3. Spread Mean Reversion
    print("\\n3. Spread Edge Return Distributions (VELVETFRUIT)")
    if len(spread_vfe) > 1:
        s_arr = np.array(spread_vfe)
        m_arr = np.array(mid_vfe)
        # Wide spreads followed by reversion?
        wide_idx = np.where(s_arr[:-1] > np.median(s_arr))[0]
        narrow_idx = np.where(s_arr[:-1] <= np.median(s_arr))[0]
        
        diff_wide = np.abs(m_arr[wide_idx+1] - m_arr[wide_idx])
        diff_narrow = np.abs(m_arr[narrow_idx+1] - m_arr[narrow_idx])
        print(f"   Absolute Mid jump 1-tick after WIDE spread:   {np.mean(diff_wide):.3f}")
        print(f"   Absolute Mid jump 1-tick after NARROW spread: {np.mean(diff_narrow):.3f}")

    # 4. Same for Vouchers (VEV_5000)
    obi_pred_vev = analyze_obi_prediction(mid_vev, obi_vev, future_ticks=[1, 3, 5])
    print("\\n4. Order Book Imbalance (OBI) Predictive Power (VEV_5000)")
    if obi_pred_vev:
        print("   Average Future Returns by OBI Quintile (Q1=strong sell, Q5=strong buy):")
        print("   Tick |      Q1 |      Q2 |      Q3 |      Q4 |      Q5 |")
        for tick, means in obi_pred_vev.items():
            print(f"     {tick:>2} | " + " | ".join([f"{m:>7.3f}" for m in means]) + " |")

print("\\nDone.")
