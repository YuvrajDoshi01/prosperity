"""Quick sweep: test L2 OBI coefficient values and narrow spread signal impact on day 0."""
import subprocess, sys, re, os, shutil

BASE = '/Users/y0d046w/Desktop/prosperity4-tester-private'
TEMPLATE = os.path.join(BASE, 'trader-logic/round-0/s38_v3_l2obi_only.py')

# Read template
with open(TEMPLATE) as f:
    base_code = f.read()

results = []

# Sweep 1: L2 OBI post coefficient
for l2_coef in [0.0, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
    code = base_code.replace("L2_OBI_POST_SHIFT = 0.8", f"L2_OBI_POST_SHIFT = {l2_coef}")
    tmp = os.path.join(BASE, 'trader-logic/round-0/s38_tmp_sweep.py')
    with open(tmp, 'w') as f:
        f.write(code)

    cmd = f"python3 -m prosperity4bt {tmp} 0--0 --no-out --no-progress"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BASE)
    output = r.stdout + r.stderr

    # Parse total profit
    m = re.search(r'Total profit:\s*([\d,.-]+)', output)
    if m:
        profit = int(m.group(1).replace(',', ''))
        results.append(('L2_OBI_POST', l2_coef, profit))
        print(f"L2_OBI_POST_SHIFT={l2_coef:4.1f} → day 0 PnL: {profit}")
    else:
        print(f"L2_OBI_POST_SHIFT={l2_coef:4.1f} → FAILED: {output[:200]}")

# Sweep 2: Use L2 OBI for TAKES too (replace total OBI)
for l2_take_coef in [0.3, 0.5, 0.8, 1.0]:
    code = base_code.replace("L2_OBI_POST_SHIFT = 0.8", f"L2_OBI_POST_SHIFT = 0.8")
    # Replace the take OBI line with L2 OBI
    code = code.replace(
        "take_fv += obi * OBI_FV_SHIFT\n                take_fv_int = round(take_fv)",
        f"""# Use L2 OBI for takes too
                sorted_bids_t = sorted(book.buy_orders.items(), reverse=True)
                sorted_asks_t = sorted(book.sell_orders.items())
                bv2_t = sorted_bids_t[1][1] if len(sorted_bids_t) > 1 else 0
                av2_t = -sorted_asks_t[1][1] if len(sorted_asks_t) > 1 else 0
                if bv2_t + av2_t > 0:
                    l2_obi_t = (bv2_t - av2_t) / (bv2_t + av2_t)
                    take_fv += l2_obi_t * {l2_take_coef}
                else:
                    take_fv += obi * OBI_FV_SHIFT
                take_fv_int = round(take_fv)"""
    )
    tmp = os.path.join(BASE, 'trader-logic/round-0/s38_tmp_sweep.py')
    with open(tmp, 'w') as f:
        f.write(code)

    cmd = f"python3 -m prosperity4bt {tmp} 0--0 --no-out --no-progress"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BASE)
    output = r.stdout + r.stderr

    m = re.search(r'Total profit:\s*([\d,.-]+)', output)
    if m:
        profit = int(m.group(1).replace(',', ''))
        results.append(('L2_OBI_TAKE', l2_take_coef, profit))
        print(f"L2_OBI_TAKE={l2_take_coef:4.1f} (post=0.8) → day 0 PnL: {profit}")
    else:
        print(f"L2_OBI_TAKE={l2_take_coef:4.1f} → FAILED: {output[:200]}")

# Clean up
tmp = os.path.join(BASE, 'trader-logic/round-0/s38_tmp_sweep.py')
if os.path.exists(tmp):
    os.remove(tmp)

print("\n=== SUMMARY ===")
print(f"s36 baseline day 0: 2,626")
for label, coef, profit in sorted(results, key=lambda x: -x[2]):
    delta = profit - 2626
    print(f"  {label}={coef:4.1f}: {profit:,} ({delta:+d})")
