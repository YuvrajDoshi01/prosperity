# IMC Prosperity 4 — Tutorial Round: Complete Context Transfer

## Competition Overview
- **IMC Prosperity 4** algorithmic trading competition
- **Tutorial Round** = practice before Round 1 (starts Apr 14, 72h)
- Products: **EMERALDS** (stable, fair=10000) and **TOMATOES** (volatile, drifting)
- Position limit: 80 per product
- Test environment: 1000 iterations / 2000 ticks (timestamps 0–199900, step 100)
- **Final scoring: 10,000 iterations on a DIFFERENT sample day** — overfit risk is real
- AWS Lambda stateless execution, 900ms timeout, traderData 50k char cap
- Supported libs: pandas, numpy, statistics, math, typing, jsonpickle + Python 3.12 stdlib
- Zero latency vs bots, price-time priority, **no PvP** (pure bot-trading)
- Must include `def bid(self): return 15` in Trader class (required for Round 2 auction mechanic, ignored otherwise)

---

## Competition Timeline & Structure

| Phase | Dates | Duration | Notes |
|-------|-------|----------|-------|
| Tutorial Round | Now → Apr 14 | Practice | EMERALDS + TOMATOES |
| **Round 1** | **Apr 14–17** | **72h** | First real products. Resin=EMERALDS, Kelp=TOMATOES + likely new product |
| Round 2 | Apr 17–20 | 72h | New products + `bid()` auction mechanic. Must hit 200K XIRECs to unlock Phase 2 |
| Intermission | Apr 20–24 | 4 days | No trading. Prep for Phase 2 |
| Round 3 | Apr 24–26 | 48h | Rapid-fire. Expect complex products |
| Round 4 | Apr 26–28 | 48h | Derivatives/baskets possible |
| Round 5 | Apr 28–30 | 48h | Final round |

~3h scoring gap between rounds. Last active submission locked at round close.

---

## Exchange Mechanics (Critical Details)

### Execution Model — DETERMINISTIC, NOT STOCHASTIC:
- Your algo trades against **bots only** — no PvP between participants
- Execution is **instantaneous with zero latency** — if your price crosses a bot's quote, you ALWAYS get filled
- No randomness, no partial-fill probability, no latency disadvantage
- Unmatched player quotes sit as resting orders for bots to potentially hit
- If no bot trades your resting order → auto-cancelled at end of iteration
- **Between iterations**: your resting orders cancelled first, THEN bots trade with each other

### Order Matching:
- Standard price-time priority
- Buy orders match at the sell order's price (you get the better price)
- Partial fills possible — remainder stays as resting order

### Position Limits — HARD ENFORCED:
- If aggregate order quantity for one side would breach limit if ALL filled → **ALL orders for that side REJECTED**
- `remaining_buy_capacity = limit - current_position` (if pos=-5, limit=80, can buy 85)
- `remaining_sell_capacity = limit + current_position` (if pos=5, limit=80, can sell 85)
- Position is net long+short, limit on absolute value

### Conversions (for future rounds):
- `conversions` integer returned from `run()` converts existing positions via alternate channel
- Costs: transport fees + import/export tariffs (from conversionObservations)
- Must already hold position, conversion amount ≤ position size
- Arbitrage when: local exchange price diverges from conversion-implied price by more than total fees
- Return 0 if unused

### Observations Data (for future rounds):
- `plainValueObservations`: simple product→value dict
- `conversionObservations`: complex struct with bidPrice, askPrice, transportFees, exportTariff, importTariff, sugarPrice, sunlightIndex
- These are likely **predictive signals** for product prices — build regression/factor models

### Data Pipeline:
- **Sample CSVs** = training set (offline analysis, calibration)
- **Test run** = 1000 iterations on sample day (rapid feedback loop)
- **Final scoring** = 10,000 iterations on DIFFERENT unseen day (out-of-sample)
- Overfitting to sample/test data is the #1 risk

---

## Running Scoreboard — All Versions Tested

| Version | Key Change | PnL | Notes |
|---------|-----------|:---:|-------|
| v1 | EMA + inventory skew MM | 1091 | First attempt, naive |
| v2 | Regression fair (mid) + 2023 winner arch | 2621 | Big jump, regression valuable |
| v3 | v2 bug fixes (best price undercut) | ~2621 | Same architecture, cleaner |
| v4 | jmerle MarketMakingStrategy (round mid) | 2518 | Simpler but worse — no regression |
| v5 | v4 + order book imbalance shift | 2636 | Imbalance helped marginally |
| **v6 / 6913.py** | **Microprice regression + jmerle MM (no liquidation)** | **2644** | **CURRENT BEST — SUBMITTED** |
| v7 | v6 + book depth asymmetry signal | 2375 | Overfit, killed PnL |
| v8a | v6 + relaxed widening (0.5→0.7 threshold) | 2644 | No difference |
| v8b | v6 + no position widening at all | 2644 | No difference |
| v8c | Microprice direct (no regression) | 2518 | Regression worth +126 |
| v8e | Post at fair±1 (mid_wall style) | 609 | **TERRIBLE** — too tight, no edge |
| v9 | Post at best±2 (1 tick tighter than v6) | 2261 | Worse — confirms best±1 is optimal |
| v10 | VWAP mid + regression | 2417 | Worse despite better offline RMSE |
| v10b | VWAP mid (no regression) | 2499 | Worse, very volatile PnL curve |

---

## Best Code: 6913.py (v6 variant, PnL = 2644)

Architecture: Strategy → MarketMakingStrategy OOP with per-symbol state persistence via traderData JSON.

### Core MM Logic (MarketMakingStrategy.act):
1. Compute `true_value` (fair price) from subclass
2. Take all asks ≤ fair (buy), all bids ≥ fair (sell)
3. Post remaining buy at `min(fair, best_bid + 1)` — undercuts best bid, capped at fair
4. Post remaining sell at `max(fair, best_ask - 1)` — undercuts best ask, floored at fair
5. **NO liquidation window** (removed — costs ~7/unit at EMERALDS, rarely needed at 1000 iters)
6. **NO position-dependent widening** (confirmed has zero effect on test day)

### EMERALDS Strategy:
- `true_value = 10000` (hardcoded, rock solid)
- Bot spread: 9992/10008 (16 wide), 96.7% of ticks
- We post at 9993/10007 (inside bots), take at 10000
- **HARD CAPPED at 1050 PnL** — structural ceiling confirmed by multiple Discord sources

### TOMATOES Strategy:
- **Microprice** = `best_bid + (bid_vol / total_vol) * (best_ask - best_bid)`
- Uses total volume across ALL book levels for imbalance weight
- **Linear regression on last 4 microprices** predicts next fair value
- Coefficients: `[0.059694, 0.117270, 0.244154, 0.578440]`, intercept: `2.208667`
- Falls back to `round(microprice)` until 4 values cached
- State persistence: cache of 4 microprices via traderData

### Key Design Decisions:
- Posting at **best±1** is optimal. Tighter (±0, mid_wall) kills edge. Wider loses priority.
- Taking at/below fair with NO position-dependent threshold tightening
- All remaining budget posted as single resting order per side

---

## 2644 Run Detailed Analysis (from 6913.log / 6913.json)

### PnL Split:
- **TOMATOES: 1594** (60.3%)
- **EMERALDS: 1050** (39.7%) — at structural cap
- **TOTAL: 2644**

### Trade Statistics:
- TOMATOES: 38 buys (135 lots, avg 4984.7) / 32 sells (109 lots, avg 4996.5) — **11.8 edge/lot**
- EMERALDS: 41 buys (266 lots, avg 9998.2) / 47 sells (304 lots, avg 10001.9) — **3.7 edge/lot**
- ~70 TOMATOES round-trips over 2000 ticks (once every ~29 ticks)
- End position: TOMATOES +26, EMERALDS -38

### PnL Curve Milestones:
```
  0% t=     0: TOM=   0    EM=   0    TOT=    0
 20% t= 39900: TOM= 341    EM= 252   TOT=  593
 50% t= 99900: TOM= 661    EM= 686   TOT= 1347
 80% t=159900: TOM=1019    EM= 917   TOT= 1936
100% t=199900: TOM=1594    EM=1050   TOT= 2644
```
- Last 20% of day generated 36% of TOMATOES PnL (drift + MTM on end position)
- PnL curve is smooth and monotonically increasing — no major drawdowns

---

## Data Analysis Findings

### EMERALDS — Fully Optimized, No More Alpha
- Fair = 10000 (std=0.72 across 20k observations, both days)
- Bot spread 9992/10008, 16 wide, 96.7% of time
- Occasionally tightens to 8-wide (bid or ask at 10000), ~3.3% of ticks
- Mean run length at same price: 115.5 ticks (very stable)
- **1050 PnL is the structural ceiling** — confirmed by Discord community

### TOMATOES — All Remaining Alpha is Here
- Mid price drifts ~90 ticks/day, strong mean reversion (lag-1 autocorr = -0.43)
- Bot spread: 13-14 normally, tightens to 5-9 about 7.2% of time
- L3 book only present 4% of ticks
- 86.4% of ticks have quote changes (very active)
- Mean bid run length: 3.9 ticks (highly dynamic)

### Signal Rankings (TOMATOES, correlation with next-tick return):
1. **Microprice-mid**: +0.56 ← used in v6 via regression ✓
2. **Volume ratio** (total imbalance): +0.53 ← captured by microprice ✓
3. **VWAP(all levels) deviation**: -0.45 (mean reverting) — tested, FAILED in live (v10/v10b)
4. **Momentum(1)**: -0.42 ← captured by regression ✓
5. **Bid levels - ask levels**: -0.63 — overfit, v7 failed

### Fair Value Estimator Quality (RMSE predicting next mid):
| Estimator | Day -2 RMSE | Day -1 RMSE | Notes |
|-----------|:-----------:|:-----------:|-------|
| Simple mid | 1.345 | 1.337 | Baseline |
| EMA(10) mid | 1.261 | 1.284 | Slow to adapt |
| Microprice (L1 imbalance) | 1.174 | 1.173 | Raw, no regression |
| Mid + regression(4) | 1.173 | 1.179 | 6% worse than microprice reg |
| **Microprice + regression(4)** | **~1.11** | **~1.11** | **Used in v6, +126 PnL. Cross-val RMSE=1.11 both ways** |
| VWAP mid (all levels) | 1.054 | 1.053 | **Best offline** but FAILED live (-145 PnL) |
| VWAP + regression(4) | 1.048 | 1.048 | FAILED live (-227 PnL) |

### Why VWAP Failed Despite Better RMSE:
VWAP uses L2 prices (5-8 ticks from touch) weighted by volume. When L2 has asymmetric heavy volume, VWAP gets dragged far from the touch, causing the strategy to post orders too aggressively in one direction. Microprice only uses L1 prices with volume weights — more responsive to what matters for the next fill. The regression's temporal smoothing (4-tick lookback) also damps whipsaws that VWAP amplifies.

**Key lesson: offline RMSE ≠ live PnL. What matters is not getting adversely selected on the tails.**

---

## What Worked ✓

1. **Microprice as fair value signal** — uses order book imbalance at L1, captures both volume and price information. MAE 0.70 vs simple mid's 0.79.
2. **Regression on last 4 microprices** — adds +126 PnL over raw microprice. Temporal smoothing prevents whipsaw. Cross-validated: train day-2/test day-1 RMSE=1.1174, reverse RMSE=1.1092 (robust, not overfit).
3. **Posting at best±1** — optimal priority vs edge tradeoff. Verified by testing ±0 (609), ±2 (2261)
4. **No liquidation window** — at 1000 iters, getting stuck at limit is rare; liquidation costs more than it saves
5. **jmerle OOP architecture** — clean Strategy/MarketMakingStrategy pattern with per-symbol state persistence
6. **EMERALDS = 10000 fixed** — zero complexity, captures full 1050 structural cap
7. **Order book imbalance shift** (v5) — marginal +118 over v4 baseline, but subsumed by microprice in v6

## What Didn't Work ✗

1. **VWAP mid** (v10/v10b) — better offline RMSE but worse live PnL (-145 to -227). L2 prices mislead
2. **Book depth asymmetry** (v7) — overfit signal, killed PnL (-269)
3. **Mid wall posting** (v8e, post at fair±0/±1) — too tight, no spread edge, PnL = 609
4. **Tighter posting** (v9, best±2) — loses priority, -383 vs v6
5. **Position-dependent spread widening** — confirmed zero effect on test day (v8a, v8b identical to v6)
6. **Liquidation window** — costs ~7/unit on EMERALDS liquidation trades, marginal benefit
7. **2023 winner's position layering** (v2/v3) — complex but no better than simple v6 approach
8. **EMA fair value** (v1) — slow to adapt, regression much better
9. **Popular price undercutting** (jmerle original) — fails when L2 has more volume than L1 (our data)
10. **Imbalance-based fair shift with large k** — mostly rounds to zero in normal spread regime

## What We Didn't Try / Remaining Ideas

1. **Directional overlay on TOMATOES** — microprice predicts 5-tick returns at 0.45 correlation. Could lean quotes directionally when signal is strong (shift buy/sell quantities, not just fair value). This is likely how fabiantum gets 3900 TOMATOES PnL.
2. **Aggressive taking during tight spreads** — TOMATOES spread tightens to 5-9 about 7.2% of time. Could detect and increase taking aggressiveness during these windows.
3. **Late-day trend exploitation** — TOMATOES has a "slow bleed" pattern around t=75K+ (per Discord intel from fabiantum). Could bias position short later in the day.
4. **Dynamic regression coefficients** — currently fixed from offline fit. Could refit on rolling window from traderData history.
5. **Fill rate optimization** — our 70 round-trips vs potentially 200+ for top scorers suggests we're leaving fills on the table.
6. **Separate taking threshold from posting threshold** — currently both use same `true_value`. Could take more aggressively than we post.
7. **"0 risk aversion"** (ishaanthenerd's hint) — implies no position-dependent behavior at all, just pure aggressive MM. Our v6 already doesn't widen, but maybe could take AT fair regardless of position.
8. **Dual-layer quoting** — post orders at TWO price levels: aggressive (best±1) AND passive (fair±1). Captures fills from both bot types.
9. **Variable position limits** — valentinz got 2.6k with effective limit 15-20 (not 80). Smaller limits = faster inventory turnover = more spread capture per unit time. Worth testing effective_limit = 40 or 20.
10. **Asymmetric spread based on signal** — when microprice bullish: tighter bid (buy more aggressively), wider ask. When bearish: wider bid, tighter ask. Leans inventory toward predicted direction.

---

## Discord Intel — Verified Scores & Strategies

| Player | Total | EMERALDS | TOMATOES | Method |
|--------|:-----:|:--------:|:--------:|--------|
| fabiantum | ~4950 | 1050 | 3900 | "predictive signals within MM", "dynamic fair value" |
| ishaanthenerd | 4700 | 1050 | ~3650 | "0 risk aversion", "thresholds to miss mid less" |
| johnny3779 | 3400 | ? | ? | "think its overfit by a little" |
| geyzsonkristoffer | 3300 | ? | ? | admits may be overfit |
| .a2ra3l | 2926 | ? | ? | |
| htdeck | 2900 | ? | ? | "without overfit", "Kelp=TOMATOES, Resin=EMERALDS" |
| pokerface911 | 2900 | ? | ? | "hit a plateau" |
| penfo | 2679 | 1050 | 1629 | |
| **OUR BEST** | **2644** | **1050** | **1594** | **microprice regression + jmerle MM** |
| advoltex | 2600 | ? | ? | "tighten spread" per Claude |
| valentinz | 2600 | 1050 | ~1550 | "mid_wall, limit 15-20" |
| oatalicious | 2500 | 1100+ | 1400 | |
| joe_goldberg26 | 2500 | 1050 | 1450 | |
| guseppy89 | 2400 | 1050 | ? | "max without overfit ~2.2k" (later improved) |
| BASELINE cluster | 2518 | 1050 | 1468 | simple mid-based MM (11+ strategies hit this) |

### Key Strategic Implications:
1. **Our 2644 = 1050 EMERALDS + 1594 TOMATOES** — we're +126 above baseline on TOMATOES
2. **fabiantum's 3900 TOMATOES = +2432 above baseline** — massive alpha exists in fair value
3. **2518 is the "default" score** — 11 different Claude-generated strategies all hit exactly 2518
4. **Non-overfit ceiling is likely 2.6-2.9k** per community consensus. Above needs real signals.
5. **fabiantum contradicts himself**: says >3.5k is overfit but claims 3.9k TOMATOES. Either his "predictive signals" are genuinely non-overfit, or he's trolling.
6. fabiantum asked "are you using a static fair value?" — strongly implying **dynamic fair value is the key differentiator**
7. ishaanthenerd's "0 risk aversion" + "thresholds to miss mid less" = no position-dependent widening (which we already don't do) + possibly taking at fair unconditionally
8. advoltex asked "do bots always do market orders?" — if yes, tighter posting doesn't help. His subsequent tightening improved score, suggesting **bots DO care about price** (they use limit orders)
9. **The "slow bleed around 75k timestamp"**: fabiantum responded "find the alpha" — suggesting the bleed IS the signal for directional trading

---

## Market Microstructure Details

### Bot Behavior:
- **EMERALDS**: Single market maker, 9992/10008 spread, 96.7% of time. Volumes: L1 ~12.5, L2 ~24.8. Occasionally widens or tightens. Quotes persist ~115 ticks on average.
- **TOMATOES**: More active, 86.4% of ticks have quote changes. Normal spread 13-14. L1 vol ~7.4, L2 vol ~19.6. Quotes persist ~3.9 ticks. Spread occasionally tightens to 5-9 (7.2% of time).
- **Bots use limit orders, not just market orders** — confirmed by advoltex's experiment where tightening spread improved fills. They care about price.

### Trade Statistics (market trades, not ours):
- TOMATOES: ~420 trades/day, ~1400 lots, avg qty 3.5, total |price movement| ~1550 in 2k ticks
- EMERALDS: ~200 trades/day, ~1100 lots, avg qty 5.5
- Large trades (qty ≥ 8): only EMERALDS, at 9992 or 10008 — probably an "Olivia" bot

### Key Price Properties:
- TOMATOES mid: mean ~5000 (varies by day), std 10-15, range ~50-90 per day
- EMERALDS mid: mean 10000.00, std 0.72, range [9996, 10004]
- TOMATOES net trade flow: negative (more selling), correlates with downward drift

---

## Reference Algorithms Studied

### A. 2023 Prosperity Winner (Stanford team)
- Used for v2-v3 architecture inspiration
- Key techniques: position-dependent aggression, undercutting, regression fair value, multiple order layers
- Products: PEARLS (=EMERALDS, fair=10000), BANANAS (=TOMATOES, regression-predicted fair)
- Regression on mid prices with dim=4 lookback

### B. jmerle (9th place, Prosperity 3, all 5 rounds)
- Used for v4-v6+ architecture (our current base)
- MarketMakingStrategy with liquidation window, soft/hard liquidation, position-dependent aggression
- Clean OOP with Strategy/MarketMakingStrategy/SignalStrategy pattern
- Products mapped: Amethysts=EMERALDS (fair=10000), Starfruit=TOMATOES (fair=round(mid))
- Also had strategies for: Orchids (conversion arbitrage), Gift Basket (stat arb), Coconut Coupon (Black-Scholes options)
- These later-round strategies are templates for Round 2+ products

---

## Technical Infrastructure

### Code Architecture (6913.py):
```
Strategy (base)
  ├── buy(price, qty), sell(price, qty)
  ├── save() → serializable state
  ├── load(data) → restore state
  └── run(state) → List[Order]

MarketMakingStrategy(Strategy)
  ├── get_true_value(state) → int  [abstract]
  └── act(state)  [core MM logic]

EmeraldsStrategy(MarketMakingStrategy)
  └── get_true_value → 10000

TomatoesStrategy(MarketMakingStrategy)
  ├── compute_microprice(od) → float
  ├── get_true_value → regression prediction or microprice fallback
  ├── cache: List[float]  (last 4 microprices)
  └── save/load: cache via traderData

Trader
  ├── strategies: Dict[str, Strategy]
  ├── bid() → 15
  └── run(state) → orders, conversions, traderData
```

### State Persistence:
- `traderData` JSON with per-symbol state
- TOMATOES: cache of last 4 microprice values
- EMERALDS: no state needed (fixed fair)
- Separators `(",",":")` to minimize traderData size

### Backtester Results (offline, 10K ticks, both days):
```
Strategy               day_-2  day_-1  total  consistency  est_2k
EMA fair + skew         6382    5834   12216     0.91      1221
Regression mid + under 15299   14456   29755     0.94      2975
jmerle base + mid      15424   14359   29784     0.93      2978
Imbalance + regression 15266   13790   29056     0.90      2905
Microprice regression  15703   13976   29679     0.89      2967
```
Note: `est_website_2k = total / 10` approximates the 2000-tick website score.

---

## Round 1 Preparation

### Known Mapping:
- **Resin = EMERALDS** equivalent (stable, fixed fair value)
- **Kelp = TOMATOES** equivalent (drifting, volatile)
- Likely adds a **3rd harder product** (conversion/pairs trade?)

### Infrastructure Ready:
- Modular architecture: just add `class NewProductStrategy(MarketMakingStrategy)`
- Regression coefficients need **refitting on new sample data** (different price levels/dynamics)
- Core MM logic (take + post at best±1) is product-agnostic
- traderData pattern handles multi-product state

### Key Risks:
- Regression coefficients overfit to tutorial round price dynamics
- 10K iteration scoring vs our 1000 iteration testing — strategy must be robust to longer runs
- New products may have different bot behavior (wider/tighter spreads, more levels)
- Position limits may differ per product

---

## Files Reference

| File | Description |
|------|-------------|
| `6913.py` | **BEST CODE** — actual 2644 submission |
| `6913.log` / `6913.json` | Full 2000-tick log of 2644 run |
| `prices_round_0_day_{-1,-2}.csv` | Sample price/book data (semicolon delimited) |
| `trades_round_0_day_{-1,-2}.csv` | Sample market trade data |
| `round0_analysis_executed.ipynb` | Jupyter notebook with full data analysis |
| `IMC_Prosperity_-_Text_channels_-_*.csv` | Discord intel dumps |
| `trader_v{1-10b}.py` | All version variants (in /home/claude/) |

---

## Strategic Framework for Round 1+

### Strategy Modules to Deploy Per Product Type:

**A. Stable Products (Resin/EMERALDS-type):**
- Fixed fair value market making
- Quote inside bot spread at best±1, take at/below fair
- Inventory is essentially risk-free since fair doesn't move
- Expect ~1050 PnL cap, focus effort elsewhere

**B. Volatile Products (Kelp/TOMATOES-type):**
- Dynamic fair value (microprice regression or similar)
- Key: the fair value estimator IS the alpha. Better estimator = more PnL
- Post at best±1, take at/below fair value
- Regression coefficients must be refit from new sample data each round
- Mean reversion is strong (autocorr ~ -0.4) — exploit in fair value calc

**C. Conversion Arbitrage (expected in Round 2+):**
- Calculate effective conversion cost: `askPrice + transportFees + importTariff` (buy via conversion) vs `bidPrice - transportFees - exportTariff` (sell via conversion)
- If local exchange price diverges from conversion-implied price by more than total fees → arbitrage
- Build position on exchange, convert to lock in risk-free profit

**D. Cross-Product / Statistical Arbitrage (expected in Round 3+):**
- Look for economically linked product pairs/baskets
- Track spread between related products, trade when it deviates from historical norms
- `plainValueObservations` may provide exogenous signals (sunlightIndex, sugarPrice) that predict prices
- Build regression models on sample data for these signals

### Key Edges to Exploit:
1. **Zero latency = guaranteed fills** when you cross bot quotes. Aggressively take mispriced liquidity.
2. **Bots are predictable** — use sample data + market_trades to reverse-engineer their behavior
3. **No PvP = no speed arms race** — edge is purely signal quality + position management
4. **Resting orders are free options** — post at attractive prices, profit if bot hits, no cost if not
5. **Observations data** (sunlight, sugar, humidity) are likely predictive signals — build factor models
6. **Deterministic execution** means your backtester can be exact — no need to model fill probability

### Round-by-Round Tactical Plan:
1. **Round 1 (72h)**: Analyze sample CSVs immediately. Deploy MM + microprice regression for Kelp. Lock in Resin at fixed fair. Look for 3rd product patterns.
2. **Round 2 (72h)**: Implement `bid()` auction mechanic. Watch for conversion arb. Hit 200K XIRECs milestone.
3. **Intermission (4 days)**: Deep post-mortem on R1/R2 logs. Refine models. Build multi-product arb framework.
4. **Rounds 3-5 (48h each)**: Rapid deployment. Pre-built modular infrastructure wins here. Expect derivatives, baskets, exotic conversions.

### Critical First-Hour Checklist for Round 1:
1. Download sample CSVs immediately
2. Run price analysis: compute mid stats, spread distribution, autocorrelation, bot patterns
3. Identify product types (stable vs volatile vs linked)
4. Fit regression coefficients on new data
5. Deploy v6 architecture with new product names + refitted params
6. Submit and iterate from live feedback
