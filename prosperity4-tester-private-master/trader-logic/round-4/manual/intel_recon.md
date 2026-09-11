# R4 Manual — "Vanilla Just Isn't Exotic Enough" — Intel Recon

**Date:** 2026-04-26
**Round:** 4 (live, ends ~2026-04-28)
**Status:** External public intel = **NIL**. Round is mid-flight, no community writeups yet.

---

## 1. External search results — what's out there

| Channel | Result |
|---|---|
| Google / Web search (15+ queries) | Zero hits for "Aether Crystal", "Solvenarian Days", "vanilla isn't exotic", "AC_50_CO", "3000 multiplier" |
| `imc-prosperity.notion.site` (wiki) | JS-rendered, opaque to WebFetch. URL pattern (R3 had `Round-3-Gloves-Off-34ce8453a0938072a58cc7de372ff551`) suggests R4 lives at a similar guid but I could not enumerate it via Google |
| Discord (no scrape access) | No proxied content reachable |
| Reddit `/r/algotrading` | Zero R4 manual posts |
| GitHub (chrispyroberts/p4, nabayansaha/p4-backtester, VincentTLe/prep) | None mention Aether/manual/R4 specifics |
| Medium 2026 writeups (Mandviwala finals, Bennett 4th UK) | Both stop at R1–R2; R3+ "soon" |
| jmerle leaderboard | UI-only, no challenge text |

**Bottom line:** the field has not yet leaked anything about R4 manual. We are operating off the in-game UI text alone — same starting point as everyone else.

---

## 2. The "3000 contract size" question — strongest available evidence

**No external confirmation exists.** All inference must come from internal consistency of the brief plus past Prosperity precedent.

**Past Prosperity options sizing (verified):**

| Edition | Round | Underlying | Option | Per-contract size convention |
|---|---|---|---|---|
| **P2 R4** | algo | COCONUT | COCONUT_COUPON (10000-strike, 250d) | 1 coupon = 1 share-equivalent. Limits 300/600. **No multiplier.** |
| **P3 R3** | algo | VOLCANIC_ROCK | VOLCANIC_ROCK_VOUCHER × 5 strikes | 1 voucher = 1 underlying. **No multiplier.** |
| **P4 R3** | algo | VELVETFRUIT_EXTRACT | VEV_4000…6500 (10 strikes) | 1 voucher = 1 underlying. Limit 300 per voucher. **No multiplier.** Brief explicitly says "give you the right to buy Velvetfruit Extract at a later point for a specific strike price" (1:1) |
| **P2 R4** manual | n/a (algo only) | n/a | — | — |
| **P3 R4** manual | suitcases | n/a (auction) | — | — |

**Prosperity has never put a multiplier on options.** Every prior options round used 1:1 (one option = one underlying-equivalent).

**Therefore the most likely interpretation of "Each contract has a contract size of 3,000":**

The 3,000 applies to the **underlying AETHER_CRYSTAL only**, as a notional-cash multiplier across the entire submitted portfolio. I.e. the score reported as `~$55 raw EV` becomes `$55 × 3,000 = $165,000 final XIRECs`. This matches the "TL;DR" caveat already in the existing writeup (line 17 of `MANUAL_R4_WRITEUP.md`).

**Alternative interpretation** (less likely but not impossible): each unit you buy/sell of *any* instrument is itself 3,000-fold (so vol cap 50 means 50 × 3,000 = 150,000 underlying-equivalents). This would be a complete break from precedent and would make a single trade move a hundred-fold of the entire P4 R3 pot. **Likely false.** P4 leaderboard PnLs at present (R3 algo top = $345k) are already gigantic; a 3,000× per-contract multiplier would put this single round into the millions.

**Recommended action:**
1. Read the full brief in the IMC UI. The phrase "contract size 3,000" is almost certainly buried in a footnote/sidebar that clarifies *what 3,000 multiplies*. Look for whether the FV display itself is in "underlying units" (mid≈50) or "notional" (mid≈150,000).
2. If the **bid/ask quotes shown in the UI are ~$50** (not ~$150,000), then 3,000 is a **score multiplier applied at the end**, not a per-quote multiplier. In that case all existing math is correct and you simply multiply final EV by 3,000.
3. If the bid/ask quotes shown are ~$150,000, then prices are quoted in notional and per-contract sizing already accounts for the 3,000.

---

## 3. Critique of existing analysis

### 3a. KO put — internally inconsistent across our own files

| File | KO put parameters | Fair value | Recommendation |
|---|---|---:|---|
| `MANUAL_R4_WRITEUP.md` | K=45, **B=35** | 0.207 (5×1M MC) | BUY 500 |
| `manual_r4_solver.py` | K=45, **B=35** | 0.207 | BUY 500 |
| `ko_precise.py` | K=45, **B=35** | 0.207 | BUY 500 |
| `quant_audit.py` | K=45, **B=35** | (re-derived) | matches |
| `cp_optimal.py` | K=45, **B=45** ⚠ | ~0 | BUY 500 (still — but wrong B) |
| `cp_optimal_results.md` | claims FV=0.207 from "user", computes MC=0 | conflict | "trust user FV" |

**The cp_optimal.py file has B=45 (knock-out at strike), which is wrong.** A K=45/B=45 down-and-out put is mathematically worthless because the moment S touches strike, the option dies — and it only pays when S < 45 at expiry. With B=45, you can only get paid if S ends < 45 *without ever having touched 45*, which is impossible (you must cross 45 to get below it). cp_optimal_results.md's "MC=0" finding is correct **for B=45**, but B=45 is the wrong barrier.

The user-stated parameters in MANUAL_R4_WRITEUP.md (K=45, B=35) yield FV ≈ 0.207, which is a valid +0.032 buy edge. **Use B=35.**

**Action:** verify on the IMC UI: does the AC_45_KO product page state barrier = 35 (writeup) or barrier = 45 (cp_optimal)? If barrier = 35, BUY 500 has +EV. If barrier = 45, BUY 500 is essentially BUY at $87.50 of nothing → SKIP.

### 3b. Position-cap / sign asymmetry

The writeup's recommendation is **6 distinct positions, all at max-cap on the edge-positive side.** This treats each instrument independently. The mathematical optimum for a "score = mean over 100 sims of total PnL" objective (no risk constraint) is exactly that: max-cap each positive-edge instrument.

If IMC's hidden scoring penalizes loss tails (e.g. "average of *positive* PnL only", or some other CVaR-flavored thing), the writeup is over-leveraged. **No public evidence either way.** R1/R2/R3 manuals all used arithmetic mean (no penalty). Default to arithmetic mean.

### 3c. "100 simulations" — likely arithmetic mean, but could be different

The challenge text apparently states "average over 100 simulations". Three interpretations:
- **(A)** Plain arithmetic mean of total PnL across 100 GBM paths — most likely (matches R1/R2/R3 manual scoring conventions).
- **(B)** Median or trimmed mean (would *lower* leverage incentive but make positive-edge picks still optimal).
- **(C)** Something with risk adjustment (rare in Prosperity history).

The 100-sim SE on the recommended portfolio is ~$127 vs EV ~$55 (per `MANUAL_R4_WRITEUP.md`). Under interpretation (A), the actual score will be `EV ± 127`, with EV positive in expectation. Under (B), the median is closer to 0 and the bet becomes less attractive. **Recommend submitting the writeup's portfolio anyway — under any interpretation in [A,B,C], a positive-edge portfolio is better than no portfolio.**

### 3d. Sigma is huge (251% annualized) — variance dominates EV

Per `cp_optimal_results.md` (table 3): for any non-trivial portfolio, sigma exceeds EV by **30-50×**. Sharpe ratios are 0.01–0.03. **The single-game outcome is path-dominated**, not edge-dominated. This is the right insight to internalize: the "EV" we compute is a long-run number; on this single 100-sim score it could come out very far from EV either direction.

The "Tier C" (3-position, EV+32, sigma 1290) recommendation in cp_optimal_results.md is **risk-adjusted superior** (lower CVaR_5%) but captures only ~60% of the EV. If the score truly is plain mean of 100 sims, **the writeup's Tier-A 6-position max-EV portfolio is correct.** If it's anything risk-adjusted, Tier C wins.

### 3e. 2-week ATM IV is mildly underpriced

`MANUAL_R4_WRITEUP.md` notes 2w IV implied = 2.470 vs stated 2.510 (1.6% discount). This is the cleanest, lowest-variance edge in the book. The 2w straddle BUY is robust to most σ misspecification. **Do not skip these even if you scale down the rest.**

---

## 4. Counter-strategy considerations (game-theoretic)

For competitive algo manuals (R1, R3 in P4) we modeled the field. **For an EV-additive options manual with no opponent dependency, no game theory matters** — your score depends only on the simulator, not on what others bid. **Just maximize EV and ignore opponents.**

Exception: if IMC scoring includes a leaderboard percentile mapping (rare), then submitting a high-variance positive-EV portfolio gives you upside on the right tail of your own simulation. The writeup's portfolio already does this.

---

## 5. Concrete next-step checklist

Order from highest ROI to lowest:

1. **Open the IMC UI for R4 manual.** Read the AC_45_KO product page. Confirm: K=45, B=35 (writeup correct) or B=45 (cp_optimal correct). **5 min, decisive.**
2. **Confirm the 3,000 multiplier semantics.** Check whether quoted prices in the UI are ~$50 (multiplier is final score scaler) or ~$150,000 (multiplier already in quotes). **2 min, decisive.**
3. **Confirm scoring rule.** Look for "average of 100 simulations" wording — confirm whether it's arithmetic, trimmed, or risk-adjusted. **2 min.**
4. If KO is B=35 and 3000× is final scaler: submit `MANUAL_R4_WRITEUP.md` Tier A portfolio (6 positions, EV ≈ +$55 raw → ~$165k after multiplier). Expected leaderboard score range: +$30k to +$300k (1σ around mean, given path variance).
5. If KO is B=45 (knock-out at strike, worthless): submit Tier A *minus* the +500 KO position (5 positions, EV ≈ +$39 raw → ~$117k). The KO leg adds only +$16 raw EV anyway.
6. **Do NOT add hedges or "smart" overlays** without a defensible model edge. Per `cp_optimal_results.md`, model EV gains over the max-cap baseline are rounding-error.

---

## 6. Open questions (require UI/Discord access)

- Is there a *single* simulation seeded by IMC, or genuinely 100 IID simulations?
- Are the 100 simulations on the **same** path (everyone scored against an identical realization) or **independent** (everyone gets their own 100)? If shared, this becomes a large-N tournament where everyone gets the same number — your relative ranking depends only on portfolio choice, not luck.
- Is the chooser exercise rule "auto-pick higher BS value at 2w" (as our solver assumes) or "auto-pick ITM side at 2w" (simpler, may differ at S near 50)?
- Are conversions enabled? (R3: no. Likely no for R4.)
- Is the underlying GBM σ exactly 2.51 in IMC's RNG, or a sampled noise variant?

**Recommend:** submit the writeup portfolio now (it's robust to most of these uncertainties), then revise if Discord chatter resolves any of the above.

---

## 7. Summary recommendation

| Decision | Recommendation | Confidence |
|---|---|---|
| Use writeup's 6-position max-cap portfolio | **Yes** | High (assuming arithmetic mean scoring) |
| KO put barrier (writeup B=35 vs cp_optimal B=45) | **Verify on UI**; default to writeup's B=35 | Medium |
| Apply 3000× multiplier expectation | **Yes**, ~$165k expected raw, but verify UI | Medium-High |
| Drop the +500 KO if B=45 confirmed | Yes — saves $87.50 cost for a known-zero payoff | High |
| Hedge with vanilla straddle | **No** — adds noise, no edge | High |
| Worry about competitor positions | **No** — non-strategic round | High |

**Bottom line: writeup is fundamentally sound, but two UI-verifiable facts (KO barrier, 3000× semantics) decide whether to submit as-is or with the small KO modification.**
