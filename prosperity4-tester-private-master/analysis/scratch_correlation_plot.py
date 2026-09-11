import pandas as pd
import glob
import matplotlib.pyplot as plt

files = sorted(glob.glob('/Users/mmaliar/src/prosperity4-tester-private/data/round3/prices_round_3_day_*.csv'))
dfs = [pd.read_csv(f, sep=';') for f in files]
df = pd.concat(dfs, ignore_index=True)

hydro = df[df['product'] == 'HYDROGEL_PACK'].set_index(['day', 'timestamp'])['mid_price']
velvet = df[df['product'] == 'VELVETFRUIT_EXTRACT'].set_index(['day', 'timestamp'])['mid_price']

merged = pd.concat([hydro, velvet], axis=1)
merged.columns = ['HYDROGEL', 'VELVET']
merged = merged.dropna()

print("Overall corr:", merged.corr().iloc[0, 1])

for day in merged.index.get_level_values('day').unique():
    day_data = merged.xs(day, level='day')
    corr = day_data.corr().iloc[0, 1]
    print(f"Day {day} corr: {corr}")

# plot
plt.figure(figsize=(10,6))
plt.scatter(merged['VELVET'], merged['HYDROGEL'], alpha=0.1)
plt.title('Scatter of Velvet vs Hydrogel')
plt.xlabel('Velvet')
plt.ylabel('Hydrogel')
import os
os.makedirs('/Users/mmaliar/src/prosperity4-tester-private/analysis/artifacts', exist_ok=True)
plt.savefig('/Users/mmaliar/src/prosperity4-tester-private/analysis/artifacts/scatter.png')

plt.figure(figsize=(12, 6))
plt.plot(merged.values[:, 0] / merged.values[0, 0], label='Hydrogel (normalized)')
plt.plot(merged.values[:, 1] / merged.values[0, 1], label='Velvet (normalized)')
plt.legend()
plt.savefig('/Users/mmaliar/src/prosperity4-tester-private/analysis/artifacts/lines.png')

