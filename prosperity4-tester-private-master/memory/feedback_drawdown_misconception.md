---
name: Drawdown is entry-cost, not a bug to eliminate
description: Feedback from 2026-04-17 session — MTM drawdowns on drift/trend trades are the cost of early entry, not a problem to solve. Eliminating them usually LOSES money.
type: feedback
originSessionId: 955e9ff4-5728-4069-8882-3e961751886f
---
When a strategy captures drift (monotonic price trend), the initial MTM drawdown is **structural and required**. It represents the cost of entering before the rally begins.

**Why:** On a drift product, prices only rise. To buy, we must cross the spread (take ask at MM's price = mid + half-spread). At t=0 with mid=X, ask=X+7, we pay X+7 and see MTM = -7 per unit = drawdown. As price drifts up to X+100 by end of day, the drawdown resolves into profit.

**What fails:**
- Posting passive bids below the ask to "wait for cheaper sellers" — **no cheaper sellers exist** during the early window (MM only offers at ask, no taker sells)
- Delayed entry — by the time the drawdown period ends, mid has risen. We pay the same or more for the same position
- Partial entry — smaller position means smaller drift capture, linearly scaled

**Evidence from 2026-04-17 session:**
- r1_medallion (WITH -519 drawdown): IPR 7,377, total 10,468
- r1_hybrid (NO drawdown, waited): IPR 7,016, total 10,107
- **Eliminating the drawdown cost -361 PnL**

**How to apply:**
- Don't try to "fix" drawdowns on drift/trend products
- A drawdown with +10% realized PnL by EoD = correct trade, not a problem
- The counterintuitive winning move is to BUY EARLY AT THE ASK during the drawdown window
- User's frustration with this was valid — the answer genuinely is "drawdown ≠ problem"
- Only worry about drawdowns when realized PnL < 0 at end of day

**When drawdowns ARE a problem:**
- Mean-reverting products (no drift) — no structural recovery mechanism
- End-of-day unrealized loss that won't resolve
- Drawdowns caused by bad fills (e.g., we posted wrong side and got adversely selected)
