# Voucher Delta-Short YOLO — R4 1k Day-3 Probe

## Hypothesis

R4 day-3 1k window shows VFE −$42 / ATM vouchers ~50% drop (structural down regime).
A naked short portfolio (VFE −200 + every voucher −300 except dust strikes 6000/6500
where bb=0) captures this drop directionally. Theoretical ceiling: $75,750 mid PnL,
$57,200 cross-spread.

## Per-Strike Short PnL — 1k Day 3 (intel/voucher_short_yolo.py)

| Product | Qty | Entry mid | Exit mid | Drop | Mid PnL | Realistic PnL |
|---|---:|---:|---:|---:|---:|---:|
| VELVETFRUIT_EXTRACT | 200 | 5295.5 | 5253.5 | 42.0 | 8,400 | 7,400 |
| VEV_4000 | 300 | 1296.0 | 1253.5 | 42.5 | 12,750 | 6,300 |
| VEV_4500 | 300 | 795.5 | 754.0 | 41.5 | 12,450 | 7,500 |
| VEV_5000 | 300 | 296.5 | 256.0 | 40.5 | 12,150 | 10,200 |
| VEV_5100 | 300 | 201.5 | 164.0 | 37.5 | 11,250 | 9,900 |
| VEV_5200 | 300 | 119.5 | 88.5 | 31.0 | 9,300 | 8,400 |
| VEV_5300 | 300 | 58.0 | 39.0 | 19.0 | 5,700 | 5,100 |
| VEV_5400 | 300 | 20.5 | 11.5 | 9.0 | 2,700 | 2,400 |
| VEV_5500 | 300 | 7.0 | 3.5 | 3.5 | 1,050 | 600 |
| VEV_6000 | 300 | 0.5 | 0.5 | 0.0 | 0 | −300 |
| VEV_6500 | 300 | 0.5 | 0.5 | 0.0 | 0 | −300 |
| **TOTAL** | | | | | **75,750** | **57,200** |

Peak unrealized $91,300 at ts=87,300; trough only −$8,400 at ts=9,100.

## Execution Reality

L1 depth is 7−21 contracts per voucher at ts=0. Cannot dump 300 in one tick.
Strategy: aggressive-take walking down all bid levels each tick + passive sells
joining best_ask — fills via bot taker flow over the first ~50 ticks.
ITM vouchers (4000−5200) carry the bulk of PnL via delta. ATM-only subset
(5300/5400/5500/6000 + VFE) yields just $17,850.

## BT Results (`r4_yolo_short.py`, --ticks 1000)

| Day | Strategy | PnL |
|---|---|---:|
| 4-1 | gated (DETECT=30, THRESH=−1.5) | **$0** (gate rejects, drift +5.0 at ts=3000) |
| 4-2 | gated | **$0** (gate rejects, drift +3.0) |
| 4-3 | gated | **$61,050** (drift −3.0 at ts=3000 → enters short) |
| 4-3 | ungated (always-short) | $66,232 |
| 4-3 | 10k window gated | **$103,600** |

Gate-induced PnL hit on day-3: −$5,182 from waiting 30 ticks, but eliminates
day 1/2 −$11k/−$8.8k tail-risk if live mirrors them.

## Regime Gate Logic

VFE mid drift from ts=0 to ts=3000:
- Day 1: +5.0 (up)
- Day 2: +3.0 (up)
- Day 3: −3.0 (down)

Threshold −1.5 cleanly separates day-3 from days 1/2. Triggers SHORT-EVERYTHING
mode only on confirmed down regime; otherwise sits flat.

## Risk Profile

This is a directional bet replacing r4_final ONLY if user is confident day-4 will
be a down regime like day-3. Pure delta exposure — no hedge, no MM safety net.

- LIVE day-4 = down regime (P>40%): probable $50k+ PnL crossed
- LIVE day-4 = flat/up: $0 PnL (gate refuses entry); foregoes r4_final's ~$6k upside
- LIVE day-4 = mid-day reversal: stuck short into rally, max drawdown ~$8k observed
  in BT day-3 trough at ts=9,100

Implementation: `trader-logic/round-4/r4_yolo_short.py`
Analysis: `trader-logic/round-4/intel/voucher_short_yolo.py`
