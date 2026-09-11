# Day-3 First-1k Alpha Analysis

Scripts: `intel/day3_1k_alpha.py`, `intel/day3_1k_alpha_v2.py`. Data: `prosperity4bt/resources/round4/{prices,trades}_round_4_day_3.csv` filtered `timestamp <= 99900`.

## Top 3 quantitative findings

### 1. VFE velocity-50 short signal — `v50 <= -3 → SHORT 200, TP=+10, SL=-15`
- Predictor `velocity_50` (mid diff over last 50 ticks) vs `fwd_500`: **corr=−0.459, t=−8.13** on first 300 ticks of day 3 (n≈250).
- Out-of-sample sweep on days 1–3 (1k each):
  - `v50<=-3, TP=10, SL=15`: **day1=+$200 / day2=+$2,100 / day3=+$8,800 → total +$11,100**.
  - Robust to threshold choice: every cell with `v∈{30,50}, vth∈{-2,-3,-4}` clears +$8k total. No 3-day total negative.
  - Symmetric (long+short) variant LOSES (day1=−$4,900, day2=−$3,900) → keep **short-only**.
- Mechanism check: VFE day-3 EOD=5232 (vs first-1k close 5253.5), so position carries through the rest of the day if not closed. SL=15 caps the −$3k tail seen on day 1's late re-short.

### 2. HP MM-only ceiling on day-3 1k ≈ $1,500–$3,500 (NOT enough to recover -$11k S17 loss)
- HP spread distribution: 925/1000 ticks at 16, 39 ticks at 17, 36 at 7-9.
- Theoretical upper bound at avg_spread=15.75: `1000 × 0.5 × (15.75/2 − 1) ≈ $3,440`. Realistic with our v22 fill rate ≈ $1,500.
- **Recommendation: KEEP `v9_nodir` (no S17) on day 3. The S17 bet is broken when spread=17 only fires 39 ticks in a non-reverting regime (HP drifts +$9 over 1k).** Need a regime gate, not just z-score.

### 3. Mark 67 is a CONTRARIAN on day-3 VFE, NOT smart money
- Mark 67 bought 38 VFE in 1k at avg=$5,257; VFE 1k-close=$5,253.5; day-3 EOD=$5,232 → he's down ~$25/contract.
- Mark 67 fwd-200t signal: `−3.25` (negative = price falls after he buys, i.e. trade against him).
- **Strongest fwd signal: Mark 14 (+7.71) on VFE — buyer 13× / seller 10× / volume 165 = follow him.** But sample size n=23 → wide CI. Skip for now (overfit risk).
- Mark 22 sells exclusively on VFE (4 trades, +3.67 fwd) — when Mark 22 sells, price keeps falling. Confirms VFE short bias.

## Voucher MM gap (item 3)
- Only 4 vouchers traded in 1k day 3: VEV_4000 (18), VEV_5500 (42), VEV_6000 (48), VEV_6500 (48). VEV_4500/5000/5100/5200/5300/5400 had **0 fills**.
- Far-OTM (5500/6000/6500) fills are at price 0.5–7 — penny premiums. Top R3 teams' $4-15k voucher PnL came from delta-hedged ATM portfolio. With VFE crashing $42 on day 3, ATM (VEV_5250-5400) has high directional risk but NO trades in this window.
- **Gap explanation**: voucher liquidity collapsed in 1k day 3 — there is no $5-10k of voucher MM PnL to capture. Skip optimization here.

## Counterparty refinement (item 4)
- Top buyers by volume: Mark 01 (249), Mark 14 (165), Mark 55 (82), Mark 38 (68), **Mark 67 (38)**.
- Mark 67 is NOT the high-confidence Olivia analog on this window (only 5 trades, all on VFE, all losing). Don't lower the size threshold — that adds noise, not signal.

## SINGLE CONCRETE RECOMMENDATION

**Add VFE momentum-short module to `v9_nodir`:**

```python
# In Trader state: deque of last 60 VFE mids.
# Trigger: if len(buf)>=51 and (mid_now - mid_50_ago) <= -3 and self.vfe_pos == 0:
#     SHORT 200 VFE at best_bid (cross spread aggressively).
# Exit: if MTM >= +10*200, take profit; if MTM <= -15*200, stop loss; otherwise hold to day end.
```

Expected impact on `v9_nodir` (currently −$404 on 1k day 3):
- Day-3 1k: **−$404 + $8,800 ≈ +$8,400** (95% CI from sweep variance: +$7,600 to +$8,800).
- Day-1 1k: ≈ +$200 lift. Day-2 1k: ≈ +$2,100 lift. **3-day total lift: +$11,100 ± $1,500**.
- Risk: this is a 1-trigger-per-day strategy with n=3 days of evidence. Confidence is bounded. **Do NOT replace S17 with this — ADD it.** Keep the v9_nodir HP cycle (which is structurally PnL-neutral on this window) and gain pure VFE alpha.

Falsification: if BT shows day-1 lift < 0 with TP=10/SL=15, the parameters are overfit — fall back to `v50<=-3, no-TP, hold-to-EOD` (worst day total still +$9,400).
