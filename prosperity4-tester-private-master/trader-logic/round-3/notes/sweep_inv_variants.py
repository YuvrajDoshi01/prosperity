"""sweep_inv_variants.py - Test multiple inventory management variants.

Variant A: Suppress same-side quotes when |pos| > thresh (v22 baseline vs thresh=50)
Variant B: Only suppress BIDS when pos > thresh (asymmetric, since pos is biased long)
Variant C: Ask-only mode when pos > thresh (post ask at mid-1 to actively flatten)
Variant D: Reduce QUOTE_SIZE proportionally when pos is high (gradual)
"""
import subprocess
import sys
import os
import re
import textwrap

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
V22_SCRIPT = os.path.join(BASE, "trader-logic", "round-3", "r3_v22.py")
TEMP_SCRIPT = os.path.join(BASE, "trader-logic", "round-3", "notes", "_temp_variant.py")


def run_bt(script_path, day):
    """Run BT and extract HP and total PnL."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(BASE, "prosperity4bt")
    result = subprocess.run(
        [sys.executable, "-m", "prosperity4bt", script_path, f"3-{day}",
         "--ticks", "10000", "--no-progress", "--no-out"],
        capture_output=True, text=True, env=env, cwd=BASE
    )
    output = result.stdout + result.stderr
    hp_pnl = total_pnl = None
    for line in output.split("\n"):
        m = re.search(r'HYDROGEL_PACK:\s*([\-\d,]+)', line)
        if m: hp_pnl = int(m.group(1).replace(",", ""))
        m = re.search(r'Total profit:\s*([\-\d,]+)', line)
        if m: total_pnl = int(m.group(1).replace(",", ""))
    return hp_pnl or 0, total_pnl or 0


def patch_v22(replacement_block):
    """Read v22, replace passive MM section, write to temp script."""
    with open(V22_SCRIPT, "r") as f:
        src = f.read()

    # The passive MM block starts after "# Passive MM fallback"
    # and goes to the end of run_hydrogel (before "return orders, hstate" at the end)
    # We need to replace from "# Passive MM fallback" to the final "return orders, hstate"

    marker_start = "    # Passive MM fallback with dynamic Layer-A skew (online edge beta)."
    marker_end = "    return orders, hstate\n\n\n# "

    idx_start = src.find(marker_start)
    idx_end = src.find(marker_end, idx_start)

    if idx_start < 0 or idx_end < 0:
        print(f"ERROR: Could not find passive MM block markers in v22")
        print(f"  marker_start found: {idx_start >= 0}")
        print(f"  marker_end found: {idx_end >= 0}")
        sys.exit(1)

    patched = src[:idx_start] + replacement_block + "\n    return orders, hstate\n\n\n# " + src[idx_end + len(marker_end):]

    with open(TEMP_SCRIPT, "w") as f:
        f.write(patched)


# Variant B: Only suppress BIDS when pos > 50 (keep asks to flatten)
VARIANT_B = """\
    # Passive MM fallback — VARIANT B: suppress bids when pos > 50
    if len(hstate.edge_buf) >= p.EDGE_BETA_MIN_SAMPLES:
        ex = _mean(hstate.edge_buf) or 0.0
        ey = _mean(hstate.ret_buf) or 0.0
        var_x  = _mean([(x - ex) ** 2 for x in hstate.edge_buf]) or 0.0
        cov_xy = _mean([(x - ex) * (y - ey) for x, y in zip(hstate.edge_buf, hstate.ret_buf)]) or 0.0
        beta = (cov_xy / var_x) if var_x > 1e-9 else 0.0
    else:
        beta = p.LAYER_A_SCALE
    beta_eff = p.EDGE_BETA_SHRINK * beta
    bid_offset = _clip(wap_edge * beta_eff, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    slack = 1
    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position
    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid   = int(round(base_bid + bid_offset))
    my_ask   = int(round(base_ask + bid_offset))
    my_bid   = max(my_bid, best_bid + 1)
    my_ask   = min(my_ask, best_ask - 1)
    my_bid   = min(my_bid, best_ask - 1)
    my_ask   = max(my_ask, best_bid + 1)
    if my_ask <= my_bid: my_ask = my_bid + 1
    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))
    # VARIANT B: suppress bids only when long > 50
    if position > 50:
        bid_qty = 0
    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))
"""

# Variant C: Active flatten — when pos > 50, post aggressive ask at best_bid+1 instead of passive ask
VARIANT_C = """\
    # Passive MM fallback — VARIANT C: aggressive flatten when pos > 50
    if len(hstate.edge_buf) >= p.EDGE_BETA_MIN_SAMPLES:
        ex = _mean(hstate.edge_buf) or 0.0
        ey = _mean(hstate.ret_buf) or 0.0
        var_x  = _mean([(x - ex) ** 2 for x in hstate.edge_buf]) or 0.0
        cov_xy = _mean([(x - ex) * (y - ey) for x, y in zip(hstate.edge_buf, hstate.ret_buf)]) or 0.0
        beta = (cov_xy / var_x) if var_x > 1e-9 else 0.0
    else:
        beta = p.LAYER_A_SCALE
    beta_eff = p.EDGE_BETA_SHRINK * beta
    bid_offset = _clip(wap_edge * beta_eff, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    slack = 1
    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position
    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid   = int(round(base_bid + bid_offset))
    my_ask   = int(round(base_ask + bid_offset))
    my_bid   = max(my_bid, best_bid + 1)
    my_ask   = min(my_ask, best_ask - 1)
    my_bid   = min(my_bid, best_ask - 1)
    my_ask   = max(my_ask, best_bid + 1)
    if my_ask <= my_bid: my_ask = my_bid + 1
    bid_qty = min(p.QUOTE_SIZE, max(0, bid_headroom))
    ask_qty = min(p.QUOTE_SIZE, max(0, ask_headroom))
    # VARIANT C: when long > 50, suppress bids, post ask at best_bid+1 (aggressive flatten)
    if position > 50:
        bid_qty = 0
        my_ask = best_bid + 1  # aggressive ask to sell
        ask_qty = min(25, position)  # sell down toward 0
    elif position < -50:
        ask_qty = 0
        my_bid = best_ask - 1  # aggressive bid to cover
        bid_qty = min(25, -position)
    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))
"""

# Variant D: Gradual quote size reduction — QUOTE_SIZE scales linearly from 25 to 5 as |pos| goes from 0 to 200
VARIANT_D = """\
    # Passive MM fallback — VARIANT D: gradual quote size reduction
    if len(hstate.edge_buf) >= p.EDGE_BETA_MIN_SAMPLES:
        ex = _mean(hstate.edge_buf) or 0.0
        ey = _mean(hstate.ret_buf) or 0.0
        var_x  = _mean([(x - ex) ** 2 for x in hstate.edge_buf]) or 0.0
        cov_xy = _mean([(x - ex) * (y - ey) for x, y in zip(hstate.edge_buf, hstate.ret_buf)]) or 0.0
        beta = (cov_xy / var_x) if var_x > 1e-9 else 0.0
    else:
        beta = p.LAYER_A_SCALE
    beta_eff = p.EDGE_BETA_SHRINK * beta
    bid_offset = _clip(wap_edge * beta_eff, -p.LAYER_A_CLIP, p.LAYER_A_CLIP)
    slack = 1
    fv = int(round(mid))
    bid_headroom = pos_lim - position
    ask_headroom = pos_lim + position
    base_bid = min(fv - slack, best_bid + 1)
    base_ask = max(fv + slack, best_ask - 1)
    my_bid   = int(round(base_bid + bid_offset))
    my_ask   = int(round(base_ask + bid_offset))
    my_bid   = max(my_bid, best_bid + 1)
    my_ask   = min(my_ask, best_ask - 1)
    my_bid   = min(my_bid, best_ask - 1)
    my_ask   = max(my_ask, best_bid + 1)
    if my_ask <= my_bid: my_ask = my_bid + 1
    # VARIANT D: scale same-side quote size based on position
    # When long, reduce bid qty; when short, reduce ask qty
    abs_pos = abs(position)
    scale = max(0.0, 1.0 - abs_pos / 200.0)  # 1.0 at pos=0, 0.0 at pos=200
    same_side_qty = max(2, int(25 * scale))
    opposite_side_qty = 25  # always quote full size on flattening side
    if position >= 0:
        bid_qty = min(same_side_qty, max(0, bid_headroom))
        ask_qty = min(opposite_side_qty, max(0, ask_headroom))
    else:
        bid_qty = min(opposite_side_qty, max(0, bid_headroom))
        ask_qty = min(same_side_qty, max(0, ask_headroom))
    if bid_qty > 0:
        orders.append(Order(P, my_bid, bid_qty))
    if ask_qty > 0:
        orders.append(Order(P, my_ask, -ask_qty))
"""


def main():
    days = [0, 1, 2]

    # Baseline: original v22
    print(f"{'Variant':>12} | ", end="")
    for d in days:
        print(f"{'D'+str(d)+' HP':>10} ", end="")
    print(f"| {'3-Day HP':>10} {'3-Day Tot':>10}")
    print("-" * 80)

    # v22 baseline
    hp_sum = 0
    tot_sum = 0
    print(f"{'v22 base':>12} | ", end="")
    for d in days:
        hp, tot = run_bt(V22_SCRIPT, d)
        hp_sum += hp
        tot_sum += tot
        print(f"{hp:10,d} ", end="")
    print(f"| {hp_sum:10,d} {tot_sum:10,d}")

    # Variant B: suppress bids when pos > 50
    patch_v22(VARIANT_B)
    hp_sum = 0; tot_sum = 0
    print(f"{'B:bid>50':>12} | ", end="")
    for d in days:
        hp, tot = run_bt(TEMP_SCRIPT, d)
        hp_sum += hp; tot_sum += tot
        print(f"{hp:10,d} ", end="")
    print(f"| {hp_sum:10,d} {tot_sum:10,d}")

    # Variant C: aggressive flatten when pos > 50
    patch_v22(VARIANT_C)
    hp_sum = 0; tot_sum = 0
    print(f"{'C:aggr>50':>12} | ", end="")
    for d in days:
        hp, tot = run_bt(TEMP_SCRIPT, d)
        hp_sum += hp; tot_sum += tot
        print(f"{hp:10,d} ", end="")
    print(f"| {hp_sum:10,d} {tot_sum:10,d}")

    # Variant D: gradual quote size reduction
    patch_v22(VARIANT_D)
    hp_sum = 0; tot_sum = 0
    print(f"{'D:gradual':>12} | ", end="")
    for d in days:
        hp, tot = run_bt(TEMP_SCRIPT, d)
        hp_sum += hp; tot_sum += tot
        print(f"{hp:10,d} ", end="")
    print(f"| {hp_sum:10,d} {tot_sum:10,d}")

    # Cleanup
    if os.path.exists(TEMP_SCRIPT):
        os.remove(TEMP_SCRIPT)


if __name__ == "__main__":
    main()
