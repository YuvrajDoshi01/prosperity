"""Robustness extension: VFE velocity short across all days + symmetric long signal.
Critical question: does v50<=-3 also generate FALSE shorts on days where VFE rallies?
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")

def simulate_vfe_velocity(day, ticks=1000, vthresh=-3, lookback=50, exit_mode='hold', stop_loss=10):
    p = pd.read_csv(ROOT/f"prosperity4bt/resources/round4/prices_round_4_day_{day}.csv", sep=';')
    p = p[(p['timestamp']<= (ticks-1)*100) & (p['product']=='VELVETFRUIT_EXTRACT')].sort_values('timestamp').reset_index(drop=True)
    p['v'] = p['mid_price'].diff(lookback)
    pos = 0
    entry = None
    pnl = 0.0
    trades = []
    for i, row in p.iterrows():
        v = row['v']; mid = row['mid_price']
        if pos == 0 and not pd.isna(v):
            if v <= vthresh:
                pos = -200; entry = mid
                trades.append((row['timestamp'], 'SHORT', mid))
            elif v >= -vthresh:
                pos = +200; entry = mid
                trades.append((row['timestamp'], 'LONG', mid))
        elif pos != 0 and entry is not None:
            # mark-to-market PnL check stop loss
            mtm = (entry - mid) * pos / abs(pos) * abs(pos)  # signed
            if pos < 0:
                mtm = (entry - mid) * 200
            else:
                mtm = (mid - entry) * 200
            if mtm < -stop_loss * 200:  # stop loss
                pnl += mtm
                trades.append((row['timestamp'], 'STOP', mid, mtm))
                pos = 0; entry = None
    # close at last tick
    last = p.iloc[-1]['mid_price']
    if pos < 0 and entry is not None:
        pnl += (entry - last) * 200
        trades.append((p.iloc[-1]['timestamp'], 'CLOSE_SHORT', last, (entry-last)*200))
    elif pos > 0 and entry is not None:
        pnl += (last - entry) * 200
        trades.append((p.iloc[-1]['timestamp'], 'CLOSE_LONG', last, (last-entry)*200))
    return pnl, trades, p

print("="*70)
print("VFE velocity strategy: SHORT on v50<=-3, LONG on v50>=+3 (symmetric)")
print("="*70)
for d in [1, 2, 3]:
    pnl, trades, _ = simulate_vfe_velocity(d, ticks=1000, vthresh=-3, lookback=50, stop_loss=15)
    print(f"\nDay {d} 1k: PnL={pnl:+.0f}, trades={len(trades)}")
    for t in trades[:5]:
        print(f"  {t}")

print("\n" + "="*70)
print("VFE velocity strategy: SHORT-ONLY on v50<=-3 (no symmetric long)")
print("="*70)

def simulate_short_only(day, ticks=1000, vthresh=-3, lookback=50, stop_loss=15, take_profit=None):
    p = pd.read_csv(ROOT/f"prosperity4bt/resources/round4/prices_round_4_day_{day}.csv", sep=';')
    p = p[(p['timestamp']<=(ticks-1)*100) & (p['product']=='VELVETFRUIT_EXTRACT')].sort_values('timestamp').reset_index(drop=True)
    p['v'] = p['mid_price'].diff(lookback)
    pos = 0; entry = None; pnl = 0.0; trades = []
    for i, row in p.iterrows():
        v = row['v']; mid = row['mid_price']
        if pos == 0 and not pd.isna(v) and v <= vthresh:
            pos = -200; entry = mid
            trades.append(('OPEN_SHORT', row['timestamp'], mid))
        elif pos < 0 and entry is not None:
            mtm = (entry - mid) * 200
            if mtm < -stop_loss * 200:
                pnl += mtm; trades.append(('STOP', row['timestamp'], mid, mtm)); pos = 0; entry = None
            elif take_profit and mtm > take_profit * 200:
                pnl += mtm; trades.append(('TP', row['timestamp'], mid, mtm)); pos = 0; entry = None
    if pos < 0 and entry is not None:
        last = p.iloc[-1]['mid_price']
        pnl += (entry - last) * 200
        trades.append(('CLOSE_EOD', p.iloc[-1]['timestamp'], last, (entry-last)*200))
    return pnl, trades

# Sweep over thresholds
print("\nSweep: short-only on velocity, no take-profit, stop_loss=15")
for vth in [-2, -3, -4, -5]:
    for lb in [30, 50, 100]:
        results = []
        for d in [1, 2, 3]:
            pnl, _ = simulate_short_only(d, vthresh=vth, lookback=lb, stop_loss=15)
            results.append(pnl)
        total = sum(results)
        print(f"  v{lb}<={vth}: day1={results[0]:+5.0f}  day2={results[1]:+5.0f}  day3={results[2]:+5.0f}  total={total:+5.0f}")

# Try with take-profit at +5
print("\nSweep: short-only, take_profit=+10pt, stop_loss=15")
for vth in [-2, -3, -4]:
    for lb in [30, 50, 100]:
        results = []
        for d in [1, 2, 3]:
            pnl, _ = simulate_short_only(d, vthresh=vth, lookback=lb, stop_loss=15, take_profit=10)
            results.append(pnl)
        total = sum(results)
        print(f"  v{lb}<={vth} TP=10: day1={results[0]:+5.0f}  day2={results[1]:+5.0f}  day3={results[2]:+5.0f}  total={total:+5.0f}")

# === Also: VFE Wall Mid MM (already in v22). What's the day 3 1k baseline? ===
# Check VFE alone via volume-weighted wall mid. If baseline MM works, we just need to NOT reverse.
# Examine spread structure
print("\n" + "="*70)
print("VFE structural analysis: where is the wall on day 3 1k?")
print("="*70)
vfe = pd.read_csv(ROOT/"prosperity4bt/resources/round4/prices_round_4_day_3.csv", sep=';')
vfe = vfe[(vfe['timestamp']<=99900) & (vfe['product']=='VELVETFRUIT_EXTRACT')].reset_index(drop=True)
vfe['spread'] = vfe['ask_price_1'] - vfe['bid_price_1']
print(f"Spread distribution: {vfe['spread'].value_counts().to_dict()}")
# Wall = level with max volume. Compare wall-mid vs simple mid drift
def wall_mid(row):
    bids = [(row[f'bid_price_{i}'], row[f'bid_volume_{i}']) for i in [1,2,3] if not pd.isna(row[f'bid_price_{i}'])]
    asks = [(row[f'ask_price_{i}'], row[f'ask_volume_{i}']) for i in [1,2,3] if not pd.isna(row[f'ask_price_{i}'])]
    if not bids or not asks: return np.nan
    wb = max(bids, key=lambda x: x[1])[0]
    wa = min(asks, key=lambda x: x[1] if x[1] else 1e9, default=(np.nan, 0))
    # actually use max-volume ask
    wa = max(asks, key=lambda x: x[1])[0]
    return (wb + wa) / 2
vfe['wall_mid'] = vfe.apply(wall_mid, axis=1)
print(f"VFE simple mid: open={vfe.iloc[0]['mid_price']}, close={vfe.iloc[-1]['mid_price']}")
print(f"VFE wall mid:   open={vfe.iloc[0]['wall_mid']}, close={vfe.iloc[-1]['wall_mid']}")
print(f"Diff (wall_mid - simple): mean={(vfe['wall_mid']-vfe['mid_price']).mean():+.2f}, std={(vfe['wall_mid']-vfe['mid_price']).std():.2f}")

# === Mark 67 + Mark 49 as VFE smart money confirmation ====================
print("\n" + "="*70)
print("Mark 67 + Mark 49 VFE trade ladder")
print("="*70)
trades = pd.read_csv(ROOT/"prosperity4bt/resources/round4/trades_round_4_day_3.csv", sep=';')
trades = trades[trades['timestamp']<=99900]
m67_vfe = trades[((trades['buyer']=='Mark 67')|(trades['seller']=='Mark 67')) & (trades['symbol']=='VELVETFRUIT_EXTRACT')]
print("\nMark 67 VFE trades (he's buying 38 vol total):")
print(m67_vfe[['timestamp','buyer','seller','price','quantity']])
# Mark 67 = SELLING (declining prices) means smart money exiting
# Mark 67 is BUYING here while VFE crashes from 5295 -> 5253
# So Mark 67 = catching falling knife = NOT smart money on day 3

# Avg trade price he buys at
print(f"\nMark 67 buy avg price: {m67_vfe[m67_vfe['buyer']=='Mark 67']['price'].mean():.1f}")
print(f"VFE close: {vfe.iloc[-1]['mid_price']}")
# If Mark 67 buys at 5257 and VFE closes 5253.5 → Mark 67 is LOSING in 1k
# but maybe wins by close of day. Check day 3 full close
vfe_full = pd.read_csv(ROOT/"prosperity4bt/resources/round4/prices_round_4_day_3.csv", sep=';')
vfe_full = vfe_full[vfe_full['product']=='VELVETFRUIT_EXTRACT']
print(f"VFE day-3 EOD: {vfe_full.iloc[-1]['mid_price']}")
