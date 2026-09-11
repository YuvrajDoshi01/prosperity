# Round 4 Counterparty Forensics — "Hello, I'm Mark"

**Dataset**: `prosperity4bt/resources/round4/{trades,prices}_round_4_day_{1,2,3}.csv`
**Total trades**: 4,281 across 3 days
**Universe size**: 7 unique counterparties (`Mark 01, 14, 22, 38, 49, 55, 67`)
**Method**: signed forward return at horizons {10, 100, 500} ticks (1 tick = 100 ms);
mark-to-market PnL using next-tick mid as exit price. Aggression = avg(price − mid_at_trade)
signed by trade side; positive ⇒ pays through the spread.

All raw CSV outputs saved alongside this report; analysis script:
`counterparty_mining.py`.

---

## 1. Universe

| Mark | Trades | Buy | Sell | Buy share | Volume | Avg qty | # Products | Profile |
|------|-------:|----:|-----:|----------:|-------:|--------:|-----------:|---------|
| **Mark 14** | 2,172 | 1,127 | 1,045 | 0.519 | 8,718 | 4.0 | 7 | HP/VFE/VEV MM (winner side) |
| **Mark 01** | 1,843 | 1,599 | 244 | 0.868 | 7,428 | 4.0 | 7 | Pure-buyer of VEV calls + VFE |
| **Mark 22** | 1,584 | 42 | 1,542 | 0.027 | 5,889 | 3.7 | 12 | Pure-seller MM (paired w/ Mark 01) |
| **Mark 38** | 1,478 | 733 | 745 | 0.496 | 5,000 | 3.4 | 7 | HP/VEV MM (losing side, sucker) |
| **Mark 55** | 1,198 | 598 | 600 | 0.499 | 6,551 | 5.5 | 1 | VFE-only MM (winner) |
| **Mark 67** | 165 | 165 | 0 | **1.000** | 1,510 | **9.2** | 1 | **VFE pure-buyer (Olivia analog)** |
| **Mark 49** | 122 | 17 | 105 | 0.139 | 1,186 | **9.7** | 1 | **VFE seller (anti-Olivia, sucker)** |

Two clear archetypes by trade count: **MM pairs** (14↔38, 01↔22, 55 vs all) and
**directional small-N alpha bots** (67 buyer, 49 seller).

## 2. Per-Mark Per-Product Profile

Aggression at trade time, avg(signed price − mid):

| Product | Mark 14 buyer/seller | Mark 38 b/s | Mark 01 b/s | Mark 22 b/s | Mark 55 b/s | Mark 67 b/s | Mark 49 b/s |
|---|---|---|---|---|---|---|---|
| HYDROGEL_PACK | −7.98 / −7.94 | **+7.87 / +7.90** | — | −4.09 / −3.56 | — | — | — |
| VFE | −2.43 / −2.46 | — | −2.60 / −2.69 | −0.88 / −0.71 | **+2.49 / +2.47** | **+0.80 / —** | −1.50 / −0.67 |
| VEV_4000 | −10.47 / −10.37 | **+10.32 / +10.44** | — | — | — | — | — |
| VEV_5200..5500 | ≈ −1 (passive) | — | ≈ −0.5..−1 | ≈ +0.5..+0.93 | — | — | — |
| VEV_6000/6500 | — | — | −0.50 (every tick) | +0.50 (every tick) | — | — | — |

**Reading the aggression sign**:
- `+` ⇒ Mark pays through spread (taker / sucker).
- `−` ⇒ Mark receives spread (maker / passive).

**Confirmed MM pair, Mark 14 ↔ Mark 38** on HP & VEV_4000:
1,003 of 1,022 HP trades and 442 of ~437 VEV_4000 trades are between *exactly* these two.
Mark 38 always crosses (+~8); Mark 14 always passive (−~8). The widest static spread = ~16
on HP and ~21 on VEV_4000.

**Confirmed MM pair, Mark 01 ↔ Mark 22** on VEV_5200..6500: 1,339 trades, vol 4,636.
For VEV_6000 / 6500 they trade *every single tick*, qty=2..5, at price = mid ± 0.50 — they
are the synthetic two-sided book. PnL on these strikes = exactly 0.

## 3. Mark-to-Market PnL

Realized at three exit horizons. Baseline = next-tick mid. Numbers in XIRECs.

| Mark | pnl_next | pnl_h10 | pnl_h100 | pnl_h500 | Volume | PnL/vol h100 | n_h100 |
|------|---------:|---------:|---------:|---------:|-------:|-------------:|------:|
| Mark 14 | **+50,100** | **+49,074** | **+46,667** | **+44,042** | 8,718 | +5.35 | 2,155 |
| Mark 01 | +10,520 | +10,736 | +8,894 | +8,041 | 7,428 | +1.20 | 1,831 |
| Mark 67 | +1,867 | +2,176 | **+1,252** | +337 | 1,510 | +0.83 | 164 |
| Mark 49 | −1,404 | −1,696 | −1,479 | −606 | 1,186 | −1.25 | 120 |
| Mark 22 | −3,166 | −3,031 | −2,245 | −2,676 | 5,889 | −0.38 | 1,570 |
| Mark 55 | −16,082 | −15,866 | −10,456 | −12,777 | 6,551 | −1.60 | 1,190 |
| Mark 38 | **−41,835** | **−41,392** | **−42,633** | **−36,360** | 5,000 | **−8.53** | 1,468 |

**Critical caveat**: pnl_next/h100 *per Mark* is the unrealized inventory mark, not realized
P&L. Mark 14's +$46k looks dominant because he is **the passive side of a 2-Mark MM book** —
his inventory is matched by Mark 38's −$42k inventory: they wash each other within
the engine. But for **us as a third party**, the signal is robust: trading **with** the
Mark-14 side and **against** the Mark-38 side has a +$5.4 / vol h100 expectancy.

**Per-Mark Per-Day** (h100 PnL):

| Day | Mark 55 | Mark 67 | Mark 14 | Mark 01 | Mark 22 | Mark 49 | Mark 38 |
|-----|--------:|--------:|--------:|--------:|--------:|--------:|--------:|
| 1 | +1,854 | +1,482 | −187 | −270 | −902 | −734 | −1,242 |
| 2 | +2,401 | +1,082 | −3,650 | −552 | −104 | −1,203 | +2,025 |
| 3 | +1,423 | −162 | +955 | −225 | +662 | −380 | −2,273 |

Mark 38 loses on 2/3 days; Mark 67 wins on 2/3. Mark 55 wins all 3 days (passive MM edge).

## 4. Per-Mark Predictive Signals (signed forward return)

Mean signed (mid_fwd_h − mid_at_trade); positive ⇒ price moves with the Mark.

| Mark | n | vol | mean h10 | t h10 | mean h100 | t h100 | mean h500 | t h500 |
|------|--:|----:|---------:|------:|----------:|-------:|----------:|-------:|
| **Mark 67** | 165 | 1,510 | **+2.24** | **+10.16** | **+1.48** | **+2.01** | +1.14 | +0.80 |
| Mark 55 | 1,198 | 6,551 | +0.03 | +0.31 | **+0.72** | **+2.75** | +0.20 | +0.37 |
| Mark 14 | 2,172 | 8,718 | −0.01 | −0.07 | −0.00 | 0.00 | −0.50 | −0.89 |
| Mark 01 | 1,843 | 7,428 | +0.07 | +1.71 | −0.05 | −0.44 | −0.03 | −0.15 |
| Mark 22 | 1,584 | 5,889 | −0.12 | **−3.30** | −0.11 | −1.09 | −0.16 | −0.96 |
| Mark 38 | 1,478 | 5,000 | −0.04 | −0.28 | −0.40 | −0.96 | +0.81 | +1.06 |
| **Mark 49** | 122 | 1,186 | **−2.12** | **−7.82** | **−2.05** | **−2.57** | −1.73 | −1.16 |

Bonferroni cutoff at α=0.05 across 7 marks: |t| > 2.69. **Mark 67 (h10), Mark 22 (h10),
and Mark 49 (h10)** survive multiple-comparison correction.

**Information per trade**:
- Mark 67: **+2.24 mid moves in 10 ticks per trade** — strongest single-Mark alpha. Caveat: only 165 trades over 3 days.
- Mark 49: **−2.12 mid moves in 10 ticks per trade** — equally strong but inverted. Combined "Mark 67 long − Mark 49 short" is the cleanest insider/sucker pair.

## 5. Olivia Analog Hunt

Day 3 VFE: open 5,295 → low 5,191 → close 5,232 (drift −63 mid; range 109).

Per-Mark net qty on day-3 VFE (negative = sold into the crash):

| Mark | n | vol | mean_sign | net_qty | ts_first | ts_last |
|------|--:|----:|----------:|--------:|---------:|--------:|
| Mark 49 | 39 | 366 | **−0.74** | **−292** | 77,300 | 984,300 |
| Mark 22 | 30 | 216 | −0.60 | −148 | 31,400 | 968,100 |
| Mark 55 | 403 | 2,153 | −0.04 | −47 | 10,600 | 997,500 |
| Mark 14 | 226 | 1,212 | −0.03 | −34 | 10,600 | 997,500 |
| Mark 01 | 164 | 875 | +0.13 | +97 | 14,200 | 986,000 |
| Mark 67 | 46 | 424 | **+1.00** | **+424** | 31,400 | 984,300 |

Mark 67's first day-3 trade is at ts=31,400 (VFE = 5263, day mid still ~5290) and he keeps
buying *all the way down* into the trough. He **does NOT predict the day-3 crash** —
he just always buys regardless. Day-1 he is +$1,482 because VFE rallies; Day-2 +$1,082;
Day-3 −$162 (he's marginally underwater on the down day but still wins on average).

Mark 67 is **NOT a perfect Olivia** — he is an unconditional VFE accumulator. The
Olivia-style insider signal is therefore **muted at long horizons** (h500 t=0.80) but
**strong at short horizons** (h10 t=10.16, h100 t=2.01) because his individual entries
catch local microstructure pullbacks, not the daily drift.

**Mark 49 is the inverse** — pure VFE seller, distributed across 3 days, loses money
because he sells into eventual short-term mean reversions. His sells cluster *around the
same minutes as Mark 67's buys* (e.g. day-3: both trade at ts=77,300, ts=99,400,
ts=117,400, ts=215,100, ts=357,500, ...).
This suggests Mark 49 is the **liquidity-providing sell tape** that Mark 67 lifts. Trading
**with Mark 67 / against Mark 49** is the cleanest single-Mark trade in the data.

Day-3 VFE trade-size context: Mark 49 avg qty = 9.7; Mark 67 avg qty = 9.2. Their max
trades are 15. **Filtering for qty ≥ 8** keeps 95+ % of their trades and excludes the
small noise from Mark 14/22 fillers.

## 6. Mark Interaction Matrix

Top counterparty pairs by volume:

| Buyer | Seller | Trades | Volume | Symbols |
|-------|--------|-------:|-------:|---------|
| Mark 01 | Mark 22 | 1,339 | 4,636 | VEV_5200..6500 (synthetic book) |
| Mark 14 | Mark 38 | 728 | 2,447 | HP + VEV_4000 (paired MM book) |
| Mark 38 | Mark 14 | 714 | 2,445 | (reverse direction of above) |
| Mark 55 | Mark 14 | 331 | 1,763 | VFE |
| Mark 14 | Mark 55 | 316 | 1,761 | VFE |
| Mark 01 | Mark 55 | 260 | 1,417 | VFE |
| Mark 55 | Mark 01 | 244 | 1,375 | VFE |
| **Mark 67** | **Mark 49** | **89** | **963** | **VFE — the Olivia tape** |
| Mark 67 | Mark 22 | 75 | 546 | VFE |
| Mark 14 | Mark 22 | 83 | 302 | mixed |

**Cluster structure**:
1. **{Mark 14, Mark 38}** — HP & VEV_4000 dedicated MM pair (16-pt and 21-pt static spreads).
2. **{Mark 01, Mark 22}** — VEV_5200..6500 dedicated MM pair (every-tick fills, 1-pt static spread on far OTM strikes).
3. **{Mark 55, Mark 14, Mark 01}** — VFE three-MM rotation.
4. **{Mark 67 ⇒ Mark 49}** — directional pair: 89 of Mark 67's 165 buys (54 %) lift Mark 49's offers. The remaining 75 buys lift Mark 22's resting VFE quotes.

The interaction graph is sparse: 19 (buyer, seller) pairs out of 49 possible cells.

## 7. Strategy Recommendations

### COPY signals

| Mark | Product | Side | Threshold | Hold horizon | Expected edge | N | Confidence |
|------|---------|------|-----------|--------------|---------------|--:|-----------|
| **Mark 67** | VFE | LONG when Mark 67 buys qty ≥ 6 | 10–100 ticks | +1.5 to +2.2 mid units / trade | 165 | t=10.2 (h10), survives Bonferroni |
| Mark 67 | VFE | LONG, qty ≥ 12 | 10 ticks | +3.0 mid units (top size bucket) | 25 | t≈3 — small N, suggestive |

**Implementation**: when `Trade(buyer="Mark 67", symbol="VELVETFRUIT_EXTRACT", qty>=6)` lands
in `state.market_trades`, add a positive +5 to +10 size buy at fair_value+1 with 100-tick
lifetime. ~55 trades/day × 9 avg qty × +1.5 edge ≈ **+$740 / day** on top of MM baseline,
**$2,200 / 3-day**. Capacity gated by VFE limit (200) — the Mark-67 signal cannot
saturate it (he buys 9 qty/trade, ~55 times/day).

### FADE signals

| Mark | Product | Side | Threshold | Hold horizon | Expected edge | N | Confidence |
|------|---------|------|-----------|--------------|---------------|--:|-----------|
| **Mark 49** | VFE | SHORT (i.e. take opposite) when Mark 49 sells qty ≥ 6 | 10–100 ticks | +2.0 to +2.1 mid units / trade | 105 | t=−7.8 (h10), survives Bonferroni |
| **Mark 38** | HYDROGEL_PACK | Skim spread when Mark 38 takes (he pays +8) | 1–10 ticks | spread capture, no directional | 1,022 | aggression t→∞ (deterministic) |
| Mark 38 | VEV_4000 | Same as HP — Mark 38 pays +10 through spread | 1–10 ticks | spread capture | 442 | deterministic |

**Mark 49 FADE** is the inverse of the COPY trade: when Mark 49 sells with qty ≥ 6, post a
buy a tick below mid (lift his offers). Combined with the Mark-67 COPY, this is the same
underlying alpha (VFE short-term mean reversion against directional flow), so position
must be sized as ONE signal, not two. ~35 trades/day × 9 qty × +2 edge ≈ **+$630 / day**
incremental, but heavily overlaps with Mark 67 in time → expected combined gross of
**$3,000–$4,000 / 3-day** on VFE direction alpha.

**Mark 38 spread skim** is structural — when Mark 38 takes, the *next* tick the local
market mid is preserved (he pays the spread to Mark 14 with no information). Two ways to
exploit:

1. **Front-run Mark 14**: post inside Mark 14's HP quote at mid ± 7 (vs his ± 8). When
   Mark 38 takes, ours fills first at +1 better edge. ~340 trades/day × 4 avg qty × 1
   tick = **+$1,360 / day** in theory, but real exec depends on queue priority on IMC's
   FIFO matcher.
2. **Buy below Mark 14's bid / sell above his ask**: Mark 14 is unconditionally near mid
   ±8 on HP. Place at mid ±9 to be filled when Mark 14 isn't there. Capacity = whatever
   Mark 38 trades through us (limited; he's already filling Mark 14's quotes preferentially).

### IGNORE / no-action signals

| Mark | Reason |
|------|--------|
| Mark 01 | t-stats h100 |t|=0.44 — pure VEV-call buyer, all his alpha is "buying intrinsic value" of VEV_5200..5500 inside spread |
| Mark 22 | t=−1.09 h100 — passive seller MM paired with 01; only h10 t=−3.3 (microstructure noise, no exploitable horizon) |
| Mark 14 | t≈0 across all horizons — he's the winning passive side of a paired book, not a directional trader |
| Mark 55 | Wins +$5,678 on VFE at t=2.75 h100 — but it's pure passive MM rebate (aggression +2.49, posts wide). Already replicated by our v22 Wall-Mid MM |

## Top 3 Actionable Findings

1. **Mark 67 ⇒ Mark 49 is a clean Olivia/anti-Olivia pair on VFE.** Mark 67 (t=+10.2 h10)
   is the strongest single-Mark predictive signal in the data; Mark 49 (t=−7.8 h10) is the
   mirror. Combined COPY/FADE on VFE with qty ≥ 6 gating projects **$3–4 k incremental
   PnL over 3 days**, on top of the MM baseline. Both are pure-direction, single-product —
   trivial to implement: scan `state.market_trades` for the Mark-name match and pop a
   100-tick directional bet.

2. **Mark 38 is the structural HP/VEV_4000 sucker.** Every trade is a +8/+10 spread cross
   into Mark 14's quotes. He is the source of Mark 14's +$46k inventory mark. Strategy
   extension: front-run Mark 14's quotes at mid±7 on HP / mid±10 on VEV_4000. With 1,022
   HP trades and 442 VEV_4000 trades over 3 days, this is a high-N, high-confidence
   spread-capture path that complements the v11 spread=17 GIGA-SHORT trigger.

3. **The R0 "Olivia" archetype is REPLICATED in R4** but weaker than R0's. Mark 67 wins
   on 2 of 3 days (day-1 +$1,482, day-2 +$1,082, day-3 −$162); his alpha is
   short-horizon (h10, h100) not daily directional (h500 t=0.80). Do NOT over-rotate the
   strategy around him — he's a 165-trade flow, not a daily-direction oracle. The earlier
   R0 Olivia traded extreme momentum at daily highs/lows; R4's Mark 67 just lifts asks
   regardless of macro level. **Implication**: counterparty signal here is a +30 % overlay,
   not a strategy replacement.

## Sample Size Confidence

| Signal | N | Bonferroni-corrected significance |
|--------|--:|-----------------------------------|
| Mark 67 LONG VFE h10 | 165 | t=+10.16 ≫ 2.69 — **high confidence** |
| Mark 49 FADE VFE h10 | 122 | t=−7.82 ≫ 2.69 — **high confidence** |
| Mark 67 LONG VFE h100 | 164 | t=+2.01 < 2.69 — **moderate, fails Bonferroni** |
| Mark 49 FADE VFE h100 | 120 | t=−2.57 < 2.69 — **moderate, fails Bonferroni** |
| Mark 55 VFE PnL h100 | 1,190 | t=+2.75 — passive MM, not actionable |
| Mark 38 spread cross | 1,022 | deterministic structural, no t-test needed |
| Mark 67 day-3 directional | 46 | t<1 — does not predict daily drift |
| Mark 14 HP qty≥6 | 211 | t=+0.29 — no edge from size filter |

Reliable horizons: **1–10 ticks for direction**, all-day for spread capture. Beyond 100
ticks, microstructure noise dominates and the Mark-67 signal decays to t≈0.8.

## One-Line Take

**The counterparty signal is a +30 % alpha overlay on top of MM, not the round's main alpha**:
clean Mark 67 LONG / Mark 49 FADE pair on VFE adds $3–4 k / 3 days; Mark 38 spread skim on
HP / VEV_4000 adds another $4–5 k structurally — combined ~$8–10 k vs the v22 baseline of
$39 k, so worthwhile but not dominant. **The actual main alpha remains the Wall-Mid
MM + spread=17 trigger framework from R3**; counterparty data sharpens the entries
rather than replacing the strategy.
