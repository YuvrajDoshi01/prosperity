# Manual Challenge: "An Intarian Welcome" - Solution

## Auction Mechanics

This is a **uniform-price clearing auction**. The exchange picks a single clearing price that:

1. **Maximizes total traded volume** - `min(cumulative bids >= P, cumulative asks <= P)`
2. **Tie-breaks on highest price** - if two prices produce equal volume, the higher price wins

All bids at or above the clearing price execute. All asks at or below it execute. Everyone trades at the **same clearing price**, regardless of their limit. Allocation follows **price-time priority** - higher-priced bids fill first, and since we submit last, we are last in line at any price level we join.

After the auction, inventory is liquidated at a fixed buyback:
- **Dryland Flax**: 30 XIRECs/unit (no fees)
- **Ember Mushroom**: 20 XIRECs/unit (0.10 fee/unit round-trip)

---

## The Key Exploit: Volume-Controlled Price Priority

The naive approach - pick the bid price that maximizes `fills * edge` at max volume - misses a powerful trick. Because we know the full book and act last, we can:

1. **Bid above our target clearing price** to gain price priority over existing bidders at that level
2. **Cap our volume** just below the threshold that would tip the clearing price upward
3. **Fill at the lower clearing price** while jumping the queue of bidders at that level

This is pure information advantage from seeing the stale book and submitting last.

---

## Dryland Flax (Buyback = 30, no fees)

### Order Book

| Bids | | Asks | |
|------|------|------|------|
| 30k @ 30 | | 40k @ 28 | |
| 5k @ 29 | | 20k @ 31 | |
| 12k @ 28 | | 20k @ 32 | |
| 28k @ 27 | | 30k @ 33 | |

### Baseline clearing (without us)

| Clearing Price | Cum. Bids >= P | Cum. Asks <= P | Traded |
|:-:|:-:|:-:|:-:|
| 27 | 75k | 0 | 0 |
| **28** | **47k** | **40k** | **40k** |
| 29 | 35k | 40k | 35k |
| 30 | 30k | 40k | 30k |

Baseline clearing: **P=28, volume=40k.** Supply <= P is flat at 40k for P in {28,29,30}.

### Exhaustive analysis

**Selling:** Profit = clearing - 30 per unit. Clearing <= 28 always, so selling is strictly negative. Ruled out.

**Buying - every viable price/volume combination:**

**P <= 27:** Below clearing. Never executes. Profit = 0.

**P = 28, any v:** Clearing stays 28 (40k). After 30k@30 and 5k@29 fill, only 5k remain. Existing 12k@28 has time priority. We get 0.

**P = 29, v < 5k:** Traded@29 = 35k + v < 40k. Clearing stays at 28 (40k > 35k+v). Our bid at 29 has *price priority* over 28-bids at clearing 28. After 30k@30 + 5k@29 = 35k, we get v fills at clearing 28. **Profit = v * (30-28) = 2v.** At v=4,999: **profit = 9,998.**

**P = 29, v >= 5k:** Traded@29 = 40k. Ties with P=28 -> clearing = 29 (tiebreaker). We get 5k (after 30k@30 and 5k@29 existing). **Profit = 5k * 1 = 5,000.** *Worse* than v=4,999.

**P = 30, v < 10k:** Traded@30 = 30k + v < 40k. Clearing stays at 29 (tied at 40k for P=28,29 -> tiebreaker picks 29). Our bid at 30 has top price priority after existing 30k@30. At clearing 29: existing 30k@30 fills, then us (v), then 5k@29 gets remaining. **Profit = v * (30-29) = v.** At v=9,999: **profit = 9,999.**

**P = 30, v >= 10k:** Traded@30 = 40k. Ties with P=28,29 -> clearing = 30. Profit = v * 0 = **0.** Cliff edge.

**P >= 31, v < 10k:** Same as P=30 - our bid counts at all clearing prices <= our bid, traded@30 = 30k+v < 40k, clearing = 29. We fill v at 29. At v=9,999: **profit = 9,999.**

**P >= 31, v >= 10k:** Traded@30 = 40k. Tie across 28,29,30 -> clearing = 30. Profit = 0.

### Comparison of best strategies

| Strategy | Clearing | Fills | Edge | Profit |
|----------|:--------:|------:|-----:|-------:|
| BUY @ 29, vol 4,999 | 28 | 4,999 | 2.00 | 9,998 |
| **BUY @ 30, vol 9,999** | **29** | **9,999** | **1.00** | **9,999** |
| BUY @ 29, vol 5,000+ | 29 | 5,000 | 1.00 | 5,000 |
| BUY @ 30, vol 10,000+ | 30 | 10,000 | 0.00 | 0 |

### Answer: BUY at 30, volume 9,999

Clearing stays at 29. We have price priority (30 > existing 29-bids), so we fill 9,999 units at clearing 29. **Profit = 9,999 XIRECs.**

The boundary is razor-sharp: at vol=10,000 the clearing flips to 30 and profit drops to zero.

Allocation at clearing 29 (traded = 40k):
1. 30k @ 30 (existing, time priority over us at same price) -> 30k filled
2. **9,999 @ 30 (us)** -> 9,999 filled (total: 39,999)
3. 5k @ 29 (existing) -> 1 filled (total: 40k, supply exhausted)

---

## Ember Mushroom (Buyback = 20, fee = 0.10/unit)

### Order Book

| Bids | | Asks | |
|------|------|------|------|
| 43k @ 20 | | 20k @ 12 | |
| 17k @ 19 | | 25k @ 13 | |
| 6k @ 18 | | 35k @ 14 | |
| 5k @ 17 | | 6k @ 15 | |
| 10k @ 16 | | 5k @ 16 | |
| 5k @ 15 | | 0 @ 17 | |
| 10k @ 14 | | 10k @ 18 | |
| 7k @ 13 | | 12k @ 19 | |

### Baseline clearing (without us)

| Clearing Price | Cum. Bids >= P | Cum. Asks <= P | Traded |
|:-:|:-:|:-:|:-:|
| 13 | 103k | 45k | 45k |
| 14 | 96k | 80k | 80k |
| **15** | **86k** | **86k** | **86k** |
| 16 | 81k | 91k | 81k |
| 17 | 71k | 91k | 71k |
| 18 | 66k | 101k | 66k |
| 19 | 60k | 113k | 60k |

Baseline clearing: **P=15, volume=86k.** Perfect supply/demand balance - no residual for us.

### Exhaustive analysis

**Selling:** Profit = clearing - 20 - 0.10 per unit. Clearing <= 15, so always deeply negative. Ruled out.

**The naive analysis (bid price sweep at max volume) misses the global optimum.** The trick is the same as Flax: bid *above* the target clearing price to gain price priority, while capping volume below the threshold that shifts clearing upward.

### Maximum fill at each clearing price - naive vs. optimized

The naive approach bids AT the clearing price level, placing us behind existing bidders at that level in time priority. The optimized approach bids ONE level above, jumping the queue:

| Clearing | Supply | Demand above clearing (excl. us) | Existing AT clearing | Naive max fill | **Optimized max fill** |
|:--------:|:------:|:--------------------------------:|:-------------------:|:--------------:|:---------------------:|
| 15 | 86k | 81k | 5k | 0 | 0 (no room even with priority) |
| 16 | 91k | 66k (>=17) | 5k@17 is above; 10k@16 at level | 10k | **19,999** (bid at 17) |
| 17 | 91k | 66k (>=18) | 5k@17 at level | 20k | **20k** (same - already at limit) |
| 18 | 101k | 60k (>=19) | 6k@18 at level | 35k | **35k** (same) |
| 19 | 113k | 43k (>=20) | 17k@19 at level | 53k | **53k** (same) |

**The critical insight is at clearing 16.** By bidding at 17 instead of 16, we jump ahead of the 10k existing at 16 in price priority. The constraint is v < 20k (at v=20k, traded@16 = traded@17 = 91k, tiebreaker pushes clearing to 17).

### Profit at each clearing level (optimized)

| Clearing | Bid Price | Volume | Fills | Edge/Unit | **Profit** |
|:--------:|:---------:|-------:|------:|----------:|-----------:|
| 15 | any | - | 0 | 4.90 | 0 |
| **16** | **17** | **19,999** | **19,999** | **3.90** | **77,996** |
| 17 | 18+ | 24,999 | 20,000 | 2.90 | 58,000 |
| 18 | 19+ | 40,999 | 35,000 | 1.90 | 66,500 |
| 19 | 20 | 43,000 | 43,000 | 0.90 | 38,700 |

### Why clearing 16 with bid at 17 wins

At bid=17, vol=19,999: traded@16 = min(81k+19,999, 91k) = **91k**. Traded@17 = min(71k+19,999, 91k) = **90,999**. Since 91k > 90,999, clearing = 16.

Allocation at clearing 16 (supply = 91k, demand = 100,999):
1. 43,000 @ 20 -> 43,000 filled
2. 17,000 @ 19 -> 60,000 filled
3. 6,000 @ 18 -> 66,000 filled
4. 5,000 @ 17 (existing, time priority over us) -> 71,000 filled
5. **19,999 @ 17 (us)** -> **90,999 filled**
6. 10,000 @ 16 (existing) -> 1 filled (only 1 unit of supply remains)

We get **19,999 fills at clearing 16**. Edge = 20 - 16 - 0.10 = **3.90/unit**.

**Profit = 19,999 * 3.90 = 77,996 XIRECs.**

### The cliff edge

At vol=20,000: traded@16 = 91k, traded@17 = 91k. Tie -> clearing = 17 (higher wins). Profit drops from 77,996 to 58,000. A single unit of volume destroys **19,996 XIRECs** of profit.

### Why this beats the naive answer (bid 18, vol 35k = 66,500)

The naive approach correctly identifies that pushing clearing to 18 unlocks 101k of supply and yields 35k fills. But it misses that at clearing 16:

- We get fewer fills (19,999 vs 35,000)
- But the edge per unit is **2* higher** (3.90 vs 1.90)
- Net: 19,999 * 3.90 = 77,996 > 35,000 * 1.90 = 66,500

The naive approach also underestimates our fill at clearing 16 because it assumes we'd bid at 16 (behind 10k existing -> max fill 10k). By bidding at 17, we jump 10k of queue and capture 19,999 fills instead.

### Answer: BUY at 17, volume 19,999

Clearing stays at 16. We fill 19,999 units at 3.90 edge. **Profit = 77,996 XIRECs.**

---

## Why selling doesn't work (either product)

Adding sell volume increases supply, which can only maintain or decrease the clearing price. For selling to profit, we need `clearing > buyback + fee`. But:

- **Flax:** Highest bid = 30 = buyback. Clearing can never exceed 30. Best case: zero edge.
- **Mushroom:** Highest bid = 20 = buyback, fee = 0.10. Best case: negative edge.

The buyback prices are set exactly at the top of the existing bid stack - by design, shorting is a dominated strategy.

Exhaustive sell-side sweep confirms: every (price, volume) sell combination produces zero or negative profit for both products.

---

## Summary

| Product | Order | Clearing | Fills | Edge | Profit |
|---------|-------|:--------:|------:|-----:|-------:|
| Dryland Flax | BUY @ 30, vol 9,999 | 29 | 9,999 | 1.00 | 9,999 |
| Ember Mushroom | BUY @ 17, vol 19,999 | 16 | 19,999 | 3.90 | 77,996 |
| **Total** | | | | | **87,995** |

### Optimization path (how we got here)

| Iteration | Flax | Mushroom | Total | What changed |
|-----------|-----:|--------:|------:|--------------|
| Naive (price sweep, max vol) | 5,000 | 66,500 | 71,500 | Baseline |
| 2D coarse sweep (1k vol steps) | 9,000 | 74,100 | 83,100 | Volume as free variable |
| Exhaustive (step=1 at boundaries) | 9,999 | 77,996 | **87,995** | Exact breakpoints + price priority exploit |

The 23% improvement from naive to exhaustive comes entirely from two insights:

1. **Volume controls the clearing price.** Bidding max volume at a given price pushes clearing higher than necessary. Capping volume just below the tipping point preserves a lower clearing price.

2. **Bid price controls queue priority independently of clearing price.** By bidding above our target clearing level, we jump ahead of existing bidders at that level - gaining fills that were previously inaccessible due to time priority.

### Verification

Results confirmed by `trader-logic/auction_solver.py` exhaustive search (step=1 at all clearing-price boundaries, both buy and sell sides, all integer prices). The solver is reusable for future manual challenges - update the order book dicts and re-run.
