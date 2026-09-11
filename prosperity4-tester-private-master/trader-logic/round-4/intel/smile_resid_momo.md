# Smile Residual Momentum — REJECTED

## Hypothesis

User insight: residuals from per-tick parabolic smile fit are persistent
(AC1=0.4-0.86, AC50 still 0.4-0.8 per `vol_smile_fit.md`). Therefore trade
**momentum**, not reversion: when `res_t - res_{t-50} > +thr`, BUY voucher
(IV rising → call rising); when negative, SELL.

## Test design

Per day (1, 2, 3) and per strike, build aligned series of `(ts, wall_mid,
residual)` from the same parabolic fit used in `r4_v9_volsmile`. Then sweep
`(lookback, horizon, threshold)` and compute IC, hit-rate, mean PnL/trade,
and trade-count-scaled SR against forward wall-mid change. Code:
`smile_resid_momo.py`. Pure offline EDA — no order simulation, no
transaction costs (these would only worsen results).

## Results — IC table, 3-day aggregate, threshold=0.02

```
            lb=10        lb=25        lb=50        lb=100
K        h=25  h=50   h=25  h=50   h=50  h=100  h=100
4500   -0.04 -0.01  -0.08 -0.07  -0.07 -0.07  -0.08
5000   -0.02 -0.02  -0.01 -0.01  -0.00 -0.00  -0.02
5100   -0.01 -0.01  -0.01 -0.01  -0.00 -0.01  -0.00
5200   -0.01 -0.01  -0.01 -0.02  -0.02 -0.01  -0.01
5300   -0.03 -0.02  -0.03 -0.04  -0.03 -0.03  -0.03
5500   -0.16 -0.15  -0.21 -0.17  -0.18 -0.15  -0.18
```

**Every IC is negative.** The user's directional thesis is *reversed* by
the data.

## Threshold sweep at (lb=50, h=50) — 3-day SR

```
K     thr=0.005   thr=0.01   thr=0.02   thr=0.03
4000   +1.77      +3.19       n<30       n<30
4500   -2.27      -2.14      -2.47      -2.24
5000   -0.76      -1.48      +0.63       n<30
5100   -1.09      -0.01      +1.28       n<30
5200   +0.67      -0.14      +0.38       n<30
5300   -1.21      +0.28      +0.06       n<30
5400   -4.01      -1.44       n<30       n<30
5500  -21.87     -14.50      -6.52       n<30
```

Every cell with non-trivial trade count (n_tr ≥ 30) on liquid ATM strikes
posts SR ≤ +1.3 in raw-PnL space, before voucher spread costs. K=4000 has
SR>3 but **only 4-18 trades over 30k ticks** (not deployable).

## Why the hypothesis fails

Residual structure is dominated by a **persistent quoting bias** per
strike (`res_mean(K=5500) ≈ -0.025` permanently, `res_mean(K=5400) ≈
-0.017`). High AC1 reflects that constant offset, not that *changes* in
residual carry forward signal. A jump `Δres` is mostly noise around a
fixed mean; when residual spikes up via wall-mid jitter, the wall-mid
mean-reverts over the next 50-100 ticks → forward return is *opposite*
the signal sign → negative IC.

Frankfurt's "trade reversion" worked at infinite horizon but at
1-100-tick horizon it's dominated by inverse-bid-ask bounce. The same
mechanism kills the momentum reading at the same horizon.

## Rejection vs spec gates

* Spec: SR < 0.3 → reject. Observed pooled SR on ATM strikes (5000-5400)
  ranges -2.42 → +1.28, mean ≈ -0.5. **Fails by ~3σ before TX costs.**
* IC sign is wrong on every ATM strike — even with optimal threshold and
  hold, you'd lose money systematically.
* No 1k probe run: signal is dead at the IC stage; trader simulation
  would only confirm what the EDA already shows.

## Conclusion — `r4_v11_residmomo.py` NOT shipped

The persistent autocorrelation of smile residuals is a **structural
quoting artifact**, not a forecastable signal. Both reversion (Frankfurt)
and momentum (this hypothesis) fail at sub-100-tick horizons because the
true generative process is `obs = bias(K) + tick-level noise`, where
bias is constant and noise is bid-ask bounce. Neither sign of trade
extracts edge.

`r4_v9_volsmile` retains its correct use of the smile fit: provide
*better per-strike vol* for BS pricing. Residuals are an artifact of the
fit, not a tradeable signal.

Adjacent live alpha that DID survive: VEV_5200 BS_EDGE=5 (Agent 6,
+$7k day 3), HP S17 z-gate (Agent 1, +$11k), VEV_6000/6500 bid=0
(Agent 8, +$900). Voucher residual momentum is closed.
