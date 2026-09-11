import pandas as pd
import glob

files = sorted(glob.glob('data/round3/prices_round_3_day_*.csv'))
dfs = [pd.read_csv(f, sep=';') for f in files]
df = pd.concat(dfs, ignore_index=True)

hydro = df[df['product'] == 'HYDROGEL_PACK'].set_index(['day', 'timestamp'])['mid_price']
velvet = df[df['product'] == 'VELVETFRUIT_EXTRACT'].set_index(['day', 'timestamp'])['mid_price']

merged = pd.concat([hydro, velvet], axis=1)
merged.columns = ['HYDROGEL_PACK', 'VELVETFRUIT_EXTRACT']

print(f"Direct correlation: {merged.corr().iloc[0, 1]}")
print(f"Correlation of diffs: {merged.diff().corr().iloc[0, 1]}")

# Let's check cross-correlation (lagged)
for lag in range(-5, 6):
    corr = merged['HYDROGEL_PACK'].corr(merged['VELVETFRUIT_EXTRACT'].shift(lag))
    print(f"Lag {lag} (VELVETFRUIT_EXTRACT shifted by {lag}): {corr}")

