"""Direct paired comparison MINE vs USER's strategy on same MC paths.

Confirms whether user's reported Sharpe 1.04 is the SCORE-Sharpe (mean / SE_score).
Computes P(MINE score > USER score) on a single 100-sim trial.
"""
import sys
sys.path.insert(0, 'trader-logic/round-4/manual')
from extended_compare import gen_paths, strategy_pnl, stats, FV, QUOTES
from statistics import NormalDist

paths = gen_paths(500_000, seed=42)
ND = NormalDist()

USER = [
    ('AC_50_CO', 'sell', 15),
    ('AC_40_BP', 'sell', 50),
    ('AC_45_KO', 'buy',  60),
    ('AC_50_P',  'buy',  17),
    ('AC_50_P_2','buy',  15),
    ('AC_50_C',  'buy',  15),
]

MINE = [
    ('AC_50_CO','sell',50), ('AC_45_KO','buy',500), ('AC_40_BP','sell',50),
    ('AC_50_P_2','buy',50), ('AC_50_C_2','buy',50),
    ('AC_50_P','buy',50), ('AC_50_C','buy',25),
    ('AC','buy',5),
]

HYBRID_OPT = [
    ('AC_50_CO','sell',50), ('AC_40_BP','sell',50),
    ('AC_50_P_2','buy',50), ('AC_50_C_2','buy',50),
    ('AC_50_P','buy',50), ('AC_50_C','buy',25),
]

print("=" * 120)
print("KO size sweep (with same hedges as MINE) — find optimum")
print("=" * 120)
print(f"{'KO':>4} {'Mean':>8} {'SD':>8} {'PathSharpe':>10} {'ScoreSharpe':>11} {'P>0':>6} {'CVaR5':>9} {'P_better_USER':>14}")
user_pnls = strategy_pnl(USER, paths)
for ko in [0, 30, 60, 100, 150, 200, 300, 500]:
    strat = list(HYBRID_OPT)
    if ko > 0:
        strat.append(('AC_45_KO','buy',ko))
    pnls = strategy_pnl(strat, paths)
    s = stats(pnls)
    diff = [a - b for a, b in zip(pnls, user_pnls)]
    diff_mean = sum(diff) / len(diff)
    diff_sd = (sum((d - diff_mean)**2 for d in diff) / (len(diff)-1))**0.5
    z = diff_mean / (diff_sd / 10) if diff_sd > 0 else 0
    p_better = ND.cdf(z) * 100
    print(f"{ko:>4} {s['mean']:+8.2f} {s['sd']:>8.1f} {s['sharpe']:>10.4f} {s['sharpe']*10:>11.4f} {s['p_pos']:>5.1f}% {s['cvar5']:>+9.1f} {p_better:>13.1f}%")

print()
print("=" * 120)
print("Direct paired comparison MINE vs USER (same paths)")
print("=" * 120)
mine_pnls = strategy_pnl(MINE, paths)
user_pnls = strategy_pnl(USER, paths)
diff = [a - b for a, b in zip(mine_pnls, user_pnls)]
diff_mean = sum(diff) / len(diff)
diff_sd = (sum((d - diff_mean)**2 for d in diff) / (len(diff)-1))**0.5

mine_s = stats(mine_pnls)
user_s = stats(user_pnls)

print(f"  MINE:   mean={mine_s['mean']:+.2f}, SD={mine_s['sd']:.1f}, path-Sharpe={mine_s['sharpe']:.4f}, score-Sharpe={mine_s['sharpe']*10:.3f}")
print(f"  USER:   mean={user_s['mean']:+.2f}, SD={user_s['sd']:.1f}, path-Sharpe={user_s['sharpe']:.4f}, score-Sharpe={user_s['sharpe']*10:.3f}")
print(f"  Diff:   mean={diff_mean:+.2f}, SD={diff_sd:.1f}, path-Sharpe={diff_mean/diff_sd:.4f}")
print(f"  100-sim score diff: SE={diff_sd/10:.2f}")
z = diff_mean / (diff_sd / 10) if diff_sd > 0 else 0
p = ND.cdf(z) * 100
print(f"  P(MINE 100-sim score > USER 100-sim score) = {p:.1f}%")

print()
print("=" * 120)
print("Expected score with x3000 multiplier")
print("=" * 120)
print(f"  MINE expected score:    {mine_s['mean']*3000:>+15,.0f}")
print(f"  USER expected score:    {user_s['mean']*3000:>+15,.0f}")
print(f"  Mine - User in expectation: {(mine_s['mean']-user_s['mean'])*3000:>+10,.0f}")
print()
print(f"  100-sim score 95% CI (theoretical, IID 100 sims):")
mine_lo = (mine_s['mean'] - 1.96 * mine_s['sd']/10) * 3000
mine_hi = (mine_s['mean'] + 1.96 * mine_s['sd']/10) * 3000
user_lo = (user_s['mean'] - 1.96 * user_s['sd']/10) * 3000
user_hi = (user_s['mean'] + 1.96 * user_s['sd']/10) * 3000
print(f"    MINE: [{mine_lo:>+11,.0f}, {mine_hi:>+11,.0f}]")
print(f"    USER: [{user_lo:>+11,.0f}, {user_hi:>+11,.0f}]")
print(f"  P(MINE positive)={ND.cdf(mine_s['mean'] * 10 / mine_s['sd'])*100:.1f}%")
print(f"  P(USER positive)={ND.cdf(user_s['mean'] * 10 / user_s['sd'])*100:.1f}%")

print()
print("=" * 120)
print("FINAL VERDICT")
print("=" * 120)
print(f"In EXPECTATION (which is the scoring rule), MINE beats USER by ${(mine_s['mean']-user_s['mean'])*3000:>,.0f}")
print(f"On a SINGLE 100-sim trial, P(MINE > USER) = {p:.1f}%")
print(f"USER's strategy has tighter CI (lower variance) but lower mean.")
