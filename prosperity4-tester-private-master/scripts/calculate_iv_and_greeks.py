import pandas as pd
import numpy as np
import os
import glob
from scipy.stats import norm
from scipy.optimize import brentq

DAYS_IN_YEAR = 250.0  # Standard for Prosperity trading year

def bs_call(S, K, T, r, sigma):
    if T <= 0:
        return np.maximum(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

def bs_vega(S, K, T, r, sigma):
    if T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return S * norm.pdf(d1) * np.sqrt(T)

def bs_delta(S, K, T, r, sigma):
    if T <= 0:
        return 1.0 if S > K else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1)

def bs_gamma(S, K, T, r, sigma):
    if T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))

def bs_theta(S, K, T, r, sigma):
    if T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)
    return theta

def bs_rho(S, K, T, r, sigma):
    if T <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * T * np.exp(-r * T) * norm.cdf(d2)

def implied_volatility(P_market, S, K, T, r):
    if T <= 0:
        return 0.0
    # Intrinsic value
    intrinsic = np.maximum(S - K, 0.0)
    if P_market <= intrinsic:
        return 0.0 # Cannot have IV if price is below intrinsic (arbitrage, or just deep ITM with 0 time value)
    
    def objective_function(sigma):
        return bs_call(S, K, T, r, sigma) - P_market
    
    try:
        # Volatility usually between 0.0001 and 10.0 (1000%)
        iv = brentq(objective_function, 1e-4, 10.0)
        return iv
    except ValueError:
        return np.nan

def main():
    data_dir = 'data/round3'
    output_dir = 'data/round3_greeks'
    os.makedirs(output_dir, exist_ok=True)
    
    files = glob.glob(os.path.join(data_dir, 'prices_round_3_day_*.csv'))
    
    # Mapping for TTE
    tte_start_mapping = {
        0: 8,
        1: 7,
        2: 6
    }
    
    for f in sorted(files):
        print(f"Processing {f}...")
        df = pd.read_csv(f, sep=';')
        
        # Get the day
        day = df['day'].iloc[0]
        
        if day not in tte_start_mapping:
            print(f"Skipping day {day}")
            continue
            
        tte_start_days = tte_start_mapping[day]
        
        # Extract underlying prices
        df_underlying = df[df['product'] == 'VELVETFRUIT_EXTRACT'][['timestamp', 'mid_price']].copy()
        df_underlying.rename(columns={'mid_price': 'S'}, inplace=True)
        
        # Merge underlying prices to the main dataframe
        df = df.merge(df_underlying, on='timestamp', how='left')
        
        # Filter for options
        options_prefix = 'VEV_'
        df_options = df[df['product'].str.startswith(options_prefix)].copy()
        
        # Extract K
        df_options['K'] = df_options['product'].str.replace(options_prefix, '').astype(float)
        
        # TTE computation
        # timestamp goes from 0 to 999900 (steps of 100 usually), 1,000,000 represents 1 day
        df_options['TTE_days'] = tte_start_days - (df_options['timestamp'] / 1_000_000)
        df_options['T_years'] = df_options['TTE_days'] / DAYS_IN_YEAR
        
        # We assume r = 0 for the game
        r = 0.0
        
        def calc_row(row):
            S = row['S']
            K = row['K']
            T = row['T_years']
            P_market = row['mid_price']
            
            if pd.isna(P_market) or pd.isna(S):
                return pd.Series([np.nan]*6, index=['IV', 'Delta', 'Gamma', 'Vega', 'Theta', 'Rho'])
                
            iv = implied_volatility(P_market, S, K, T, r)
            if pd.isna(iv) or iv == 0.0:
                delta = 1.0 if S > K else 0.0
                gamma = 0.0
                vega = 0.0
                theta = 0.0
                rho = 0.0
            else:
                delta = bs_delta(S, K, T, r, iv)
                gamma = bs_gamma(S, K, T, r, iv)
                vega = bs_vega(S, K, T, r, iv)
                theta = bs_theta(S, K, T, r, iv)
                rho = bs_rho(S, K, T, r, iv)
                
            return pd.Series([iv, delta, gamma, vega, theta, rho], index=['IV', 'Delta', 'Gamma', 'Vega', 'Theta', 'Rho'])
        
        # Apply calculations
        print("Calculating IV and Greeks...")
        greeks = df_options.apply(calc_row, axis=1)
        
        # Join back
        df_options = pd.concat([df_options, greeks], axis=1)
        
        # Save output
        out_name = os.path.basename(f).replace('prices_', 'greeks_')
        out_path = os.path.join(output_dir, out_name)
        df_options.to_csv(out_path, sep=';', index=False)
        print(f"Saved {out_path}\n")

if __name__ == '__main__':
    main()
