# Mark 38 Alpha — R4 v6 Reverse-Engineering

**Verdict: NO INCREMENTAL ALPHA. v6 BT byte-identical to v5.**
1k probe $6,390 / 10k def $163,376 / 10k imc $156,182. Do NOT submit `r4_v6_m38.py`.

## Mark 38 universe

| Product | Trades | Aggression | Direction | Per-day |
|---|---:|---:|---|---:|
| HP | 1,022 | +7.87/+7.90 | 515b/507s — 50/50 | 311–375 |
| VEV_4000 | 442 | +10.32/+10.44 | 209b/233s | 128–164 |
| Other VEV | 16 total | — | noise (≤3/strike) | — |

* Time-of-day: uniform 91–118 / 100k bucket.
* Inter-arrival: median 1.8–2.1k ticks (HP), 4.8–5.4k (VEV_4000).
* Forward-mid signed: HP t = -1.4/-0.4 (h1/h10); VEV_4000 +0.8/+1.4. **No directional signal.**

## Mark 14 quote location is deterministic

| Product | Spread | n ticks | Mid offset |
|---|---:|---:|---|
| HP | 16 (92.5%) | 27,754 | ±8.0 |
| HP | 15/17 | 1,261 | ±7.5 / ±8.5 |
| VEV_4000 | 21 (74.9%) | 22,473 | ±10.5 |
| VEV_4000 | 20/22 | 6,931 | ±10.0 / ±11.0 |

Mark 14 holds the entire visible book ~95% of ticks. No L3.

## v5 already skims Mark 38

* **HP** passive MM at `(best_bid+1, best_ask-1)` size 200 → mid±7. Every M38
  take routes through us by price priority. HP P&L $53,788 / $49,901 — saturated.
* **VEV_4000/4500** deep-ITM theta MM (`r4_final_v5.py` L989-1020) at
  `min(intrinsic±1, vbb+1)`. Intrinsic ≈ mid → clamp resolves to `(vbb+1, vba-1)` =
  same skim, +9 edge / fill.

## Layers tested

| Variant | Bid/Ask | 1k | 10k def | 10k imc |
|---|---|---:|---:|---:|
| v5 | existing | 6,390 | 163,376 | 156,182 |
| v6 SKIM @ vbb+1 (size +30, cap 100) | vbb+1/vba-1 | 6,390 | 163,376 | 156,182 |
| v6 SKIM @ vbb+2 | vbb+2/vba-2 | 6,390 | 163,376 | 155,945 (-237) |

vbb+1 collapses with deep-ITM theta MM (same px). vbb+2 regresses imc — gives up
edge with no flow gain because BT M38 volume is CSV-exogenous.

## Why M38 is fundamentally capped in BT

In `market_trades.csv` M38's volume is fixed. Posting inside M14 captures it —
v5 already does. Larger size stacks behind us; tighter price gives up edge
without unlocking flow. v5 holds the maximum-edge quote at maximum size on
every M38-relevant level.

## Recommendation

Keep v5. Skip r4_v6_m38 (not strict-Pareto). Higher-EV next: voucher OBI
scaling, m67 copy, vol-surface skew, HP timing. M38 is fully priced.

Files: `intel/mark38_alpha.py`, `r4_v6_m38.py` (working, rejected).
