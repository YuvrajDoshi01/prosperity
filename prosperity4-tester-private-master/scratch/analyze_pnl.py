import json
import pandas as pd
from io import StringIO

log_path = "/home/mmaliar/prosperity4-tester-private/imc_logs/421553/421553.json"

with open(log_path) as f:
    data = json.load(f)

raw_log = data.get("activitiesLog", "")

csv_lines = []
in_csv = False

for line in raw_log.split("\n"):
    if line.startswith("day;timestamp;product"):
        in_csv = True
        csv_lines.append(line)
    elif in_csv:
        if line.strip() == "" or "Trade History:" in line:
            in_csv = False
        else:
            csv_lines.append(line)

csv_text = "\n".join(csv_lines)
if not csv_text:
    print("Could not find activities CSV log.")
    exit()

df = pd.read_csv(StringIO(csv_text), sep=";")
df["pnl"] = pd.to_numeric(df["profit_and_loss"], errors='coerce')
df["timestamp"] = pd.to_numeric(df["timestamp"], errors='coerce')
df = df.dropna(subset=["timestamp"])
df["timestamp"] = df["timestamp"].astype(int)

pnl_matrix = df.pivot(index="timestamp", columns="product", values="pnl")
# ffill will copy last known PnL, because when no trade on tick, product might not be logged or PnL is carried forward
pnl_matrix = pnl_matrix.ffill().fillna(0)

pnl_matrix["TOTAL"] = pnl_matrix.sum(axis=1)

print("Final PnL by Product:")
print(pnl_matrix.iloc[-1].to_string())

max_pnl = pnl_matrix["TOTAL"].cummax()
drawdown = pnl_matrix["TOTAL"] - max_pnl
max_dd = drawdown.min()
max_dd_timestamp = drawdown.idxmin()
peak_pnl = pnl_matrix["TOTAL"].max()
peak_timestamp = pnl_matrix["TOTAL"].idxmax()

print(f"\nPeak PnL: {peak_pnl} at timestamp {peak_timestamp}")
print(f"Max Drawdown: {max_dd} ending at timestamp {max_dd_timestamp}")

mid_point = df["timestamp"].max() // 2
first_half = pnl_matrix.loc[pnl_matrix.index <= mid_point]
second_half = pnl_matrix.loc[pnl_matrix.index > mid_point]

print("\n--- First Half Ending PnL ---")
print(first_half.iloc[-1].to_string())

print("\n--- Second Half PnL Change ---")
pnl_change = second_half.iloc[-1] - first_half.iloc[-1]
print(pnl_change.to_string())

print(f"\n--- Drawdown Attribution (From {peak_timestamp} to {max_dd_timestamp}) ---")
dd_start = pnl_matrix.loc[peak_timestamp]
dd_end = pnl_matrix.loc[max_dd_timestamp]
dd_diff = dd_end - dd_start
print(dd_diff.sort_values().to_string())
