"""Sweep: s38 base with no-flatten, position skew, VWAP take FV, and combos."""
import subprocess, sys, re, os

BASE = '/Users/y0d046w/Desktop/prosperity4-tester-private'

# Read s38 as base
with open(os.path.join(BASE, 'trader-logic/round-0/s38_l2obi_takes.py')) as f:
    s38_base = f.read()

results = []

def run_variant(name, code):
    tmp = os.path.join(BASE, 'trader-logic/round-0/s39_tmp.py')
    with open(tmp, 'w') as f:
        f.write(code)
    cmd = f"python3 -m prosperity4bt {tmp} 0 --no-out --no-progress"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BASE)
    out = r.stdout + r.stderr
    # Parse per-day results
    day_profits = {}
    for line in out.split('\n'):
        m = re.search(r'Round 0 day (-?\d+): ([\d,.-]+)', line)
        if m:
            day_profits[int(m.group(1))] = int(m.group(2).replace(',', ''))
    total = re.search(r'Total profit:\s*([\d,.-]+)', out.split('Profit summary')[-1] if 'Profit summary' in out else '')
    total_profit = int(total.group(1).replace(',', '')) if total else 0
    results.append((name, day_profits.get(0, 0), day_profits.get(-1, 0), day_profits.get(-2, 0), total_profit))
    d0 = day_profits.get(0, 0)
    print(f"{name:35s} → d0={d0:>6,}  d-1={day_profits.get(-1,0):>6,}  d-2={day_profits.get(-2,0):>6,}  total={total_profit:>6,}")
    os.remove(tmp)

# 1. s38 baseline (with terminal flatten)
run_variant("s38_baseline", s38_base)

# 2. s38 without terminal flatten
no_flat = s38_base.replace("TERMINAL_TIMESTAMP = 900000", "TERMINAL_TIMESTAMP = 999999999")
run_variant("s38_no_flatten", no_flat)

# 3. s38 + position-proportional FV skew (Avellaneda-style)
for gamma in [0.005, 0.01, 0.015, 0.02, 0.03]:
    code = s38_base.replace(
        "fair_value_int = round(fair_value)",
        f"""# Position-proportional quote skew (A-S style)
                pos_skew = state.position.get("TOMATOES", 0) * {gamma}
                fair_value -= pos_skew
                fair_value_int = round(fair_value)"""
    )
    run_variant(f"s38_skew_gamma={gamma}", code)

# 4. s38 no-flatten + skew
for gamma in [0.01, 0.015, 0.02]:
    code = s38_base.replace("TERMINAL_TIMESTAMP = 900000", "TERMINAL_TIMESTAMP = 999999999")
    code = code.replace(
        "fair_value_int = round(fair_value)",
        f"""# Position-proportional quote skew (A-S style)
                pos_skew = state.position.get("TOMATOES", 0) * {gamma}
                fair_value -= pos_skew
                fair_value_int = round(fair_value)"""
    )
    run_variant(f"s38_no_flat+skew={gamma}", code)

# 5. s38 with VWAP replacing microprice for FV (but keep L2 OBI)
vwap_code = s38_base.replace(
    """                # ── Fair value: microprice regression (identical to s36) ──
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                microprice = (best_bid + (total_bid_vol / (total_bid_vol + total_ask_vol))
                              * (best_ask - best_bid)
                              if (total_bid_vol + total_ask_vol) > 0 else mid)

                hist = self.microprice_history
                if len(hist) >= REGRESSION_LAGS:
                    hist = hist[1:]
                hist.append(microprice)
                self.microprice_history = hist

                if len(hist) == REGRESSION_LAGS:
                    fair_value = REGRESSION_INTERCEPT + sum(
                        c * x for c, x in zip(REGRESSION_COEFS, hist))
                else:
                    fair_value = microprice""",
    """                # ── Fair value: VWAP (R²=0.40, the dominant signal) ──
                total_bid_vol = sum(book.buy_orders.values())
                total_ask_vol = sum(-v for v in book.sell_orders.values())
                vwap_num = 0.0
                vwap_den = 0.0
                for p, v in sorted_bids:
                    vwap_num += p * v
                    vwap_den += v
                for p, v in sorted_asks:
                    vwap_num += p * (-v)
                    vwap_den += (-v)
                fair_value = vwap_num / vwap_den if vwap_den > 0 else mid"""
)
run_variant("s38_vwap_fv", vwap_code)

# 6. VWAP FV + no flatten + skew
for gamma in [0.01, 0.015]:
    code = vwap_code.replace("TERMINAL_TIMESTAMP = 900000", "TERMINAL_TIMESTAMP = 999999999")
    code = code.replace(
        "fair_value_int = round(fair_value)",
        f"""pos_skew = state.position.get("TOMATOES", 0) * {gamma}
                fair_value -= pos_skew
                fair_value_int = round(fair_value)"""
    )
    run_variant(f"vwap_no_flat+skew={gamma}", code)

print(f"\n{'='*80}")
print(f"{'RANKING (Day 0 only — calibration day)':^80}")
print(f"{'='*80}")
for name, d0, d1, d2, total in sorted(results, key=lambda x: -x[1]):
    delta = d0 - 2626
    print(f"  {name:35s}  d0={d0:>6,} ({delta:>+5})  d-1={d1:>6,}  d-2={d2:>6,}")
