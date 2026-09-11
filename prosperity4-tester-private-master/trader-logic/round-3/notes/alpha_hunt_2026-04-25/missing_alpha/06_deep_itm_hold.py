"""H6: Deep-ITM voucher hold (VEV_4000, VEV_4500). PnL from intrinsic+drift over 10k ticks."""
import pandas as pd
import numpy as np

BASE = r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3"

for day in [0, 1, 2]:
    p = pd.read_csv(f"{BASE}/prices_round_3_day_{day}.csv", sep=";")
    s_open = p[p["product"] == "VELVETFRUIT_EXTRACT"].iloc[0]["mid_price"]
    s_close = p[p["product"] == "VELVETFRUIT_EXTRACT"].iloc[-1]["mid_price"]
    print(f"\nDay {day}: VFE open={s_open:.0f} close={s_close:.0f}")
    for k in [4000, 4500, 5000]:
        v = p[p["product"] == f"VEV_{k}"].reset_index(drop=True)
        if v.empty:
            print(f"  VEV_{k}: no data")
            continue
        c_open = v.iloc[0]["mid_price"]
        c_close = v.iloc[-1]["mid_price"]
        c_low = v["mid_price"].min()
        # Naive: long +100 from open to close
        pnl_100 = 100 * (c_close - c_open)
        # Long +300 (limit) from open to close
        pnl_300 = 300 * (c_close - c_open)
        # Avg ask price for entry, bid for exit
        ask_open = v.iloc[0]["ask_price_1"]
        bid_close = v.iloc[-1]["bid_price_1"]
        pnl_300_realistic = 300 * (bid_close - ask_open)
        print(f"  VEV_{k}: open={c_open:.1f} close={c_close:.1f} low={c_low:.1f} | "
              f"+100 P&L=${pnl_100:+,.0f} | +300 mid={pnl_300:+,.0f} | "
              f"+300 ask->bid=${pnl_300_realistic:+,.0f}")
