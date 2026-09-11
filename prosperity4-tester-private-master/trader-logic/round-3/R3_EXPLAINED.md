# Round 3 — "Gloves Off" Explained

## TWO Challenges (scored separately, both count)

1. **Algorithmic trader** — 12 products across 2 asset classes
2. **Manual auction** — single-shot two-bid game for Ornamental Bio-Pods

---

## Algorithmic Challenge — 12 Products

### Asset Class 1: Delta-1 Spot Products (2 products)
Normal commodities — no derivative structure.

| Product | Limit | ~Price | Spread | Behavior |
|---|---:|---:|---:|---|
| **HYDROGEL_PACK** | 200 | 9,991 | 16 | Stable, mild mean-reversion |
| **VELVETFRUIT_EXTRACT** (VFE) | 200 | 5,247 | 5 | Stable, mild mean-reversion |

**VELVETFRUIT_EXTRACT is the UNDERLYING for the options.** HYDROGEL_PACK is unrelated — independent stable product to MM.

### Asset Class 2: Vouchers (10 products) = Call Options on VFE
Each voucher = right to buy VELVETFRUIT_EXTRACT at a specific strike at expiry.

| Voucher | Strike | ~Price | Status (spot ≈ 5,247) |
|---|---:|---:|---|
| VEV_4000 | 4,000 | 1,247 | Deep ITM (delta ≈ 1.0) |
| VEV_4500 | 4,500 | 747 | ITM (delta ≈ 1.0) |
| VEV_5000 | 5,000 | 253 | Mid-ITM (delta ≈ 0.7) |
| VEV_5100 | 5,100 | 168 | Slightly ITM (delta ≈ 0.7) |
| VEV_5200 | 5,200 | 97 | Near-ATM (delta ≈ 0.5) |
| VEV_5300 | 5,300 | 49 | Slightly OTM (delta ≈ 0.3) |
| VEV_5400 | 5,400 | 18 | OTM (delta ≈ 0.1) |
| VEV_5500 | 5,500 | 8 | OTM (delta ≈ 0.05) |
| VEV_6000 | 6,000 | 0.50 | Far OTM (penny-pegged) |
| VEV_6500 | 6,500 | 0.50 | Far OTM (penny-pegged) |

**Position limit: 300 per voucher** (vs 200 for delta-1). Total notional capacity = 200×2 + 300×10 = **3,400 contracts**.

### Time to Expiry (TTE)
Vouchers expire 7 Solvenarian days after R1 start.

| Period | TTE |
|---|---:|
| Historical day 0 (tutorial period CSV) | 8 days |
| Historical day 1 (R1 period CSV) | 7 days |
| Historical day 2 (R2 period CSV) | 6 days |
| **R3 submission day** | **5 days** |

⚠ "historical day 0 = tutorial round" refers to **time period only** — the products (VEV/HP) are NEW. No overlap with R0 (TOMATOES) or R1/R2 (IPR/ACO).

### Round-End Liquidation
> *"Inventory does not carry over into the next round. Open positions auto-liquidated against hidden fair value at round end."*

Each round is self-contained. No exercise — at round end, IMC marks voucher positions to hidden fair value (likely Wall Mid or BS-theoretical) and pays out.

### How It's Tested
- **Test submissions** run on **1,000 ticks of day 2** only (timestamps 0-99,900 step 100)
- **Final scoring** runs full days (10,000 ticks × 3 days, presumed)
- Verified universally on community leaderboard (1,506 entries)

### Stdout Gotcha
**Print statements are NOT captured by the website sandbox**. Only `activitiesLog` (order book snapshots) is preserved. For diagnostics, use `state.traderData` (50KB cap).

---

## Manual Challenge — "Celestial Gardeners' Guild"

**Mechanics:**
- Submit two **integer** bids: `b1 ≤ b2`, both in `[670, 920]`.
- Each counterparty has a reserve price uniform discrete on `{670, 675, ..., 915, 920}` (51 values, step 5).
- **Sell price next day = 920** (fixed, fair value).

**Trade rules per counterparty (reserve `r`)**:
| Condition | Outcome |
|---|---|
| `r < b1` | Trade at b1, profit = `920 - b1` |
| `b1 ≤ r < b2` AND `b2 > mean_b2` | Trade at b2, full profit = `920 - b2` |
| `b1 ≤ r < b2` AND `b2 ≤ mean_b2` | Trade at b2, **penalized**: profit = `(920-mean_b2)³ / (920-b2)²` |
| `r ≥ b2` | No trade |

`mean_b2` is endogenous (depends on all players' b2) — multiple Nash equilibria.

**Recommended: `(b1=766, b2=866)`** — robust optimum across `mu ∈ [830, 865]`.

---

## Current State (FINAL)

See `README.md` for active state and `memory/project_round3_v1.md` for full strategy history.

**TL;DR**: Submitted r3_v11 → website **$12,246** (sub 402350). Manual: (b1=766, b2=866).
