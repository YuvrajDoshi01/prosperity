import os
import pandas as pd

r3_dir = "/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages/prosperity4bt/resources/round3"
r4_dir = "/home/mmaliar/prosperity4-tester-private/venv/lib/python3.14/site-packages/prosperity4bt/resources/round4"

os.makedirs(r4_dir, exist_ok=True)

# Truncate prices
p_file = f"{r3_dir}/prices_round_3_day_0.csv"
df_p = pd.read_csv(p_file, sep=";")
df_p_trunc = df_p[df_p["timestamp"] <= 4900]
df_p_trunc.to_csv(f"{r4_dir}/prices_round_4_day_0.csv", sep=";", index=False)
df_p_trunc.to_csv(f"{r4_dir}/prices_round_3_day_0.csv", sep=";", index=False)

# Truncate trades
t_file = f"{r3_dir}/trades_round_3_day_0.csv"
df_t = pd.read_csv(t_file, sep=";")
df_t_trunc = df_t[df_t["timestamp"] <= 4900]
df_t_trunc.to_csv(f"{r4_dir}/trades_round_4_day_0.csv", sep=";", index=False)
df_t_trunc.to_csv(f"{r4_dir}/trades_round_3_day_0.csv", sep=";", index=False)

print("Truncation complete!")
