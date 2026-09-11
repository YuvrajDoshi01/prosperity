import pandas as pd
import glob

files = sorted(glob.glob('data/round3/prices_round_3_day_*.csv'))
dfs = [pd.read_csv(f, sep=';') for f in files]
df = pd.concat(dfs, ignore_index=True)

hydro = df[df['product'] == 'HYDROGEL_PACK'].set_index(['day', 'timestamp'])['mid_price']
velvet = df[df['product'] == 'VELVETFRUIT_EXTRACT'].set_index(['day', 'timestamp'])['mid_price']

merged = pd.concat([hydro, velvet], axis=1)
merged.columns = ['HYDROGEL', 'VELVET']
merged = merged.dropna()

print(merged.head())
print("Corr:", merged.corr().iloc[0, 1])

print("Mean HYDROGEL:", merged['HYDROGEL'].mean())
print("Mean VELVET:", merged['VELVET'].mean())
print("Ratio:", merged['HYDROGEL'].mean() / merged['VELVET'].mean())

merged['rolling_corr'] = merged['HYDROGEL'].rolling(100).corr(merged['VELVET'])
print("Mean rolling corr (100-period):", merged['rolling_corr'].mean())

# Check rolling correlation of diffs
diffs = merged[['HYDROGEL', 'VELVET']].diff().dropna()
print("Diffs Corr:", diffs.corr().iloc[0, 1])
diffs['rolling_corr'] = diffs['HYDROGEL'].rolling(100).corr(diffs['VELVET'])
print("Mean diff rolling corr (100-period):", diffs['rolling_corr'].mean())
