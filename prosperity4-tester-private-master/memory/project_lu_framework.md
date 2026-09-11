---
name: Linear Utility Framework (P2 #2) — Patterns and Exact Params
description: Deep research findings from P2/P3 winners' code. 7 consistent patterns. LU's exact AMETHYSTS/STARFRUIT parameters. What works for stable vs drift products.
type: project
originSessionId: 955e9ff4-5728-4069-8882-3e961751886f
---
Deep dive into how top P2/P3 teams won their Round 1. Researched actual GitHub source from:
- Linear Utility (P2 #2): `round_1_v6.py`
- chrispyroberts (P3 #7): `final_round_1_trader.py`
- Alpha Animals / CarterT27 (P3 #9)
- TimoDiehm (P3)

## The 7 consistent patterns across winners

1. **Take → Clear → Make pipeline** (canonical LU). Take crossing orders, flatten overhang at FV, then post passively. Never skip clear.

2. **Two-regime FV**: stable = fixed constant (AMETHYSTS=10000, RESIN=10000); random-walk = filtered MM-mid. **Raw mid / microprice REJECTED by all 4 teams on random-walk product.**

3. **Adverse-volume gate**: `prevent_adverse=True, adverse_volume=15` — skip levels with vol > 15 (informed flow).

4. **Penny/join/default posting** (not fixed offsets):
   - `disregard_edge=1` (ignore inside market within 1 of FV)
   - `join_edge=2` (join if within 2 of FV, else penny by 1)
   - `default_edge=4` (post at FV±4 if no reference inside market)

5. **Soft < hard position limit** (LU: 10/20 = 50% ratio). Skew quotes 1 tick toward neutral at soft limit.

6. **Small mean-reversion coef** for random-walk: LU's `reversion_beta=-0.229` on 1-lag return. (Doesn't apply to drift products like IPR.)

7. **Clear width = 0** — flatten exactly at FV, not FV±N.

## Linear Utility AMETHYSTS params (exact)

```
take_width=1, clear_width=0, prevent_adverse=True, adverse_volume=15,
disregard_edge=1, join_edge=2, default_edge=4, soft_position_limit=10 (on LIMIT=20)
```

## Linear Utility STARFRUIT (random-walk) params (exact)

```
take_width=1, clear_width=0, prevent_adverse=True, adverse_volume=15,
reversion_beta=-0.229, disregard_edge=1, join_edge=0, default_edge=1
```

Note STARFRUIT uses `join_edge=0, default_edge=1` (tighter than AMETHYSTS) — they trust FV more.

## STARFRUIT FV formula (filtered-MM-mid + mean reversion)

```python
filtered_ask = [p for p in sell_orders if abs(sell_orders[p]) >= 15]
filtered_bid = [p for p in buy_orders if buy_orders[p] >= 15]
mmmid = (min(filtered_ask) + max(filtered_bid)) / 2
last_returns = (mmmid - last_price) / last_price
fair = mmmid + mmmid * (last_returns * -0.229)
```

## Verified on P4 (2026-04-17)

**LU framework works on stable products (ACO).** Applied to ACO in r1_v4:
- Predicted: +3% × 3,091 = +87 PnL
- Actual: +88 PnL (3,091 → 3,179)
- Matches theory to the unit.

**LU framework BREAKS on drift products (IPR).** Applied to IPR in r1_v3:
- take_width=1 requires ask ≤ fv−1
- With filtered-MM-mid at t=0, fv ≈ 11998. Threshold = 11997. Ask at 12006 NOT taken.
- IPR regressed from 7,446 → 4,796 (-2,650)
- Root cause: LU's framework assumes FV is present-value accurate; drift needs future-value FV

## How to apply in future rounds

- **Stable products (fixed FV like AMETHYSTS/RESIN/ACO)**: port LU framework directly. Expect +3% from clear step.
- **Random-walk (mean-reverting like STARFRUIT/KELP)**: filtered-MM-mid + small negative beta + LU framework.
- **Drift products (IPR-like with structural trend)**: simple mid + drift_bias, take aggressively at fv+slack. Do NOT use LU framework.
- **Scale soft_limit** by LIMIT ratio: LU uses 10/20 = 50%. For LIMIT=80, soft=40.
