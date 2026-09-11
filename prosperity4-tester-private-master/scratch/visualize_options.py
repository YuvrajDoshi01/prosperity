import os
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/home/mmaliar/prosperity4-tester-private/prosperity4bt/resources/round3"
OUT_DIR = "/home/mmaliar/prosperity4-tester-private/scratch/plots"
os.makedirs(OUT_DIR, exist_ok=True)

STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VEV_PRODUCTS = [f'VEV_{k}' for k in STRIKES]
DAYS = [0, 1, 2]
TTE_MAP = {0: 8/365, 1: 7/365, 2: 6/365}
R = 0.0

plt.style.use('dark_background')

# Vectorized Black-Scholes IV solver (Newton-Raphson)
def vectorized_implied_vol(market_prices, S, K, T, r=0.0):
    sigma = np.full_like(market_prices, 0.3, dtype=float)
    intrinsic = np.maximum(0, S - K)
    
    # only compute where market_price > intrinsic
    valid = (market_prices > intrinsic + 1e-8) & (T > 1e-10)
    sigma_valid = sigma[valid]
    mp_valid = market_prices[valid]
    S_valid = S[valid]
    if isinstance(K, np.ndarray):
        K_valid = K[valid]
    else:
        K_valid = np.full_like(mp_valid, K)
    if isinstance(T, np.ndarray):
        T_valid = T[valid]
    else:
        T_valid = np.full_like(mp_valid, T)
        
    for _ in range(30):
        sigma_valid = np.maximum(sigma_valid, 0.001)
        d1 = (np.log(S_valid / K_valid) + (r + 0.5 * sigma_valid**2) * T_valid) / (sigma_valid * np.sqrt(T_valid))
        d2 = d1 - sigma_valid * np.sqrt(T_valid)
        
        price = S_valid * norm.cdf(d1) - K_valid * np.exp(-r * T_valid) * norm.cdf(d2)
        vega = S_valid * norm.pdf(d1) * np.sqrt(T_valid)
        
        diff = price - mp_valid
        
        # update
        step = diff / np.maximum(vega, 1e-12)
        sigma_valid -= step
        
        if np.max(np.abs(diff)) < 1e-4:
            break
            
    sigma[valid] = sigma_valid
    sigma[~valid] = np.nan
    
    # filter ridiculous IVs
    sigma = np.where((sigma < 0.001) | (sigma > 5.0), np.nan, sigma)
    return sigma

def load_and_prepare_data():
    all_data = []
    
    for d in DAYS:
        print(f"Loading Day {d}...")
        path = os.path.join(DATA_DIR, f'prices_round_3_day_{d}.csv')
        df = pd.read_csv(path, sep=';', on_bad_lines='skip')
        
        df = df[['timestamp', 'product', 'mid_price', 'bid_price_1', 'ask_price_1']].dropna(subset=['mid_price'])
        
        # We need underlying price at each timestamp
        underlying = df[df['product'] == 'VELVETFRUIT_EXTRACT'][['timestamp', 'mid_price']].rename(columns={'mid_price': 'S'})
        
        # Merge underlying back
        df = df.merge(underlying, on='timestamp', how='left')
        df['day'] = d
        # Adjust time so they are continuous across days
        df['global_time'] = d * 1000000 + df['timestamp']
        df['T'] = TTE_MAP[d]
        
        # Calculate spread
        df['spread'] = df['ask_price_1'] - df['bid_price_1']
        
        valid_opts = df[df['product'].str.startswith('VEV_')].copy()
        
        # Extract strike from product name
        valid_opts['K'] = valid_opts['product'].str.split('_').str[1].astype(float)
        
        # Set market price
        valid_opts['market_price'] = valid_opts['mid_price']
        
        # Compute IV
        print(f"Computing IV for Day {d}...")
        valid_opts['IV'] = vectorized_implied_vol(
            valid_opts['market_price'].values,
            valid_opts['S'].values,
            valid_opts['K'].values,
            valid_opts['T'].values
        )
        
        all_data.append(valid_opts)
        
        # Add velvetfruit data too for some plots
        v_df = df[df['product'] == 'VELVETFRUIT_EXTRACT'].copy()
        all_data.append(v_df)
        
    final_df = pd.concat(all_data, ignore_index=True)
    return final_df

print("Loading data...")
df = load_and_prepare_data()

print("Preprocessing complete. Starting to generate plots...")

# Separate options and underlying
opts = df[df['product'].str.startswith('VEV_')].copy()
uf = df[df['product'] == 'VELVETFRUIT_EXTRACT'].copy()

# Ensure types are good
opts['IV'] = pd.to_numeric(opts['IV'])
opts['K'] = pd.to_numeric(opts['K'])
opts['spread'] = pd.to_numeric(opts['spread'])
uf['mid_price'] = pd.to_numeric(uf['mid_price'])

# Plot 1: implied_vol_smile_by_contract
plt.figure(figsize=(10, 6))
sns.boxplot(data=opts, x='product', y='IV', order=VEV_PRODUCTS)
plt.xticks(rotation=45)
plt.title('Implied Volatility Summary By Contract')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'implied_vol_smile_by_contract.png'))
plt.close()
print("Saved implied_vol_smile_by_contract.png")

# Plot 2: implied_vol_smile_by_day
plt.figure(figsize=(10, 6))
day_smile = opts.groupby(['day', 'K'])['IV'].median().reset_index()
sns.lineplot(data=day_smile, x='K', y='IV', hue='day', marker='o', palette='Set1')
plt.title('Median IV Smile By Day')
plt.grid(alpha=0.3)
plt.savefig(os.path.join(OUT_DIR, 'implied_vol_smile_by_day.png'))
plt.close()
print("Saved implied_vol_smile_by_day.png")

# Plot 3: implied_vol_smile
plt.figure(figsize=(10, 6))
sns.scatterplot(data=opts, x='K', y='IV', alpha=0.01, color='lightblue')
median_smile = opts.groupby('K')['IV'].median().reset_index()
plt.plot(median_smile['K'], median_smile['IV'], 'r-o', linewidth=2, label='Median IV')
plt.title('Implied Volatility Smile (All Days Cloud + Median)')
plt.legend()
plt.grid(alpha=0.3)
plt.savefig(os.path.join(OUT_DIR, 'implied_vol_smile.png'))
plt.close()
print("Saved implied_vol_smile.png")

# Plot 4: implied_vol_timeseries
plt.figure(figsize=(14, 6))
sns.lineplot(data=opts, x='global_time', y='IV', hue='product', hue_order=VEV_PRODUCTS, alpha=0.7)
plt.title('Implied Volatility Timeseries')
plt.xticks([]) 
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'implied_vol_timeseries.png'))
plt.close()
print("Saved implied_vol_timeseries.png")

# Plot 5: iv_mean_vs_velvet_mid
mean_iv_time = opts.groupby('global_time')['IV'].mean().reset_index().rename(columns={'IV': 'mean_IV'})
uf_merged = uf.merge(mean_iv_time, on='global_time', how='inner')
plt.figure(figsize=(8, 6))
sns.scatterplot(data=uf_merged, x='mid_price', y='mean_IV', alpha=0.1, hue='day', palette='Set1')
plt.title('Mean IV vs VELVETFRUIT_EXTRACT Mid Price')
plt.grid(alpha=0.3)
plt.savefig(os.path.join(OUT_DIR, 'iv_mean_vs_velvet_mid.png'))
plt.close()
print("Saved iv_mean_vs_velvet_mid.png")

# Plot 6: iv_residuals
median_iv_c = opts.groupby('product')['IV'].median().reset_index().rename(columns={'IV': 'median_IV'})
opts = opts.merge(median_iv_c, on='product')
opts['IV_residual'] = opts['IV'] - opts['median_IV']

plt.figure(figsize=(14, 6))
sns.lineplot(data=opts, x='global_time', y='IV_residual', hue='product', hue_order=VEV_PRODUCTS, alpha=0.5)
plt.title('IV Residuals (IV - Contract Median IV) Over Time')
plt.xticks([])
plt.axhline(0, color='red', linestyle='--', alpha=0.5)
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'iv_residuals.png'))
plt.close()
print("Saved iv_residuals.png")

# Plot 7: iv_vs_strike_price
plt.figure(figsize=(10, 6))
sns.violinplot(data=opts, x='K', y='IV', inner='quartile')
plt.title('IV Distribution vs Strike Price')
plt.grid(axis='y', alpha=0.3)
plt.savefig(os.path.join(OUT_DIR, 'iv_vs_strike_price.png'))
plt.close()
print("Saved iv_vs_strike_price.png")

# Plot 8: iv_zscore_heatmap
def calc_zscore(group):
    group = group.sort_values('global_time')
    mean_roll = group['IV'].rolling(50, min_periods=10).mean()
    std_roll = group['IV'].rolling(50, min_periods=10).std()
    group['IV_zscore'] = (group['IV'] - mean_roll) / (std_roll + 1e-6)
    return group

opts = opts.groupby('product', group_keys=False).apply(calc_zscore)
opts['time_bin'] = pd.cut(opts['global_time'], bins=150, labels=False)
heatmap_data = opts.groupby(['product', 'time_bin'])['IV_zscore'].mean().unstack()
# Safely reindex to handle any missing ones
heatmap_valid = [p for p in VEV_PRODUCTS if p in heatmap_data.index]
heatmap_data = heatmap_data.loc[heatmap_valid]

plt.figure(figsize=(14, 6))
sns.heatmap(heatmap_data, cmap='coolwarm', center=0, cbar_kws={'label': 'IV Z-Score (Rolling 50 ticks)'})
plt.title('IV Z-Score Heatmap (Rows=Contract, Cols=Time Bins)')
plt.xlabel('Time Bin (Global)')
plt.ylabel('Contract')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'iv_zscore_heatmap.png'))
plt.close()
print("Saved iv_zscore_heatmap.png")

# Plot 9: market_bid_ask_spreads
plt.figure(figsize=(12, 6))
sns.boxplot(data=opts, x='product', y='spread', order=VEV_PRODUCTS)
plt.title('Market Bid-Ask Spreads By Contract')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'market_bid_ask_spreads.png'))
plt.close()
print("Saved market_bid_ask_spreads.png")

# Plot 10: market_iv_term_structure
plt.figure(figsize=(10, 6))
term_struct = opts.groupby(['K', 'T'])['IV'].median().reset_index()
sns.lineplot(data=term_struct, x='T', y='IV', hue='K', palette='viridis', marker='o')
plt.gca().invert_xaxis()
plt.xlabel('Time To Expiry (TTE, years)')
plt.title('Market IV Term Structure (IV vs TTE per Strike)')
plt.legend(title='Strike', bbox_to_anchor=(1.05, 1), loc='upper left')
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'market_iv_term_structure.png'))
plt.close()
print("Saved market_iv_term_structure.png")

# Plot 11: market_regime_cross_asset
uf = uf.sort_values('global_time')
uf['ret'] = uf['mid_price'].pct_change()
opts = opts.sort_values(['product', 'global_time'])
opts['opt_ret'] = opts.groupby('product')['mid_price'].pct_change()
merged_ret = opts[['global_time', 'product', 'opt_ret']].merge(uf[['global_time', 'ret']], on='global_time', how='inner')

plt.figure(figsize=(10, 6))
sample_ret = merged_ret.dropna().sample(min(20000, len(merged_ret.dropna())))
sns.scatterplot(data=sample_ret, x='ret', y='opt_ret', alpha=0.3, hue='product', palette='tab10', s=10)
plt.title('Cross-Asset Return Distribution (Underlying vs Options)')
plt.xlabel('VELVETFRUIT_EXTRACT Return')
plt.ylabel('Option Mid Return')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.axvline(0, color='red', linestyle='--', alpha=0.3)
plt.axhline(0, color='red', linestyle='--', alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'market_regime_cross_asset.png'))
plt.close()
print("Saved market_regime_cross_asset.png")

# Plot 12: market_regime_underlying
plt.figure(figsize=(14, 6))
ax1 = plt.gca()
ax2 = ax1.twinx()
ax1.plot(uf['global_time'], uf['mid_price'], color='dodgerblue', alpha=0.7, label='Mid Price')
ax1.set_ylabel('VELVETFRUIT Mid', color='dodgerblue')
ax1.tick_params(axis='y', labelcolor='dodgerblue')

uf['roll_vol'] = uf['ret'].rolling(200).std() * np.sqrt(250000) 
ax2.plot(uf['global_time'], uf['roll_vol'], color='tomato', alpha=0.5, label='Rolling Vol (200 ticks)')
ax2.set_ylabel('Rolling Volatility (Proxy)', color='tomato')
ax2.tick_params(axis='y', labelcolor='tomato')

ax1.set_xticks([])
plt.title('Underlying Market Regime (Price and Rolling Volatility)')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'market_regime_underlying.png'))
plt.close()
print("Saved market_regime_underlying.png")

print("All plots generated in", OUT_DIR)
