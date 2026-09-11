# r3_v13 Layer Results

Built incrementally on top of r3_v12.py (day-2 1k $12,410, 3-day $56,654).
Each layer BT-tested on day-2 1k window primarily; 3-day verified at end and after stacking.

## Day-2 1k BT (the website-tested window)

| Layer | Description | 1k-day-2 BT | Δ vs v12 | 3-day BT | Status |
|-------|-------------|-------------:|---------:|---------:|--------|
| 0 | v12 baseline | $12,410 | — | $56,654 | unchanged |
| F | VEV_4000 SIZE 5→15, cap ±100 | $12,410 | +$0 | (n/a) | kept |
| G | MM 4500/5000/5100/5200 SIZE=15 | $12,410 | +$0 | (n/a) | kept |
| H | VEV_5300 SIZE=15 + bid bb+1 (no BS cap) | $12,410 | +$0 | $56,621 | kept |
| I | VFE OBI skews Wall Mid FV (β=0.3) | $12,158 | −$252 | (skipped) | **REVERTED** |
| I' | VFE OBI skews Wall Mid FV (β=0.15) | $12,158 | −$252 | (skipped) | **REVERTED** |
| J | VFE OBI tilts voucher BS FV | $12,410 | +$0 | (n/a) | kept |
| K | VEV_4000 inventory dampener (cap 50, halve at \|pos\|>35) | $12,410 | +$0 | $56,621 | kept |

## Per-product day-2 1k breakdown (final v13, identical to v12)

| Product | v12 | v13 | Δ |
|---------|----:|----:|--:|
| HYDROGEL_PACK | 10,224 | 10,224 | 0 |
| VELVETFRUIT_EXTRACT | 1,940 | 1,940 | 0 |
| VEV_4000 | 134 | 134 | 0 |
| VEV_5300 | 136 | 136 | 0 |
| VEV_5400 | 3 | 3 | 0 |
| VEV_5200 | -28 | -28 | 0 |
| Others | 0 | 0 | 0 |
| **Total** | **12,410** | **12,410** | **0** |

## 10k 3-day BT

| Day | v12 BT | v13 BT | Δ |
|-----|--------:|--------:|--:|
| Day 0 | $28,508 | $28,508 | 0 |
| Day 1 | $9,383  | $9,350  | -$33 |
| Day 2 | $18,764 | $18,764 | 0 |
| **Total** | **$56,654** | **$56,621** | **-$33** |

Day-1 -$33 = noise from Layer G's tiny adverse fills on 5000/5100/5200 (-$92 net across 4 strikes from VEV_4500: -$34, VEV_5000: -$32, VEV_5100: -$26 vs v12 zero). Offset by positive deltas elsewhere.

## Why all Tier-2 layers were inert/harmful

### Layer F (VEV_4000 SIZE 5→15, cap 50→100): inert
- Microstructure agent finding "engine caps fills at market_trade qty per side per tick" CONFIRMED here. Increasing posted size from 5 to 15 produces identical fill quantity. SIZE 15 = SIZE 5 in observed flow.
- Position never approaches the 100 cap in 1k window (max ±5–10 from intermittent fills).
- Kept because larger headroom doesn't hurt and potentially helps in regime shifts.

### Layer G (MM on VEV_4500/5000/5100/5200): inert day-2 1k, slight 3-day cost
- VEV_4500/5000/5100 see zero takers in 1k window — confirmed by alpha hunt.
- VEV_5200 already had v9 logic; new posts collide with it but limit-checked headroom prevents double-orders.
- Day 1 saw $-92 net from these strikes (small adverse fills around volatile timestamps).
- Kept; benign.

### Layer H (VEV_5300 SIZE=15, bb+1 unconditional): inert
- VEV_5300 stays $136 on day-2 1k. Engine saturation again — taker volume per tick is the binding constraint.
- The "BS-fair-2 cap pushed bid below bb+1" claim from agent was correct in some ticks of full 10k, but for the 1k window the cap rarely binds.
- Day 2 full-day VEV_5300 = $762 (matches v12); the bid_px change has no measurable effect because the BS cap only binds in low-IV regimes.

### Layer I (VFE OBI skew on Wall Mid FV): −$252 day-2 1k → REVERTED
- `fv = round(wm + 0.3 × OBI_combined)` flipped FV by ±1 whenever OBI sign was consistent — and consistent-sign OBI is exactly when Wall Mid is most reliable.
- Tried β=0.15 — same result (round() saturates on |OBI| > ~0.15 either way).
- The β=0.30 estimate from VFE agent #3 was on raw correlation IC (0.30 with mid-mid), not on the realized PnL after spread cost. Once you re-discretize to integer prices, you essentially shift the MM ask DOWN when OBI is positive (which is when buy pressure is high — you give away edge to buyers).
- A continuous-price MM (no rounding) might benefit; the integer engine kills this layer.
- **Reverted** entirely; FV stays at `round(wm)`.

### Layer J (VFE OBI tilts voucher BS FV): inert
- `fv_bs += 0.5 × OBI × delta`. Typical |OBI| < 0.5 and |delta| < 1 → max |skew| ≈ 0.25.
- BS edge V_BS_EDGE = 10 ≫ 0.25 → never moves any take threshold across an integer price.
- Zero effect day-2 1k. Could matter at much smaller V_BS_EDGE but reducing edge invites adverse selection.
- Kept because cost is zero.

### Layer K (VEV_4000 inventory dampener): inert
- |VEV_4000_pos| never crosses 35 in 1k or 10k BT due to engine fill cap (pos sees max ±5–10 from arbitrage flows).
- Tested cap 100 → 60 → 50: identical PnL across all three ($18,764 day-2 full, $9,350 day-1, $28,508 day-0).
- Kept the original v12 cap=50 with new dampener at \|pos\|>35 as defense-in-depth.

## Notes / surprises

- **Engine saturation kills all SIZE-increase alpha**. Microstructure agent's earlier SIZE 15 = 30 = 60 finding extends to SIZE 5 → 15 — fills are determined by counter-side market_trade qty per side per tick, NOT by what we post. Post 15 if you want, but expect ≤ 5 fills.
- **OBI alpha killed by integer rounding**. The day-2-1k regression with Layer I shows that even a small continuous skew (β=0.15) blows up at integer prices on a stable-mid product like VFE.
- **Day-2 full-day "regression" claimed in spec was already v12's baseline** — not a new bug to fix. v13 matches v12 on day 2 ($18,764).
- Realistic v13 day-2 1k uplift: **+$0** (vs v12's $12,410).
- Multi-day uplift: **−$33** (within noise band).
- Expected v13 website score: **$12,410 × 0.99 ≈ $12,286** (BT × 0.99 ratio verified).

## Recommendation

**v13 is functionally equivalent to v12** for the website 1k window. The Tier-2 alpha estimates from the alpha hunt (+$1,500–2,500) didn't materialize because:
1. Most posted-size increases hit the engine fill cap.
2. OBI signal is real (correlation-wise) but doesn't survive integer-price discretization on tight-spread products.
3. The day-2-1k window is already near-saturated with v12's logic.

**If submitting v13, expect website ~ $12,286** (same as v12's predicted $12,286).
**v12 remains the submission of record.** v13's only structural improvements are larger position headroom on VEV_4000 (cap +50, with dampener for safety) and broader voucher MM coverage (4500/5000/5100/5200) which mostly idle but provide some defense against regime shifts.

## File locations

- Strategy: `trader-logic/round-3/r3_v13.py`
- Results: `trader-logic/round-3/notes/alpha_hunt_2026-04-25/v13_layer_results.md`
