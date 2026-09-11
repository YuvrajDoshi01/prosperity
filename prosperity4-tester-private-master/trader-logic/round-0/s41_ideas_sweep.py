"""
Test 8 genuinely untested ideas on top of s40_v2 baseline.
Each idea is isolated, then best combinations are tested.
"""
import subprocess, sys, re, os

BASELINE = "trader-logic/round-0/s40_v2.py"
TMPFILE = "trader-logic/round-0/s41_tmp.py"

with open(BASELINE) as f:
    baseline_code = f.read()

def run_bt(path, day):
    cmd = [sys.executable, "-m", "prosperity4bt", path, f"0-{day}", "--no-out", "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    m = re.search(r'Total profit:\s*([-\d,]+)', out)
    if m:
        return int(m.group(1).replace(',', ''))
    return None

def test_variant(name, code):
    with open(TMPFILE, 'w') as f:
        f.write(code)
    d0 = run_bt(TMPFILE, 0) or 0
    d1 = run_bt(TMPFILE, -1) or 0
    d2 = run_bt(TMPFILE, -2) or 0
    total = d0 + d1 + d2
    print(f"{name:<40} {d0:>8,} {d1:>8,} {d2:>8,} {total:>8,}")
    sys.stdout.flush()
    return d0, d1, d2, total

print(f"{'Variant':<40} {'Day0':>8} {'Day-1':>8} {'Day-2':>8} {'Total':>8}")
print("=" * 75)

# ── Baseline: s40_v2 as-is ──
test_variant("s40_v2_baseline", baseline_code)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 1: Order submission sequencing — sells before buys when long
# ═══════════════════════════════════════════════════════════════════════════
code1 = baseline_code.replace(
    """                # ── Phase 1: Take at L2 OBI-enhanced FV (same as s38) ──
                for price, vol in sorted(book.sell_orders.items()):
                    if buy_capacity > 0 and price <= take_fv_int:
                        qty = min(buy_capacity, -vol)
                        tom_orders.append(Order("TOMATOES", price, qty))
                        buy_capacity -= qty

                for price, vol in sorted(book.buy_orders.items(), reverse=True):
                    if sell_capacity > 0 and price >= take_fv_int:
                        qty = min(sell_capacity, vol)
                        tom_orders.append(Order("TOMATOES", price, -qty))
                        sell_capacity -= qty""",
    """                # ── Phase 1: Take at L2 OBI-enhanced FV — POSITION-AWARE ORDER ──
                if pos > 0:
                    # Long: sell first (reduce position), then buy
                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_capacity > 0 and price >= take_fv_int:
                            qty = min(sell_capacity, vol)
                            tom_orders.append(Order("TOMATOES", price, -qty))
                            sell_capacity -= qty
                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_capacity > 0 and price <= take_fv_int:
                            qty = min(buy_capacity, -vol)
                            tom_orders.append(Order("TOMATOES", price, qty))
                            buy_capacity -= qty
                else:
                    # Short/flat: buy first (reduce position), then sell
                    for price, vol in sorted(book.sell_orders.items()):
                        if buy_capacity > 0 and price <= take_fv_int:
                            qty = min(buy_capacity, -vol)
                            tom_orders.append(Order("TOMATOES", price, qty))
                            buy_capacity -= qty
                    for price, vol in sorted(book.buy_orders.items(), reverse=True):
                        if sell_capacity > 0 and price >= take_fv_int:
                            qty = min(sell_capacity, vol)
                            tom_orders.append(Order("TOMATOES", price, -qty))
                            sell_capacity -= qty""")
test_variant("idea1_order_sequencing", code1)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 2: No carry signal (test if it's noise)
# ═══════════════════════════════════════════════════════════════════════════
code2 = baseline_code.replace("CARRY_THRESHOLD = 0.5", "CARRY_THRESHOLD = 999.0")
test_variant("idea2_no_carry", code2)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 3: Position-dependent take threshold for TOMATOES
# ═══════════════════════════════════════════════════════════════════════════
code3 = baseline_code.replace(
    """                take_fv_int = round(fair_value)""",
    """                # Position-dependent take threshold: more willing to reduce
                take_fv_adj = fair_value
                if pos > 30:
                    take_fv_adj -= 0.3  # shift FV down → easier to sell
                elif pos < -30:
                    take_fv_adj += 0.3  # shift FV up → easier to buy
                take_fv_int = round(take_fv_adj)""")
test_variant("idea3_pos_take_thresh", code3)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 4: EMERALDS position-dependent posting skew
# ═══════════════════════════════════════════════════════════════════════════
code4 = baseline_code.replace(
    """                if buy_capacity > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_capacity))""",
    """                if buy_capacity > 0:
                    # Position-dependent: when long, back off buy; when short, get aggressive
                    em_bid_offset = 1  # default: FV - 1
                    if pos > 30:
                        em_bid_offset = 2  # back off when already long
                    elif pos < -30:
                        em_bid_offset = 0  # at FV when short (eager to buy)
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - em_bid_offset, bids[0][0] + 1), buy_capacity))""")
code4 = code4.replace(
    """                if sell_capacity > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_capacity))""",
    """                if sell_capacity > 0:
                    # Position-dependent: when short, back off sell; when long, get aggressive
                    em_ask_offset = 1  # default: FV + 1
                    if pos < -30:
                        em_ask_offset = 2  # back off when already short
                    elif pos > 30:
                        em_ask_offset = 0  # at FV when long (eager to sell)
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + em_ask_offset, asks[0][0] - 1), -sell_capacity))""")
test_variant("idea4_em_pos_skew", code4)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 5: Asymmetric sizing — cap extending side at 20
# ═══════════════════════════════════════════════════════════════════════════
code5 = baseline_code.replace(
    """                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # ── Phase 1: Take""",
    """                buy_capacity = POSITION_LIMIT - pos
                sell_capacity = POSITION_LIMIT + pos

                # ── Asymmetric sizing: cap extending side for posting ──
                post_buy_cap = buy_capacity
                post_sell_cap = sell_capacity
                if pos > 40:
                    post_buy_cap = min(buy_capacity, 15)  # limit buys when already long
                elif pos < -40:
                    post_sell_cap = min(sell_capacity, 15)  # limit sells when already short

                # ── Phase 1: Take""")
# Replace posting to use post_buy_cap/post_sell_cap
code5 = code5.replace(
    "tom_orders.append(Order(\"TOMATOES\", bid_price, buy_capacity))",
    "tom_orders.append(Order(\"TOMATOES\", bid_price, post_buy_cap))")
code5 = code5.replace(
    "tom_orders.append(Order(\"TOMATOES\", ask_price, -sell_capacity))",
    "tom_orders.append(Order(\"TOMATOES\", ask_price, -post_sell_cap))")
test_variant("idea5_asym_sizing", code5)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 6: Position-dependent rounding control
# ═══════════════════════════════════════════════════════════════════════════
code6 = baseline_code.replace(
    """                take_fv_int = round(fair_value)""",
    """                # Position-dependent rounding: when long, floor FV; when short, ceil FV
                import math
                if pos > 20:
                    take_fv_int = math.floor(fair_value)  # more willing to sell
                elif pos < -20:
                    take_fv_int = math.ceil(fair_value)   # more willing to buy
                else:
                    take_fv_int = round(fair_value)""")
test_variant("idea6_pos_rounding", code6)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 7: Multi-level posting (two price levels)
# ═══════════════════════════════════════════════════════════════════════════
code7 = baseline_code.replace(
    """                else:
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        tom_orders.append(Order("TOMATOES", bid_price, buy_capacity))
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        tom_orders.append(Order("TOMATOES", ask_price, -sell_capacity))""",
    """                else:
                    if buy_capacity > 0:
                        bid_price = min(post_fv_int - 1, best_bid + 1)
                        bid_price = min(bid_price, best_ask - 1)
                        primary_buy = min(buy_capacity, 40)
                        tom_orders.append(Order("TOMATOES", bid_price, primary_buy))
                        if buy_capacity - primary_buy > 0:
                            bid2 = min(post_fv_int - 2, best_bid)
                            bid2 = min(bid2, best_ask - 1)
                            tom_orders.append(Order("TOMATOES", bid2, buy_capacity - primary_buy))
                    if sell_capacity > 0:
                        ask_price = max(post_fv_int + 1, best_ask - 1)
                        ask_price = max(ask_price, best_bid + 1)
                        primary_sell = min(sell_capacity, 40)
                        tom_orders.append(Order("TOMATOES", ask_price, -primary_sell))
                        if sell_capacity - primary_sell > 0:
                            ask2 = max(post_fv_int + 2, best_ask)
                            ask2 = max(ask2, best_bid + 1)
                            tom_orders.append(Order("TOMATOES", ask2, -(sell_capacity - primary_sell)))""")
test_variant("idea7_multi_level", code7)

# ═══════════════════════════════════════════════════════════════════════════
# IDEA 8: Combined best ideas (we'll fill in after seeing individual results)
# ═══════════════════════════════════════════════════════════════════════════
# Combine: order sequencing + no carry + EM pos skew
code8 = code1  # start with order sequencing
code8 = code8.replace("CARRY_THRESHOLD = 0.5", "CARRY_THRESHOLD = 999.0")
# Add EM pos skew
code8 = code8.replace(
    """                if buy_capacity > 0:
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - 1, bids[0][0] + 1), buy_capacity))""",
    """                if buy_capacity > 0:
                    em_bid_offset = 1
                    if pos > 30:
                        em_bid_offset = 2
                    elif pos < -30:
                        em_bid_offset = 0
                    em_orders.append(Order("EMERALDS", min(EMERALD_FV - em_bid_offset, bids[0][0] + 1), buy_capacity))""")
code8 = code8.replace(
    """                if sell_capacity > 0:
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + 1, asks[0][0] - 1), -sell_capacity))""",
    """                if sell_capacity > 0:
                    em_ask_offset = 1
                    if pos < -30:
                        em_ask_offset = 2
                    elif pos > 30:
                        em_ask_offset = 0
                    em_orders.append(Order("EMERALDS", max(EMERALD_FV + em_ask_offset, asks[0][0] - 1), -sell_capacity))""")
test_variant("idea8_combo_seq+nocarry+em", code8)

if os.path.exists(TMPFILE):
    os.remove(TMPFILE)
