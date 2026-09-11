# YOLO Block Sanity Check — r4_final.py (v8)

**Verdict: REMOVE the YOLO regime gate.** Use `r4_v9_riskmgmt.py` (gate disabled).

## 1. The trade in plain language

At ts=3000 (3% into the day), if VFE has drifted ≤ -1.5 from open, **enter -300 on every voucher (8 strikes) + -200 VFE and hold to EOD**. Single binary commit, no exit logic, max position size on 9 instruments.

## 2. Why it works on day-3 historicals

- **Real day-3 BT**: $160,299 (vs $69,955 without YOLO) → +$90,344 marginal.
- **Real days 1/2**: gate skips (drift was +5.0 / +3.0), v8 == v7c.
- **Days 1/2 counterfactual** (analytical, if gate had fired): -$28,900 / -$47,650.

## 3. Bayesian P(day-3 regime LIVE)

Conflicting evidence:

| Source | Pulls toward | Strength |
|---|---|---|
| Memory: "day-3 = R4 live eval seed" | day-3 repeats | strong |
| Top teams $50k LIVE day-3 1k | bearish but not max-short | moderate |
| IMC admin: "no big regime change R4" | days 1/2 stable (bullish) | strong |
| 3 historical days, day-3 unique | uniform 33% | moderate |
| Days 1/2 BOTH bullish (+$20.5/+$28) | days 1/2 prior | moderate |

**Posterior estimate: P(crash regime LIVE) ≈ 0.55** — generous toward "live = day-3 seed."

## 4. Synthetic Monte Carlo (50 paths, bootstrap from real days)

`intel/yolo_synthetic_mc.py` — calibrate per-strike IVs at ts=3000 day-2, bootstrap 10k VFE returns per path, apply gate rule, compute analytical PnL via Black-Scholes.

| Prior | Gate fires | Full YOLO mean | SD | Sharpe | CVaR-5 |
|---|---:|---:|---:|---:|---:|
| A. Day-3 repeats | 42% | +$34,910 | $120,075 | **0.29** | -$263,784 |
| B. Uniform pooled | 44% | -$15,408 | $145,646 | -0.11 | -$339,990 |
| C. Days-1/2 only (bullish) | 26% | -$9,609 | $84,852 | -0.11 | -$238,768 |

**Bayesian-weighted (P=0.55 day-3, 0.45 bullish):**

| Strategy | E[PnL] | σ | Sharpe | CVaR-5 | P(loss>$50k) |
|---|---:|---:|---:|---:|---:|
| no_yolo | $0 | $0 | — | $0 | 0.0% |
| **full_yolo (v8)** | **+$14,877** | $107,983 | 0.14 | -$252,527 | **27.4%** |
| half_yolo_small (-100 each) | +$5,272 | $38,049 | 0.14 | -$88,528 | 7.3% |
| deep_itm_only (-300 × 4) | +$9,245 | $64,986 | 0.14 | -$146,393 | 18.1% |
| deep_itm + VFE | +$11,123 | $77,330 | 0.14 | -$172,508 | 21.5% |

**All YOLO variants share Sharpe ≈ 0.14** (Sharpe is invariant to size for a binary trade) — sizing only trades EV for variance.

## 5. Why YOLO fails the Frankfurt test

Frankfurt's published philosophy: with a $200k lead, cut mean-reversion size in half — accept lower EV for variance reduction. v8 baseline (no-yolo days 1/2 + voucher MM = $171k 3-day BT) is already a strong lead.

YOLO's risk profile:
- Sharpe 0.14 — well below the 0.5+ floor any prudent fund applies.
- CVaR-5 = -$253k — **single bad path wipes the entire round budget**.
- 27% probability of losing >$50k — that's coin-flip territory for catastrophic loss.
- $15k Bayesian EV is **not worth** $253k tail.

**Top-team behavior corroborates**: $50k LIVE day-3 1k is consistent with passive voucher MM + VFE Wall-Mid + HP S17 cycling — NOT with -300×8 max-short. Nobody publicly seen committing on a hardcoded ts=3000 gate.

## 6. Smaller variants don't help

Half-yolo (-100×8) and deep-ITM-only (-300×4) keep Sharpe = 0.14 and just shrink both sides of the distribution. They don't fix the fundamental issue: the gate is fitted to a single observed pattern (day-3 crash) with an n=1 confirmatory event, embedded in a 3-day sample.

## 7. Recommendation

**Ship `r4_v9_riskmgmt.py`** (v8 with `YOLO_DRIFT_THRESHOLD = -1e9`). Loses $90k on day-3-replay if it happens, gains +$253k tail-risk insurance with positive Sharpe-weighted trade.

Alternative considered and rejected: `r4_yolo_f_deep_itm.py` (-300 × {4000, 4500, 5100, 5200} only). Same Sharpe 0.14 under Bayesian mix, still exposes -$172k CVaR-5. Marginal improvement insufficient.

## 8. Falsification criteria

What would change my mind:
- IMC publishes that day-4 IS day-3 seed deterministically (P=1.0 → mean +$35k, Sharpe 0.29 — borderline).
- Live ts=3000 drift on day-4 shows ≤ -5 (very strong crash signal) — but you can't gate on that without seeing it; if known before submission, just skip the gate logic and short manually.
- Discord competitor explicitly running max-short YOLO with positive live track record ≥ $200k.

## Files

- `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/r4_v9_riskmgmt.py` — submission candidate
- `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/yolo_synthetic_mc.py` — Monte Carlo
- `C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel/yolo_mc_metrics.json` — raw metrics
