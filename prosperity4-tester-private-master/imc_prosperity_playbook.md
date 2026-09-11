# IMC Prosperity: Complete Playbook from Winning Teams (P1–P4)

**The top teams across three editions of IMC Prosperity share a surprisingly consistent playbook: simple, principled strategies outperform complex models every time.** Across 30,000+ competing teams, the winners relied on robust fair-value estimation, disciplined position management, and deep understanding of bot behavior — not machine learning or exotic math. The gap between a top-100 and top-10 finish comes down to mechanical understanding of how the simulation engine processes orders, how PnL is scored against a hidden fair value, and how specific bots can be exploited through careful experimentation.

This document consolidates code-level implementation details from the GitHub repos of 2nd-place finishers (Stanford Cardinal in P1, Linear Utility in P2, Frankfurt Hedgehogs in P2 and P3), 9th-place finisher jmerle (P2), Alpha Animals (9th, P3), CMU Physics (7th, P3), pe049395 (13th, P2), Martin Oravec (73rd, P3), Matius Chong, and multiple other public writeups.

The most impactful findings: Olivia detection relied on a **quantity=15 filter at running min/max extremes**, basket arbitrage succeeded with a **z-score threshold of 7 on a 45-tick rolling window**, Black-Scholes implementations universally used **r=0** with `statistics.NormalDist` instead of scipy, and the matching engine's **sequential processing order** (not FIFO) created exploitable asymmetries that backtesting could never fully replicate.

---

## Table of Contents

1. [Competition Structure & Product Archetypes](#1-competition-structure--product-archetypes)
2. [The Matching Engine: How Orders Are Actually Processed](#2-the-matching-engine-how-orders-are-actually-processed)
3. [PnL Scoring: The Hidden Fair Value](#3-pnl-scoring-the-hidden-fair-value)
4. [The "Wall Mid" Insight](#4-the-wall-mid-insight)
5. [The `run()` API and Conversion Mechanics](#5-the-run-api-and-conversion-mechanics)
6. [Bot Archetypes & Behavior](#6-bot-archetypes--behavior)
7. [Olivia Detection & Copy-Trading (Detailed)](#7-olivia-detection--copy-trading-detailed)
8. [Fair Value Formulas by Product Type](#8-fair-value-formulas-by-product-type)
9. [Basket Arbitrage: Exact Formulas & the Z-Score Trick](#9-basket-arbitrage-exact-formulas--the-z-score-trick)
10. [Options Pricing: Black-Scholes & the Volatility Smile](#10-options-pricing-black-scholes--the-volatility-smile)
11. [Cross-Exchange Arbitrage & the Hidden Taker Bot](#11-cross-exchange-arbitrage--the-hidden-taker-bot)
12. [Cross-Product Signals](#12-cross-product-signals)
13. [Position Management](#13-position-management)
14. [traderData Persistence & State Management](#14-traderdata-persistence--state-management)
15. [Code Architecture: The Monolithic Trader Pattern](#15-code-architecture-the-monolithic-trader-pattern)
16. [Parameter Optimization & Anti-Overfitting](#16-parameter-optimization--anti-overfitting)
17. [Backtester vs. Website Discrepancies](#17-backtester-vs-website-discrepancies)
18. [Defensive Coding & Lambda Survival](#18-defensive-coding--lambda-survival)
19. [Custom Tooling & Community Toolkit](#19-custom-tooling--community-toolkit)
20. [Manual Rounds](#20-manual-rounds)
21. [Story Tips: Reliability & Traps](#21-story-tips-reliability--traps)
22. [Score Ceilings & Per-Product PnL Benchmarks](#22-score-ceilings--per-product-pnl-benchmarks)
23. [The Prosperity 2 Data-Reuse Exploit](#23-the-prosperity-2-data-reuse-exploit)
24. [Mathematical Frameworks: Simple Models Beat Complex Ones](#24-mathematical-frameworks-simple-models-beat-complex-ones)
25. [Prosperity 4: What to Expect](#25-prosperity-4-what-to-expect)
26. [Key Repositories & Resources](#26-key-repositories--resources)

---

## 1. Competition Structure & Product Archetypes

The competition's structure has remained remarkably stable since 2023, with each edition featuring the same five product archetypes: a fixed-price asset, a random-walk asset, ETF baskets, options, and cross-exchange arbitrage. Teams who studied prior years' open-source code had a decisive advantage.

| Round | P1 (2023) | P2 (2024) | P3 (2025) | Core Strategy |
|-------|-----------|-----------|-----------|---------------|
| 1 | Pearls (10k), Bananas | Amethysts (10k), Starfruit | Resin (10k), Kelp, Squid Ink | Market making around fair value |
| 2 | Coconuts / Piña Coladas | — | Picnic Baskets 1 & 2 | Pair trading / stat arb on ETF spread |
| 3 | Berries, Diving Gear | Gift Basket + components | Volcanic Rock Vouchers (5 strikes) | Signal-driven / basket arb / options pricing |
| 4 | Picnic Basket + components | Orchids (cross-exchange) | Magnificent Macarons | Cross-exchange location arbitrage |
| 5 | Bot IDs revealed | Coconut Coupons + bot IDs | Bot IDs revealed | Black-Scholes options + copy-trading Olivia |

**Round 1 (Market Making)** is the foundation. Top teams implemented market-taking (aggressively hitting mispriced quotes) and market-making (posting passive quotes around fair value) simultaneously. Position clearing — executing zero-EV trades purely to bring inventory back toward zero — boosted PnL by roughly **3%** according to Linear Utility's measurements.

**Rounds 2–3 (Baskets and Options)** introduced the biggest PnL opportunities. For basket products, the core trade is always the same: compute a synthetic fair value as the weighted sum of components, measure the spread between basket market price and synthetic, and trade mean-reversion when the spread exceeds a threshold. Frankfurt Hedgehogs enhanced this with Olivia's inferred position — dynamically biasing entry thresholds based on whether the insider bot was long or short on constituent products, earning **40,000–60,000 SeaShells per round** on baskets alone.

For options (Coconut Coupons in P2, Volcanic Rock Vouchers in P3), **Black-Scholes pricing** was the universal framework. Multiple teams confirmed that simple BS with implied-volatility mean-reversion outperformed more sophisticated binomial or stochastic-vol models.

**Round 4 (Cross-Exchange Arbitrage)** involved products tradeable on both a local and foreign exchange, with shipping costs, tariffs, and conversion limits. The edge came from a **hidden taker bot** that would aggressively fill sell orders at prices slightly above the best bid, executing ~60% of eligible trades.

**Round 5 (Trader IDs)** revealed counterparty identities, confirming what sharp teams had already deduced: a bot named **"Olivia"** consistently bought exactly 15 lots at daily minimums and sold 15 at daily maximums. Copy-trading her signals was the simplest high-value strategy in the competition.

Each round's evaluation runs across **multiple simulation days** (typically 3), each containing **~10,000 timestamps at 100ms intervals**. Scores are cumulative across all 5 rounds, combining algorithmic and manual trading PnL. Positions reset between simulation days.

---

## 2. The Matching Engine: How Orders Are Actually Processed

The Prosperity matching engine operates fundamentally differently from a real exchange. **All previous orders are wiped at each timestep.** There is no persistent order book and therefore no queue position to maintain.

Within each timestep, the simulation clears all previous orders, then sequentially processes participants in a fixed sequence, confirmed by the Frankfurt Hedgehogs: **"First some deep-liquidity makers, then occasionally some takers, then our own bot's actions (take or make), followed by other bots — usually more takers."**

**Speed is irrelevant** — every participant sees the same order book snapshot and can submit any combination of orders. The player's position in the sequence (after initial makers but before most takers) creates a specific dynamic: passive orders posted by the player can be hit by taker bots that act later in the same timestep.

The official documentation states the critical rule: when a player submits a buy or sell order with quantity larger than the matching counterparty, **"the remaining quantity will be left as an outstanding quote with which the trading bots will then potentially trade."** This means player limit orders posted inside the spread can and do get filled by subsequent taker bots within the same timestep.

**The answer to the key strategy question is yes**: if you post a bid at best_bid+5 (inside the spread), taker bots that process after you in the sequence **will** hit your order if it represents the best available price. Linear Utility's backtester explicitly models this: "If there was a trade between bots at a price worse than our own quotes, we'd attribute the trade to ourselves."

However, **community backtesters cannot replicate this**. jmerle's backtester operates on static historical replay, matching player orders against recorded order depths first, then against that timestamp's market trades. It offers three matching modes:

- `--match-trades all` (default): all market trades can fill your orders
- `--match-trades worse`: only trades at prices worse than your quotes count (inspired by Linear Utility)
- `--match-trades none`

Critically, market trades in the backtester fill at **your order's price**, not the trade price — a sell order at 9 fills at 9 even if a buyer exists at 10.

**Position limits are enforced pre-matching with an independent buy/sell check**: the engine verifies that `position + total_buy_quantity ≤ limit` AND `position - total_sell_quantity ≥ -limit` before matching ANY orders. If either condition fails, **all orders for that product are cancelled** — both buys and sells. This worst-case check assumes every order fills simultaneously, meaning you must size conservatively. This is a trap that catches unprepared teams repeatedly.

The practical implication: **for strategies that depend on getting filled by bots (market making, taker exploitation), only the official Prosperity website gives accurate results**. For strategies that mainly take liquidity, the backtester is sufficient.

---

## 3. PnL Scoring: The Hidden Fair Value

This is arguably the most important mechanical detail in the competition. **PnL is mark-to-market against a hidden internal "fair value" — not the visible mid price or last trade price.**

Linear Utility confirmed this empirically: "When we tested our algorithm on the website, we figured out that the website was marking our PnL to the market maker's mid instead of the actual mid price. We verified this by backtesting an algorithm that bought 1 starfruit and held it — our PnL graph marked to market maker mid exactly replicated the PnL graph on the website."

The scoring formula:

```
PnL = sum(cash flows from all trades) + (current_position × hidden_fair_value)
```

For Orchids specifically, a storage cost of `0.1 × |long_position|` was deducted per timestamp. There is **no explicit liquidation penalty** at end-of-day, but positions are marked to the hidden fair value, so holding large positions introduces variance.

Any local backtester using the visible mid price for mark-to-market would systematically diverge from official scoring.

---

## 4. The "Wall Mid" Insight

The single most important technical discovery shared across all top-performing teams is deceptively simple. IMC's simulation always includes a **deep-liquidity market-maker bot** quoting large sizes on both sides of the order book. The midpoint of these "wall" quotes — dubbed the **"Wall Mid"** — tracks the hidden fair value that IMC uses for PnL calculation far more accurately than the raw mid-price.

Linear Utility (2nd place, P2) described it clearly: "At all times, there was a market making bot quoting relatively large sizes on both sides, at prices unaffected by smaller participants. Using this market maker's mid price as fair turned out to be much less noisy."

pe049395 (13th, P2) independently confirmed: "Both bid and ask sides consistently had one level with significantly large quantities. The average of these two prices closely resembled the hidden fair value."

This insight matters because PnL is marked against IMC's hidden fair value, not the visible mid-price. Teams using raw mid-price as their fair value estimate were systematically biased, while teams using Wall Mid consistently quoted tighter, more accurate spreads. **Every 2nd-place team across all three editions used this technique.**

jmerle's implementation for extracting Wall Mid:

```python
popular_buy_price = max(buy_orders, key=lambda tup: tup[1])[0]   # highest volume bid
popular_sell_price = min(sell_orders, key=lambda tup: tup[1])[0]  # highest volume ask (note: sell qtys are negative)
true_value = round((popular_buy_price + popular_sell_price) / 2)
```

pe049395 tried microprice (`best_bid × ask_vol + best_ask × bid_vol) / (bid_vol + ask_vol)`) but found it noisier than the wall-level mid.

---

## 5. The `run()` API and Conversion Mechanics

### The run() method

The `run()` method evolved across editions. In Prosperity 1, it returned only `Dict[str, List[Order]]`. Starting in Prosperity 2, the signature became a 3-tuple:

```python
def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
    result = {}       # symbol → list of Orders
    conversions = 0   # integer: positive = import, negative = export
    traderData = ""   # string persisted to next call
    return result, conversions, traderData
```

### Conversion mechanics

`conversions` is a **single integer**, not a per-product dictionary. A positive value imports (buys from the foreign exchange at its `askPrice` plus `importTariff` plus `transportFees`). A negative value exports (sells at the foreign `bidPrice` minus `exportTariff` minus `transportFees`). The conversion executes at the **next timestamp** — you request it this tick, it settles next tick.

**Only specific products have conversions**, and tutorial/Round 0 products never do:

- Amethysts (P2, pegged at 10,000), Pearls (P1), and Rainforest Resin (P3) had **no** conversion mechanism
- Conversions were introduced for **Orchids in Prosperity 2 Round 2** and **Magnificent Macarons in Prosperity 3 Round 4**

The conversion data arrives via `state.observations.conversionObservations['PRODUCT']`, a `ConversionObservation` object with fields: `bidPrice`, `askPrice`, `transportFees`, `importTariff`, `exportTariff`, `sunlight`, and `humidity`. All fees are dynamic, changing each timestep. Orchids additionally carried a **0.1 SeaShells/unit/tick storage cost** for net long positions. Macarons had a **hard conversion limit of 10 units per timestep** (position limit 75).

### Implied price formulas

From Linear Utility's code:

```python
implied_bid = obs.bidPrice - obs.exportTariff - obs.transportFees - 0.1  # storage
implied_ask = obs.askPrice + obs.importTariff + obs.transportFees
```

---

## 6. Bot Archetypes & Behavior

Understanding the simulation's mechanics separates top-10% teams from winners. Four distinct bot archetypes appear consistently:

### Wall Makers
Quote large sizes on both sides, providing the Wall Mid signal. They don't react to player orders. They process first in the sequential pipeline.

### Olivia (the insider)
Trades at daily extremes with quantity 15. She has appeared in every edition since P1:
- P1: Olivia on Ukuleles/Berries
- P2: Rhianna on Roses; Vladimir/Remy on Chocolate
- P3: Olivia on Squid Ink/Croissants

Detection method: track daily running min/max; flag trades occurring at extremes in the expected direction with quantity=15.

### Hidden taker bots
Aggressively fill orders at specific conditions. These bots appear nowhere in the visible order book — they manifest only as fills on player orders that meet specific conditions:
- **Orchids (P2):** Only buy-side (hitting player sells), filling at ~100% rate at full position size
- **Macarons (P3):** Fill ~60% of eligible trades at `int(externalBid + 0.5)`. Separate volume-based trigger: if best bid volume > 9, a sell at best ask was guaranteed to be bought
- **Rainforest Resin (P3):** Bots that crossed the true 10,000 price, buying above and selling below

### Small noise traders
Place orders at unusual prices, creating apparent mispricings. Using Wall Mid filters these out.

Frankfurt Hedgehogs built a **fallback system**: if bot behavior changed (as it did after IMC's Round 3 patch in P3), their algorithm automatically reverted from hardcoded strategies to robust statistical approaches. This dual-mode architecture is a best practice for future competitions.

---

## 7. Olivia Detection & Copy-Trading (Detailed)

### Anonymous detection (Rounds 1–4)

Frankfurt Hedgehogs (2nd place, P3) discovered that Olivia consistently traded in **lots of exactly 15** at daily extremes on Squid Ink and Croissants. Their detection logic:

```python
daily_min, daily_max = float('inf'), float('-inf')
olivia_signal = "NEUTRAL"

for each timestamp:
    current_mid = (best_bid + best_ask) / 2
    daily_min = min(daily_min, current_mid)
    daily_max = max(daily_max, current_mid)
    
    for trade in market_trades:
        if trade.quantity == 15:  # Olivia's signature lot size
            if trade.price <= daily_min and trade.is_buy:
                olivia_signal = "LONG"
            elif trade.price >= daily_max and trade.is_sell:
                olivia_signal = "SHORT"
    
    # Invalidation: new extrema contradicting signal
    if olivia_signal == "LONG" and current_mid < previous_signal_price:
        olivia_signal = "NEUTRAL"
```

Alpha Animals (9th place, P3) used a more data-driven approach: they calculated the percentage of "good trades" (buying before price increases, selling before drops) for every anonymous trader over rolling windows, then flagged traders with hit rates significantly above chance.

CMU Physics (7th place, P3) independently spotted the quantity=15 pattern in Round 2 but didn't build a reliable strategy until Round 5 when IDs were revealed.

### Named detection (Round 5)

Simply checking `trade.buyer == "Olivia"` or `trade.seller == "Olivia"`. Frankfurt Hedgehogs reported this eliminated false positives and saved "a few hundred SeaShells" per round compared to anonymous detection.

### Cross-product amplification

This was the real unlock. Frankfurt Hedgehogs used Olivia's inferred position on Croissants to dynamically bias basket spread thresholds — shifting long entry from **-50 to -80** and short entry from **+50 to +20** when Olivia was detected as short. This cross-product adjustment generated **40,000–60,000 SeaShells per round** on baskets alone.

CMU Physics went further, leveraging Olivia's Croissant signal to take maximum effective positions of **1,050 Croissants** (250 direct + 800 through basket positions), achieving **120,000 SeaShells** on their best day versus 50,000 from basket arbitrage alone.

Stanford Cardinal (2nd place, P1) summarized it simply: "We realized Olivia bought at the lowest point and sold at the highest point, so we used her exclusively to trade Ukuleles."

---

## 8. Fair Value Formulas by Product Type

### Stable products (Pearls, Amethysts, Rainforest Resin)

Hardcoded at **10,000**. No estimation needed. The entire challenge is optimizing market-making around this known price. Buy anything below 10,000, sell anything above, and quote around the fixed value with a configurable spread. Frankfurt Hedgehogs earned a consistent **~39,000 SeaShells per round** on Rainforest Resin alone. Linear Utility's backtesting showed **~16,000/day** with an additional 3% from position clearing.

### Slow random-walk products (Bananas, Starfruit, Kelp)

The winning formula is the **Wall Mid** — not a simple mid-price calculation, but the average of the two highest-volume price levels on each side of the book. See Section 4 for jmerle's implementation.

Alternative approaches tried:
- **Microprice** (pe049395): `(best_bid × ask_vol + best_ask × bid_vol) / (bid_vol + ask_vol)` — found noisier than Wall Mid
- **Simple moving average with window 8** (Matius Chong) for Kelp
- **Z-score reversion** (Martin Oravec, 73rd, P3): 10-tick rolling window on mid, only skewing quotes when |z| > 1, with spread set to `max(floor, rolling_std_dev)`
- **Linear regression on 5–10 recent prices** — multiple teams used this for fair value estimation

### Volatile mean-reverting products (Squid Ink)

No single formula dominated:
- **Alpha Animals (9th, P3):** Detected price movements exceeding **3 standard deviations from a 10-timestamp moving window** and traded the reversal
- **Matius Chong:** EMA-based z-scores: `z = (EMA_short - EMA_long) / StdDev_long`, entering when z crossed fixed thresholds
- **Frankfurt Hedgehogs:** Abandoned quantitative approaches entirely for Squid Ink, instead copy-trading Olivia who consistently bought at daily minimums and sold at daily maximums

Martin Oravec's z-score mean reversion on Squid Ink "worked decently on the backtester" but "lost money after the first round" — a cautionary tale about volatile products.

---

## 9. Basket Arbitrage: Exact Formulas & the Z-Score Trick

### Composition ratios

Explicitly defined by the competition:

- **P1:** `PICNIC_BASKET = 1×UKULELE + 4×DIP + 2×BAGUETTE` (premium ≈ **375**)
- **P2:** `GIFT_BASKET = 4×CHOCOLATE + 6×STRAWBERRIES + 1×ROSES` (premium ≈ **379.5**)
- **P3:** `PICNIC_BASKET1 = 6×CROISSANTS + 3×JAMS + 1×DJEMBES`; `PICNIC_BASKET2 = 4×CROISSANTS + 2×JAMS`

The spread calculation was universal: `spread = basket_mid - Σ(weight_i × component_i_mid)`. This spread oscillated around a stable mean with mean-reverting behavior.

### Linear Utility's parameters (the z-score trick)

The most important implementation detail — a z-score approach with hardcoded mean and tiny rolling standard deviation window:

```python
PARAMS = {
    Product.SPREAD: {
        "default_spread_mean": 379.50439988484239,
        "default_spread_std": 76.07966,
        "spread_std_window": 45,        # Very small rolling window
        "zscore_threshold": 7,           # Appears extreme but works
        "target_position": 58,           # Near 60-unit limit
    },
}
```

The z-score threshold of **7** appears absurdly high, but the key innovation was the **45-tick rolling standard deviation window**. This tiny window caused local volatility to compress during quiet periods, making the z-score spike precisely when spreads began reverting — effectively timing entries near local extrema. With a hardcoded mean of **379.50** (the fundamental premium level), the strategy avoided the noise of estimating mean on limited data. This generated approximately **135,000 SeaShells per day** in backtests.

### Frankfurt Hedgehogs' approach

Fixed thresholds with light grid search, prioritizing "landscape stability over pure performance peaks." Their critical insight was reasoning from the **data-generating process**: constituent prices were independently randomized, then mean-reverting noise was added to produce basket prices. This meant baskets revert to synthetic value but components do NOT respond to baskets — so hedging with components reduced expected value. They traded baskets only, using components purely as signals.

### Hedging: avoid it

**Most successful teams avoided hedging with components.** Pe049395 (13th place, P2) traded only GIFT_BASKET to reduce transaction costs. Jmerle (9th place, P2) attempted trading individual components alongside baskets but lost **36,000 SeaShells on ROSES** from overfitting — a cautionary tale. The exception was CMU Physics, who strategically used baskets as leverage for Olivia's Croissant signal, accepting the basket spread risk.

---

## 10. Options Pricing: Black-Scholes & the Volatility Smile

Options products appeared in P2 (COCONUT_COUPON) and P3 (VOLCANIC_ROCK_VOUCHER). Every successful team used the same core insight: **risk-free rate = 0**, and implied volatility was the real trading signal.

### Linear Utility's exact implementation (P2)

```python
from math import log, sqrt
from statistics import NormalDist

class BlackScholes:
    @staticmethod
    def black_scholes_call(spot, strike, time_to_expiry, volatility):
        d1 = (log(spot/strike) + 0.5 * volatility**2 * time_to_expiry) / \
             (volatility * sqrt(time_to_expiry))
        d2 = d1 - volatility * sqrt(time_to_expiry)
        return spot * NormalDist().cdf(d1) - strike * NormalDist().cdf(d2)
```

Two critical implementation details:
1. Using `statistics.NormalDist().cdf()` instead of `scipy.stats.norm.cdf()` — **scipy was unavailable** in the competition environment
2. Completely omitting the `exp(-rT)` discount factor (r=0)

Their parameters: **strike=10,000**, **time-to-expiry=247/250 years**, **mean IV ≈ 0.1596 (16%)**, **delta ≈ 0.53**. The strategy was mean-reversion on implied volatility around 16%, with a threshold of **0.00163** for trading the mispricing. Delta hedging was theoretically incomplete — 600 coupons × 0.53 delta required 318 coconuts, but the position limit was 300.

### Prosperity 3's multi-strike volatility smile

Five vouchers at strikes 9500–10500 introduced the volatility smile. Frankfurt Hedgehogs fit a **quadratic parabola** across strikes:

```
fitted_IV(m_t) = a · m_t² + b · m_t + c
```

where `m_t = log(spot/strike)` is time-scaled moneyness. They computed IV from market mid prices for each voucher, fit the quadratic smile across all five strikes, then traded deviations between the fitted "fair" IV and actual market IV — "IV scalping."

Crucially, they did **not** delta-hedge traditionally, finding that "explicit delta hedging would have been prohibitively expensive given bid-ask spreads" — roughly **40,000+ SeaShells per day** in spread costs alone.

### CMU Physics' critical discovery

The quadratic smile fit **broke down on submission days**, severely over- or underestimating actual IV. Switching to a **short rolling mean of mid IV per strike** instead of the quadratic fit jumped their PnL from **80,000 to 200,000 per day** in backtests.

### Martin Oravec's blended approach (73rd, P3)

Combined the global quadratic curve with a per-strike rolling IV average (window=150), trading on a z-score defined as `deviation / (std_IV × vega)` with ±1 entry bands. Used delta and vega for risk control.

---

## 11. Cross-Exchange Arbitrage & the Hidden Taker Bot

Cross-exchange products (Orchids in P2, Macarons in P3) were tradeable on both a local and foreign exchange, with shipping costs, tariffs, and conversion limits.

### The Orchids arbitrage loop (P2)

Linear Utility (2nd, P2) discovered the killer strategy: sell Orchids locally at `foreign_ask_price - 2`, then convert (import from the foreign exchange) to close the short position next tick. The local market contained a hidden taker bot that filled sell orders aggressively, while foreign exchange prices were consistently cheaper.

jmerle (9th, P2) refined this: "The trick was to continuously short sell to the limit at a price at which you could immediately convert profitably back to 0 in the next iteration... you can convert your position to 0 and then immediately go short again in the same iteration." This generated **~109,000 SeaShells** from Orchids alone.

### The hidden taker bots (detailed)

**Orchids (P2):** Linear Utility discovered "a massive taker in the local orchids market. Sell orders — and just sell orders — just a bit above the best bids would be instantly taken for full size." Only buy-side (hitting player sells), filling at **~100% rate** at full position size. This enabled the local-sell + foreign-import arbitrage loop generating 500k+ SeaShells projected over a full day.

**Macarons (P3):** Frankfurt Hedgehogs found the evolved version: "offers priced at about `int(externalBid + 0.5)` would often get filled, even when no visible orderbook participants were present." This taker only filled **~60%** of eligible trades — a deliberate reduction from P2's near-certainty. Matius Chong identified a separate volume-based trigger: **"if best bid volume > 9 on the local exchange, a sell order placed at the best ask price was guaranteed to be bought."**

How teams discovered it: "best asks occasionally priced close to best bid consistently getting filled was a clear signal" in historical data. Teams who studied P2 writeups had a structural edge because similar smart-taker behavior had appeared in Orchids.

### PnL benchmarks for cross-exchange

**Macarons** (conversion arbitrage): theoretical ceiling **130,000–160,000/round**, top teams achieved **80,000–100,000/round** — the single highest-PnL product across all archetypes.

---

## 12. Cross-Product Signals

Beyond the notorious data-reuse exploit, legitimate cross-product signals fell into three narrow categories.

### Basket-component relationships (strongest)

Basket prices mean-reverted to their synthetic values computed from components, providing the core basket arbitrage signal. Frankfurt Hedgehogs' key insight was directional: components led baskets, not the reverse, because the data-generating process randomized components independently and added noise to create basket prices.

### External data → product signals

- **P1:** The rate of change of DOLPHIN_SIGHTINGS (a non-tradeable observable) predicted DIVING_GEAR price movements, with buy signals at derivative ≥ +0.002 and sell at ≤ -0.002
- **P3:** The Sunlight Index affected Macarons pricing, though Frankfurt Hedgehogs found pure arbitrage outperformed their logistic regression model using sunlight features (coefficient -2.0517, p-value 0.0000)

### Cross-product Olivia signals

Frankfurt Hedgehogs used Olivia's Croissant trades to bias basket spread thresholds — a cross-product signal flowing from a single component to the ETF-level trading parameters. See Section 7 for details.

### The negative result

Alpha Animals explicitly confirmed: "We spent considerable time modeling price movements of virtually every product to find correlations, seasonality, or other patterns. Despite extensive analysis, many of these efforts didn't yield actionable strategies." No team found profitable signals between genuinely unrelated products.

---

## 13. Position Management

Position management follows four increasingly aggressive tiers:

### Tier 1: Position-aware sizing
Ensures orders never exceed remaining capacity:
```python
to_buy = limit - position
to_sell = limit + position
```

### Tier 2: Inventory skewing
Adjusts prices based on exposure. jmerle only buys below fair value when position exceeds 50% of limit.

### Tier 3: Zero-EV clearing
Linear Utility's innovation — executes at-fair-value trades just to reduce position, accepting 0 expected profit to free capacity for future profitable trades. Boosted PnL by **~3%**. This compounds across thousands of timesteps and 15 products.

### Tier 4: Soft/hard liquidation
Uses a rolling 10-tick window tracking whether position is at the limit; if stuck at limit for ≥50% of the window, aggressively flatten at slight losses.

### The critical independent buy/sell check

The engine verifies that `position + total_buy_quantity ≤ limit` AND `position - total_sell_quantity ≥ -limit` before matching ANY orders. If either condition fails, **all orders for that product are cancelled** — both buys and sells. This worst-case check assumes every order fills simultaneously, meaning you must size conservatively.

---

## 14. traderData Persistence & State Management

The `traderData` string persists **within a single simulation day only** — each new day starts with an empty string. There is no documented hard character limit on the string itself, though jmerle's logger allocates `max_log_length = 3750` characters split three ways for visualization purposes.

### Serialization approaches

Teams keep data compact using:
- `json.dumps(data, separators=(",", ":"))` to eliminate whitespace
- `jsonpickle.encode()` for convenience at the cost of size (most common among top teams because it serializes complex Python objects including custom classes)

### What to store

Top teams store: rolling price windows (deques of recent mids), EMA values, position-at-limit tracking (boolean windows for liquidation triggers), strategy thresholds (e.g., initial prices for directional trades), and bot detection state (running min/max for insider trader identification).

### Deserialization pattern

jmerle's pattern is cleanest — each Strategy class implements `save()` and `load()` methods, with the Trader class aggregating them into a single JSON dict keyed by symbol.

In Prosperity 1, before `traderData` existed, teams used instance variables directly — but these were lost on Lambda restarts, causing issues Stanford Cardinal documented as "Lambda error bugs."

---

## 15. Code Architecture: The Monolithic Trader Pattern

The competition mandated a single `class Trader` with a `run(self, state: TradingState)` method. A consistent architecture emerged across top teams.

**No team used separate Strategy classes or inheritance hierarchies.** The universal pattern was a monolithic Trader with:

1. A `Product` enum/class with string constants
2. A `self.params` dictionary enabling parameterized instantiation for grid search
3. Conditional routing per product via `if Product.X in state.order_depths`
4. Separate private methods per strategy type (not per product)

### Linear Utility's architecture

```python
class Trader:
    def __init__(self, params=None):
        self.params = params or DEFAULT_PARAMS  # Enables grid search
    
    def run(self, state: TradingState):
        traderObject = {}
        if state.traderData and state.traderData != "":
            traderObject = jsonpickle.decode(state.traderData)
        
        result = {}
        # Product routing via conditional blocks
        if Product.AMETHYSTS in self.params and Product.AMETHYSTS in state.order_depths:
            result[Product.AMETHYSTS] = self.trade_amethysts(state)
        
        # Basket products handled together in one method
        spread_orders, traderObject[Product.SPREAD] = self.trade_spread(state, ...)
        
        traderData = jsonpickle.encode(traderObject)
        return result, conversions, traderData
```

### The Logger compression class

A critical infrastructure piece, independently developed by multiple teams and widely adopted. It truncated log output to stay within the **3,750-character limit** that, if exceeded, caused Lambda timeout errors — the single most common cause of submission failures.

```python
self.max_log_length = 3750  # IMC's strict limit
max_item_length = (self.max_log_length - base_length) // 3
# Truncate traderData, new_trader_data, and logs equally
```

---

## 16. Parameter Optimization & Anti-Overfitting

With only approximately 3 days of historical data per round, overfitting was the dominant failure mode.

### Frankfurt Hedgehogs' "landscape stability" principle

The most influential anti-overfitting approach: "Rather than picking the best parameter set based on maximum backtested profit, we chose combinations that showed consistent, flat regions of good performance." They used fixed thresholds with light grid search, rejecting any strategy that couldn't be justified from first principles. Their rule: "If you can't explain why a strategy should work from first principles, then any 'outperformance' in historical data is probably noise."

### pe049395's Monte Carlo data augmentation (13th, P2)

The most technically sophisticated approach. They generated synthetic market data by perturbing historical data — adding noise, shifting price levels, varying spread distributions — then optimized parameters across both original and synthetic datasets. This tested whether strategies were robust to data variations rather than fitted to specific samples.

### Linear Utility's parameterized grid search

By accepting a `params` dictionary in the constructor, they could iterate over parameter combinations programmatically. For Round 5, jmerle ran **3,600 backtests** in a single grid search to find counterparty trading signals.

### Community optimization tools

**prosperity3opt** offered Optuna-based multi-objective optimization (NSGA-II for simultaneous PnL/Sharpe/drawdown optimization) with built-in overfitting protections including trial limits of 50–80 for multi-objective runs.

### Parameter selection discipline

Choose values in **flat regions** of backtested performance grids rather than peak-performing parameters, maximizing robustness over in-sample returns.

### Three-tier backtesting (best practice)

1. Quick vectorized backtests in Jupyter for prototyping
2. jmerle's backtester for systematic parameter sweeps
3. Official website submission for final validation

Frankfurt Hedgehogs specifically noted: "If a strategy mainly depended on bot interactions, we backtested using the official Prosperity website; if it mainly involved taking or simple quoting logic, we used Jasper's open-source backtester."

---

## 17. Backtester vs. Website Discrepancies

Score discrepancies between local backtesting and official website submissions were a persistent source of frustration, with several well-documented causes.

### Cause 1: Hidden fair value marking

PnL was marked to a hidden fair value, not the observable mid price. Any local backtester using the visible mid price for mark-to-market would systematically diverge. (See Section 3.)

### Cause 2: Non-modelable bot behavior

Frankfurt Hedgehogs noted that jmerle's backtester "cannot fully replicate the subtle nuances of bot behavior, simply because that behavior was not fully observable." Specific gaps included taker bot timing for products like Macarons, conversion mechanics, and fill probability estimation for passive orders.

### Cause 3: New data generation

New data was generated for each scoring run, meaning historical backtests could only approximate live conditions.

### Specific failure cases

- Martin Oravec's z-score mean reversion on Squid Ink "worked decently on the backtester" but "lost money after the first round"
- jmerle's component trading on Roses produced a 36,000-SeaShell loss despite positive backtests
- Volatile products (Squid Ink, Macarons) showed the largest backtester-to-website divergence
- Stable products (Amethysts, Rainforest Resin) tracked closely

---

## 18. Defensive Coding & Lambda Survival

When a Trader's `run()` method throws an exception or times out, the tick is skipped — no orders are placed. The Trader instance persists (instance variables survive), and `traderData` from the last successful run carries forward. A single bad tick doesn't kill the algorithm, but losing ticks at critical moments (like when Olivia signals) can cost thousands of SeaShells.

### The #1 cause of runtime failures

**Log output exceeding Lambda's size limit.** Alpha Animals reported being "unable to visualize later runs from AWS Lambda errors" due to verbose logging.

### Essential defensive patterns

- `state.position.get(product, 0)` for missing positions (products not yet traded have no position entry)
- `if product in state.order_depths` before accessing order data
- `if state.traderData and state.traderData != ""` before deserialization
- Fallback system that automatically reverts to non-hardcoded strategies if bot behavior changes (Frankfurt Hedgehogs' insurance against mid-competition environment shifts)

---

## 19. Custom Tooling & Community Toolkit

### jmerle's tool suite (community standard)

The backbone of the Prosperity ecosystem, spanning all four editions:
- **Backtesters:** `prosperity2bt`, `prosperity3bt` via pip (P3 repo: 107 stars, 45 forks)
- **Browser-based visualizers:** Walk through execution timestamp by timestamp
- **CLI submitters**
- **Alternative leaderboard viewers** with detailed score breakdowns

### Custom tools from top teams

- **Linear Utility:** Custom Dash/Plotly dashboard with **synchronized timestamp navigation** across all charts and order book depth displays
- **Frankfurt Hedgehogs:** Scatter-plot order book visualizations optimized for Prosperity's 1–4 price level structure, with trade filtering by trader type (Maker/Small taker/Big taker/Informed/Own), dynamic downsampling, and normalized price views
- **Alpha Animals:** Research Jupyter notebooks alongside trading code

### Community-built tools

- **Max Bo's Observable notebook:** Interactive P2 sandbox visualizer (later adapted by LorR for P3)
- **prosperity3opt:** Optuna-based hyperparameter optimization with multi-objective support (NSGA-II for simultaneous PnL/Sharpe/drawdown optimization)
- **kevin-fu1:** OOP rewrite of jmerle's backtester for P4
- **Noah1921:** Maintained shared spreadsheets for manual trading expeditions on the Prosperity Discord

### Standard toolkit checklist

- jmerle's backtester (available for P1/P2/P3; installable via `pip install prosperity3bt`)
- jmerle's visualizer (web-based)
- jmerle's alternative leaderboard
- Custom grid-search frameworks for parameter optimization
- Monte Carlo data augmentation (pe049395) to avoid overfitting on limited historical data

### Critical caveat

The open-source backtester cannot simulate taker bot behavior or conversion mechanics perfectly. Top teams used the backtester for most products but validated bot-interaction-dependent strategies through IMC's official submission system.

jmerle noted that publishing open-source tools "got people in a helpful mood, leading to useful strategy hints being shared" — a community dynamic where tool-builders gained strategic intelligence in return.

---

## 20. Manual Rounds

Manual trading contributes roughly **5–15% of total score** for top teams, but a separate **$5,000 "Best Manual Trader" prize** exists starting from P3. Five challenge types recur across editions:

### Currency/FX arbitrage (P2 R2, P3 R1)
Given exchange rate matrices, find the optimal ≤5-trade conversion path. Solved by brute-force graph search. Maximum profit typically ~8.9%.

### Two-price bidding optimization (P2 R1, P3 R3)
Maximize expected value buying from sellers with uniformly distributed reserve prices. P2's optimal solution was bids at 952 and 978, derived analytically.

### Game theory crowding (P2 R3–R4, P3 R2 and R4)
Choose containers/suitcases with multiplied rewards divided among all players selecting the same option. Requires modeling other players' behavior — contrarian picks consistently outperform headline-grabbing high multipliers.

### News-based portfolio allocation (P1 R4, P2 R5, P3 R5)
Read fictional newspaper articles, allocate capital across ~10 assets. Fee-aware sizing is critical — the optimal formula from Stanford Cardinal (2nd, P1) is `y = 2.5x/6` where x is expected percentage move.

Frankfurt Hedgehogs' manual strategy was explicitly conservative: "Our approach was more about playing it safe, rather than taking risks" — accepting lower expected returns for lower variance across game theory rounds.

### Manual round scores

- Frankfurt Hedgehogs scored **126,751** (optimal was 194,522) on P3's manual round
- jmerle scored **115,000** (optimal 157,000) on P2's manual round

---

## 21. Story Tips: Reliability & Traps

Each Prosperity edition wrapped products in narrative with character tips. The pattern was consistent: **story elements accurately described product mechanics** (e.g., "this product behaves like an option," "this basket contains these components") but **directional tips in manual rounds were unreliable**.

### The Red Flags trap (P3)

The most dramatic example. The narrative described a company with "operations in ruins" and uncertain reprinting timelines — suggesting a sell. Most teams sold. **The product surged +50.9%**, making it the largest trap in P3's news round. Frankfurt Hedgehogs scored only 126,751 versus an optimal 194,522, primarily because they underestimated Red Flags.

### Products where tips aligned with outcomes
- Quantum Coffee: health concerns → **-66.8%** actual
- Cacti Needle: public blame narrative → **-41.2%**
- VR Monocle: surging usage → **+22.4%**

### Products where tips misled
- Haystacks: expected +12% based on P2's "Sleddit" analogy, actual **-0.48%**
- Solar Panels: expected -30% based on P1's "fishing rods," actual only **-8.9%**

### Algorithmic story signals

Occasionally contained real signals:
- P1's Dolphin Sightings were a genuine leading indicator for Diving Gear prices
- P3's Sunlight Index legitimately affected Macarons pricing

The winning approach: treat narrative as a hint about where to look — then validate everything quantitatively. The data always trumped the story.

---

## 22. Score Ceilings & Per-Product PnL Benchmarks

### Final scores from documented top teams

- **Linear Utility:** 3,501,647 SeaShells (2nd place, P2) — includes multi-million-SeaShell profits from the data-reuse exploit in Rounds 4–5
- **Frankfurt Hedgehogs:** 1,433,876 SeaShells (2nd place, P3) — no comparable exploit

### Per-product breakdowns (Frankfurt Hedgehogs, P3)

| Product | Strategy | PnL per Round |
|---------|----------|---------------|
| Macarons | Conversion arbitrage | 80,000–100,000 (ceiling: 130,000–160,000) |
| Baskets | Arb + Olivia adjustment | 40,000–60,000 |
| Croissants | Olivia signal | ~20,000 |
| Rainforest Resin | Stable market-making | ~39,000 |
| Squid Ink | Olivia following | ~8,000 |

### PnL from specific strategies

- **Orchids (P2):** ~109,000 SeaShells from conversion arbitrage alone (jmerle)
- **Baskets with CMU Physics' max Olivia leverage:** 120,000 SeaShells on best day
- **Amethysts (P2):** ~16,000/day baseline market-making (Linear Utility)
- **Basket arb (P2):** ~135,000/day in backtests (Linear Utility's z-score approach)

The stable product served as a reliable baseline — differentiation came entirely from complex products.

---

## 23. The Prosperity 2 Data-Reuse Exploit

The single largest edge in any Prosperity edition came from a meta-game discovery, not an algorithmic innovation. In Prosperity 2, **price paths for coconuts and other products were near-exact copies of Prosperity 1 data**, scaled by constant multipliers.

Linear Utility (2nd, P2) found that Diving Gear returns from 2023 predicted ROSES returns in 2024 with **R² = 0.99** (multiplier ~3×), and Coconut prices in P1 predicted Coconut prices in P2 with beta = 1.25.

Armed with effectively perfect future price knowledge, top teams implemented **dynamic programming algorithms** that optimized position trajectories accounting for spread crossing costs, available volume, and position limits. This exploit generated millions of SeaShells in rounds 4–5 and was the primary differentiator among the top 4 teams.

Jasper Merle (9th, P2) concluded: "The trick to getting multi-million profits in rounds 4-5 was exploiting coconut data being a near-exact match with Prosperity 1."

### IMC's response

In Prosperity 3, bot behavior was initially **>95% identical to P2** in rounds 1–2 (enabling hardcoding exploits), but Frankfurt Hedgehogs responsibly reported this to IMC. The organizers then **patched bot behavior from Round 3 onward**, banned hardcoding, and reran earlier rounds.

The lesson for Prosperity 4 participants: IMC now actively monitors for historical data exploitation and introduces non-deterministic elements into bot behavior.

---

## 24. Mathematical Frameworks: Simple Models Beat Complex Ones

Despite the quant-heavy participant pool, **no winning team used Avellaneda-Stoikov, complex microstructure models, or machine learning**. pe049395 (13th, P2) explicitly tested Ornstein-Uhlenbeck process-based market making and Poisson distribution execution probability models — neither outperformed simpler approaches.

### The winning mathematical toolkit

| Framework | Application |
|-----------|-------------|
| Expected utility per trade: `(profit + inventory_risk_adjustment) × execution_probability` | Grid-searched over parameters |
| Black-Scholes with r=0 | Options pricing with IV curve fitting (quadratic in moneyness) |
| Z-score pair trading | Fixed mean, rolling std dev for basket spreads |
| Linear regression on 5–10 recent prices | Random-walk fair value estimation |
| Dynamic programming | Optimal position trajectory (when future prices known/strongly predicted) |

### Philosophy from top teams

- **Frankfurt Hedgehogs:** "If you can't explain why a strategy should work from first principles, then any outperformance in historical data is probably noise."
- **Stanford Cardinal (2nd, P1):** "Our main ideas were to be rigorous about not overfitting."
- **Kevin (6th place, later hired by IMC):** "We were brainstorming about machine learning, but in the end, we used something pretty simple. Get the foundation right first."

The teams placing 1st through 5th consistently chose the simplest strategy that could capture each product's primary inefficiency, then invested their remaining effort in robust parameter selection, custom tooling, and fallback systems.

---

## 25. Prosperity 4: What to Expect

### Timeline & format

- Registration opened **March 16, 2026**
- Tutorial round running until **April 13**
- Full competition (Rounds 1–5): **April 14–30** (first round launches April 14)
- Theme: **outer space** ("A trading challenge of cosmic proportions")
- Currency: **XIRECs**
- Prize pool: **$50,000** ($25K first place), winner crowned "IMC Global Trading Talent of the Year"
- Teams of up to 5 STEM university students, 15 days across 5 algorithmic + manual rounds
- **Notable new rule:** Top 10 finishers from any previous Prosperity are removed from rankings

### Expected product archetypes

Based on three years of structural consistency:

- **Round 0 (Tutorial):** One stable product (pegged ~10,000) and one volatile product (random walk)
- **Round 1:** Market making around fair value
- **Round 2:** ETF/basket instruments
- **Round 3:** Options/derivatives
- **Round 4:** Cross-exchange arbitrage with conversions
- **Round 5:** Trader ID reveal

Names will be space-themed. No P4-specific product names have been publicly revealed yet.

### What's changed

IMC has **progressively hardened bot behavior** — P3's mid-competition patches signal that P4 bots will likely include non-deterministic elements from the start. The hardcoding exploit from P3 is likely prevented from the start.

### Available P4 tools

A community backtester already exists (kevin-fu1/imc-prosperity-4-backtester), though jmerle's definitive version hasn't been released yet. The QuantNet forums show active teammate recruitment.

---

## 26. Key Repositories & Resources

### Top team repositories

| Team | Placement | Repository |
|------|-----------|-----------|
| Frankfurt Hedgehogs | 2nd, P2 & P3 | `github.com/TimoDiehm/imc-prosperity-3` — most detailed write-up, full polished code |
| Linear Utility | 2nd, P2 | `github.com/ericcccsliu/imc-prosperity-2` — custom backtester, grid-search framework |
| Stanford Cardinal | 2nd, P1 | `github.com/ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal` — foundational strategies |
| Alpha Animals | 9th, P3 | `github.com/CarterT27/imc-prosperity-3` — research notebooks, systematic bot identification |

### Community infrastructure

| Tool | Link |
|------|------|
| jmerle's P3 backtester | `github.com/jmerle/imc-prosperity-3-backtester` (install: `pip install prosperity3bt`) |
| jmerle's visualizer | Web-based, timestamp-by-timestamp execution walkthrough |
| P4 community backtester | `github.com/kevin-fu1/imc-prosperity-4-backtester` |
| prosperity3opt | Optuna-based hyperparameter optimization |

### Preparation advice from top finishers

Frankfurt Hedgehogs published their full P3 code with a pointed message: "This repo won't help you win, but it will help you understand why you didn't."

Alpha Animals confirmed the meta explicitly: "This year's Prosperity was very similar to the last two years, and we were able to successfully adapt and build upon previous winning open-source strategies."

### Three novel insights from three years of analysis

1. **Preparation is asymmetrically rewarded** — teams who studied all prior write-ups before Round 1 had a 2–3 round head start on teams discovering patterns from scratch
2. **Position management is alpha** — the 3% PnL boost from position clearing and zero-EV inventory neutralization compounds across thousands of timesteps and 15 products
3. **The meta-game matters** — IMC actively evolves bot behavior in response to published exploits, meaning P4's winners will likely be the teams who identify *new* behavioral patterns rather than replaying known ones

The most actionable P4 preparation: build visualization tools, pre-code strategy templates for each archetype (market making, basket arb, options, cross-exchange), and study the Frankfurt Hedgehogs and Linear Utility repos line by line — their code contains the real curriculum.
