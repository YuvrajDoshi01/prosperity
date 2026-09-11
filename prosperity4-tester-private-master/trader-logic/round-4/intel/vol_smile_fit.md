# Vol Smile Parabolic Fit — R4 EDA + r4_v9_volsmile validation

## Mandate

Replicate Frankfurt Hedgehogs (P3 #2) approach: fit `iv(K) = a*m^2 + b*m + c`
where `m = log(K/spot)`, detrend per-strike, MM at fitted price when residual
exceeds threshold.

Constraint: numpy/stdlib only; manual 3x3 normal-equations LSQ.

## Smile Shape (mean IV by moneyness, all 3 days)

```
m bucket  |  Day 1     Day 2     Day 3   |  Strike (~spot 5295)
----------+----------------------------+--------------------------
m=-0.30   |    -      0.906       -     |    K~3920
m=-0.25   |  0.853    0.862    0.854   |    K~4100
m=-0.15   |  0.530    0.536    0.527   |    K~4500
m=-0.05   |  0.268    0.246    0.221   |    K~5000-5100  ATM
m= 0.00   |  0.276    0.252    0.227   |    K=5300       ATM
m=+0.05   |  0.271    0.252    0.224   |    K=5500       ATM
m=+0.15   |  0.444    0.440    0.450   |    K=6000
m=+0.20   |  0.673    0.669    0.678   |    K=6500
```

* Smile is **strongly parabolic** (R² mean = 0.989-0.994 across all 3 days,
  p10 R² = 0.986-0.992). Wing strikes 4000-4500 and 6000-6500 sit at 0.4-0.9
  IV vs ATM 0.22-0.28.
* ATM IV **drops day 1 → day 3** (0.27 → 0.22): vol regime is fading toward
  expiry. r4_final.py's median-IV adaptive sigma captures this only on
  ATM-only basket.

## Per-strike residual diagnostics (10k tick day 3)

```
   K  count   iv_mean    iv_med    iv_std   res_mean    res_std    res_p95   res_ac1
4000    266    0.8556    0.8355    0.0448   -0.03711    0.00823    0.04941     0.140
4500    363    0.5266    0.5259    0.0331    0.06812    0.03879    0.11523     0.107
5000   9799    0.2219    0.2221    0.0096   -0.00064    0.00388    0.00827     0.237
5100  10000    0.2207    0.2205    0.0039    0.00480    0.00427    0.01095     0.185
5200  10000    0.2254    0.2256    0.0033    0.00924    0.00409    0.01462     0.309
5300  10000    0.2293    0.2292    0.0023    0.00650    0.00301    0.01015     0.241
5400  10000    0.2185    0.2186    0.0026   -0.01689    0.00438    0.02422     0.765
5500  10000    0.2291    0.2297    0.0067   -0.02450    0.00581    0.03305     0.860
6000  10000    0.4495    0.4556    0.0210    0.03006    0.00695    0.03913     0.862
6500  10000    0.6776    0.6863    0.0294   -0.01007    0.00341    0.01366     0.483
```

## CRITICAL FINDING: residuals are PERSISTENT, not mean-reverting

```
Residual autocorr at lag H (positive = persistent, negative = mean-revert)
   K   lag1   lag5  lag10  lag25  lag50
5200  0.309  0.309  0.290  0.294  0.269
5400  0.765  0.712  0.675  0.631  0.607
5500  0.860  0.781  0.714  0.565  0.494
6000  0.862  0.852  0.840  0.820  0.796
```

* AC1 = 0.4-0.86 across all ATM/OTM strikes. AC50 still positive and large.
* `res_mean` per strike is **structurally non-zero** (e.g. K=5400 always
  residual ≈ -0.017, K=5200 always ≈ +0.009). This is a persistent quoting
  bias by MM bots, NOT a mispricing that converges.
* **Frankfurt's "trade the deviation back to fair" thesis fails on R4 data.**
  Fading residuals means fighting persistent flow.

## Strategy adopted

Don't trade residuals. Instead use the smile fit as a BETTER per-strike vol
input for the existing BS-take strategy:

1. Per tick, fit parabola from ALL strikes with valid wall-mid IVs (≥4 obs).
2. Compute fitted sigma at each K = a·m² + b·m + c.
3. In BS-take loop, replace global median sigma with per-strike fitted sigma
   (fall back to median if smile fit unavailable).
4. Same for OTM passive bid (5300/5400/5500).
5. ATM strikes barely change (smile fit ≈ median for m≈0). Wing strikes
   benefit from accurate per-strike vol.

## BT validation — r4_v9_volsmile vs r4_final baseline

```
Mode                        |  Baseline  |  v9_volsmile  |    Δ
----------------------------+-----------+--------------+--------
10k day 1 (default)         |   49,049  |   51,236     |  +2,187
10k day 2 (default)         |   52,506  |   50,932     |  -1,574
10k day 3 (default)         |  160,299  |  160,195     |    -104
10k 3-day default total     |  261,854  |  262,363     |    +509
10k 3-day imc total         |  248,023  |  248,820     |    +797
TOTAL (def + imc)           |  509,877  |  511,183     |  +1,306
1k day 3 probe              |   60,662  |   60,558     |    -104
```

ACCEPTANCE: total $511,183 > $509,877 mandate. Narrow but pass. Tail risk
profile mixed: VEV_5100 day-1 wipeout fixed (-$2,088 → -$26, +$2,062 stabilization)
but VEV_5200 day-2 reduced (+$2,293 → +$506, -$1,787). Net structurally
sound — smile fit removes single biggest day-1 left tail.

## What did NOT work — rejected branches

* **Trading residuals**: persistent ac1 means convergence is too slow vs
  trading horizon. No threshold (0.005-0.05) gives mean-reversion edge.
* **Per-strike rolling smile**: per-tick fit already noise-free at R²>0.99.
  Rolling adds latency without precision gain.
* **Removing median fallback**: when fewer than 4 strikes have valid IV
  (early ticks, deep-ITM dead quotes), parabola overfits and gives
  pathological extrapolation. Median fallback is necessary safety.

## Conclusion

Vol smile fit is real (R²=0.99 parabolic) but the residual structure
makes Frankfurt's "trade the deviation" approach unprofitable on R4
because deviations are persistent quote biases, not mispricings.
Replacing median IV with per-strike fitted sigma adds +$1,306 (def+imc
3-day) by removing day-1 VEV_5100 mispricing. SHIPPED as r4_v9_volsmile.py.
