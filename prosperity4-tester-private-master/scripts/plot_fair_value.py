import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import argparse
from scipy.stats import norm

def bs_call(S, K, T, r, sigma):
    # Handle cases where T <= 0
    T_safe = np.maximum(T, 1e-8)
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T_safe) / (sigma * np.sqrt(T_safe))
    d2 = d1 - sigma * np.sqrt(T_safe)
    
    call_price = S * norm.cdf(d1) - K * np.exp(-r * T_safe) * norm.cdf(d2)
    
    # If T <= 0, return intrinsic
    return np.where(T <= 0, np.maximum(S - K, 0.0), call_price)

def main():
    parser = argparse.ArgumentParser(description="Plot Fair Value vs Actual Price")
    parser.add_argument('--day', type=int, default=0, help='Day to plot (0, 1, or 2)')
    args = parser.parse_args()

    filepath = f"data/round3_greeks/greeks_round_3_day_{args.day}.csv"
    if not os.path.exists(filepath):
        print(f"File {filepath} not found. Ensure calculate_iv_and_greeks.py has been run.")
        return

    print(f"Loading data for Day {args.day}...")
    df = pd.read_csv(filepath, sep=';')
    
    out_dir = "data/round3_fair_value"
    os.makedirs(out_dir, exist_ok=True)
    
    # Calculate Historical Volatility of the underlying
    # S is the same for all options at a given timestamp, so just grab one option's S
    df_underlying = df[df['product'] == 'VEV_5000'].copy().sort_values('timestamp')
    log_returns = np.log(df_underlying['S'] / df_underlying['S'].shift(1))
    
    # 10,000 timestamps per day, 250 days per year
    historical_volatility = log_returns.std() * np.sqrt(10000 * 250)
    print(f"Calculated Historical Volatility (Annualized): {historical_volatility:.4f} (or {historical_volatility*100:.2f}%)")
    
    # Alternatively, median IV of options with IV > 0. Let's print it for context.
    median_iv = df[df['IV'] > 0]['IV'].median()
    print(f"Median Implied Volatility (for context): {median_iv:.4f} (or {median_iv*100:.2f}%)")
    
    # Let's use the historical volatility to price fair value
    # We can also use ATM IV, but HV is a common "true" fair value baseline.
    sigma = historical_volatility
    r = 0.0
    
    df['Fair_Value'] = bs_call(df['S'].values, df['K'].values, df['T_years'].values, r, sigma)
    df['Abs_Diff'] = np.abs(df['mid_price'] - df['Fair_Value'])
    df['Diff'] = df['mid_price'] - df['Fair_Value']
    
    products = sorted(df['product'].unique())
    
    print(f"Plotting options...")
    for prod in products:
        prod_df = df[df['product'] == prod].sort_values('timestamp')
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
        fig.suptitle(f"Fair Value vs Market Price: {prod} (Day {args.day})", fontsize=16, fontweight='bold')
        
        # Top plot: Prices
        ax1.plot(prod_df['timestamp'], prod_df['mid_price'], label='Market Price (mid_price)', color='blue', alpha=0.8)
        ax1.plot(prod_df['timestamp'], prod_df['Fair_Value'], label=f'BS Fair Value (HV = {sigma*100:.1f}%)', color='orange', alpha=0.8, linestyle='--')
        ax1.set_ylabel('Price', fontsize=12)
        ax1.legend(loc='best')
        ax1.grid(True, linestyle='--', alpha=0.5)
        
        # Bottom plot: Difference
        ax2.plot(prod_df['timestamp'], prod_df['Abs_Diff'], label='Absolute Diff', color='red', alpha=0.7)
        ax2.set_xlabel('Timestamp', fontsize=12)
        ax2.set_ylabel('Abs Difference', fontsize=12)
        ax2.legend(loc='best')
        ax2.grid(True, linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        
        out_file = os.path.join(out_dir, f"{prod}_day_{args.day}.png")
        plt.savefig(out_file, dpi=300)
        plt.close(fig)
        
    print(f"Saved fair value graphs to {out_dir}/")

if __name__ == '__main__':
    main()
