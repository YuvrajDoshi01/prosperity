# P3 2025 vs R3 2026 EDA — Day 2 cross-year comparison

**Date:** 2026-04-25
**Script:** `scripts/p3_vs_r3_eda.py`
**Source:** `previous-prosperity/p3_r3/prices_round_3_day_2.csv` (P3 historical, shared by Nancy)

## Headline corrections to Nancy's Discord analysis

| Nancy's claim | Reality (this EDA) | Verdict |
|---|---|---|
| "ATM IV ≈ 1.46%" | ATM IV = **27.02%** (annualized, T=3/250) | ❌ Off by 18× — likely TTE convention error |
| "Smile is flat (a=-5.60)" | a = **+0.12** (positive, mild U-shape) | ⚠ Partially right (flat among ATM strikes 5000-5400) |
| "Skip VEV_4000/4500 — zero time value, no spread" | dev_std 0.84 / 0.76, ac(1) = **0.003 / 0.018** | ❌ **Most scalpable strikes** — ac~0 = pure noise |
| "Deviation autocorr +0.99 (drift)" | TRUE for ATM strikes (5200-6500: ac(1) 0.96-0.997) | ✓ Correct for the strikes she analyzed |
| "Rainforest Resin ↔ HYDROGEL_PACK (OU)" | Resin half-life **0.2** ticks, HP **293.8**. Squid Ink half-life **307.4** | ❌ Wrong analog — should be Squid Ink |
| "VOLCANIC_ROCK ↔ VELVETFRUIT_EXTRACT" | Confirmed structurally similar (vouchers, OU underlying) | ✓ Correct |

## OU parameters (validates HP ↔ Squid Ink analog)

| Product | n | Mean | Stdev | Range | OU phi | Half-life (ticks) |
|---|---:|---:|---:|---|---:|---:|
| **HYDROGEL_PACK** (R3 2026) | 10,000 | 9989.40 | 31.62 | [9891, 10051] | 0.9976 | **293.8** |
| VELVETFRUIT_EXTRACT (R3 2026) | 10,000 | 5255.39 | 16.99 | [5207, 5300] | 0.9980 | 347.6 |
| RAINFOREST_RESIN (P3 2025) | 10,000 | 10000.04 | 2.15 | [9994, 10006] | 0.0147 | 0.2 |
| KELP (P3 2025) | 10,000 | 2048.75 | 1.57 | [2040, 2052] | 0.8791 | 5.4 |
| **SQUID_INK** (P3 2025) | 10,000 | 1827.49 | 28.70 | [1770, 1927] | 0.9977 | **307.4** |
| VOLCANIC_ROCK (P3 2025) | 10,000 | 10166.77 | (n/a) | (n/a) | (n/a) | (n/a) |

**Squid Ink (P3 2025) is the proper analog of HYDROGEL_PACK** — half-life 307.4 vs HP 293.8, range stdev similar. Rainforest Resin is essentially constant (range = 12 ticks over 10k samples) — nothing to learn from there.

## Volatility smile (R3 2026 day 2)

Per-strike mean IV (annualized, T = 3 days / 250):

| K | n samples | Mean IV | %ile of moneyness |
|---:|---:|---:|---|
| 4000 | 1,006 | 99.93% | deep ITM |
| 4500 | 2,774 | 56.99% | ITM |
| 5000 | 9,977 | 27.26% | mid ITM |
| 5100 | 10,000 | 26.50% | ITM |
| 5200 | 10,000 | 27.20% | ≈ ATM |
| 5300 | 10,000 | 27.73% | OTM |
| 5400 | 10,000 | 25.77% | OTM |
| 5500 | 10,000 | 28.16% | OTM |
| 6000 | 10,000 | 47.43% | deep OTM |
| 6500 | 10,000 | 72.05% | deep deep OTM |

**Smile fit** (moneyness m = log(K/S) / sqrt(T)):
```
IV(m) = 0.1208 × m² + 0.0001 × m + 0.2702
ATM IV (m=0) = 27.02%
R² = 0.9902
```

**Two-regime smile observation:**
- ATM region (K=5000–5400): IV in 25.77%–27.73% range — **truly flat**, supports Nancy's claim within this region
- Wings (K=4000, 4500, 6000, 6500): IV jumps to 50–100% — strong smile

If Nancy fit only K=5000–5400, she'd see a flat line. The full strike spectrum has a pronounced smile.

## Deviation autocorrelation — the big finding

Lag-1 autocorrelation of (market mid − BS fair using mean-IV-per-strike):

| K | dev_std | ac(1) | ac(10) | Trading implication |
|---:|---:|---:|---:|---|
| **4000** | 0.835 | **0.003** | 0.021 | **Pure noise — directly scalpable** |
| **4500** | 0.762 | **0.018** | 0.039 | **Pure noise — directly scalpable** |
| 5000 | 0.608 | 0.276 | 0.286 | Weak persistence |
| 5100 | 1.024 | 0.808 | 0.804 | Moderate drift |
| 5200 | 1.934 | 0.963 | 0.960 | Strong drift |
| 5300 | 1.836 | 0.974 | 0.969 | Strong drift |
| 5400 | 0.910 | 0.967 | 0.952 | Strong drift |
| 5500 | 0.748 | 0.977 | 0.930 | Strong drift |
| 6000 | 0.097 | 0.997 | 0.979 | Frozen at floor |
| 6500 | 0.067 | 0.997 | 0.980 | Frozen at floor |

**The autocorrelation is BIMODAL across the strike spectrum:**
- **Deep ITM (4000, 4500): ac(1) ≈ 0** → mid-vs-fair deviations are pure noise → **scalp it**
- ATM (5100–5500): ac(1) ≈ 0.96–0.98 → highly persistent → don't scalp, MM around fair
- Deep OTM (6000–6500): ac(1) ≈ 0.997 → frozen at near-zero → no edge

**This validates our v17 Phase 4.1 theta carry alpha** (+$233 live on VEV_4000/4500). Those deep-ITM strikes have scalpable bid-ask deviations precisely because the autocorrelation is ~0. Nancy's "skip 4000/4500" recommendation was wrong — they're the *most* scalpable strikes.

## P3 2025 reference numbers (VOLCANIC_ROCK vouchers, day 2)

| K | Mean IV | dev_std | ac(1) |
|---:|---:|---:|---:|
| 9500 | 18.99% | 0.413 | 0.411 |
| 9750 | 15.02% | 0.694 | 0.404 |
| 10000 | 13.34% | 2.120 | 0.311 |
| 10250 | 13.10% | 2.697 | 0.988 |
| 10500 | 14.20% | 1.536 | 0.982 |

P3 ATM region (K=10000-10250) had dev_std comparable to R3's (1.5-2.7 vs R3's 1.8-1.9). Smile shape: ATM ~13%, wings rising to 18%. Same flat-with-wings pattern as R3 but at lower vol.

## Strategy implications for v18+ (R4 prep)

1. **Keep Phase 4.1 theta carry on VEV_4000/4500** — empirically validated by the autocorr finding. Nancy's recommendation to skip them is wrong on this dataset.

2. **MM around BS fair only on ATM region (5100-5500)** — autocorr 0.8-0.98 means deviations drift, single-sigma BS-anchored MM with delta hedge can work.

3. **Skip K=6000/6500** — Nancy correct; ac(1)=0.997 with dev_std~0.07 means the market essentially never deviates from "essentially zero" — no edge.

4. **HP analog should be Squid Ink (P3 2025), not Resin** — same OU half-life (~300 ticks). Any P3 strategy on Resin is irrelevant; any on Squid Ink is portable.

5. **TTE convention matters** — Nancy's IV numbers used a different convention. We use T = days/250 (standard 250-trading-day year). Document and stay consistent.

## Files referenced

- Source CSVs: `previous-prosperity/p3_r3/{prices,trades}_round_3_day_{0,1,2}.csv`
- EDA script: `scripts/p3_vs_r3_eda.py`
- Live validation of Phase 4.1: `run-logs/round-3/405628.zip` (sub 405628, +$233 from VEV_4000/4500)
- Memory: `memory/reference_p3_2025_data.md` (Nancy's analysis), `memory/project_round3_v17_validated.md` (live results)
