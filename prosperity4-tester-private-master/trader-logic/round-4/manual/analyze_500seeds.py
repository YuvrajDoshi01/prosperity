"""Compare 5-seed vs 500-seed Phase 2 results, build tightened Pareto frontier."""
import json
import numpy as np

p2_5 = json.load(open("results/phase2_results.json"))
p2_500 = json.load(open("results/phase2_500seeds_results.json"))

print("=" * 110)
print(f"5-SEED vs 500-SEED PHASE 2 COMPARISON")
print("=" * 110)
print(f"5-seed:   {p2_5['n_seeds']} seeds x {p2_5['n_paths_per_seed']:,} paths = "
      f"{p2_5['n_seeds']*p2_5['n_paths_per_seed']/1e9:.1f}B paths/strat")
print(f"500-seed: {p2_500['n_seeds']} seeds x {p2_500['n_paths_per_seed']:,} paths = "
      f"{p2_500['n_seeds']*p2_500['n_paths_per_seed']/1e9:.1f}B paths/strat")

idx_5 = {tuple(sorted(r['positions'].items())): r for r in p2_5['ranking']}
idx_500 = {tuple(sorted(r['positions'].items())): r for r in p2_500['ranking']}

print("\n=== TOP 15 BY 500-SEED MEAN (with both estimates) ===")
print(f"{'#':>3} {'Strategy':<48} {'5s mean':>13} {'500s mean':>13} {'500s SE':>9} "
      f"{'500s Sharpe':>12} {'500s CVaR-5%':>14} {'500s CVaR5 SE':>13}")
for r in p2_500['ranking'][:15]:
    key = tuple(sorted(r['positions'].items()))
    r5 = idx_5.get(key)
    m5 = r5['mean'] if r5 else 0
    print(f"{r['rank']:>3} {r['name'][:46]:<48} ${m5:>+12,.0f} ${r['mean']:>+12,.0f} "
          f"${r['mean_se']:>8,.0f} {r['sharpe']:>12.4f} ${r['cvar5']:>+13,.0f} ${r['cvar5_se']:>12,.0f}")

print("\n=== KEY CANDIDATES ===")
KEY = [
    ("DROP_60C (base)", {"AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DOM_NICE_v3 (+15 AC_50_C)", {"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+25 AC_45_P", {"AC_45_P": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+25 AC_50_C", {"AC_50_C": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+50 AC_45_P+25 AC_50_C", {"AC_50_C": 25, "AC_45_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DOM_NICE_v2 (+50 AC_35_P)", {"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
]

print(f"{'Candidate':<35} {'5s mean':>13} {'500s mean':>13} {'SE shrink':>11} "
      f"{'500s Sharpe':>12} {'500s CVaR-5%':>14}")
for label, pos in KEY:
    key = tuple(sorted(pos.items()))
    r5 = idx_5.get(key)
    r500 = idx_500.get(key)
    if r500:
        se_ratio = r5['mean_se'] / r500['mean_se'] if r5 else 0
        print(f"{label[:34]:<35} ${r5['mean'] if r5 else 0:>+12,.0f} ${r500['mean']:>+12,.0f} "
              f"{se_ratio:>10.1f}x ${r5['mean_se'] if r5 else 0:>5,.0f}->${r500['mean_se']:>3,.0f}  "
              f"{r500['sharpe']:>5.4f}    ${r500['cvar5']:>+13,.0f}")

# Rebuild Pareto frontier with 500-seed precision
all_strats = p2_500['ranking']
pareto_idx = []
for i, r in enumerate(all_strats):
    dominated = False
    for j, q in enumerate(all_strats):
        if i == j: continue
        if (q['mean'] >= r['mean'] and q['sharpe'] >= r['sharpe'] and q['cvar5'] >= r['cvar5'] and
            (q['mean'] > r['mean'] or q['sharpe'] > r['sharpe'] or q['cvar5'] > r['cvar5'])):
            dominated = True
            break
    if not dominated:
        pareto_idx.append(i)

print(f"\n=== 500-SEED PARETO FRONTIER ({len(pareto_idx)} candidates) ===")
pareto = [all_strats[i] for i in pareto_idx]
pareto.sort(key=lambda x: -x['mean'])
for r in pareto:
    pos_str = ', '.join(f'{k}={v}' for k, v in r['positions'].items())
    print(f"  mean=${r['mean']:>+10,.0f} +/- ${r['mean_se']:>4,.0f}  "
          f"sharpe={r['sharpe']:.4f}  cvar5=${r['cvar5']:>+11,.0f} +/- ${r['cvar5_se']:>5,.0f}")
    print(f"  {pos_str}")

# Verify DOM_NICE_v3 vs DOM_NICE_v2 with tightened SE
v3_key = tuple(sorted({"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}.items()))
v2_key = tuple(sorted({"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}.items()))
v3 = idx_500.get(v3_key)
v2 = idx_500.get(v2_key)

if v3 and v2:
    dmean = v3['mean'] - v2['mean']
    dmean_se = np.sqrt(v3['mean_se']**2 + v2['mean_se']**2)
    z_mean = dmean / dmean_se
    dcvar = v3['cvar5'] - v2['cvar5']
    dcvar_se = np.sqrt(v3['cvar5_se']**2 + v2['cvar5_se']**2)
    z_cvar = dcvar / dcvar_se
    print(f"\n=== DOM_NICE_v3 vs DOM_NICE_v2 PAIRED COMPARISON (500 seeds) ===")
    print(f"  Mean delta: ${dmean:+,.0f} +/- ${dmean_se:.0f}  (z={z_mean:+.2f})")
    print(f"  Sharpe delta: {v3['sharpe'] - v2['sharpe']:+.4f}")
    print(f"  CVaR-5% delta: ${dcvar:+,.0f} +/- ${dcvar_se:,.0f}  (z={z_cvar:+.2f})")
    if z_mean > 2 and z_cvar > 2:
        print(f"  *** v3 strictly dominates v2 at >2-sigma confidence on both mean and CVaR ***")
