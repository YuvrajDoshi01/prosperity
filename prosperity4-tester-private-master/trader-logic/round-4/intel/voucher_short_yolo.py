"""
VOUCHER DELTA-SHORT YOLO analysis for R4 1k day-3 probe.

H0: shorting -300 each of ATM vouchers + VFE -200 at ts=0 mid, holding to ts=99900,
    yields ~$50k+ MTM PnL given the day-3 down regime.

Mechanics:
- Position limit per voucher = 300. We can short -300 each on 5300, 5400, 5500, 6000.
- VFE limit = 200.
- Max theoretical short portfolio = sum(300 * voucher_drop) + 200 * VFE_drop.
"""
from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path

CSV = Path(r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4/prices_round_4_day_3.csv")

# --- 1. Load per-product time series of mid + best bid + best ask ---
series = defaultdict(list)  # product -> list of (ts, mid, bb, ba, bb_vol, ba_vol)
with CSV.open() as f:
    rdr = csv.DictReader(f, delimiter=';')
    for row in rdr:
        ts = int(row['timestamp'])
        if ts > 99900:
            continue
        prod = row['product']
        mid = float(row['mid_price']) if row['mid_price'] else None
        bb = int(row['bid_price_1']) if row['bid_price_1'] else None
        ba = int(row['ask_price_1']) if row['ask_price_1'] else None
        bbv = int(row['bid_volume_1']) if row['bid_volume_1'] else 0
        bav = int(row['ask_volume_1']) if row['ask_volume_1'] else 0
        series[prod].append((ts, mid, bb, ba, bbv, bav))

products = sorted(series.keys())
print(f"Products: {products}")
print(f"Ticks per product: {len(series[products[0]])}")

# --- 2. Entry/exit prices: short = sell at best_bid (or mid as theoretical) ---
# Also track stop-loss path: max mid encountered from entry to exit
def entry_exit_pnl(prod, qty, mode='mid'):
    """Returns (entry, exit, pnl, max_mid, min_mid) for a short held full 1k.
    qty is the SHORT size (positive number, contract is sold then bought back).
    mode: 'mid' = both legs at mid. 'realistic' = sell at bb, buy at ba.
    """
    s = series[prod]
    if not s:
        return None
    t0 = s[0]
    tN = s[-1]
    if mode == 'mid':
        entry = t0[1]; exit_p = tN[1]
    else:  # realistic: short sells into best_bid; cover buys best_ask
        entry = t0[2] if t0[2] is not None else t0[1]  # bid
        exit_p = tN[3] if tN[3] is not None else tN[1]  # ask
    pnl = (entry - exit_p) * qty
    mids = [r[1] for r in s if r[1] is not None]
    return {
        'product': prod,
        'qty': qty,
        'entry': entry,
        'exit': exit_p,
        'drop': entry - exit_p,
        'pnl': pnl,
        'max_mid': max(mids),
        'min_mid': min(mids),
        'max_drawdown': max(mids) - entry,  # how much price went UP against short
    }

# --- 3. Compute SHORT PnL per voucher and VFE ---
print("\n=== SHORT PORTFOLIO @ entry mid -> exit mid (theoretical) ===")
print(f"{'Product':<22} {'Qty':>5} {'Entry':>9} {'Exit':>9} {'Drop':>8} {'PnL':>10} {'MaxAdverse':>10}")
total_pnl_mid = 0
target_shorts = [
    ('VELVETFRUIT_EXTRACT', 200),
    ('VEV_4000', 300),
    ('VEV_4500', 300),
    ('VEV_5000', 300),
    ('VEV_5100', 300),
    ('VEV_5200', 300),
    ('VEV_5300', 300),
    ('VEV_5400', 300),
    ('VEV_5500', 300),
    ('VEV_6000', 300),
    ('VEV_6500', 300),
]
results = {}
for prod, qty in target_shorts:
    r = entry_exit_pnl(prod, qty, mode='mid')
    if r:
        results[prod] = r
        print(f"{prod:<22} {r['qty']:>5} {r['entry']:>9.1f} {r['exit']:>9.1f} {r['drop']:>8.1f} {r['pnl']:>10.0f} {r['max_drawdown']:>10.1f}")
        total_pnl_mid += r['pnl']
print(f"{'TOTAL (all shorts mid)':<22} {'':>5} {'':>9} {'':>9} {'':>8} {total_pnl_mid:>10.0f}")

# --- 4. Realistic execution: cross spread ---
print("\n=== SHORT PORTFOLIO @ best_bid entry -> best_ask exit (realistic) ===")
total_pnl_real = 0
for prod, qty in target_shorts:
    r = entry_exit_pnl(prod, qty, mode='realistic')
    if r:
        print(f"{prod:<22} {r['qty']:>5} {r['entry']:>9} {r['exit']:>9} {r['drop']:>8.1f} {r['pnl']:>10.0f}")
        total_pnl_real += r['pnl']
print(f"{'TOTAL (realistic)':<22} {'':>5} {'':>9} {'':>9} {'':>8} {total_pnl_real:>10.0f}")

# --- 5. ATM-only subset ---
print("\n=== ATM ONLY (5300, 5400, 5500, 6000) + VFE ===")
atm_subset = ['VELVETFRUIT_EXTRACT', 'VEV_5300', 'VEV_5400', 'VEV_5500', 'VEV_6000']
atm_pnl = sum(results[p]['pnl'] for p in atm_subset if p in results)
print(f"ATM mid PnL: {atm_pnl:.0f}")

# --- 6. Order book depth at ts=0 (can we actually short 300?) ---
print("\n=== ENTRY FEASIBILITY (ts=0 best_bid depth) ===")
print(f"{'Product':<22} {'BB':>8} {'BBvol':>6} {'BA':>8} {'BAvol':>6}")
for prod, qty in target_shorts:
    s = series[prod]
    if s:
        t0 = s[0]
        print(f"{prod:<22} {str(t0[2]):>8} {t0[4]:>6} {str(t0[3]):>8} {t0[5]:>6}")

# --- 7. Adverse path: at any point in 1k, how much was max VFE rise? ---
vfe = series['VELVETFRUIT_EXTRACT']
vfe_mids = [r[1] for r in vfe if r[1] is not None]
print(f"\nVFE entry mid: {vfe_mids[0]}, max: {max(vfe_mids)}, min: {min(vfe_mids)}, exit: {vfe_mids[-1]}")
print(f"VFE max adverse run-up: {max(vfe_mids) - vfe_mids[0]:.1f}")
print(f"VFE max favorable drop: {vfe_mids[0] - min(vfe_mids):.1f}")

# --- 8. Per-tick portfolio MTM trajectory (peak unrealized PnL) ---
print("\n=== PEAK UNREALIZED PnL TRAJECTORY ===")
# Build aligned timestamps
ts_set = set(r[0] for r in series['VELVETFRUIT_EXTRACT'])
# index per product by ts
idx = {p: {r[0]: r for r in series[p]} for p in [t[0] for t in target_shorts] if p in series}

peak_unrealized = -1e18
trough_unrealized = 1e18
peak_ts = trough_ts = 0
for ts in sorted(ts_set):
    pnl = 0
    ok = True
    for prod, qty in target_shorts:
        if prod not in idx: continue
        rec = idx[prod].get(ts)
        if rec is None or rec[1] is None:
            ok = False; break
        entry = idx[prod][0][1]
        if entry is None: ok = False; break
        pnl += (entry - rec[1]) * qty
    if not ok: continue
    if pnl > peak_unrealized:
        peak_unrealized = pnl; peak_ts = ts
    if pnl < trough_unrealized:
        trough_unrealized = pnl; trough_ts = ts

print(f"Peak unrealized PnL: ${peak_unrealized:.0f} at ts={peak_ts}")
print(f"Trough unrealized PnL: ${trough_unrealized:.0f} at ts={trough_ts}")
print(f"Final realized PnL (mid): ${total_pnl_mid:.0f}")
