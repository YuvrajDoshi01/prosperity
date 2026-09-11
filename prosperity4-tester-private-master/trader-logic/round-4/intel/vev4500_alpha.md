# VEV_4500 Alpha Hunt — DROP

## TL;DR
**Skip VEV_4500.** Bot quotes wide and centered ON intrinsic; bot takers absent (0/0/2 market trades across 3 days, vol=1/0/5 vs VEV_4000's 333/256/287). The imc-mode $1,225 day-3 is fictitious carry-over from R3 calibration (`extra_rate=0.009`, qty_range (1,3) in `order_match_maker.py:41`). Live PnL ≈ default-mode $0–$18, NOT $1,225.

## Microstructure (10k ticks/day, all 3 days)
| Metric | VEV_4500 | VEV_4000 | VFE |
|---|---|---|---|
| L1 spread (median) | **16** | 21 | 5 |
| L1 vol | 9 | 11 | 25 |
| Market trades D1/D2/D3 | 1/0/2 | 164/128/150 | — |
| Trade volume D1/D2/D3 | 1/0/5 | 333/256/287 | — |

VEV_4500 is the **lowest-flow voucher in the universe**. VEV_4000 has 60–100× more counterparty trades despite a wider spread.

## Why dead
1. **Mid-price ≡ intrinsic** to ±0.5 in 98% of spread-16 ticks — option fairly priced as pure intrinsic, zero time value (median TV = 0.0, range [-6, +5.5]).
2. **Bot quotes 8 ticks wide each side of intrinsic.** Our `intrinsic±1` post is inside-spread 99% of ticks (gap to bot best ≈ 5.5 ticks). We always pass `bid_px <= vba-1` gate, but no taker arrives — bot doesn't ping VEV_4500.
3. **No intrinsic arb edge ≥ 5** any tick across 3 days (very_cheap=0, very_rich=0). 0.9–1.2% of ticks have `ask ≤ intrinsic`, all by 1–4.5 ticks (round-trip negative after fees of 0).
4. **Position limit non-binding** (cap=100, never reached).

## imc vs default
- Default `match-mode all` matches against `market_trades.csv` → ~5 contracts × $1 edge = $18 day 3. **This is the truthful estimate.**
- imc mode synthesizes invisible takers via CRC32 hash at `extra_rate=0.009` (calibrated from R3) → ~90 phantom takers × ~$13 spread capture = $1,225. R3 calibration does NOT carry to R4 — counterparty mining confirms VEV_4500 is dead in R4.

## Recommendation: KEEP CODE, ZERO EXPECTATIONS
- Deep-ITM MM block (`r4_final.py:750`) is **harmless** (0 fills) and **safe** (intrinsic±1 with `pos_cap=100`).
- Removing saves ~5 µs/tick; not worth the diff risk near submission.
- **Do NOT widen** to `intrinsic±0` (cross-spread fill at intrinsic = zero edge, full carry risk).
- **Do NOT model** R4 PnL using imc mode for VEV_4500 — it's $1,200+ phantom. Trust default.
- If hunting VEV_4500, the only real edge is **intrinsic-arb takes when `ask ≤ intrinsic-2`** (~0.2% of ticks, qty 1–3): tighten existing arb to `V_INTRINSIC_EDGE=2`, expected ≤$30 over 10k ticks.

Net: VEV_4500 contributes <$50 live. Spend optimization budget on HP, VFE, VEV_5300.
