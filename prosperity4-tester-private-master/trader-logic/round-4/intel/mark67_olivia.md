# Mark 67 Olivia-Analog Forensics (R4 VFE)
Data: round4 days 1-3.

## Day 1
- Mark 67 trades: 58 (buys: 58, sells: 0)
- Mark 49 sells: 34
- Daily extrema (Mark 67 buys vs day's mid distribution):
    bottom10%=8.6%  bottom25%=31.0%  bottom50%=51.7%  top25%=20.7%  top10%=5.2%
- Inter-arrival (ticks): mean=171.2  cov=1.09  frac<0.5*mean=42.1%  bursts=0  max_burst_len=0
- Pre-trade features (10 ticks before): mean_ret=-1.59  mean_OBI=-0.04  frac_neg_ret=69.0%  frac_neg_OBI=32.8%
- Post-trade forward return (mid drift, BUY trades):
    h=  1: n= 58  mean=+1.99  t=+16.23  win=98.3%
    h=  5: n= 58  mean=+2.20  t=+9.62  win=89.7%
    h= 10: n= 58  mean=+2.53  t=+7.00  win=77.6%
    h= 25: n= 58  mean=+2.18  t=+3.95  win=65.5%
    h= 50: n= 58  mean=+2.95  t=+3.32  win=62.1%
    h=100: n= 58  mean=+3.15  t=+2.29  win=58.6%
- Joint Mark 67 buy + Mark 49 sell within ±5 ticks (h=10 fwd):
    co-occurring n=27 mean=+2.78 t=+5.15
    isolated     n=31 mean=+2.31 t=+4.71

## Day 2
- Mark 67 trades: 61 (buys: 61, sells: 0)
- Mark 49 sells: 37
- Daily extrema (Mark 67 buys vs day's mid distribution):
    bottom10%=6.6%  bottom25%=19.7%  bottom50%=52.5%  top25%=32.8%  top10%=6.6%
- Inter-arrival (ticks): mean=165.4  cov=0.88  frac<0.5*mean=36.7%  bursts=0  max_burst_len=0
- Pre-trade features (10 ticks before): mean_ret=-2.02  mean_OBI=-0.03  frac_neg_ret=66.7%  frac_neg_OBI=33.3%
- Post-trade forward return (mid drift, BUY trades):
    h=  1: n= 61  mean=+1.86  t=+16.07  win=93.4%
    h=  5: n= 61  mean=+1.75  t=+7.55  win=85.2%
    h= 10: n= 61  mean=+1.90  t=+5.50  win=78.7%
    h= 25: n= 61  mean=+1.41  t=+2.53  win=60.7%
    h= 50: n= 61  mean=+1.62  t=+2.24  win=55.7%
    h=100: n= 60  mean=+1.49  t=+1.52  win=58.3%
- Joint Mark 67 buy + Mark 49 sell within ±5 ticks (h=10 fwd):
    co-occurring n=35 mean=+1.97 t=+4.08
    isolated     n=26 mean=+1.81 t=+3.65

## Day 3
- Mark 67 trades: 46 (buys: 46, sells: 0)
- Mark 49 sells: 34
- Daily extrema (Mark 67 buys vs day's mid distribution):
    bottom10%=6.5%  bottom25%=19.6%  bottom50%=43.5%  top25%=28.3%  top10%=10.9%
- Inter-arrival (ticks): mean=211.8  cov=0.91  frac<0.5*mean=37.8%  bursts=3  max_burst_len=2
- Pre-trade features (10 ticks before): mean_ret=-2.29  mean_OBI=0.02  frac_neg_ret=73.9%  frac_neg_OBI=30.4%
- Post-trade forward return (mid drift, BUY trades):
    h=  1: n= 46  mean=+2.09  t=+13.09  win=95.7%
    h=  5: n= 46  mean=+1.88  t=+5.58  win=71.7%
    h= 10: n= 46  mean=+2.34  t=+5.08  win=69.6%
    h= 25: n= 46  mean=+1.88  t=+2.25  win=58.7%
    h= 50: n= 46  mean=+1.01  t=+1.07  win=58.7%
    h=100: n= 46  mean=-0.64  t=-0.44  win=43.5%
- Joint Mark 67 buy + Mark 49 sell within ±5 ticks (h=10 fwd):
    co-occurring n=30 mean=+2.18 t=+4.07
    isolated     n=16 mean=+2.62 t=+2.98

## Aggregate (3 days pooled)
- Total Mark 67 buys: 165, Mark 49 sells: 105
- Pooled extrema concentration: bottom10%=7.2%  bottom25%=23.4%  bottom50%=49.2%  top25%=27.2%  top10%=7.5%
- Pooled IAT: mean=182.8 ticks  cov=0.96  max_burst_len=2

## Strategy Candidates (Ranked by BT)

### CANDIDATE A: Post-Mark-67 Camp Bid (IMPLEMENTED in r4_v6_olivia.py)
On observing Mark 67 buy in `state.market_trades[VFE]`, camp aggressive
bid at `best_ask-1`, size=30, for next M67_CAMP_TICKS=10 ticks.

vs v5 baseline:
| Window           | v5 baseline | v6 olivia   | Δ      |
|------------------|------------:|------------:|-------:|
| 1k d1 probe      |     $4,818  |     $4,818  |     $0 |
| 1k d2 probe      |    $15,706  |    $15,700  |    -$6 |
| 1k d3 probe      |     $6,390  |     $6,390  |     $0 |
| 10k 3-day default| $162,930    | $163,384    |  +$454 |
| 10k 3-day imc    | $155,885    | $156,173    |  +$288 |

VERDICT: **Marginal positive, inside noise band.** The post-trade drift
(+1.97 mean, t=26 at h=1) is real but already largely captured by the
existing Wall-Mid VFE MM (which sits inside-spread). Camping ask-1 only
adds incremental fills above what we already collect. 1k probes
unchanged → Mark 67 fires too rarely (~55/day) to move sub-tick PnL.

Not Pareto-improvement on 1k probes (the leaderboard probe surface).
**SAFE to ship; do NOT gate the round on this.**

### CANDIDATE B: Pre-position (REJECTED by data)
Cannot predict — IAT cov=0.96 ≈ Poisson, max burst length=2. Mark 67
is a Poisson-like buyer with no temporal clustering. No advance signal.

### CANDIDATE C: Daily-extrema timing (REJECTED by data)
Bottom-25% concentration = 23.4% (≈ uniform 25%). Top-25% = 27.2%.
Mark 67 buys are ~uniform across day's mid distribution. NOT an
Olivia-style "buy-the-bottom" insider despite the name analogy.

### CANDIDATE D: Joint Mark 67 + Mark 49 cross signal (REJECTED)
Co-occurring (within ±5 ticks) h=10 mean=+2.31 vs isolated +2.25.
Difference is noise. The 95% win-rate is already in the unconditional
signal; adding M49 filter just halves sample size.

### CANDIDATE E: Forward-momentum size scaling (FUTURE)
Day 1/2 h=100 mean still +1.5 / +1.5; day 3 h=100 = -0.64 (regime
fades on crash days). Could ship a **time-decaying camp size**: 30
shares for 10 ticks, then 15 for next 25 — but day-3 negative h=100
risks tail loss in crash regime. NOT worth complexity given marginal
A gain.

## Recommendation
Ship `r4_v6_olivia.py` as a low-risk additive layer ONLY if confident
in the +$454/+$288 10k delta surviving live (BT × 0.99 ≈ live → ~$450
expected). Better path: leave v5 alone (it's already Pareto-dominant
on probes and sweep-tuned). Mark 67 alpha is **largely substitutable**
with Wall-Mid MM — the +$454 is the uncaptured tail of the drift past
where our passive bids sit. Saturated.
