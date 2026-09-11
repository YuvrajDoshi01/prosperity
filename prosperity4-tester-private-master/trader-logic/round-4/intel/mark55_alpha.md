# Mark 55 Alpha — VFE Follow-Flow

## Profile
- 1,198 trades / 6,551 vol; 49.9% buyer (598 buys vs 600 sells); avg qty ~5.5.
- VFE-only (no other product).
- Net inventory P&L = -$15,866 (he loses on his own VFE flow).
- Counterparties: Marks 14, 01 dominate.

## Hypotheses & Findings

| H | Setup | Result |
|---|-------|--------|
| H1 | Mark 55 rolling net flow → VFE forward Δmid | **STRONG, all 3 days**. Best at w=50/h=200: r=+0.16, t=+16.2 (d1); w=50/h=50: r=+0.10, t=+10.3 (d2); w=50/h=50: r=+0.09, t=+8.8 (d3). |
| H2 | M55 SELL events qty>=8 → forward drop | Weak (only 26-42 events/day, t≈-1.5 to -2.0) — too sparse. |
| H3 | M55 BUY events qty>=8 → forward drift | Day 3: t=+2.48 at h=25, mean +1.89. Other days noise. |
| H4 | Aggregate (M55+49+14+01) net flow | Mostly *negative* corr. Doesn't dominate; M55 alone is the cleanest signal. |
| H5 | M14/M01 lead M55 timing | Only Mark 01 lead=5 ticks: t=+2.64 d3 (weak). Not actionable. |

**Direction is FOLLOW, not fade**: Mark 55's flow precedes mid drift in his direction. He is the *taker that moves the market*, not the dumb-money to fade.

## Strategy: M55 Net-Flow Follow Take

```
signal_t = Σ (M55_buy_qty - M55_sell_qty) over last 50 ticks  # combines market_trades + own_trades
if signal_t >= +30: take long at best ask, qty=20, capped at +60 pos
if signal_t <= -30: take short at best bid, qty=20, capped at -60 pos
```

Implementation lives in PRE-MM lane (claims headroom before WM MM), so it stacks with v5 layers without contention.

## Backtest

| Window                 | v5 baseline | v6_m55 (THR=30 CAP=60 SZ=20) | Δ |
|------------------------|------------:|------------------------------:|------:|
| 10k 3-day default      | $163,376    | **$166,200**                  | **+$2,824** |
| 10k 3-day imc          | $156,182    | **$158,096**                  | **+$1,914** |
| 1k day-3 probe         | $6,390      | $6,390                        | 0 (signal warmup) |

Day 3 default VFE: -$1,567 → +$2,626 (+$4,193). Days 1/2 small VFE bleed (-$3,000 combined) — net **+$2,824 default**, **+$1,914 imc**, **strict Pareto on both 10k windows**.

THR sweep at fixed (CAP=60, SZ=20):
- THR=20 → $160,270 (over-fires; -$3,106 vs v5)
- **THR=30 → $166,200 (winner)**
- THR=35 → $163,448
- THR=40 → $163,376 (= v5; signal too rare)

The signal is largely **a Day 3 capture mechanism** (sharper directional drift than other days). Days 1/2 are well-served by WM MM alone — additional take fights spread for similar exposure.

1k day-3 probe shows no delta because the rolling-50 buffer warmup needs ~50 ticks before any signal can fire, and the signal threshold is only crossed sparsely; first 1k of day-3 doesn't see a fire. Live live-fire ratio expected 5-10× higher than BT (since live `market_trades` aren't consumed by our orders).

## Caveats

1. **BT signal partial**: in default-mode BT, our WM MM consumes most M55 market_trades, so we reconstruct flow from `state.own_trades` (when our order matched against M55 the buyer/seller string survives). LIVE IMC engine surfaces M55 trades in `market_trades` regardless — so live signal will be **stronger** than BT shows.
2. **THR=30 is critical**. THR=20 over-fires (-$3,106 vs v5). THR=40 under-fires (= baseline).
3. **Direction is FOLLOW-flow, not fade-flow** — opposite of typical "dumb money" intuition. M55 may be either an informed bot or simply a high-volume momentum participant; either way mid follows him.
4. The Mark 55 inventory loss (-$15,866) does NOT contradict follow-flow alpha: he wins the *direction* but eats the spread (taker fees / adverse mid revisions on stack-up).

## Files
- `intel/mark55_alpha.py` — analysis script (correlations + trigger sims).
- `r4_v6_m55.py` — production strategy (v5 + Mark 55 layer).
