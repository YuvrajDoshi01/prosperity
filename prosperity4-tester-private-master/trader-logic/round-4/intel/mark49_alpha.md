# Mark 49 VFE alpha — reverse-engineering report

## TL;DR

**Sign in the brief was inverted.** In round-4 data (days 1-3), Mark 49 is
a "wrong-side" taker on VELVETFRUIT_EXTRACT. After Mark 49 **SELLs**,
mid **rises**; after Mark 49 **BUYs**, mid **falls**. He gets faded by the market.

| Trigger | n | H=1 mean | t-stat | H=10 mean | t-stat |
|---|---:|---:|---:|---:|---:|
| Mark 49 SELL VFE (any qty) | 105 | **+1.90** | **+20.0** | +2.14 | +7.6 |
| Mark 49 SELL VFE qty>=8 | 93 | +1.95 | +18.5 | +2.21 | +7.2 |
| Mark 49 BUY VFE | 17 | **-1.26** | **-4.0** | -1.97 | -2.3 |

Trade is **BUY VFE** (not SELL) when Mark 49 sells. **SELL VFE** when Mark 49 buys.

## Brief sign discrepancy

Brief stated: `h=1: t=-19.04, mean=-1.81 (97% drop after he sells)`.
Reproduced in our data with same H=1: **t=+20.03, mean=+1.90**. The brief's stat
likely came from a flipped-sign convention or stale dataset. Verified by:
- 105 trades, only 8% of horizons show negative mean — the data is dense and consistent.
- Forward returns persist out to H=50 (+1.99, t=+3.2).
- Symmetry on the BUY side (n=17, H=1, t=-4.0 same magnitude opposite sign).

## Per-day stationarity (qty>=8, H=10, SIZE=30)

| Day | n | Total LONG-fade PnL |
|---|---:|---:|
| 1 | 29 | $2,280 |
| 2 | 36 | $1,965 |
| 3 | 28 | $1,920 |
| **Total** | **93** | **$6,165** (theoretical max, mid-to-mid) |

Stable across all three days. Not a single-day artifact.

## Daily extrema check

Mark 49 SELLs cluster in the **40-70% decile** of daily VFE range — middle of the
price range, NOT at daily highs. Hypothesis 5 (extrema concentration) refuted.

## Sequence layers

Both `M49 SELL → M55 SELL` (n=94) and `M49 SELL → M14 BUY` (n=73) inherit Mark 49's
sign. Adding sequence filters subsets the signal but doesn't flip it. Brief's
sequence numbers (-1.41, -1.13) are also sign-inverted vs our data. Skip these
filters — they don't add edge over the simple Mark 49 trigger.

## 1k day-3 probe gating risk

Only **n=2 firings** in the first 1k ticks of day 3 (ts<=99,900), worth $75 mid-to-mid.
The alpha lives in the 10k 3-day window, almost entirely in days 1+2 + day-3 tail.

**Implication**: 1k probe will be near-flat (≤+$100). Pareto bar still met if
def/imc 10k 3-day improve and 1k probe doesn't regress meaningfully.

## Implementation contract (final BT-tested)

`run_mark49_fade` in `r4_v6_m49.py`:
- Scan `state.market_trades[VFE]` each tick for new Mark 49 fills.
- M49 SELL qty>=8: target +20 long, hold 5 ticks, take at best_ask.
- M49 BUY qty>=1: target -20 short, hold 5 ticks, take at best_bid.
- Cap |inventory contribution| at +/-20 (VFE LIMIT=200 unaffected).
- Dedupe via `vstate.m49_seen` ring of recent ts.

## Final BT vs v5 baseline

| Window | v5 | v6_m49 | Delta |
|---|---:|---:|---:|
| 1k day 1 | $4,818 | $4,514 | **-$304** REGRESS |
| 1k day 2 | $15,706 | $15,700 | -$6 (noise) |
| 1k day 3 probe | $6,390 | $6,390 | 0 |
| 10k 3-day default | $162,930 | $167,382 | **+$4,452** |
| 10k 3-day imc | $156,182 | $159,540 | **+$3,358** |

**Pareto verdict: FAIL on 1k day 1.** v6_m49 wins large on 10k both modes
but loses $304 on day-1 1k window. Brief required strict Pareto win across
all three test windows.

## Why Pareto fails: spread tax

Edge: Mark 49 SELL → mid drift +$1.90/share at H=1, +$2.21 at H=10 (n=93).
VFE typical spread = 2-3. Half-spread cost on aggressive take = $1.0-$1.5.
Net realised edge: ~$0.5-$1.0/share.

Tested four entry styles, none Pareto-positive:

| Entry | Day-1 1k | 10k def | 10k imc | Notes |
|---|---:|---:|---:|---|
| Aggressive at ask, size 30 hold 10 | $3,970 | +$5,880 | +$3,892 | -$424 day-1 1k |
| Aggressive at ask, size 20 hold 5 | $4,514 | +$4,452 | +$3,358 | -$304 day-1 1k (final) |
| Passive at bb+1 (collides w/ WM MM) | $4,818 | $0 | $0 | zero incremental fills |
| Passive at ba-1 (still no fills) | $4,818 | $0 | $0 | zero incremental fills |

The WM MM in v5 already posts at `min(fv-1, bb+1)` and is hit by takers
(Mark 67 etc.) at the precise moments Mark 49 dumps. **v5 implicitly captures
the Mark 49 drift** via passive WM bids. Adding aggressive M49-take just pays
spread to expedite an already-capturable position.

## Recommendation

**Do NOT ship r4_v6_m49.** Keep file in repo as evidence of negative result.
The Mark 49 anti-Olivia signal is real and reproducible (t=+20.0, n=105),
but its $0.5-$1/share net-of-spread edge is already absorbed by v5's
Wall-Mid market-making. Further gains would require either:
1. Taker-priority at exchange (we have none),
2. Predictive model that fires BEFORE M49 prints (no leading data observed),
3. Tighter spreads on VFE in real environment than CSV (test on live).

If we knew the **live** environment had VFE spread=2 with WM MM under-utilised,
the M49 fade could swing positive. Until then, v5 remains the Pareto frontier.

## Files

- `intel/mark49_alpha.py` — EDA + signal verification
- `r4_v6_m49.py` — candidate (BT-rejected, kept for archive)
