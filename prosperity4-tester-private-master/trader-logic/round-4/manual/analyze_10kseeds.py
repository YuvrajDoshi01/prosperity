"""Compare 5-seed, 500-seed, 10K-seed runs. Build final tightened Pareto frontier."""
import json
import numpy as np

p2_5 = json.load(open("results/phase2_results.json"))
p2_500 = json.load(open("results/phase2_500seeds_results.json"))
p2_10k = json.load(open("results/phase2_10kseeds_results.json"))

print("=" * 110)
print("PHASE 2 SEED PROGRESSION: 5 -> 500 -> 10000")
print("=" * 110)

idx_5 = {tuple(sorted(r['positions'].items())): r for r in p2_5['ranking']}
idx_500 = {tuple(sorted(r['positions'].items())): r for r in p2_500['ranking']}
idx_10k = {tuple(sorted(r['positions'].items())): r for r in p2_10k['ranking']}

KEY = [
    ("DROP_60C (base)", {"AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+25 AC_45_P", {"AC_45_P": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DOM_NICE_v3 (+15 AC_50_C)", {"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+25 AC_50_C", {"AC_50_C": 25, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DROP+50 AC_45_P+25 AC_50_C", {"AC_50_C": 25, "AC_45_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
    ("DOM_NICE_v2 (+50 AC_35_P)", {"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}),
]

print(f"{'Strategy':<35} {'5s mean':>12}±SE {'500s mean':>12}±SE {'10K mean':>12}±SE")
print(f"{' ':<35} {' ':>13} {' ':>13} {' ':>13}")
for label, pos in KEY:
    key = tuple(sorted(pos.items()))
    r5 = idx_5.get(key); r500 = idx_500.get(key); r10k = idx_10k.get(key)
    print(f"{label[:34]:<35} ${r5['mean']:>+10,.0f}±${r5['mean_se']:>3,.0f} "
          f"${r500['mean']:>+10,.0f}±${r500['mean_se']:>3,.0f} "
          f"${r10k['mean']:>+10,.0f}±${r10k['mean_se']:>3,.0f}")

print(f"\n=== CVaR-5% PROGRESSION ===")
print(f"{'Strategy':<35} {'5s CVaR-5%':>14}±SE {'500s CVaR-5%':>14}±SE {'10K CVaR-5%':>14}±SE")
for label, pos in KEY:
    key = tuple(sorted(pos.items()))
    r5 = idx_5.get(key); r500 = idx_500.get(key); r10k = idx_10k.get(key)
    print(f"{label[:34]:<35} ${r5['cvar5']:>+12,.0f}±${r5['cvar5_se']:>4,.0f} "
          f"${r500['cvar5']:>+12,.0f}±${r500['cvar5_se']:>4,.0f} "
          f"${r10k['cvar5']:>+12,.0f}±${r10k['cvar5_se']:>4,.0f}")

# Rebuild Pareto frontier with 10K-seed precision
all_strats = p2_10k['ranking']
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

print(f"\n=== 10K-SEED PARETO FRONTIER ({len(pareto_idx)} candidates) ===")
pareto = [all_strats[i] for i in pareto_idx]
pareto.sort(key=lambda x: -x['mean'])
for r in pareto:
    pos_str = ', '.join(f'{k}={v}' for k, v in r['positions'].items())
    print(f"  mean=${r['mean']:>+10,.0f}±${r['mean_se']:>3,.0f}  "
          f"sharpe={r['sharpe']:.4f}  cvar5=${r['cvar5']:>+11,.0f}±${r['cvar5_se']:>5,.0f}")
    print(f"  {pos_str}")

# Paired test: DOM_NICE_v3 vs DOM_NICE_v2 with 10K-seed precision
v3_key = tuple(sorted({"AC_50_C": 15, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}.items()))
v2_key = tuple(sorted({"AC_35_P": 50, "AC_50_P_2": 50, "AC_50_C_2": 50, "AC_50_CO": -50, "AC_40_BP": -50, "AC_45_KO": 500}.items()))
v3 = idx_10k.get(v3_key); v2 = idx_10k.get(v2_key)
if v3 and v2:
    dmean = v3['mean'] - v2['mean']
    dmean_se = np.sqrt(v3['mean_se']**2 + v2['mean_se']**2)
    z_mean = dmean / dmean_se
    dcvar = v3['cvar5'] - v2['cvar5']
    dcvar_se = np.sqrt(v3['cvar5_se']**2 + v2['cvar5_se']**2)
    z_cvar = dcvar / dcvar_se
    print(f"\n=== DOM_NICE_v3 vs DOM_NICE_v2 PAIRED COMPARISON (10K seeds) ===")
    print(f"  Mean delta: ${dmean:+,.0f} +/- ${dmean_se:.0f}  (z={z_mean:+.2f})")
    print(f"  Sharpe delta: {v3['sharpe'] - v2['sharpe']:+.4f}")
    print(f"  CVaR-5% delta: ${dcvar:+,.0f} +/- ${dcvar_se:,.0f}  (z={z_cvar:+.2f})")

# Verdict: did the 10K-seed run REORDER or REVISE any top-10 ranking?
print(f"\n=== TOP 10 RANKING STABILITY: 5-seed vs 10K-seed ===")
top10_5 = sorted(p2_5['ranking'], key=lambda x: -x['mean'])[:10]
top10_10k = sorted(p2_10k['ranking'], key=lambda x: -x['mean'])[:10]
for r5, r10k in zip(top10_5, top10_10k):
    same = tuple(sorted(r5['positions'].items())) == tuple(sorted(r10k['positions'].items()))
    marker = "  " if same else "**"
    print(f"  {marker} {r5['name'][:42]:<42} | {r10k['name'][:42]:<42}")
