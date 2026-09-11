#!/usr/bin/env python3
"""
Voucher (Call Option) Microstructure Analysis for IMC Prosperity 4
Focus: Strikes 5000, 5300, 5400, 5500 on VELVETFRUIT_EXTRACT (underlying ~5250)
"""

import csv
import math
import statistics
from collections import defaultdict, Counter

# ============================================================
# DATA LOADING
# ============================================================
BASE = "/Users/y0d046w/Desktop/prosperity4-tester-private/prosperity4bt/resources/round3"
DAYS = [0, 1, 2]
STRIKES = [5000, 5300, 5400, 5500]
STRIKE_NAMES = [f"VEV_{k}" for k in STRIKES]
UND = "VELVETFRUIT_EXTRACT"
TTE_MAP = {0: 8, 1: 7, 2: 6}  # time to expiry in days

def load_prices(day):
    """Returns dict: product -> list of dicts sorted by timestamp"""
    path = f"{BASE}/prices_round_3_day_{day}.csv"
    data = defaultdict(list)
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            product = row['product']
            ts = int(row['timestamp'])
            rec = {'timestamp': ts, 'day': int(row['day'])}
            # Parse bid/ask levels
            for side in ['bid', 'ask']:
                for lvl in range(1, 4):
                    pk = f'{side}_price_{lvl}'
                    vk = f'{side}_volume_{lvl}'
                    p = row.get(pk, '')
                    v = row.get(vk, '')
                    rec[pk] = float(p) if p else None
                    rec[vk] = int(float(v)) if v else None
            rec['mid_price'] = float(row['mid_price']) if row['mid_price'] else None
            data[product].append(rec)
    # Sort by timestamp
    for p in data:
        data[p].sort(key=lambda x: x['timestamp'])
    return data

def load_trades(day):
    """Returns list of trade dicts"""
    path = f"{BASE}/trades_round_3_day_{day}.csv"
    trades = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            trades.append({
                'timestamp': int(row['timestamp']),
                'buyer': row.get('buyer', ''),
                'seller': row.get('seller', ''),
                'symbol': row['symbol'],
                'price': float(row['price']),
                'quantity': int(row['quantity']),
            })
    return trades

print("Loading data...")
all_prices = {}
all_trades = {}
for d in DAYS:
    all_prices[d] = load_prices(d)
    all_trades[d] = load_trades(d)
print("Data loaded.\n")

# Helper: build timestamp -> mid lookup for a product on a day
def mid_lookup(prices_day, product):
    return {r['timestamp']: r['mid_price'] for r in prices_day[product] if r['mid_price'] is not None}

def best_bid(rec):
    return rec.get('bid_price_1')

def best_ask(rec):
    return rec.get('ask_price_1')

def spread(rec):
    b, a = best_bid(rec), best_ask(rec)
    if b is not None and a is not None:
        return a - b
    return None

# Build convenient per-product, per-day lookups
# prices_by[day][product] = list of recs sorted by ts
# ts_index[day][product] = {ts: rec}
ts_index = {}
for d in DAYS:
    ts_index[d] = {}
    for p in STRIKE_NAMES + [UND]:
        ts_index[d][p] = {r['timestamp']: r for r in all_prices[d][p]}

# ============================================================
# PART A: PRICE DYNAMICS
# ============================================================
print("=" * 90)
print("PART A: PRICE DYNAMICS")
print("=" * 90)

# A1: Mid price time series statistics
print("\n--- A1: Mid Price Time Series Statistics ---")
header = f"{'Strike':<10} {'Day':>3} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8} {'Open':>8} {'Close':>8} {'Drift':>8} {'AR1_ret':>8}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        mids = [r['mid_price'] for r in all_prices[d][sname] if r['mid_price'] is not None]
        if not mids:
            print(f"{sname:<10} {d:>3} -- no data --")
            continue
        mn = statistics.mean(mids)
        sd = statistics.stdev(mids) if len(mids) > 1 else 0
        mi, mx = min(mids), max(mids)
        op, cl = mids[0], mids[-1]
        drift = cl - op
        # AR1 on returns
        rets = [mids[i] - mids[i-1] for i in range(1, len(mids))]
        if len(rets) > 2:
            mean_r = statistics.mean(rets)
            var_r = sum((r - mean_r)**2 for r in rets) / len(rets)
            if var_r > 0:
                cov_r = sum((rets[i] - mean_r) * (rets[i-1] - mean_r) for i in range(1, len(rets))) / (len(rets) - 1)
                ar1 = cov_r / var_r
            else:
                ar1 = 0
        else:
            ar1 = 0
        print(f"{sname:<10} {d:>3} {mn:>8.1f} {sd:>8.2f} {mi:>8.1f} {mx:>8.1f} {op:>8.1f} {cl:>8.1f} {drift:>+8.1f} {ar1:>+8.3f}")

# VFE underlying stats
print(f"\n{'UND':<10}", end="")
for d in DAYS:
    mids = [r['mid_price'] for r in all_prices[d][UND] if r['mid_price'] is not None]
    op, cl = mids[0], mids[-1]
    mn = statistics.mean(mids)
    sd = statistics.stdev(mids)
    print(f"  Day{d}: mean={mn:.1f} std={sd:.1f} [{min(mids):.0f},{max(mids):.0f}] drift={cl-op:+.0f}")
print()

# A2: Bid-ask spread statistics
print("\n--- A2: Bid-Ask Spread Statistics ---")
header = f"{'Strike':<10} {'Day':>3} {'MnSpd':>6} {'MdSpd':>6} {'Mode':>5} {'Spd=1':>6} {'Spd=2':>6} {'Spd=3':>6} {'Spd>=4':>6} {'NoBook':>6}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        spreads = []
        no_book = 0
        for r in all_prices[d][sname]:
            s = spread(r)
            if s is not None:
                spreads.append(s)
            else:
                no_book += 1
        if not spreads:
            print(f"{sname:<10} {d:>3} -- no data --")
            continue
        cnt = Counter(spreads)
        total = len(spreads) + no_book
        mn = statistics.mean(spreads)
        md = statistics.median(spreads)
        mo = cnt.most_common(1)[0][0]
        s1 = sum(1 for s in spreads if s == 1) / total * 100
        s2 = sum(1 for s in spreads if s == 2) / total * 100
        s3 = sum(1 for s in spreads if s == 3) / total * 100
        s4p = sum(1 for s in spreads if s >= 4) / total * 100
        nb = no_book / total * 100
        print(f"{sname:<10} {d:>3} {mn:>6.2f} {md:>6.1f} {mo:>5.0f} {s1:>5.1f}% {s2:>5.1f}% {s3:>5.1f}% {s4p:>5.1f}% {nb:>5.1f}%")

# A3: Time value analysis
print("\n--- A3: Time Value = mid - max(S-K, 0) ---")
header = f"{'Strike':<10} {'Day':>3} {'TTE':>4} {'MnTV':>8} {'StdTV':>8} {'MinTV':>8} {'MaxTV':>8} {'TV_open':>8} {'TV_close':>8} {'TV_drift':>8}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        vfe_mids = mid_lookup(all_prices[d], UND)
        voucher_recs = all_prices[d][sname]
        tvs = []
        tv_open = tv_close = None
        for r in voucher_recs:
            ts = r['timestamp']
            vm = r['mid_price']
            um = vfe_mids.get(ts)
            if vm is not None and um is not None:
                intrinsic = max(um - k, 0)
                tv = vm - intrinsic
                tvs.append(tv)
                if tv_open is None:
                    tv_open = tv
                tv_close = tv
        if not tvs:
            print(f"{sname:<10} {d:>3} -- no data --")
            continue
        print(f"{sname:<10} {d:>3} {TTE_MAP[d]:>4} {statistics.mean(tvs):>8.2f} {statistics.stdev(tvs):>8.2f} {min(tvs):>8.1f} {max(tvs):>8.1f} {tv_open:>8.1f} {tv_close:>8.1f} {tv_close - tv_open:>+8.1f}")

# A4: Buy-and-hold PnL (full day: buy 300 at ask tick 0, sell at bid tick 9999)
print("\n--- A4: Buy-and-Hold PnL (300 contracts, full day 10k ticks) ---")
header = f"{'Strike':<10} {'Day':>3} {'Ask_0':>8} {'Bid_N':>8} {'PnL/ct':>8} {'PnL_300':>10}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        recs = all_prices[d][sname]
        ask0 = best_ask(recs[0]) if recs else None
        bidn = best_bid(recs[-1]) if recs else None
        if ask0 is not None and bidn is not None:
            pnl_per = bidn - ask0
            pnl_300 = pnl_per * 300
            print(f"{sname:<10} {d:>3} {ask0:>8.0f} {bidn:>8.0f} {pnl_per:>+8.1f} {pnl_300:>+10.0f}")
        else:
            print(f"{sname:<10} {d:>3} -- missing book --")

# A5: Buy-and-hold PnL (first 1k ticks only = website test)
print("\n--- A5: Buy-and-Hold PnL (300 contracts, first 1k ticks = 0-99900) ---")
header = f"{'Strike':<10} {'Day':>3} {'Ask_0':>8} {'Bid_999':>8} {'PnL/ct':>8} {'PnL_300':>10}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        recs = all_prices[d][sname]
        ask0 = best_ask(recs[0]) if recs else None
        # tick 999 = timestamp 99900
        rec999 = ts_index[d][sname].get(99900)
        bid999 = best_bid(rec999) if rec999 else None
        if ask0 is not None and bid999 is not None:
            pnl_per = bid999 - ask0
            pnl_300 = pnl_per * 300
            print(f"{sname:<10} {d:>3} {ask0:>8.0f} {bid999:>8.0f} {pnl_per:>+8.1f} {pnl_300:>+10.0f}")
        else:
            print(f"{sname:<10} {d:>3} -- missing book --")

# ============================================================
# PART B: MARKET MAKING ANALYSIS
# ============================================================
print("\n" + "=" * 90)
print("PART B: MARKET MAKING ANALYSIS")
print("=" * 90)

# B6: Spread analysis for MM feasibility
print("\n--- B6: MM Feasibility (Spread Distribution & Inside-Posting Room) ---")
header = f"{'Strike':<10} {'Day':>3} {'Spd>=2':>7} {'Spd>=3':>7} {'Spd>=4':>7} {'HalfSpd':>8} {'BidDist':>8} {'AskDist':>8}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        n_total = 0
        n_ge2 = 0
        n_ge3 = 0
        n_ge4 = 0
        bid_dists = []
        ask_dists = []
        for r in all_prices[d][sname]:
            b, a, m = best_bid(r), best_ask(r), r['mid_price']
            if b is None or a is None or m is None:
                continue
            n_total += 1
            s = a - b
            if s >= 2: n_ge2 += 1
            if s >= 3: n_ge3 += 1
            if s >= 4: n_ge4 += 1
            bid_dists.append(m - b)
            ask_dists.append(a - m)
        if n_total == 0:
            print(f"{sname:<10} {d:>3} -- no data --")
            continue
        pct2 = n_ge2 / n_total * 100
        pct3 = n_ge3 / n_total * 100
        pct4 = n_ge4 / n_total * 100
        hspd = statistics.mean(bid_dists + ask_dists)
        bd = statistics.mean(bid_dists)
        ad = statistics.mean(ask_dists)
        print(f"{sname:<10} {d:>3} {pct2:>6.1f}% {pct3:>6.1f}% {pct4:>6.1f}% {hspd:>8.2f} {bd:>8.2f} {ad:>8.2f}")

# B7: Taker flow from trades
print("\n--- B7: Taker Flow Analysis ---")
header = f"{'Strike':<10} {'Day':>3} {'#Trades':>8} {'TotQty':>8} {'AvgQty':>7} {'AvgIAT':>8} {'MdIAT':>8} {'AtBid%':>7} {'AtAsk%':>7} {'AtMid%':>7} {'Other%':>7}"
print(header)
print("-" * len(header))

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        sym_trades = [t for t in all_trades[d] if t['symbol'] == sname]
        if not sym_trades:
            print(f"{sname:<10} {d:>3} {'-- no trades --':>50}")
            continue
        n_trades = len(sym_trades)
        total_qty = sum(t['quantity'] for t in sym_trades)
        avg_qty = total_qty / n_trades

        # Inter-arrival times
        timestamps = sorted(set(t['timestamp'] for t in sym_trades))
        if len(timestamps) > 1:
            iats = [timestamps[i] - timestamps[i-1] for i in range(1, len(timestamps))]
            avg_iat = statistics.mean(iats)
            md_iat = statistics.median(iats)
        else:
            avg_iat = md_iat = float('inf')

        # Classify trades relative to book
        at_bid = at_ask = at_mid = other = 0
        for t in sym_trades:
            ts = t['timestamp']
            rec = ts_index[d][sname].get(ts)
            if rec is None:
                other += 1
                continue
            b, a, m = best_bid(rec), best_ask(rec), rec['mid_price']
            tp = t['price']
            if b is not None and tp <= b:
                at_bid += 1
            elif a is not None and tp >= a:
                at_ask += 1
            elif m is not None and abs(tp - m) < 0.01:
                at_mid += 1
            else:
                other += 1

        ab_pct = at_bid / n_trades * 100
        aa_pct = at_ask / n_trades * 100
        am_pct = at_mid / n_trades * 100
        ot_pct = other / n_trades * 100

        iat_str = f"{avg_iat:>8.0f}" if avg_iat < 1e6 else f"{'inf':>8}"
        md_str = f"{md_iat:>8.0f}" if md_iat < 1e6 else f"{'inf':>8}"
        print(f"{sname:<10} {d:>3} {n_trades:>8} {total_qty:>8} {avg_qty:>7.1f} {iat_str} {md_str} {ab_pct:>6.1f}% {aa_pct:>6.1f}% {am_pct:>6.1f}% {ot_pct:>6.1f}%")

# Net direction
print("\n--- B7b: Net Taker Direction (buy qty - sell qty proxy) ---")
print(f"{'Strike':<10} {'Day':>3} {'AtBidQty':>9} {'AtAskQty':>9} {'NetBuy':>9} {'Imbalance':>10}")
print("-" * 60)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        sym_trades = [t for t in all_trades[d] if t['symbol'] == sname]
        bid_qty = ask_qty = 0
        for t in sym_trades:
            ts = t['timestamp']
            rec = ts_index[d][sname].get(ts)
            if rec is None:
                continue
            b, a = best_bid(rec), best_ask(rec)
            tp = t['price']
            if b is not None and tp <= b:
                bid_qty += t['quantity']  # seller-initiated
            elif a is not None and tp >= a:
                ask_qty += t['quantity']  # buyer-initiated
        net = ask_qty - bid_qty
        total = ask_qty + bid_qty
        imb = net / total * 100 if total > 0 else 0
        print(f"{sname:<10} {d:>3} {bid_qty:>9} {ask_qty:>9} {net:>+9} {imb:>+9.1f}%")

# ============================================================
# PART C: DIRECTIONAL SIGNALS
# ============================================================
print("\n" + "=" * 90)
print("PART C: DIRECTIONAL SIGNALS")
print("=" * 90)

# C8: VFE forward returns
print("\n--- C8: VFE Forward Return Analysis ---")
print(f"{'Day':>3} {'Horizon':>8} {'MnRet':>8} {'MdRet':>8} {'StdRet':>8} {'Sharpe':>8} {'%Pos':>7} {'AR1':>8}")
print("-" * 65)

for d in DAYS:
    vfe_recs = all_prices[d][UND]
    vfe_ts = {r['timestamp']: r['mid_price'] for r in vfe_recs if r['mid_price'] is not None}
    timestamps = sorted(vfe_ts.keys())

    for horizon in [10, 50, 100, 200]:
        fwd_rets = []
        for i, ts in enumerate(timestamps):
            ts_fwd = ts + horizon * 100
            if ts_fwd in vfe_ts:
                fwd_rets.append(vfe_ts[ts_fwd] - vfe_ts[ts])
        if len(fwd_rets) < 10:
            continue
        mn = statistics.mean(fwd_rets)
        md = statistics.median(fwd_rets)
        sd = statistics.stdev(fwd_rets)
        sharpe = mn / sd * math.sqrt(10000 / horizon) if sd > 0 else 0
        pct_pos = sum(1 for r in fwd_rets if r > 0) / len(fwd_rets) * 100
        # AR1
        ret_mean = mn
        var_r = sum((r - ret_mean)**2 for r in fwd_rets) / len(fwd_rets)
        if var_r > 0 and len(fwd_rets) > 2:
            cov_r = sum((fwd_rets[i] - ret_mean) * (fwd_rets[i-1] - ret_mean) for i in range(1, len(fwd_rets))) / (len(fwd_rets) - 1)
            ar1 = cov_r / var_r
        else:
            ar1 = 0
        print(f"{d:>3} {horizon:>8} {mn:>+8.2f} {md:>+8.2f} {sd:>8.2f} {sharpe:>+8.3f} {pct_pos:>6.1f}% {ar1:>+8.3f}")

# VFE daily drift
print("\n--- C8b: VFE Daily Drift ---")
for d in DAYS:
    vfe_recs = all_prices[d][UND]
    mids = [r['mid_price'] for r in vfe_recs if r['mid_price'] is not None]
    print(f"Day {d}: open={mids[0]:.0f} close={mids[-1]:.0f} drift={mids[-1]-mids[0]:+.0f} high={max(mids):.0f} low={min(mids):.0f} range={max(mids)-min(mids):.0f}")

# C9: Empirical delta
print("\n--- C9: Empirical Delta (10-tick rolling regression dV/dS) ---")
print(f"{'Strike':<10} {'Day':>3} {'MnDelta':>8} {'StdDelta':>9} {'Q25':>8} {'Q50':>8} {'Q75':>8} {'Delta_0':>8} {'Delta_N':>8}")
print("-" * 80)

DELTA_WINDOW = 10

def rolling_delta(vfe_mids_list, voucher_mids_list, window=10):
    """Compute rolling empirical delta using OLS on window of (dS, dV) pairs"""
    deltas = []
    for i in range(window, len(vfe_mids_list)):
        ds_list = []
        dv_list = []
        for j in range(i - window, i):
            ds = vfe_mids_list[j+1] - vfe_mids_list[j]
            dv = voucher_mids_list[j+1] - voucher_mids_list[j]
            ds_list.append(ds)
            dv_list.append(dv)
        # OLS: delta = sum(ds*dv) / sum(ds^2)
        ss_ds = sum(x**2 for x in ds_list)
        if ss_ds > 0:
            delta = sum(ds_list[k] * dv_list[k] for k in range(len(ds_list))) / ss_ds
        else:
            delta = None
        if delta is not None:
            deltas.append(delta)
    return deltas

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        # Build aligned time series
        vfe_recs = all_prices[d][UND]
        vouch_recs = all_prices[d][sname]
        vfe_ts = {r['timestamp']: r['mid_price'] for r in vfe_recs if r['mid_price'] is not None}
        vouch_ts = {r['timestamp']: r['mid_price'] for r in vouch_recs if r['mid_price'] is not None}
        common_ts = sorted(set(vfe_ts.keys()) & set(vouch_ts.keys()))
        if len(common_ts) < DELTA_WINDOW + 2:
            print(f"{sname:<10} {d:>3} -- insufficient data --")
            continue
        vfe_m = [vfe_ts[t] for t in common_ts]
        vouch_m = [vouch_ts[t] for t in common_ts]
        deltas = rolling_delta(vfe_m, vouch_m, DELTA_WINDOW)
        if not deltas:
            print(f"{sname:<10} {d:>3} -- no deltas --")
            continue
        deltas_sorted = sorted(deltas)
        n = len(deltas_sorted)
        q25 = deltas_sorted[n // 4]
        q50 = deltas_sorted[n // 2]
        q75 = deltas_sorted[3 * n // 4]
        print(f"{sname:<10} {d:>3} {statistics.mean(deltas):>+8.3f} {statistics.stdev(deltas):>9.3f} {q25:>+8.3f} {q50:>+8.3f} {q75:>+8.3f} {deltas[0]:>+8.3f} {deltas[-1]:>+8.3f}")

# C9b: Impact of +10 VFE move on voucher
print("\n--- C9b: Voucher Response to +10 VFE Move ---")
print(f"{'Strike':<10} {'Day':>3} {'#Events':>8} {'MnDV':>8} {'MdDV':>8} {'StdDV':>8}")
print("-" * 50)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        vfe_ts_map = mid_lookup(all_prices[d], UND)
        vouch_ts_map = mid_lookup(all_prices[d], sname)
        timestamps = sorted(set(vfe_ts_map.keys()) & set(vouch_ts_map.keys()))
        dvs = []
        for i in range(1, len(timestamps)):
            ds = vfe_ts_map[timestamps[i]] - vfe_ts_map[timestamps[i-1]]
            if abs(ds) >= 8 and abs(ds) <= 15:  # "roughly +/-10" events
                dv = vouch_ts_map[timestamps[i]] - vouch_ts_map[timestamps[i-1]]
                if ds < 0:
                    dv = -dv  # normalize to +10 direction
                dvs.append(dv)
        if len(dvs) > 2:
            print(f"{sname:<10} {d:>3} {len(dvs):>8} {statistics.mean(dvs):>+8.2f} {statistics.median(dvs):>+8.2f} {statistics.stdev(dvs):>8.2f}")
        else:
            print(f"{sname:<10} {d:>3} {'-- too few events --':>35}")

# C10: Gamma analysis
print("\n--- C10: Gamma / Convexity Analysis ---")
print("  (Change in empirical delta as S moves, using 200-tick blocks)")
print(f"{'Strike':<10} {'Day':>3} {'Block':>6} {'MnS':>8} {'MnDelta':>9} {'StdDelta':>9}")
print("-" * 55)

BLOCK_SIZE = 2000  # 200 ticks per block for delta estimation

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        vfe_ts_map = mid_lookup(all_prices[d], UND)
        vouch_ts_map = mid_lookup(all_prices[d], sname)
        timestamps = sorted(set(vfe_ts_map.keys()) & set(vouch_ts_map.keys()))

        n_blocks = len(timestamps) // BLOCK_SIZE
        block_results = []
        for b in range(n_blocks):
            start = b * BLOCK_SIZE
            end = (b + 1) * BLOCK_SIZE
            block_ts = timestamps[start:end]
            vfe_m = [vfe_ts_map[t] for t in block_ts]
            vouch_m = [vouch_ts_map[t] for t in block_ts]
            deltas = rolling_delta(vfe_m, vouch_m, 10)
            if deltas:
                mn_s = statistics.mean(vfe_m)
                mn_d = statistics.mean(deltas)
                sd_d = statistics.stdev(deltas) if len(deltas) > 1 else 0
                block_results.append((b, mn_s, mn_d, sd_d))
                print(f"{sname:<10} {d:>3} {b:>6} {mn_s:>8.0f} {mn_d:>+9.3f} {sd_d:>9.3f}")

        # Gamma estimate: slope of delta vs S across blocks
        if len(block_results) >= 3:
            xs = [br[1] for br in block_results]
            ys = [br[2] for br in block_results]
            mx = statistics.mean(xs)
            my = statistics.mean(ys)
            ss_x = sum((x - mx)**2 for x in xs)
            if ss_x > 0:
                gamma = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs))) / ss_x
                print(f"  >> {sname} Day{d} GAMMA estimate: {gamma:+.6f} (d(delta)/dS per unit S)")

# ============================================================
# PART D: STRATEGY COMPARISON
# ============================================================
print("\n" + "=" * 90)
print("PART D: STRATEGY COMPARISON")
print("=" * 90)

# D11: Buy-and-hold vs short-and-hold at various horizons
print("\n--- D11: Direction Comparison (300 contracts) ---")
print(f"{'Strike':<10} {'Day':>3} {'Dir':>6} {'N=100':>9} {'N=500':>9} {'N=1000':>9} {'N=5000':>9} {'N=9999':>9}")
print("-" * 70)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        recs = all_prices[d][sname]
        if not recs:
            continue
        ask0 = best_ask(recs[0])
        bid0 = best_bid(recs[0])
        if ask0 is None or bid0 is None:
            continue

        # Buy-and-hold PnL at various horizons
        long_pnls = []
        short_pnls = []
        for n_tick in [100, 500, 1000, 5000, 9999]:
            ts_target = n_tick * 100
            rec_n = ts_index[d][sname].get(ts_target)
            if rec_n is None:
                # Use closest available
                rec_n = ts_index[d][sname].get(min(ts_index[d][sname].keys(), key=lambda x: abs(x - ts_target)))
            bid_n = best_bid(rec_n) if rec_n else None
            ask_n = best_ask(rec_n) if rec_n else None

            if bid_n is not None:
                long_pnl = (bid_n - ask0) * 300
            else:
                long_pnl = None

            if ask_n is not None:
                short_pnl = (bid0 - ask_n) * 300
            else:
                short_pnl = None

            long_pnls.append(long_pnl)
            short_pnls.append(short_pnl)

        long_strs = [f"{p:>+9.0f}" if p is not None else f"{'N/A':>9}" for p in long_pnls]
        short_strs = [f"{p:>+9.0f}" if p is not None else f"{'N/A':>9}" for p in short_pnls]
        print(f"{sname:<10} {d:>3} {'LONG':>6} {''.join(long_strs)}")
        print(f"{sname:<10} {d:>3} {'SHORT':>6} {''.join(short_strs)}")

# D12: Passive bid accumulation
print("\n--- D12: Passive Bid Accumulation (OTM strikes: 5300, 5400, 5500) ---")
print(f"{'Strike':<10} {'Day':>3} {'FillEvents':>11} {'TotQtyFill':>11} {'AvgPrice':>9} {'TermBid':>8} {'PnL/ct':>8} {'PnL_accum':>10}")
print("-" * 80)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    if k < 5300:
        continue
    for d in DAYS:
        sym_trades = [t for t in all_trades[d] if t['symbol'] == sname]
        recs = all_prices[d][sname]

        # Trades at or below our hypothetical bid (best_bid + 1)
        # We approximate: count trades where trade_price <= best_bid + 1
        fill_prices = []
        fill_qtys = []
        accumulated = 0
        cap = 300

        for t in sorted(sym_trades, key=lambda x: x['timestamp']):
            ts = t['timestamp']
            rec = ts_index[d][sname].get(ts)
            if rec is None:
                continue
            b = best_bid(rec)
            if b is None:
                continue
            our_bid = b + 1
            # We get filled if trade price <= our bid (someone selling into us)
            if t['price'] <= our_bid and accumulated < cap:
                fill_qty = min(t['quantity'], cap - accumulated)
                fill_prices.append(t['price'])
                fill_qtys.append(fill_qty)
                accumulated += fill_qty

        if accumulated > 0:
            avg_px = sum(fill_prices[i] * fill_qtys[i] for i in range(len(fill_prices))) / sum(fill_qtys)
            term_bid = best_bid(recs[-1]) if recs else None
            pnl_per = (term_bid - avg_px) if term_bid is not None else None
            pnl_accum = pnl_per * accumulated if pnl_per is not None else None
            term_str = f"{term_bid:>8.0f}" if term_bid is not None else f"{'N/A':>8}"
            pnl_str = f"{pnl_per:>+8.1f}" if pnl_per is not None else f"{'N/A':>8}"
            pnl_a_str = f"{pnl_accum:>+10.0f}" if pnl_accum is not None else f"{'N/A':>10}"
            print(f"{sname:<10} {d:>3} {len(fill_prices):>11} {accumulated:>11} {avg_px:>9.1f} {term_str} {pnl_str} {pnl_a_str}")
        else:
            print(f"{sname:<10} {d:>3} {'-- no fills --':>50}")

# D13: Theta decay analysis
print("\n--- D13: Theta Decay Analysis ---")
print("\n  D13a: Intraday Theta (time value at start vs end of day)")
print(f"{'Strike':<10} {'Day':>3} {'TTE':>4} {'TV_first':>9} {'TV_last':>9} {'TV_chg':>9} {'TV_chg%':>8}")
print("-" * 60)

theta_cross_day = defaultdict(list)  # sname -> [(day, tte, tv_mean)]

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        vfe_ts_map = mid_lookup(all_prices[d], UND)
        vouch_ts_map = mid_lookup(all_prices[d], sname)
        timestamps = sorted(set(vfe_ts_map.keys()) & set(vouch_ts_map.keys()))
        if len(timestamps) < 100:
            continue

        # First 100 ticks average TV
        tvs_start = []
        for ts in timestamps[:100]:
            intrinsic = max(vfe_ts_map[ts] - k, 0)
            tv = vouch_ts_map[ts] - intrinsic
            tvs_start.append(tv)

        # Last 100 ticks average TV
        tvs_end = []
        for ts in timestamps[-100:]:
            intrinsic = max(vfe_ts_map[ts] - k, 0)
            tv = vouch_ts_map[ts] - intrinsic
            tvs_end.append(tv)

        tv_first = statistics.mean(tvs_start)
        tv_last = statistics.mean(tvs_end)
        tv_chg = tv_last - tv_first
        tv_chg_pct = tv_chg / tv_first * 100 if tv_first != 0 else 0

        print(f"{sname:<10} {d:>3} {TTE_MAP[d]:>4} {tv_first:>9.2f} {tv_last:>9.2f} {tv_chg:>+9.2f} {tv_chg_pct:>+7.1f}%")

        # For cross-day analysis
        all_tvs = []
        for ts in timestamps:
            intrinsic = max(vfe_ts_map[ts] - k, 0)
            tv = vouch_ts_map[ts] - intrinsic
            all_tvs.append(tv)
        theta_cross_day[sname].append((d, TTE_MAP[d], statistics.mean(all_tvs)))

print("\n  D13b: Cross-Day Theta (average TV by TTE)")
print(f"{'Strike':<10} {'Day0(TTE8)':>12} {'Day1(TTE7)':>12} {'Day2(TTE6)':>12} {'Theta/day':>10}")
print("-" * 60)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    entries = theta_cross_day.get(sname, [])
    if len(entries) < 2:
        continue
    entries.sort(key=lambda x: x[0])
    vals = {e[0]: e[2] for e in entries}
    d0 = vals.get(0, None)
    d1 = vals.get(1, None)
    d2 = vals.get(2, None)

    d0_str = f"{d0:>12.2f}" if d0 is not None else f"{'N/A':>12}"
    d1_str = f"{d1:>12.2f}" if d1 is not None else f"{'N/A':>12}"
    d2_str = f"{d2:>12.2f}" if d2 is not None else f"{'N/A':>12}"

    # Theta per day: average of consecutive differences
    theta_ests = []
    if d0 is not None and d1 is not None:
        theta_ests.append(d1 - d0)  # TV change for 1 day less TTE
    if d1 is not None and d2 is not None:
        theta_ests.append(d2 - d1)
    if theta_ests:
        avg_theta = statistics.mean(theta_ests)
        print(f"{sname:<10} {d0_str} {d1_str} {d2_str} {avg_theta:>+10.2f}")
    else:
        print(f"{sname:<10} {d0_str} {d1_str} {d2_str} {'N/A':>10}")

# ============================================================
# PART E: CROSS-DAY STABILITY
# ============================================================
print("\n" + "=" * 90)
print("PART E: CROSS-DAY STABILITY SUMMARY")
print("=" * 90)

print("\n--- E1: Direction of Full-Day Drift (VFE mid close - open) ---")
for d in DAYS:
    vfe_recs = all_prices[d][UND]
    mids = [r['mid_price'] for r in vfe_recs if r['mid_price'] is not None]
    print(f"  Day {d}: {mids[-1] - mids[0]:+.0f}")

print("\n--- E2: Buy-and-Hold Full-Day Sign Consistency ---")
for sname, k in zip(STRIKE_NAMES, STRIKES):
    signs = []
    for d in DAYS:
        recs = all_prices[d][sname]
        if not recs:
            signs.append(0)
            continue
        ask0 = best_ask(recs[0])
        bidn = best_bid(recs[-1])
        if ask0 is not None and bidn is not None:
            pnl = bidn - ask0
            signs.append(1 if pnl > 0 else (-1 if pnl < 0 else 0))
        else:
            signs.append(0)
    consistent = all(s == signs[0] for s in signs) and signs[0] != 0
    print(f"  {sname}: signs={signs}  consistent={'YES' if consistent else 'NO'}")

print("\n--- E3: Taker Flow Direction Consistency ---")
for sname, k in zip(STRIKE_NAMES, STRIKES):
    signs = []
    for d in DAYS:
        sym_trades = [t for t in all_trades[d] if t['symbol'] == sname]
        bid_qty = ask_qty = 0
        for t in sym_trades:
            ts = t['timestamp']
            rec = ts_index[d][sname].get(ts)
            if rec is None:
                continue
            b, a = best_bid(rec), best_ask(rec)
            tp = t['price']
            if b is not None and tp <= b:
                bid_qty += t['quantity']
            elif a is not None and tp >= a:
                ask_qty += t['quantity']
        net = ask_qty - bid_qty
        signs.append(1 if net > 0 else (-1 if net < 0 else 0))
    consistent = all(s == signs[0] for s in signs) and signs[0] != 0
    print(f"  {sname}: net_buy_signs={signs}  consistent={'YES' if consistent else 'NO'}")

print("\n--- E4: Intraday Theta Sign Consistency ---")
for sname, k in zip(STRIKE_NAMES, STRIKES):
    signs = []
    for d in DAYS:
        vfe_ts_map = mid_lookup(all_prices[d], UND)
        vouch_ts_map = mid_lookup(all_prices[d], sname)
        timestamps = sorted(set(vfe_ts_map.keys()) & set(vouch_ts_map.keys()))
        if len(timestamps) < 200:
            signs.append(0)
            continue
        tvs_start = [vouch_ts_map[ts] - max(vfe_ts_map[ts] - k, 0) for ts in timestamps[:100]]
        tvs_end = [vouch_ts_map[ts] - max(vfe_ts_map[ts] - k, 0) for ts in timestamps[-100:]]
        tv_chg = statistics.mean(tvs_end) - statistics.mean(tvs_start)
        signs.append(1 if tv_chg > 0 else (-1 if tv_chg < 0 else 0))
    consistent = all(s == signs[0] for s in signs) and signs[0] != 0
    print(f"  {sname}: theta_signs={signs}  consistent={'YES' if consistent else 'NO'}")

print("\n--- E5: Cross-Day Theta (TV decreasing with TTE) Consistency ---")
for sname, k in zip(STRIKE_NAMES, STRIKES):
    entries = theta_cross_day.get(sname, [])
    entries.sort(key=lambda x: x[0])
    if len(entries) >= 2:
        tvs = [e[2] for e in entries]
        decreasing = all(tvs[i] > tvs[i+1] for i in range(len(tvs)-1))
        print(f"  {sname}: TVs by day={[f'{tv:.1f}' for tv in tvs]}  monotone_decreasing={'YES' if decreasing else 'NO'}")
    else:
        print(f"  {sname}: insufficient data")

print("\n--- E6: Empirical Delta Stability ---")
for sname, k in zip(STRIKE_NAMES, STRIKES):
    day_deltas = []
    for d in DAYS:
        vfe_ts_map = mid_lookup(all_prices[d], UND)
        vouch_ts_map = mid_lookup(all_prices[d], sname)
        common_ts = sorted(set(vfe_ts_map.keys()) & set(vouch_ts_map.keys()))
        if len(common_ts) < DELTA_WINDOW + 2:
            day_deltas.append(None)
            continue
        vfe_m = [vfe_ts_map[t] for t in common_ts]
        vouch_m = [vouch_ts_map[t] for t in common_ts]
        deltas = rolling_delta(vfe_m, vouch_m, DELTA_WINDOW)
        if deltas:
            day_deltas.append(statistics.mean(deltas))
        else:
            day_deltas.append(None)
    delta_strs = [f"{d:+.3f}" if d is not None else "N/A" for d in day_deltas]
    if all(d is not None for d in day_deltas):
        rng = max(day_deltas) - min(day_deltas)
        mn = statistics.mean(day_deltas)
        cv = rng / abs(mn) if mn != 0 else float('inf')
        print(f"  {sname}: deltas={delta_strs}  range/mean_ratio={cv:.2f}")
    else:
        print(f"  {sname}: deltas={delta_strs}")

# ============================================================
# BONUS: VFE vs Voucher correlation matrix
# ============================================================
print("\n" + "=" * 90)
print("BONUS: INTER-STRIKE RETURN CORRELATIONS (Day 2, 1k ticks)")
print("=" * 90)

d = 2
products_corr = [UND] + STRIKE_NAMES
ts_range = range(0, 100000, 100)  # first 1k ticks
returns_by_product = {}

for p in products_corr:
    mids = []
    for ts in ts_range:
        rec = ts_index[d][p].get(ts)
        if rec and rec['mid_price'] is not None:
            mids.append(rec['mid_price'])
        else:
            mids.append(None)
    rets = []
    for i in range(1, len(mids)):
        if mids[i] is not None and mids[i-1] is not None:
            rets.append(mids[i] - mids[i-1])
        else:
            rets.append(0)
    returns_by_product[p] = rets

def correlation(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    sx = math.sqrt(sum((x - mx)**2 for x in xs) / n)
    sy = math.sqrt(sum((y - my)**2 for y in ys) / n)
    if sx > 0 and sy > 0:
        return cov / (sx * sy)
    return 0

print(f"\n{'':>22}", end="")
for p in products_corr:
    label = p.replace("VELVETFRUIT_EXTRACT", "VFE").replace("VEV_", "")
    print(f"{label:>8}", end="")
print()

for p1 in products_corr:
    label1 = p1.replace("VELVETFRUIT_EXTRACT", "VFE").replace("VEV_", "")
    print(f"{label1:>22}", end="")
    for p2 in products_corr:
        corr = correlation(returns_by_product[p1], returns_by_product[p2])
        print(f"{corr:>8.3f}", end="")
    print()

# ============================================================
# BONUS: Spread width TOP-OF-BOOK analysis per tick for each strike
# ============================================================
print("\n" + "=" * 90)
print("BONUS: VOLUME AT BEST BID/ASK (L1 depth)")
print("=" * 90)
print(f"\n{'Strike':<10} {'Day':>3} {'MnBidVol':>9} {'MnAskVol':>9} {'MdBidVol':>9} {'MdAskVol':>9} {'Imbalance':>10}")
print("-" * 60)

for sname, k in zip(STRIKE_NAMES, STRIKES):
    for d in DAYS:
        bid_vols = []
        ask_vols = []
        for r in all_prices[d][sname]:
            bv = r.get('bid_volume_1')
            av = r.get('ask_volume_1')
            if bv is not None:
                bid_vols.append(bv)
            if av is not None:
                ask_vols.append(abs(av))  # ask vols may be negative
        if not bid_vols or not ask_vols:
            continue
        mn_bv = statistics.mean(bid_vols)
        mn_av = statistics.mean(ask_vols)
        md_bv = statistics.median(bid_vols)
        md_av = statistics.median(ask_vols)
        imb = (mn_bv - mn_av) / (mn_bv + mn_av) * 100 if (mn_bv + mn_av) > 0 else 0
        print(f"{sname:<10} {d:>3} {mn_bv:>9.1f} {mn_av:>9.1f} {md_bv:>9.0f} {md_av:>9.0f} {imb:>+9.1f}%")

print("\n\n=== ANALYSIS COMPLETE ===\n")
