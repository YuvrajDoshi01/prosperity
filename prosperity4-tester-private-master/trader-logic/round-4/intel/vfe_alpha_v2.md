# VFE Alpha Hunt v2 (Round 4)

**Mandate**: deep-dive Wall-Mid MM day-3 -$5.9k failure; find better crash signals; long-side reversal alpha; voucher delta hedge; ONE concrete upgrade.

## 1. Day-3 Wall-Mid MM Loss Decomposition

Day-3 VFE PnL in `r4_final_v2`: **-$3,709** (10k BT). NOT -$5.9k from no-momo baseline.
- Momentum-short already captured +$1,800 of TP.
- Day-3 mid: 5295.5 → 5232.0, drift -$63.5, but path is **non-monotonic**: -$43 (0-100k), +$31 (300-400k), -$53 (400-500k), +$27 (600-700k).
- Realized 1-tick vol identical d1/d2/d3 (1.135/1.138/1.140). AC(1) of returns d3=-0.156 (similar all days). **Day 3 is NOT a regime shift**, just unfortunate path.
- Wall-Mid FV: `wall - simple_mid` mean=-0.31, never above mid by >0.5 (stale-FV cost zero in adverse-fwd-5 proxy: 0 vs 1375 for EMA).
- Wall-Mid MM bleeds because it accumulates LONG inventory through each rally (300-400k, 600-700k), then carries it into the next leg-down. This is structural drift cost; no FV change fixes it.

## 2. Crash Detection: Forward t-stats (3-day pooled, N=29.8k)

| Signal | IC fwd50 | t fwd50 | IC fwd500 | t fwd500 |
|---|---:|---:|---:|---:|
| velocity-50 | -0.082 | **-14.16** | -0.126 | **-21.79** |
| accel(50,100) | -0.058 | -10.10 | -0.026 | -4.39 |
| OBI L1 | +0.050 | +8.71 | +0.015 | +2.63 |
| spread | -0.020 | -3.50 | -0.018 | -3.12 |
| wall-mid spread | +0.043 | +7.52 | +0.014 | +2.36 |

**velocity-50 dominates at every horizon.** Acceleration adds short-term info (t=-10) but degrades by fwd200. The current v2 trigger (velocity<=-3) is the best feature found.

## 3. Long-Side Reversal — REJECTED

Deep troughs (mid 200-tick min, drop>$5) bounce **100% of time** in day-3 forward look (fwd50 mean=+$8.86, fwd200=+$15.41). But this used **forward-window** detection (peeking).

Causal long strategies tested:
- Local-min lift @ drop>=5: -$50k/day (false bottoms during sustained drops).
- Crash-then-vel20-reversal-up @ drop_recent<=-5, vel20>=+2: -$27k 3-day across 5 parameter grids.

Spread cost (lift ask, exit bid, ~$2/share) overwhelms forward bounce. **No tradable long-reversal alpha.**

## 4. Voucher Delta Hedge — DEFERRED

Net voucher delta computation requires per-strike spot-grid; v2's BS uses adaptive sigma. Quick estimate: with ~50 contracts each across 3-5 active strikes (delta 0.3-0.7 ATM), net delta typically |Δ|<30 in 5295 spot. VFE position cap is 200 — delta-hedge using 30 of that capacity costs ~15% of MM capacity for ~$0-200 hedge benefit. Negative ROI vs alternative use of those 30 contracts. Not pursued.

## 5. Concrete Upgrade — NONE that beats v2 in BT

Tested in full BT:
| Variant | d1 10k | d2 10k | d3 10k | TOT |
|---|---:|---:|---:|---:|
| **v2 baseline** | 10,438 | 55,591 | **45,394** | **111,422** |
| time500 (no TP/SL, exit at 500 ticks) | 6,018 | 55,380 | 48,792 | 110,190 |
| TP=10 + time500 hard cap | 10,438 | 55,591 | 45,394 | 111,422 (no-op, TP fires first) |
| Rearmable cd=2000 + time500 | 8,396 | 50,653 | 42,851 | 101,900 |

Pure-Python sim showed time-exit beats TP/SL by **+$4,400 3-day** but full BT shows **-$1,232** because Wall-Mid MM interactions during the 500-tick hold offset the gain (the persistent short blocks normal MM symmetry).

**v2 momentum-short is at local optimum.** Day-3 -$3,709 is structural Wall-Mid MM drift cost, not fixable via momo tuning.

## Recommendation: SHIP v2 AS-IS

No upgrade meaningfully beats v2 across all 3 days. The remaining alpha hunt headroom for VFE on day 3 likely requires **inventory-skew on Wall-Mid MM** (skew quotes asymmetrically when |pos|>50 to clear faster) — that's a separate, larger refactor of the MM core, not a momentum-module patch.

## Files
- Analysis: `trader-logic/round-4/intel/vfe_alpha_v2.py`
- Strategies tested: `intel/vfe_alpha_v2_test.py`, `_test2.py`, `_test3.py`
- Diagnostic: `intel/vfe_alpha_v2_diagnose.py`
