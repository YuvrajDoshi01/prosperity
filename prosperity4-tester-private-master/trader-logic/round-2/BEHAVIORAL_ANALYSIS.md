# R1 Leaderboard: Human Behavior Deep Dive

Analysis of 22,130 teams across OVERALL, ALGO, and MANUAL leaderboards from Prosperity 4 Round 1. The goal is to decode how real humans allocate effort and attention in a competition of this shape, and use those patterns to anticipate what competitors will do in R2's manual challenge.

## The engagement funnel

Registration number in isolation is misleading. Of 22,130 teams:

| Segment | Count | Share | Behavior |
|---------|------:|------:|----------|
| Ghosts | 16,213 | 73.3% | Registered, never submitted anything |
| Algo-only | 1,380 | 6.2% | Built a trader, skipped the manual challenge |
| Manual-only | 418 | 1.9% | Clicked the manual form, never coded |
| Both | 4,119 | 18.6% | Actually competed on both fronts |

The real competition is the 5,917 teams that did something. Registration is free and easy to abandon. Most people sign up in a wave of curiosity, never open the IDE, and forget. This is universal in online competitions and the ratio here is typical.

For R2 game theory this matters a lot. If Speed rank is computed across all 22,130 teams with the ghost majority sitting at sp = 0, then any positive Speed investment puts you in the top 27%. If it's computed across active players only, the bar is much higher. The R2 brief says "rank-based across all players" without qualifier, so the plain reading is the former. Our Speed investment in the 40s range lands far above the engagement threshold either way.

## The leak asymmetry

The R1 manual optimum of 87,995 was leaked to Discord. This is the single most informative data point in the entire leaderboard because it turns manual score into a measure of information access rather than optimization skill.

Score distribution:

| Band | Teams | Share |
|------|------:|------:|
| Exactly 87,995 (leak) | 1,790 | 8.09% |
| 80,000 to 87,994 | 677 | 3.06% |
| 50,000 to 80,000 | 1,491 | 6.74% |
| 0.01 to 50,000 | 1,049 | 4.74% |
| Exactly 0 | 17,327 | 78.30% |
| Negative | 266 | 1.20% |

Breaking the leak-copy cohort down by algo performance shows the asymmetry clearly. Among teams with ALGO > 50k (the "serious algo" tier of 4,240 teams), 38.8% hit the leak exactly. Among teams with ALGO = 0 or low, leak adoption is single-digit percent. The people who read Discord are the same people who build good traders. The leak didn't make casual players elite, it just let the already-serious skip some work.

## The near-miss cluster

The non-exact high scorers are the most interesting cohort. They look like this:

| Score | Teams | What happened |
|------:|------:|---------------|
| 87,994.10 | 210 | Off by 0.9, probably rounding error or typo |
| 87,897.10 | 156 | Volume off by ~100 units |
| 87,896.10 | 55 | Volume variant |
| 87,000 to 87,900 range | ~200 more | Various near-miss patterns |

These are people who either solved the auction themselves and landed close, or tried to copy the leak and mistyped. Given the dominance of 87,994.10 (exactly 0.9 off from optimum), my read is many of these are copy-paste errors from the Discord message. Some are real independent solvers.

The truly independent solvers show up in the 50k to 85k band where people got a clean solve on one product but not both. 521 teams scored exactly 71,500 (Mushroom-only bet). 255 at 47,700 (partial solve). 145 at 52,700 (Flax-only optimum plus partial Mushroom). Each of these is a specific suboptimal strategy the team committed to.

About 1,630 teams (7.4% of registered, 28% of engaged) sit in this independent-partial-solver band. They tried the math, got somewhere, didn't cheat. This is the closest thing we have to a clean sophistication signal in the manual data.

## Elite cohort

Top 100 OVERALL spans 193,300 to 213,845. Their ALGO scores are all above 105k. Ninety of them hit the leak exactly. Ten are at 87,897 or 87,994, meaning they probably solved on their own.

Team names tell a story. The top 30 includes multiple variants of "DU" (probably one university group with coordinated submissions: "DU Trading", "DU Quant", "DU Trading Desk", "DU Market Makers", "DU Market Making"). Finance-adjacent names dominate: "Seven Deuce Capital", "72 Sigma", "Flowstate". The top of the leaderboard is dominated by teams that explicitly identify as quant / trading / capital, and many are recurring university programs.

This has two implications. First, a significant share of elite teams are professionally trained. They are likely to run solvers on R2's manual challenge the way we did. Second, the same tight community that shared the R1 leak will share R2 analysis. Anything that becomes Discord conventional wisdom will cluster teams tightly at the same answer.

## Country-level signatures

| Country | Teams | Engagement | Elite share |
|---------|------:|-----------:|------------:|
| India | 9,531 (43%) | 13.5% manual | 13 of 100 |
| US | 4,334 (20%) | 25.4% manual | 24 of 100 |
| UK | 2,018 (9%) | 21.8% manual | 14 of 100 |
| Australia | 1,137 (5%) | 28.4% manual | 14 of 100 |
| Switzerland | 300 (1.4%) | 34.3% manual | 4 of 100 |
| Netherlands | 453 (2%) | 29.6% manual | 2 of 100 |
| Germany | 419 (2%) | 31.3% manual | 4 of 100 |

India dominates registrations but underperforms on every engagement and quality metric. This is almost certainly driven by promotion in Indian student communities: many people sign up, few actually play. This is not a cultural judgment, it's how the pipeline works. The elite tier is disproportionately Anglophone plus Western European.

Switzerland, Netherlands, Germany, and Spain have the highest leak-copy rates (13-16%), consistent with tightly networked finance student communities that share info fast. Australia punches above its weight in the elite (14 of 100 from 5% of teams), suggesting a concentrated serious cohort.

For R2, expect the competitive dynamics to be driven by US, UK, AU, and small European nations. The Indian ghost pool anchors the Speed rank distribution at 0 but does not shape the competition at the top.

## Irrationality signals

266 teams scored negative on manual. The minimum was -3,507,500. In the R1 auction, negative scores meant bidding way above what the cleared volume could support. These teams either misunderstood the clearing mechanic or treated volume as a free lunch.

394 teams had negative ALGO scores, with minimum of -40.4 million. These are traders who blew up spectacularly, either by violating position limits repeatedly or by selling cheap and buying expensive at scale.

The R2 manual has a similar failure mode. If you dial up all three pillars to max but misjudge the Speed rank, you can pay 50k for a small gross. The 1-2% population that always over-bids in these challenges will probably do it again on R2.

## Behavioral archetypes for R2

Based on the R1 data, I see seven distinct player archetypes that will show up in R2's Invest & Expand challenge:

**The Ghost (70% of registrations, 0% of competition).** Did nothing on R1 manual. Will do nothing on R2 manual. Shows up in Speed rank at sp = 0 and anchors the bottom.

**The Copy-Paster (8% of registrations, 35% of engaged).** Copied the R1 leak. For R2, will wait for Discord to post someone's analysis, then copy whatever allocation goes viral. If a specific answer gets evangelized, expect 30-40% of engaged players to pile in.

**The Partial Solver (7% of registrations, 28% of engaged).** Did the math on R1 manual, got somewhere but not optimum. For R2 they'll pick reasonable-looking allocations in the 20/40/40 to 15/50/35 range without running a solver. Spread across a band, not clustered tightly.

**The Nash Hunter (1.5% of registrations, 7% of engaged).** Solved R1 independently. For R2 will do game theory analysis like we did, land near (15, 44, 41) via independent reasoning. Small but tight cluster at the equilibrium.

**The Contrarian (0.5% of registrations, 2% of engaged).** Knows about Schelling points. For R2 picks one or two points off the Nash to beat the crowd on rank. Strategically dangerous because they'll undercut anyone who sits at the obvious answer.

**The Round-Number Picker (5% of registrations, 25% of engaged).** Picks 33/33/34, 50/30/20, 40/40/20. Speed investments cluster at 20, 30, 33, 40, 50. Very predictable allocation pattern.

**The Over-Invester (2% of registrations, 8% of engaged).** Read the brief, thought Speed was decisive, over-allocates to sp = 60+. Same psychological type as the negative-score auctioneers on R1. They push the top of the Speed distribution.

## What this means for our R2 allocation

### The herd risk at the Nash point

If we publish our (15, 44, 41) analysis or anyone in our sophistication tier independently arrives at the same answer (likely), that allocation becomes a Schelling point. The Copy-Paster bucket will converge on it the moment it hits Discord. 35% of engaged players copying the same allocation means sp = 41 gets crowded. Crowding on sp doesn't hurt you directly because rank is a function of percentile, not cluster density. But it means ties get broken somehow (probably by submission order), so you don't gain rank by being in the cluster.

### The contrarian edge

Going sp = 42 or sp = 43 (one or two points above the Nash) puts you above the crowded equilibrium, above the round-number herd at 40, and just below the Over-Invester tail that starts at 50+. You still get most of the Nash Scale and Research values. The Speed multiplier is marginally better because you sit cleanly above the biggest cluster. This is the Archetype 5 Contrarian play, and the math just barely favors it if you believe the Nash cluster will be crowded.

### The country dispersion argument

If we take the plain reading of "rank across all players" literally, the Indian ghost pool puts 43% of teams at sp = 0. Add the US/UK/AU non-submitters (probably another 15-20%), and you have over 60% of the rank pool at the bottom. Sp = 10 already puts you in the top 40%. Sp = 20 puts you in the top 25%. The marginal Speed multiplier gain above that is small because you're climbing an already-tall percentile.

This argues for a more Scale-heavy allocation than the v3 Nash, because you don't actually need sp = 41 to get a decent Speed multiplier. Something like (18, 50, 32) might dominate in the "across all players" interpretation.

### Our final read

The safest interpretation is that rank is across engaged players and the Nash analysis still applies. Our recommendation stays at (15, 44, 41), with a slight lean toward (15, 43, 42) if we want contrarian edge over the crowded Nash cluster.

If the user has a strong prior that rank is literally all 22k teams, shifting to (18, 50, 32) is defensible. The point is that the population interpretation matters more than any other parameter in the model.

## What the data cannot tell us

The R1 manual was a deterministic puzzle with a leaked answer. R2 manual is a game-theoretic allocation problem. The behavioral data tells us about engagement, sophistication distribution, and information-sharing dynamics. It does not directly tell us:

- Whether R2 will see a similar leak (probably yes, given the community dynamics)
- What specific allocation will go viral if there is one
- Whether the round-number pickers will anchor on 20, 30, 33, 40, or 50 for Speed
- How many teams will drop out between R1 and R2 (some will, hard to predict fraction)

The honest recommendation is to treat (15, 44, 41) as our primary pick and (15, 43, 42) as our contrarian hedge, with the understanding that the true optimum depends on behavioral factors we cannot fully observe. Our R1 cumulative of 177k locks in the 200k threshold, so we're playing for upside, not survival.
