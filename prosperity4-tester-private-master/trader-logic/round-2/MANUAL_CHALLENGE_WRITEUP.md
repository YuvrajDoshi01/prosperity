# Round 2 Manual Challenge: Invest and Expand

## The problem

Round 2's manual challenge gives you a 50,000 XIREC budget split across three pillars. You pick a percentage allocation for each, the percentages cannot sum to more than 100, and whatever you spend gets subtracted from your gross outcome at the end.

The three pillars behave very differently. Research grows on a log curve from 0 up to 200,000, so the first few percent buy you a lot and later percent buy you very little. Scale is linear, topping out at 7 times at 100%. Speed is the awkward one: it is rank based against everyone else in the competition. Whoever invests the most gets a 0.9 multiplier, whoever invests the least gets 0.1, and everyone else is linearly interpolated by rank.

Your score is `Research(r) * Scale(s) * Speed(sp) - 50000 * (r + s + sp) / 100`.

Two things make this hard. First, Research and Scale compound multiplicatively, so the sweet spot trades off concave returns on research against linear returns on scale. Second, Speed is a game you play against strangers. You cannot optimize it in isolation because its payoff depends on what everyone else does.

## The approach: brute force plus scenario sweep

For the deterministic part of the problem (Research and Scale given a fixed Speed multiplier), brute force is trivial. We enumerate every integer triple where `r + s + sp <= 100`. That comes out to 176,851 allocations. Evaluating each takes microseconds.

The hard part is Speed. Without knowing how competitors allocate, we cannot compute Speed directly. We have to make assumptions about the distribution of competitor speed investments, compute an expected multiplier under that assumption, and then evaluate allocations.

So we built a scenario sweep. For each allocation, we compute the payoff under many different hypothesized competitor distributions, then look at which allocations do well on average and which do well in the worst case.

### Scenarios we covered

The first version of the solver tested 18 scenarios: six values of mean competitor speed (15, 20, 25, 30, 35, 40) crossed with three spreads (sigma of 10, 15, 20), assuming a Normal distribution of competitor investments.

For the second version we expanded this significantly. 101 scenarios in total:

* 96 Normal distributions covering mean 5 through 60 and sigma 5 through 25
* 6 Uniform distributions with different floor and ceiling combinations
* 4 Bimodal mixtures representing markets where most people lowball and a minority bid aggressively
* 5 rank simulations where we draw 200 actual competitor samples from different priors (Normal, Uniform, Beta, Bimodal) and compute our rank exactly

The Beta and Bimodal priors are there because the actual player population probably is not a clean Normal. Most players will pick round numbers like 30 or 50, a chunk will go all-in on one pillar, and a few will put almost nothing on Speed because they did not realize it was a rank game. Covering these cases makes the solver output more robust to model mis-specification.

### Total computation

176,851 allocations times 101 scenarios is about 17.9 million evaluations. The whole thing runs in a few seconds because each evaluation is a handful of floating point operations.

## Results

### Per scenario winners

Each scenario has its own optimal allocation and they move predictably. When mean competitor Speed is low (say mu = 15), the optimal allocation pushes Scale hard (around s = 54) because we can be competitive on Speed with relatively little investment. When mean Speed is high (mu = 55 or 60), the optimum tilts toward Speed (sp = 60 plus) because otherwise we get a very low multiplier.

This matches intuition. If everyone else is asleep on Speed, you coast. If everyone else is aggressive, you have to match them.

### Mean optimal across all scenarios

The allocation that maximizes average payoff across all 101 scenarios is **(r=16, s=46, sp=38)**. It returns a mean of 172,539 with a worst case of negative 10,463 and a best case of 305,815.

Almost every allocation in the top 10 by mean clusters in the same neighborhood: r between 15 and 17, s between 44 and 48, sp between 37 and 41. The differences are under a thousand XIRECs in mean PnL. So any allocation in that cluster is effectively equivalent.

### Robust optimum

The allocation that maximizes the worst case is dramatically different: **(r=11, s=29, sp=60)**. It guarantees at least 59,301 in every scenario we tested, with a mean of 125,463.

This one works because 60% on Speed is high enough to pay for the top rank multiplier under almost any competitor distribution we could think of. You sacrifice Research and Scale to buy certainty.

### Sensitivity table

| Allocation | Mean | Worst | Best | Character |
|-----|-----:|------:|-----:|-----------|
| (16, 46, 38) | 172,539 | -10,463 | 305,815 | Mean optimal |
| (15, 44, 41) | 171,807 | -12,972 | 283,062 | Point optimum under mu=30, sigma=15 |
| (15, 46, 39) | 172,434 | -11,307 | 298,202 | v1 mean optimal |
| (15, 40, 45) | 167,634 | -15,994 | 252,784 | Round-numbers heuristic |
| (11, 29, 60) | 125,463 | +59,301 | 146,741 | Worst-case robust |

## Why the worst case goes negative

A few allocations in our top-10-by-mean list have negative worst-case PnL. The reason is that when Speed multiplier lands at 0.1 (you are dead last on Speed), the gross becomes very small and the budget cost dominates. This happens when you under-invest in Speed and everyone else went heavy on it.

That failure mode is only possible in a narrow slice of scenarios (extreme competitor behavior). For the expected payoff we care about, it washes out.

## Game theory and what competitors are actually going to do

The mean-across-all-scenarios answer treats every scenario as equally likely. That is not really the case. Real player behavior is predictable in specific ways, and if we weight scenarios by their realistic prior probability, the picture shifts.

### How people actually allocate

Most competitors in a challenge like this fall into a handful of behavioral buckets. Watching past Prosperity manual rounds and general human decision making, the most common patterns are roughly:

**Equal splitters (30 to 40% of players).** People default to 33/33/33 or 34/33/33. It feels fair and requires no reasoning. Under this allocation, Speed is about 33, which puts them somewhere in the middle of the rank distribution.

**Round number pickers (20 to 30% of players).** People reach for 50/30/20, 40/40/20, 50/25/25, and similar. Speed allocations cluster at 20, 25, 30, 40, 50. Very few people pick something like 38 or 46 because those do not feel like natural stopping points.

**Research maximizers (10 to 15% of players).** The 200,000 number in the Research formula is very attention grabbing. Some people see that and go heavy on Research, something like 70/20/10 or 80/10/10. This leaves their Speed investment low, which is actually fine for them individually but pushes the distribution of Speed allocations downward overall.

**Scale maximizers (5 to 10% of players).** A smaller group notices that Scale caps at 7 and figures that 100% Scale gives them a 7x multiplier. They allocate 0/100/0 or similar. Same effect on the Speed distribution.

**Speed hawks (10 to 15% of players).** People who read the brief carefully and realize Speed is rank based sometimes overcorrect by going heavy on Speed. 20/30/50, 15/30/55, or even 10/20/70. These are the people who push the top of the distribution.

**Sophisticated game theorists (5 to 10% of players).** This is us and a handful of other teams. Everyone in this bucket is trying to figure out what everyone else will do. Some end up picking mean-optimal allocations, others pick robust allocations. Either way they are not going to be exactly uniform.

Adding all this up, the empirical distribution of competitor Speed investments probably looks bimodal. There is a fat mode around 25 to 35 (equal splitters plus round number pickers plus Research maximizers with leftovers), and a thinner mode around 50 to 70 (Speed hawks). The population mean is probably somewhere between 30 and 38.

### What this means for our allocation

If the realistic mean of competitor Speed is 30 to 38, then our Normal scenarios with mu in that range are the ones that actually matter. Looking at the per-scenario optima:

* mu = 30: optimal is around (15, 44, 41)
* mu = 35: optimal is around (14, 41, 45)
* mu = 40: optimal is around (13, 38, 49)

Our sp = 38 in the (16, 46, 38) recommendation sits right in the middle of the competitor mass. If the realistic mean is closer to 35, we are slightly under on Speed but well positioned on Research and Scale. If the realistic mean is closer to 30, we are comfortably above average on Speed and getting a decent multiplier.

The (11, 29, 60) robust allocation bets on the Speed hawk scenario being common. Looking at the player behavior distribution, the hawk fraction is probably 10 to 15%. That is a minority. The robust allocation pays a large certainty premium (about 47k in mean PnL) to insure against a scenario that probably does not materialize.

### The meta game: what if everyone thinks this way

A common trap in this kind of challenge is overcorrection. If you think through competitor psychology and decide "everyone is going to under-invest in Speed, so I should over-invest to get the 0.9 multiplier," you end up at the robust allocation. If a critical mass of other sophisticated teams reaches the same conclusion, they all cluster at high Speed, the distribution of competitor Speed shifts upward, and the robust allocation loses its edge.

This is actually a structural reason to resist the pull toward high Speed allocations. Anyone who reasons carefully ends up at roughly (15, 45, 40) or (16, 46, 38). The cluster around that point is crowded with smart players, but crucially they all get a similar Speed multiplier (somewhere around 0.6 to 0.7) because they are all at the same percentile. Research and Scale then decide who wins inside that group.

Going dramatically higher on Speed only helps you if you are pulling away from the smart cluster. If half the smart money is at sp = 40 and you go to sp = 60, you move from the 65th percentile to maybe the 85th percentile. That is a Speed multiplier gain from about 0.62 to 0.78, or 26%. But you paid for it with 20% less Research and Scale, which directly multiplies your gross. The math does not quite pencil out.

### One more wrinkle: the example in the brief

The brief gives an example where players invest 70, 70, 70, 50, 40, 40, 30 on Speed. The lowest value is 30, the highest is 70, the median is 50. If that example anchors people, it pushes the realistic competitor Speed distribution higher than our default estimate.

We would shift our scenario weighting slightly toward mu = 35 to 40 to account for this anchoring effect. That moves the point optimum from (15, 44, 41) to (14, 41, 45). The difference is three points of Speed for three points off Scale and one off Research.

## Our recommendation

Go with **(15, 44, 41)** or (14, 41, 45). Either is fine. Pick whichever feels right.

Both sit in the dense cluster of allocations where sophisticated players land. Both pick up most of the expected payoff in realistic scenarios. Both avoid the over-correction toward Speed that the robust allocation represents.

If you want to push slightly toward game theory conservatism (betting that competitor Speed will cluster higher due to the brief's example), pick (14, 41, 45).

If you want to push slightly toward naive expectation (betting most competitors will default to round-number allocations like 33/33/33), pick (15, 44, 41).

The brute force mean optimum of (16, 46, 38) is also fine, just slightly more aggressive on Scale at the cost of Speed. All three allocations have very similar expected payoffs in realistic scenarios.

### Why not (11, 29, 60)

The robust allocation only wins if a lot of competitors bid very high on Speed. That scenario requires either a uniform high-Speed prior across the field or a dominant Speed hawk population. Neither matches the psychological reality of the player base. The 47k in foregone expected PnL is a real cost, not theoretical, and we have no strong reason to think the adversarial scenarios are likely.

### Why not go even higher than 40 on Speed

Because of the smart cluster crowding argument above. Pushing past 45 on Speed buys you marginal percentile gain at a significant Research and Scale cost. The Speed curve is close to linear around the 50th to 80th percentile, but Research starts flattening past 15 or so. Moving budget from the steep part of Research to the linear part of Speed is not efficient.

## What brute force cannot solve

We want to be honest about what this analysis does and does not accomplish.

What it does accomplish:
* Exhaustive coverage of the integer allocation space
* Robust coverage of parametric distribution assumptions about competitors
* Explicit rank simulation against drawn competitor samples

What it does not accomplish:
* We cannot observe the actual competitor distribution. We can only model it.
* The choice between mean-optimal and robust-optimal is a judgment call about how much faith you have in the model.
* Fractional allocations are not in the search space. The UI appears to only accept integer percentages, so this is probably not a gap, but we have not verified every input field.

The real residual uncertainty is in the Speed multiplier, not in the Research or Scale calculations. Those two are deterministic functions of your input. If our Speed modeling is close to reality, (16, 46, 38) is very close to optimal. If it is way off, all bets are on whether the true distribution looks more like our Normal scenarios or our bimodal ones.

## Files produced

* [invest_expand_solver.py](invest_expand_solver.py) - original 18-scenario solver
* [invest_expand_solver_v2.py](invest_expand_solver_v2.py) - expanded 101-scenario solver with multiple distribution models
* [invest_expand_solver_v3.py](invest_expand_solver_v3.py) - game-theory-aware solver with behavioral population Monte Carlo and iterated best response
* [invest_expand_results.json](invest_expand_results.json) - v1 outputs
* [invest_expand_results_v2.json](invest_expand_results_v2.json) - v2 outputs
* [invest_expand_results_v3.json](invest_expand_results_v3.json) - v3 outputs with Nash fixed point

## The v3 game-theory brute force

The v3 solver integrates the behavioral psychology directly into the brute force rather than treating it as a post-hoc correction. The setup:

* Build a realistic competitor population of 1000 players
* Sample from the six behavioral buckets in their estimated proportions (35% equal splitters, 25% round number pickers, 12% Research maximizers, 7% Scale maximizers, 12% Speed hawks, 9% sophisticated)
* The sophisticated bucket is self-referential: they allocate near whatever we are solving for, so we iterate
* Run 100 Monte Carlo trials per iteration, each with a freshly drawn population
* Compute mean, median, p10, and p90 PnL per allocation across trials

### Iterated best response

Start with seed_sp = 40. Solve for best allocation assuming sophisticated players cluster around sp = 40. Get new best_sp. Feed back. Repeat until sp stabilizes.

Result: converged on iteration 1. Starting from seed 40, the optimum is sp = 41. One point difference, below our tolerance. This means (15, 44, 41) is a stable point under realistic population dynamics: even when a chunk of the field picks this same allocation, it remains the best response.

### Population-aware payoff distribution

Under the behavioral population model the expected PnL for (15, 44, 41) is 227,975 with a p10 of 222,963 and p90 of 233,029. That 10,000 wide envelope is much tighter than v2's scenario spread because the behavioral model pins down what competitor Speed actually looks like.

The top 10 allocations by population-aware mean PnL all cluster at sp = 41 or 42, with small shifts between r and s:

| Rank | Allocation | Mean | p10 | p90 |
|-----:|:-----------|-----:|----:|----:|
| 1 | (15, 44, 41) | 227,975 | 222,963 | 233,029 |
| 2 | (14, 45, 41) | 227,675 | 222,669 | 232,724 |
| 3 | (16, 43, 41) | 227,598 | 222,592 | 232,645 |
| 4 | (13, 46, 41) | 226,614 | 221,627 | 231,643 |
| 5 | (17, 42, 41) | 226,612 | 221,624 | 231,641 |

The top 5 are within 1.4k of each other, which is less than one standard deviation of trial noise.

### How our candidates compare under the population model

| Allocation | Mean | p10 | p90 | Source |
|:-----------|-----:|----:|----:|:-------|
| (15, 44, 41) | 227,975 | 222,963 | 233,029 | v3 Nash fixed point |
| (16, 46, 38) | 222,792 | 217,257 | 228,010 | v2 mean-optimal |
| (15, 46, 39) | 220,721 | 214,633 | 226,395 | v1 mean-optimal |
| (14, 41, 45) | 211,987 | 207,323 | 216,484 | v2 anchoring-corrected |
| (15, 40, 45) | 211,689 | 207,030 | 216,181 | Round number heuristic |
| (14, 40, 46) | 206,641 | 201,836 | 210,773 | v1 robust |
| (11, 29, 60) | 136,394 | 134,675 | 138,172 | v2 robust |

The (11, 29, 60) robust allocation sacrifices 91k in mean PnL compared to (15, 44, 41). The over-correction toward Speed is not worth the tight guarantee. And the allocations that under-invest in Speed compared to the Nash point lose between 5k and 16k in mean PnL.

### Why the fixed point is at sp = 41

The equilibrium is roughly where your Speed investment sits just above the sophisticated cluster. Going below 41 cedes rank to the sophisticated bucket and drops you into the fat round-number mass where many competitors sit. Going above 41 costs Research and Scale multiplicatively faster than it gains Speed percentile. The tradeoff is tightest near 41.

The math is consistent across different competitor populations too. We ran sanity checks with alternate bucket fractions (equal splitters at 25% vs 45%, Speed hawks at 5% vs 20%) and the equilibrium sp stays in the 40 to 43 range.

## Bottom line

Submit **(r=15, s=44, sp=41)**.

The v3 game-theory solver confirms this is a Nash fixed point under iterated best response against a realistic behavioral population. Expected PnL is 227,975 with a p10 of 223k and p90 of 233k. It is simultaneously the brute-force mean-optimal under population-aware scenario weighting AND the equilibrium where sophisticated players stabilize after best-responding to each other.

The alternative allocations we considered all lose to (15, 44, 41) under the realistic population model:

* (16, 46, 38) loses 5k by under-weighting Speed
* (11, 29, 60) loses 91k by massively over-correcting toward Speed insurance that the realistic distribution does not require

The 177k Round 1 cushion guarantees threshold safety regardless of how the manual challenge goes. The manual is pure upside. (15, 44, 41) captures the best expected outcome with a tight variance envelope.
