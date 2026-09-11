# R4 Microstructure Alpha — Findings

Data: `prosperity4bt/resources/round4/{prices,trades}_round_4_day_{1,2,3}.csv`
Script: `trader-logic/round-4/intel/microstructure_alpha.py`
Forward horizon: 100 ticks (= 10s) unless noted. N ≈ 29,700/product/days.

## 1. OBI L1 → fwd-mid-return correlation (3 days pooled)

| product | corr(OBI, fwd100) | mean ret OBI>0.5 | mean ret OBI<-0.5 |
|---|---:|---:|---:|
| **VEV_5500** | **+0.103** | +0.32 | -0.60 |
| **VEV_4000** | **+0.077** | +4.71 | -4.80 |
| VEV_5400 | +0.061 | +0.26 | -0.36 |
| VEV_4500 | +0.056 | +3.43 | -4.43 |
| HYDROGEL_PACK | +0.038 | +2.47 | -5.82 |
| VFE | +0.038 | +0.55 | -0.40 |

VEV_6000/6500 books too thin, no signal. VEV_4000 OBI>0.7 N=39 mean fwd25=+5.6 ; OBI<-0.7 N=30 fwd25=-4.6. **Caveat**: |OBI|>0.5 fires only when VEV_4000 spread compresses 21→10 (regime conditional, not freely actionable).

## 2. L3 microprice vs simple mid

| product | corr(micro_dev, fwd25) | h=10 IC |
|---|---:|---:|
| VFE | **+0.084 / +0.139** | strongest tradable |
| HP | +0.080 / +0.115 | strong |
| VEV_4000 | (L1 dominates) | — |

VFE micro_dev quintiles → fwd25: q0=-0.38, q1=-0.11, q2/3=+0.29/+0.48 (monotonic, 30k obs). HP same shape, larger magnitude (9pt σ).

## 3. VPIN (Lee-Ready proxy, 50 buckets)

| symbol | trades | VPIN_mean | p90 |
|---|---:|---:|---:|
| HP | 1022 | 0.13 | 0.25 |
| VFE | 1381 | 0.13 | 0.25 |
| VEV_5400 | 276 | 0.21 | 0.49 |
| VEV_4000 | 442 | 0.21 | 0.42 |

HP/VFE VPIN low (balanced flow → safe to MM). Voucher VPIN doubles → widen voucher edges in high-VPIN windows.

## 4. HP spread state-machine

States {7,8,9,15,16,17}. P(s=16 | any) ≈ 0.92; absorbing. Spread=17 (N=494) → **mean fwd100 = -6.52** (validates v11 GIGA SHORT trigger). Spread=15 (N=767) → +0.02 (no edge). Transition `17→17 = 5.1%`, `17→15 = 0%` confirms 17 is a stress spike, not gradient.

## 5. RECOMMENDATION — single signal to add to `r4_final_v2`

**HP/VFE microprice-dev fair-value tilt** (NOT a take signal, an MM bias):

```python
# inside HP / VFE quote logic
def micro_l2(od):
    bv1=od.buy_orders.get(best_bid,0); bv2=sum(v for p,v in od.buy_orders.items() if p<best_bid)
    av1=-od.sell_orders.get(best_ask,0); av2=-sum(v for p,v in od.sell_orders.items() if p>best_ask)
    bvt=bv1+bv2; avt=av1+av2
    if bvt==0 or avt==0: return (best_bid+best_ask)/2
    bp=(best_bid*bv1+(best_bid-1)*bv2)/bvt; ap=(best_ask*av1+(best_ask+1)*av2)/avt
    return (bp*avt+ap*bvt)/(bvt+avt)
fv += round(0.4 * (micro_l2(od) - mid))   # tilt FV toward microprice
```

**Why this one**: (a) IC=+0.14 on VFE / +0.12 on HP at h=10 is the largest tradable signal (29k obs/day, monotonic across 5 quintiles); (b) it's a tilt on existing Wall-Mid MM, not a new take — no per-trade cost cliff like VEV_4000 OBI; (c) survives all 3 days; (d) orthogonal to spread=17 GIGA SHORT (different timescale). Falsification: BT v2 — if `imc` mode HP+VFE PnL drops vs r4_final_v2 baseline on day-2 1k AND 10k 3-day, kill it. Sizing: 0.4 coefficient = half-Kelly given t-stat ≈ 8 over 30k obs.

**Not recommended**: VEV_4000 OBI alone (regime-gated, N=69 events, post-cost net only +$483 over 3 days). HP spread=17 already in r3_v11; no marginal alpha.

Files:
- C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/microstructure_alpha.py
- C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/microstructure_alpha.md
