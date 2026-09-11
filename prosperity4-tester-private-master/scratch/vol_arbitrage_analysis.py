import os
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/home/mmaliar/prosperity4-tester-private/prosperity4bt/resources/round3"
OUT_DIR = "/home/mmaliar/prosperity4-tester-private/scratch/plots/vol_arb"
os.makedirs(OUT_DIR, exist_ok=True)

DAYS = [0, 1, 2]
TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
R = 0.0

plt.style.use('dark_background')

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

print("Loading data...")
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

# 1. Compute underlying returns and Realized Volatility
# Assume 1 tick is roughly 1 second in Prosperity. Assume 10,000 ticks a day.
# Annualization = 250 days * 10,000 ticks = 2,500,000
ANNUAL_TICKS = 2500000
uf['ret'] = uf['mid_price'].pct_change()
# Keep Realized Vol (RV) as moving standard deviation of returns * sqrt(annual_ticks)
uf['rv_100'] = uf['ret'].rolling(100).std() * np.sqrt(ANNUAL_TICKS)
uf['rv_100'] = uf['rv_100'].fillna(method='bfill')

# Merge RV into opts
opts = opts.merge(uf[['global_time', 'ret', 'rv_100']], on='global_time', how='inner')

# Calculate option forward mid-price differences (to calculate PnL of simple trades)
opts['opt_fwd_diff'] = opts.groupby('product')['mid_price'].diff(-1) * -1 # price[t+1] - price[t]
opts['IV_pct'] = opts['IV'] * 100 # work in percentage for IV readability
opts['RV_pct'] = opts['rv_100'] * 100

print("Calculating Volatility Arbitrage Signals & PnL...")

def calc_signals(group):
    group = group.sort_values('global_time')
    # Rolling IV mean and std for mean reversion
    roll_mean = group['IV_pct'].rolling(100).mean()
    roll_std = group['IV_pct'].rolling(100).std()
    
    # Signal 1: Z-score mean reversion
    group['iv_zscore'] = (group['IV_pct'] - roll_mean) / (roll_std + 1e-6)
    # Strategy 1: if z < -1.5 (too low), buy (pos=+1). If z > 1.5, sell (pos=-1)
    group['pos_iv_reversion'] = 0
    group.loc[group['iv_zscore'] < -1.5, 'pos_iv_reversion'] = 1
    group.loc[group['iv_zscore'] > 1.5, 'pos_iv_reversion'] = -1
    
    # Strategy 2: RV vs IV
    # If RV > IV by 5% (volatility is underpriced in options), buy. If RV < IV by 5%, sell.
    group['vol_spread'] = group['RV_pct'] - group['IV_pct']
    group['pos_rv_iv'] = 0
    group.loc[group['vol_spread'] > 5.0, 'pos_rv_iv'] = 1
    group.loc[group['vol_spread'] < -5.0, 'pos_rv_iv'] = -1
    
    # Compute simple daily PnL without transaction costs (Delta-neutrality is assumed not needed, but realistically required)
    # To keep analysis simple, we just look at holding the option unhedged to see basic alpha. 
    # (Since this is a quick estimate)
    group['pnl_rev'] = group['pos_iv_reversion'] * group['opt_fwd_diff']
    group['pnl_rv'] = group['pos_rv_iv'] * group['opt_fwd_diff']
    
    # IV diffs for correlation
    group['delta_iv'] = group['IV_pct'].diff()
    return group

opts = opts.groupby('product', group_keys=False).apply(calc_signals)

# Aggregate cumulative PnL
opts['cum_pnl_rev'] = opts.groupby('product')['pnl_rev'].cumsum()
opts['cum_pnl_rv'] = opts.groupby('product')['pnl_rv'].cumsum()

# PLOT 1: Theoretical PnL - IV Mean Reversion
plt.figure(figsize=(12, 6))
sns.lineplot(data=opts, x='global_time', y='cum_pnl_rev', hue='product', alpha=0.8)
plt.title('Est. PnL: Mean Reversion Strategy (Buy Z < -1.5, Sell Z > 1.5)')
plt.ylabel('Cumulative PnL (Shells per 1 Option)')
plt.xticks([])
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'pnl_iv_reversion.png'))
plt.close()

# PLOT 2: Theoretical PnL - RV vs IV 
plt.figure(figsize=(12, 6))
sns.lineplot(data=opts, x='global_time', y='cum_pnl_rv', hue='product', alpha=0.8)
plt.title('Est. PnL: RV vs IV Strategy (Buy RV > IV+5%, Sell RV < IV-5%)')
plt.ylabel('Cumulative PnL (Shells per 1 Option)')
plt.xticks([])
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'pnl_rv_vs_iv.png'))
plt.close()

print("Calculating Lead-Lag Correlations...")

# Lag Analysis
lags = [-5, -3, -1, 0, 1, 3, 5]
corr_results_spot = []
corr_results_rv = []

for lag in lags:
    # shift positive means taking future values of spot. 
    # If lag > 0: corr(delta_iv[t], ret[t - lag]). "Do past returns predict current IV changes?"
    opt_sub = opts[['global_time', 'product', 'delta_iv']].copy()
    uf_sub = uf[['global_time', 'ret', 'rv_100']].copy()
    
    # shift uf
    uf_sub['ret_lagged'] = uf_sub['ret'].shift(lag)
    uf_sub['rv_diff_lagged'] = uf_sub['rv_100'].diff().shift(lag)
    
    merged = opt_sub.merge(uf_sub, on='global_time', how='inner').dropna()
    
    # Calculate corr for each product
    for prod, g in merged.groupby('product'):
        c_spot = g['delta_iv'].corr(g['ret_lagged'])
        c_rv = g['delta_iv'].corr(g['rv_diff_lagged'])
        corr_results_spot.append({'product': prod, 'lag': lag, 'corr': c_spot})
        corr_results_rv.append({'product': prod, 'lag': lag, 'corr': c_rv})

df_corr_spot = pd.DataFrame(corr_results_spot)
df_corr_rv = pd.DataFrame(corr_results_rv)

# PLOT 3: Spot-Vol Correlation
plt.figure(figsize=(10, 6))
sns.lineplot(data=df_corr_spot, x='lag', y='corr', hue='product', marker='o')
plt.title('Lead-Lag: Spot Returns vs Option IV Changes')
plt.xlabel('Lag (Ticks). X > 0 means Asset Return Precedes IV Change')
plt.ylabel('Correlation')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.grid(alpha=0.3)
plt.axvline(0, color='red', linestyle='--', alpha=0.5)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'corr_spot_vol_lags.png'))
plt.close()

# PLOT 4: RV-Vol Correlation
plt.figure(figsize=(10, 6))
sns.lineplot(data=df_corr_rv, x='lag', y='corr', hue='product', marker='o')
plt.title('Lead-Lag: Realized Volatility Changes vs Option IV Changes')
plt.xlabel('Lag (Ticks). X > 0 means Realized Vol Change Precedes IV Change')
plt.ylabel('Correlation')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.grid(alpha=0.3)
plt.axvline(0, color='red', linestyle='--', alpha=0.5)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'corr_rv_iv_lags.png'))
plt.close()

print("Detecting Jumps & Modes...")

# Detecting Modes where IV Jumps heavily
# We define a jump as an absolute delta_iv > 3 standard deviations of typical delta_iv
opts['delta_iv_abs'] = opts['delta_iv'].abs()
jump_flags = []

def calc_jumps(group):
    std_iv = group['delta_iv'].std()
    group['is_jump'] = group['delta_iv_abs'] > (3 * std_iv)
    return group

opts = opts.groupby('product', group_keys=False).apply(calc_jumps)

# PLOT 5: IV Jump occurrences
plt.figure(figsize=(14, 6))
# Plot base IV for VEV_5000 as reference
sample_opt = opts[opts['product'] == 'VEV_5000']
plt.plot(sample_opt['global_time'], sample_opt['IV_pct'], label='VEV_5000 IV', color='gray', alpha=0.5)

# Scatter red dots where any option jumped
jumps = opts[opts['is_jump'] == True]
plt.scatter(jumps['global_time'], jumps['IV_pct'], color='red', s=10, label='Major IV Jump Detected', zorder=5)

plt.title('Regime Modes: Clustered IV Jumps Across Time')
plt.xlabel('Global Time')
plt.ylabel('Implied Volatility (%)')
plt.xticks([])
plt.legend()
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'iv_jump_regimes.png'))
plt.close()

print("Analyses complete. Plots saved in", OUT_DIR)
