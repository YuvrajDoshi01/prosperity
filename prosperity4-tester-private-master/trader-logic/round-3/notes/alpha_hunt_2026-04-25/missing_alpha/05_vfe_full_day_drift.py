"""H5: VFE full-day drift. Naked-long EV?"""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

for day in [0, 1, 2]:
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    v = p[p["product"] == "VELVETFRUIT_EXTRACT"].reset_index(drop=True)
    open_p = v.iloc[0]["mid_price"]
    close_p = v.iloc[-1]["mid_price"]
    high = v["mid_price"].max()
    low = v["mid_price"].min()
    print(f"Day {day}: open={open_p:.0f} close={close_p:.0f} drift={close_p-open_p:+.0f} (low={low:.0f} hi={high:.0f})")
    print(f"  Buy-and-hold +200: ${(close_p-open_p)*200:+,.0f}")
    print(f"  Max drawdown of +200: ${(low-open_p)*200:+,.0f} (intraday low - open)")
    # 5-min EMA vs 30-min EMA crossover
    v["ema5"] = v["mid_price"].ewm(span=50, adjust=False).mean()  # 5m if 100ms tick = 50t per ~5s, but this is loose
    v["ema30"] = v["mid_price"].ewm(span=300, adjust=False).mean()
    # Trend: long if ema5 > ema30
    trend_long = (v["ema5"] > v["ema30"])
    # PnL: hold +200 when trend_long, +0 otherwise
    v["dmid"] = v["mid_price"].diff()
    pnl_trend_200 = (v["dmid"].shift(-1) * trend_long * 200).sum()
    print(f"  Trend-following EMA50/300 long-only +200: ${pnl_trend_200:+,.0f}")
    # Symmetric long/short
    pnl_ls = (v["dmid"].shift(-1) * np.where(trend_long, 200, -200)).sum()
    print(f"  Trend symmetric +/-200: ${pnl_ls:+,.0f}")
