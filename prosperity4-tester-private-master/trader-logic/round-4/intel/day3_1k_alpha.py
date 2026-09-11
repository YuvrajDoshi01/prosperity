"""Day 3 first-1k alpha hunt for IMC Prosperity 4 R4.
Targets:
1. VFE crash early-warning signals (drift = -$42 over 1k)
2. HP MM-only PnL (no S17 GIGA SHORT)
3. Voucher MM gap analysis
4. Counterparty Mark refinement
5. Concrete recommendation to add to v9_nodir
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
PRICES = ROOT / "prosperity4bt/resources/round4/prices_round_4_day_3.csv"
TRADES = ROOT / "prosperity4bt/resources/round4/trades_round_4_day_3.csv"

prices = pd.read_csv(PRICES, sep=';')
trades = pd.read_csv(TRADES, sep=';')

# Filter to first 1k ticks (timestamp <= 99900, step 100)
prices = prices[prices['timestamp'] <= 99900].copy()
trades = trades[trades['timestamp'] <= 99900].copy()

VOUCHERS = [f"VEV_{k}" for k in [4000, 4500, 5000, 5250, 5500, 5750, 6000, 6250, 6500, 6750]]
print(f"Tick count per product check: {prices.groupby('product').size().to_dict()}")

# === 1. VFE CRASH EARLY-WARNING ============================================
print("\n" + "="*70)
print("1. VFE CRASH EARLY-WARNING SIGNALS (target: short VFE early)")
print("="*70)

vfe = prices[prices['product'] == 'VELVETFRUIT_EXTRACT'].sort_values('timestamp').reset_index(drop=True)
vfe['mid'] = vfe['mid_price']
vfe['spread'] = vfe['ask_price_1'] - vfe['bid_price_1']
vfe['bid_vol_total'] = vfe[['bid_volume_1','bid_volume_2','bid_volume_3']].fillna(0).sum(axis=1)
vfe['ask_vol_total'] = vfe[['ask_volume_1','ask_volume_2','ask_volume_3']].fillna(0).sum(axis=1)
vfe['obi'] = (vfe['bid_vol_total'] - vfe['ask_vol_total']) / (vfe['bid_vol_total'] + vfe['ask_vol_total'])
vfe['micro'] = (vfe['bid_price_1']*vfe['ask_vol_total'] + vfe['ask_price_1']*vfe['bid_vol_total']) / (vfe['bid_vol_total']+vfe['ask_vol_total'])

# Forward returns at multiple horizons
for h in [50, 100, 200, 500]:
    vfe[f'fwd_{h}'] = vfe['mid'].shift(-h) - vfe['mid']

# Predictive features for SHORT signal
print(f"\nVFE: open={vfe.iloc[0]['mid']}, close_1k={vfe.iloc[-1]['mid']}, drift={vfe.iloc[-1]['mid']-vfe.iloc[0]['mid']}")
print(f"VFE early window (first 200 ticks): mid range [{vfe.head(200)['mid'].min()}, {vfe.head(200)['mid'].max()}]")

# Test: does early OBI/micro deviation predict 500-tick drop?
# Use only first 300 ticks of features
early = vfe.head(300).copy()

def t_stat(x, y):
    """Simple t-stat on regression slope."""
    mask = (~np.isnan(x)) & (~np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 10: return np.nan, np.nan
    n = len(x)
    cov = np.cov(x, y)[0,1]
    sx = np.std(x, ddof=1)
    sy = np.std(y, ddof=1)
    if sx == 0 or sy == 0: return np.nan, np.nan
    r = cov / (sx*sy)
    t = r * np.sqrt(n-2) / np.sqrt(max(1-r*r, 1e-9))
    return r, t

print(f"\n--- Predictors of VFE fwd_500 (in first 300 ticks) ---")
for feat in ['obi', 'spread', 'mid']:
    r, t = t_stat(early[feat].values, early['fwd_500'].values)
    print(f"  {feat:10s}: corr={r:+.3f}, t={t:+.2f}")

# Mid drop velocity: rolling slope of last 30 ticks
vfe['velocity_30'] = vfe['mid'].diff(30)
vfe['velocity_50'] = vfe['mid'].diff(50)
early2 = vfe.head(300).copy()
for feat in ['velocity_30', 'velocity_50']:
    r, t = t_stat(early2[feat].values, early2['fwd_500'].values)
    print(f"  {feat:10s}: corr={r:+.3f}, t={t:+.2f}")

# When does VFE first show negative drift > 5pts?
vfe['cum_drift'] = vfe['mid'] - vfe.iloc[0]['mid']
first_neg5 = vfe[vfe['cum_drift'] <= -5]
first_neg10 = vfe[vfe['cum_drift'] <= -10]
print(f"\nVFE first time cum_drift <= -5: ts={first_neg5.iloc[0]['timestamp'] if len(first_neg5) else 'never'}")
print(f"VFE first time cum_drift <= -10: ts={first_neg10.iloc[0]['timestamp'] if len(first_neg10) else 'never'}")

# Strategy: short VFE 200 contracts at first cum_drift <= -3 (or whatever) and hold
print("\n--- VFE short-on-drop simulator ---")
LIMIT = 200
for trigger in [-2, -3, -5, -8, -10]:
    trig_idx = vfe[vfe['cum_drift'] <= trigger].index
    if len(trig_idx) == 0:
        continue
    entry_ts = vfe.loc[trig_idx[0], 'timestamp']
    entry_mid = vfe.loc[trig_idx[0], 'mid']
    # PnL = (entry - exit) * LIMIT, exit at last tick
    exit_mid = vfe.iloc[-1]['mid']
    pnl_hold = (entry_mid - exit_mid) * LIMIT
    print(f"  trigger drift<={trigger}: entry ts={entry_ts} mid={entry_mid:.1f} exit={exit_mid:.1f} -> PnL hold={pnl_hold:+.0f}")

# Also simulate "short at ts=0" baseline
entry0 = vfe.iloc[0]['mid']; exit0 = vfe.iloc[-1]['mid']
print(f"  baseline short@ts=0: entry={entry0:.1f} exit={exit0:.1f} -> PnL={LIMIT*(entry0-exit0):+.0f}")

# === 2. HP MM-only alpha ===================================================
print("\n" + "="*70)
print("2. HP MM-only PnL (no S17 GIGA SHORT)")
print("="*70)

hp = prices[prices['product'] == 'HYDROGEL_PACK'].sort_values('timestamp').reset_index(drop=True)
hp['mid'] = hp['mid_price']
hp['spread'] = hp['ask_price_1'] - hp['bid_price_1']
print(f"HP: open={hp.iloc[0]['mid']}, close={hp.iloc[-1]['mid']}, range=[{hp['mid'].min()}, {hp['mid'].max()}]")
print(f"HP spread distribution: {hp['spread'].value_counts().to_dict()}")

# Theoretical MM PnL: capture spread/2 per round-trip when spread >= 5
# Crude: count ticks where spread >= 5, mult by realistic fill rate
spread_5plus = (hp['spread'] >= 5).sum()
print(f"HP ticks spread>=5: {spread_5plus}")

# Better: simulate passive MM at best+1/best-1 with conservative fill rate
# In R3 we saw ~30% fill rate per tick on tight markets
# 1k ticks * 30% fill * spread/2 cap
avg_spread = hp['spread'].mean()
print(f"HP avg spread: {avg_spread:.2f}, theoretical MM PnL upper bound (50% fill, spread/2-1 capture): {1000*0.5*(avg_spread/2-1):.0f}")

# === 3. Voucher MM gap =====================================================
print("\n" + "="*70)
print("3. Voucher MM analysis")
print("="*70)

vfe_open = vfe.iloc[0]['mid']
print(f"VFE_open={vfe_open}, VFE_close={vfe.iloc[-1]['mid']}")
print(f"\nVoucher | open_mid | close_mid | spread_avg | total_volume_traded")
voucher_total_traded = 0
for vk in VOUCHERS:
    v = prices[prices['product'] == vk].sort_values('timestamp')
    if len(v) == 0:
        continue
    v_trades = trades[trades['symbol'] == vk]
    voucher_total_traded += v_trades['quantity'].sum()
    sp = (v['ask_price_1'] - v['bid_price_1']).mean()
    print(f"{vk}  | {v.iloc[0]['mid_price']:>8.1f} | {v.iloc[-1]['mid_price']:>8.1f} | {sp:>8.2f}   | {v_trades['quantity'].sum()}")
print(f"\nTotal voucher volume traded in 1k: {voucher_total_traded}")

# === 4. Counterparty refinement ============================================
print("\n" + "="*70)
print("4. Counterparty Mark analysis (1k day 3)")
print("="*70)

# Pivot trades by buyer/seller
trades['side'] = trades['buyer'].astype(str)
buyers = trades.groupby('buyer').agg(n=('quantity','count'), vol=('quantity','sum'))
sellers = trades.groupby('seller').agg(n=('quantity','count'), vol=('quantity','sum'))
print("\nTop buyers (Marks):")
print(buyers.sort_values('vol', ascending=False).head(10))
print("\nTop sellers (Marks):")
print(sellers.sort_values('vol', ascending=False).head(10))

# Per Mark per product
print("\nMark 67 (Olivia analog) trades:")
m67 = trades[(trades['buyer']=='Mark 67') | (trades['seller']=='Mark 67')]
print(m67[['timestamp','buyer','seller','symbol','price','quantity']])

print("\nMark 49 (anti-Olivia) trades:")
m49 = trades[(trades['buyer']=='Mark 49') | (trades['seller']=='Mark 49')]
print(m49[['timestamp','buyer','seller','symbol','price','quantity']])

# Smart-money detection: which Mark's trades best predict forward direction on VFE/HP?
def mark_alpha(symbol):
    sub = trades[trades['symbol']==symbol]
    px = prices[prices['product']==symbol].set_index('timestamp')['mid_price']
    rows = []
    for mark in pd.unique(pd.concat([sub['buyer'], sub['seller']])):
        if not isinstance(mark, str) or not mark.startswith('Mark'):
            continue
        # Mark as buyer = bullish signal
        mb = sub[sub['buyer']==mark]
        ms = sub[sub['seller']==mark]
        n = len(mb)+len(ms)
        if n < 2: continue
        # forward 200t mid change after Mark trades
        fwd_buys = []; fwd_sells = []
        for ts in mb['timestamp']:
            t_aligned = (ts // 100) * 100
            if t_aligned in px.index and t_aligned+20000 in px.index:
                fwd_buys.append(px.loc[t_aligned+20000] - px.loc[t_aligned])
        for ts in ms['timestamp']:
            t_aligned = (ts // 100) * 100
            if t_aligned in px.index and t_aligned+20000 in px.index:
                fwd_sells.append(px.loc[t_aligned+20000] - px.loc[t_aligned])
        signal = (np.mean(fwd_buys) if fwd_buys else 0) - (np.mean(fwd_sells) if fwd_sells else 0)
        rows.append((mark, len(mb), len(ms), signal))
    df = pd.DataFrame(rows, columns=['mark','n_buys','n_sells','fwd_signal'])
    return df.sort_values('fwd_signal', key=abs, ascending=False)

print("\n--- VFE smart-money mark alpha (fwd 200t) ---")
print(mark_alpha('VELVETFRUIT_EXTRACT').head(10))
print("\n--- HP smart-money mark alpha (fwd 200t) ---")
print(mark_alpha('HYDROGEL_PACK').head(10))

# === 5. Recommendation simulator ==========================================
print("\n" + "="*70)
print("5. RECOMMENDATION: short VFE on velocity trigger")
print("="*70)

# Best VFE strategy: short at velocity_50 < -2 (i.e. mid dropped 2pts in 50t)
vfe['v30'] = vfe['mid'].diff(30)
vfe['v50'] = vfe['mid'].diff(50)
trigger_idx = vfe[(vfe.index >= 50) & (vfe['v50'] <= -2)].index
if len(trigger_idx) > 0:
    ti = trigger_idx[0]
    entry_ts = vfe.loc[ti, 'timestamp']; entry_mid = vfe.loc[ti, 'mid']
    exit_mid = vfe.iloc[-1]['mid']
    print(f"v50<=-2 trigger: ts={entry_ts} mid={entry_mid:.1f} exit={exit_mid:.1f} -> PnL(short 200)={200*(entry_mid-exit_mid):+.0f}")

trigger_idx = vfe[(vfe.index >= 50) & (vfe['v50'] <= -3)].index
if len(trigger_idx) > 0:
    ti = trigger_idx[0]
    entry_ts = vfe.loc[ti, 'timestamp']; entry_mid = vfe.loc[ti, 'mid']
    exit_mid = vfe.iloc[-1]['mid']
    print(f"v50<=-3 trigger: ts={entry_ts} mid={entry_mid:.1f} exit={exit_mid:.1f} -> PnL(short 200)={200*(entry_mid-exit_mid):+.0f}")

# Also test on day 1, 2 to ensure it doesn't blow up
print("\n--- Robustness: same v50<=-3 trigger on days 1, 2 (overfit check) ---")
for d in [1, 2]:
    p = pd.read_csv(ROOT/f"prosperity4bt/resources/round4/prices_round_4_day_{d}.csv", sep=';')
    p = p[(p['timestamp']<=99900) & (p['product']=='VELVETFRUIT_EXTRACT')].sort_values('timestamp').reset_index(drop=True)
    p['v50'] = p['mid_price'].diff(50)
    trig = p[(p.index>=50) & (p['v50']<=-3)].index
    if len(trig)>0:
        ti = trig[0]
        e = p.loc[ti,'mid_price']; ex = p.iloc[-1]['mid_price']
        print(f"  day{d}: trigger ts={p.loc[ti,'timestamp']} mid={e} exit={ex} -> PnL(short 200)={200*(e-ex):+.0f}")
    else:
        print(f"  day{d}: trigger never fires, PnL=0")

# Day 0 too
try:
    p = pd.read_csv(ROOT/"prosperity4bt/resources/round4/prices_round_4_day_0.csv", sep=';')
    print("day0 exists")
except FileNotFoundError:
    print("day0 not in r4 (expected)")
