import os
import numpy as np
import pandas as pd
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/home/mmaliar/prosperity4-tester-private/prosperity4bt/resources/round3"
DAYS = [0, 1, 2]
TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}

def vectorized_implied_vol(market_prices, S, K, T, r=0.0):
    sigma = np.full_like(market_prices, 0.3, dtype=float)
    intrinsic = np.maximum(0, S - K)
    valid = (market_prices > intrinsic + 1e-8) & (T > 1e-10)
    sigma_valid = sigma[valid]
    mp_valid = market_prices[valid]
    S_valid = S[valid]
    K_valid = np.full_like(mp_valid, K) if not isinstance(K, np.ndarray) else K[valid]
    T_valid = np.full_like(mp_valid, T) if not isinstance(T, np.ndarray) else T[valid]
        
    for _ in range(30):
        sigma_valid = np.maximum(sigma_valid, 0.001)
        d1 = (np.log(S_valid / K_valid) + (r + 0.5 * sigma_valid**2) * T_valid) / (sigma_valid * np.sqrt(T_valid))
        d2 = d1 - sigma_valid * np.sqrt(T_valid)
        price = S_valid * norm.cdf(d1) - K_valid * np.exp(-r * T_valid) * norm.cdf(d2)
        vega = S_valid * norm.pdf(d1) * np.sqrt(T_valid)
        diff = price - mp_valid
        step = diff / np.maximum(vega, 1e-12)
        sigma_valid -= step
        if np.max(np.abs(diff)) < 1e-4: break
            
    sigma[valid] = sigma_valid
    sigma[~valid] = np.nan
    sigma = np.where((sigma < 0.001) | (sigma > 5.0), np.nan, sigma)
    return sigma

all_data = []
for d in DAYS:
    path = os.path.join(DATA_DIR, f'prices_round_3_day_{d}.csv')
    df = pd.read_csv(path, sep=';', on_bad_lines='skip')
    df = df[['timestamp', 'product', 'mid_price']].dropna()
    underlying = df[df['product'] == 'VELVETFRUIT_EXTRACT'][['timestamp', 'mid_price']].rename(columns={'mid_price': 'S'})
    df = df.merge(underlying, on='timestamp', how='left')
    df['day'] = d
    df['global_time'] = d * 1000000 + df['timestamp']
    df['T'] = TTE_MAP[d]
    valid_opts = df[df['product'].str.startswith('VEV_')].copy()
    valid_opts['K'] = valid_opts['product'].str.split('_').str[1].astype(float)
    valid_opts['IV'] = vectorized_implied_vol(valid_opts['mid_price'].values, valid_opts['S'].values, valid_opts['K'].values, valid_opts['T'].values)
    all_data.append(valid_opts)
    
    v_df = df[df['product'] == 'VELVETFRUIT_EXTRACT'].copy()
    all_data.append(v_df)

df = pd.concat(all_data, ignore_index=True)
opts = df[df['product'].str.startswith('VEV_')].copy().sort_values(['product', 'global_time'])
uf = df[df['product'] == 'VELVETFRUIT_EXTRACT'].copy().sort_values('global_time')

ANNUAL_TICKS = 2500000
uf['ret'] = uf['mid_price'].pct_change()
uf['rv_100'] = uf['ret'].rolling(100).std() * np.sqrt(ANNUAL_TICKS)
uf['rv_100'] = uf['rv_100'].fillna(method='bfill')

opts = opts.merge(uf[['global_time', 'ret', 'rv_100']], on='global_time', how='inner')
opts['opt_fwd_diff'] = opts.groupby('product')['mid_price'].diff(-1) * -1 
opts['IV_pct'] = opts['IV'] * 100 
opts['RV_pct'] = opts['rv_100'] * 100

def calc_signals(group):
    group = group.sort_values('global_time')
    roll_mean = group['IV_pct'].rolling(100).mean()
    roll_std = group['IV_pct'].rolling(100).std()
    
    group['iv_zscore'] = (group['IV_pct'] - roll_mean) / (roll_std + 1e-6)
    
    group['pos_iv_reversion'] = 0
    group.loc[group['iv_zscore'] < -1.5, 'pos_iv_reversion'] = 1
    group.loc[group['iv_zscore'] > 1.5, 'pos_iv_reversion'] = -1
    
    group['vol_spread'] = group['RV_pct'] - group['IV_pct']
    group['pos_rv_iv'] = 0
    group.loc[group['vol_spread'] > 3.0, 'pos_rv_iv'] = 1
    group.loc[group['vol_spread'] < -3.0, 'pos_rv_iv'] = -1
    
    group['pnl_rev'] = group['pos_iv_reversion'] * group['opt_fwd_diff']
    group['pnl_rv'] = group['pos_rv_iv'] * group['opt_fwd_diff']
    
    return group

opts = opts.groupby('product', group_keys=False).apply(calc_signals)

tot_rev = opts.groupby('product')['pnl_rev'].sum()
tot_rv = opts.groupby('product')['pnl_rv'].sum()

print("--- PNL RESULTS ---")
print("Total Expected PnL (Mean Reversion - IV Z-Score):", tot_rev.sum())
print("Total Expected PnL (RV vs IV spread):", tot_rv.sum())

print("\\nDetails per instrument:")
for p in tot_rev.index:
    print(f"{p}: Rev PnL = {tot_rev[p]:.2f}, RV PnL = {tot_rv[p]:.2f}")
