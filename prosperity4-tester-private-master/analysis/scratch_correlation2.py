import pandas as pd
import glob
import matplotlib.pyplot as plt

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

# Is one roughly double the other?
print("Mean HYDROGEL:", merged['HYDROGEL'].mean())
print("Mean VELVET:", merged['VELVET'].mean())
print("Ratio:", merged['HYDROGEL'].mean() / merged['VELVET'].mean())

# Plot them
fig, ax1 = plt.subplots(figsize=(10, 6))

color = 'tab:red'
ax1.set_xlabel('Time')
ax1.set_ylabel('HYDROGEL', color=color)
ax1.plot(merged.reset_index(drop=True).index, merged['HYDROGEL'].values, color=color, alpha=0.5)
ax1.tick_params(axis='y', labelcolor=color)

ax2 = ax1.twinx()
color = 'tab:blue'
ax2.set_ylabel('VELVET', color=color)
ax2.plot(merged.reset_index(drop=True).index, merged['VELVET'].values, color=color, alpha=0.5)
ax2.tick_params(axis='y', labelcolor=color)

fig.tight_layout()
plt.savefig('artifacts/hydro_velvet.png')

