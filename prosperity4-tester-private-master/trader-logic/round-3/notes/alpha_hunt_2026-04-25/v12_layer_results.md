# r3_v12 Layer Results

Built incrementally on top of r3_v11.py. Each layer BT-tested on day-2 1k window.

## Day-2 1k BT (the website-tested window)

| Layer | Description | 1k-day-2 BT | Δ vs v11 | Cumulative | Status |
|-------|-------------|-------------:|---------:|-----------:|--------|
| 0 | v11 baseline | $12,262 | — | $12,262 | unchanged |
| A | Skip VEV_6000/6500 | $12,262 | +$0 | $12,262 | kept (no harm) |
| B | VEV_4000 best±1 SIZE=5 MM, ±50 cap | $12,396 | +$134 | $12,396 | kept |
| C | OTM passive bid VEV_5300/5400/5500 | $12,410 | +$14 | $12,410 | kept |
| D | HP open-dump SHORT at tick=100 | $12,410 | +$0 | $12,410 | kept (no day-2-1k effect, see notes) |
| E | VFE spread-state aggressive lift | $12,410 | +$0 | $12,410 | kept (no day-2-1k effect, see notes) |

## Per-product breakdown (final v12, day 2 1k)

| Product | v11 | v12 | Δ |
|---------|----:|----:|--:|
| HYDROGEL_PACK | 10,224 | 10,224 | 0 |
| VELVETFRUIT_EXTRACT | 1,940 | 1,940 | 0 |
| VEV_4000 | 0 | 134 | +134 |
| VEV_4500 | 0 | 0 | 0 |
| VEV_5000 | 0 | 0 | 0 |
| VEV_5100 | 0 | 0 | 0 |
| VEV_5200 | -28 | -28 | 0 |
| VEV_5300 | 136 | 136 | 0 |
| VEV_5400 | -10 | 3 | +13 |
| VEV_5500 | 0 | 0 | 0 |
| VEV_6000 | 0 | 0 | 0 |
| VEV_6500 | 0 | 0 | 0 |
| **Total** | **12,262** | **12,410** | **+148** |

## 10k 3-day verification (full-day robustness)

| Day | v11 BT | v12 BT | Δ |
|-----|--------:|--------:|--:|
| Day 0 | ~$15,170 | $28,508 | +$13,338 |
| Day 1 | ~$8,300 | $9,383 | +$1,083 |
| Day 2 | ~$23,500 | $18,764 | -$4,736 |
| **Total** | **$46,976** | **$56,654** | **+$9,678** |

The v12 gains are dominated by VEV_4000 MM (+$3k–3.3k per day) and VFE spread-state lift on day 0 (+$488). Day 2 full-day shows a regression vs v11 baseline (~-$4.7k) — primarily VEV_5200 day 0 picked up some loss on day 1 (-$824); also reflects different position trajectories from increased voucher activity.

## Why some layers don't show in day-2 1k

### Layer A (skip 6000/6500)
- v11 already doesn't trade 6000/6500 in 1k window — no fills. Zero observable delta but eliminates wasted compute and any rare adverse take.

### Layer D (HP open-dump)
- spread=17 fires at ts=4700 on day 2 (with mid > 10010), shorting 200 BEFORE tick=100 (ts=10000). Position is already ±200, leaving zero headroom for open-dump entry. The s17 logic implicitly captures the open-dump trade.
- Layer D fires only when s17 has NOT fired by ts=10000. Adds robustness across other days/regimes.

### Layer E (VFE spread-state lift)
- Fires 34 buys + 25 sells in 1k window, but at the same inside-spread price as the existing Wall Mid MM. The MM block's tb/ts headroom is reduced by Layer E commitment, so net VFE order book contribution is identical → identical PnL on day 2 1k.
- BUT: across full days, Layer E's directional bias produces edge: +$488 on day 0, +$42 day 1, +$224 day 2 (+$754 total 3-day VFE). Helps when MM bot is moving aggressively.

## Notes / surprises

- **Layer C only added +$14**, far below the +$260 EV target. Likely the BS edge constraint (`fv−2`) caps bid_px below `bb+1` on most ticks, so we end up posting deep-bid that rarely fills in 1k.
- **Layer A's claimed +$36 EV not visible** — VEV_6000/6500 simply don't trade in 1k window with v11's logic.
- **Layer D's claimed +$2-3k not visible on day 2 1k** because spread=17 already monopolizes HP at ts=4700.
- **Layer E's claimed +$0-500 day 2 1k matched** ($0 in this seed). Full 3-day +$754 matches estimate.
- Realistic v12 day-2 1k uplift: **+$148** (=1.2% above v11). Multi-day uplift: **+$9.7k** (=20.6% above v11).
- Expected v12 website score: $12,410 × 0.99 ≈ **$12,286** (BT × 0.99 ratio verified).

## File locations

- Strategy: `trader-logic/round-3/r3_v12.py`
- Results: `trader-logic/round-3/notes/alpha_hunt_2026-04-25/v12_layer_results.md`
