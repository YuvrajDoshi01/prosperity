# Mark 01 Forensics — R4 v6 Probe

**Verdict**: alpha real (t=±3.1, n=504) but **structurally unobservable in BT/live**.
Consumed by competing makers before reaching `state.market_trades`. Cannot ship.

## Findings

### 1. Per-day flow
- **VFE**: net = -32, -23, +97 vs day drift = +20, +28, **-64**. Sign-match 0/3 — anti-correlated.
- **VEV_5300/5400/5500**: 100% buyer every day, regardless of underlying. Pure long-vega bot.
- **VEV_6000/6500**: synthetic book with Mark 22, every-tick fills mid+/-0.5. PnL = 0 (dead code).

### 2. Time clustering
Uniform per 100k bucket. Inter-trade gap median 41-79 ticks. Only 4-7% within 5 ticks. No burst structure.

### 3. VEV_5300 fade (t=-3.26 raw) — REJECTED
Cross-retracement test: avg(price - mid) = -0.91, avg(mid_fwd - mid) = -0.12. The -0.12 is half-spread mean reversion of his own cross. Not tradable. Same for VEV_5400/5500.

### 4. Mark 01 + Mark 22 pair — DEAD
6000/6500 mid never moves. 5200..5500 alpha already covered by raw signal #5; pairing adds nothing.

### 5. VFE h=1 directional (the real signal)

| Side | n | mean h=1 | t | per-day cum (5t hold) |
|------|---|----------|---|-----------------------|
| BUY  | 260 | **+0.233** | **+3.32** | d1=+44 d2=-15 d3=+46 |
| SELL | 244 | **-0.211** | **-3.10** | (mirror) |
| baseline | 29997 | -0.0005 | -0.08 | n/a |

Both >2sd vs baseline, Bonferroni-survive (α=0.05/7 marks → |t|>2.69).
Capacity: ~85 events/day × 0.23 mid × 5 ticks ≈ $30/day MTM. Day-2 inverted.

## Strategy: `r4_v6_m01.py`

On Mark 01 VFE trade in `state.market_trades` (qty≥3), latch 5-tick directional bet: post inside-spread side, size 8, ±80 cap.

### BT (10k 3-day, vs r4_final_v5.py)

| Window | v5 | v6 m01 | Δ |
|---|---|---|---|
| 1k probe d1/d2/d3 | $4818/$15706/$6390 | identical | **0** |
| 10k 3-day default | **$163,376** | $163,376 | **0** |
| 10k 3-day imc | **$156,182** | $156,242 | **+$60** |

**Fails Pareto criteria.**

## Why it doesn't translate

BT diagnostic (1k day 3):
- CSV: 13 Mark 01 VFE trades. BT surfaces only **5** in `state.market_trades`. **0** in `own_trades`.
- Net: 1 actionable signal per 1k ticks (qty≥3 filter).

The matcher consumes Mark 01's trades through Mark 55/22/14/67 (other passive makers at the same price tier) before they reach our state. Mark 01 is a peer MM — our Wall-Mid quotes don't intercept him. Same root cause as rejected v6/v7 counterparty layer in `project_round4_v3_synthesis.md`: **substitution, not addition**.

## Recommendation: SHIP r4_final_v5.py UNCHANGED

Mark 01 cell of the alpha matrix is **closed**. Re-investigation would need BT framework changes to expose consumed market_trades, not a strategy iteration.

Files: `intel/mark01_alpha.py`, `intel/mark01_alpha_v2.py`, `r4_v6_m01.py`.
