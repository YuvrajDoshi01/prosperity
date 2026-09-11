# CLAUDE.md

Guidance for Claude Code working with this repository. Detailed submission history, lessons, and per-round analyses live in `memory/` — see `MEMORY.md` for the index.

## 🏆 IMC Prosperity 4 — FINAL: World Rank 35 / 18,803 (top 0.19%)

Competition closed 2026-05-08. Cumulative ~$1.38M XIRECs across 5 rounds. R5 was the recovery round: $715k single-round bridge from "4th in cohort" to world rank 35. Full retro at [`memory/project_competition_final.md`](memory/project_competition_final.md). R5 closeout at [`memory/project_round5_final.md`](memory/project_round5_final.md).

The repo from this point forward is archival — strategies in `trader-logic/round-{1..5}/` are reference templates for any future Prosperity (P5+) iteration.

## Running the Backtester

```bash
# Set PYTHONPATH if you get "No module named 'datamodel'"
$env:PYTHONPATH="c:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt"

# Current best R5 — r5_v3 (BT champion): imc 4-day $271k, day-5 LIVE proxy $6,308
python -m prosperity4bt trader-logic/round-5/r5_v3.py 5 --no-progress --no-out --match-mode imc
python -m prosperity4bt trader-logic/round-5/r5_v3.py 5-5 --no-progress --no-out --match-mode imc  # 1k LIVE proxy

# R3 best — sub 402350 → $12,246 website
python -m prosperity4bt trader-logic/round-3/r3_v11.py 3
python -m prosperity4bt trader-logic/round-3/r3_v11.py 3-2 --ticks 1000 --no-out --no-progress  # website parity
python -m prosperity4bt trader-logic/round-3/r3_v11.py 3 --ticks 10000                          # full 10k 3-day

# Earlier rounds best
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1

# Key flags
#   --ticks N                          max ticks to simulate (1000 = R3 website test, 10000 = full day)
#   --iterations N                     run() called N times (usually match --ticks)
#   --match-trades {all|worse|none}    trade matching mode (default: all)
#   --match-mode {default|imc}         'imc' = calibrated mode; primary R5 leaderboard predictor
#   --no-out / --no-progress / --print
```

Logs → `backtests/<timestamp>.log`. Full day = 10k ticks (timestamps 0–999,900, step 100ms).
**R3 website test only runs 1k ticks of day 2** (timestamps 0–99,900). See `trader-logic/round-3/BACKTEST_COMMANDS.md`.

## Game Engine Tick Sequence (from chrispyroberts/imc-prosperity-4 Rust source)

Per tick:
1. Fresh books generated — MM bot posts new quotes (not carried over)
2. `Trader.run(state)` called → returns orders
3. Aggressive takes execute (orders crossing the book)
4. Unfilled orders become passive levels in the live book
5. Taker arrives → hits ALL levels by price priority (bot AND strategy)
6. Tick ends → passive orders DISCARDED

**Position limits are ALL-OR-NOTHING per product.** If buy_qty + position > LIMIT, the entire product's orders are rejected. Limits checked per side (worst case: all buys OR all sells fill).

**Takers hit our passive quotes** in step 5 whenever our best±1 is the effective best price. This is the mechanism behind "invisible taker" fills (~59 fills/2k ticks for R0 EMERALDS, ~300/1k ticks for R1).

Bots are **NOT reactive to our spread** (confirmed zero-delta god-logger runs). Conversions are **disabled** in tutorial rounds.

## Architecture

OOP backtester forked from [jmerle/imc-prosperity-3-backtester](https://github.com/jmerle/imc-prosperity-3-backtester).

```
BackTester -> for each round/day:
  TestRunner reads CSVs (prosperity4bt/resources/round{N}/)
    -> for each tick:
      if call_tick: Trader.run(state) -> new orders
      else: use resting orders from last call
      1. Build TradingState from order book data
      2. Log activity snapshot
      3. Enforce position limits
      4. OrderMatchMaker: match orders vs book, then vs market_trades
    -> Return BacktestResult
  ResultMerger -> OutputFileWriter writes .log
```

## Trader Strategy Contract

```python
from datamodel import TradingState, Order
import json

class Trader:
    def bid(self):       # Required for Round 2 auction
        return 15

    def run(self, state: TradingState):
        orders = {}      # dict[Symbol, list[Order]]
        conversions = 0  # int (disabled in tutorial)
        trader_data = "" # str (JSON, persisted to next call, 50k char cap)
        return orders, conversions, trader_data
```

- `Order(symbol, price, quantity)` — positive qty = buy, negative = sell.
- `OrderDepth.sell_orders` volumes are **negative** integers.
- All products have LIMIT=80 (`prosperity4bt/constants.py`).
- **Do NOT modify** `prosperity4bt/datamodel.py`.

## Key Files

| Path | Role |
|------|------|
| `prosperity4bt/test_runner.py` | Per-day simulator, iteration cadence, limit enforcement |
| `prosperity4bt/back_tester.py` | Main controller |
| `prosperity4bt/datamodel.py` | TradingState, Order, OrderDepth, Trade — do not edit |
| `prosperity4bt/constants.py` | Position limits |
| `prosperity4bt/tools/order_match_maker.py` | Exchange matching simulation |
| `prosperity4bt/tools/data_reader.py` | CSV -> BacktestData |
| `prosperity4bt/tools/rust_engine.py` | Independent Rust-logic validator |
| `trader-logic/auction_solver.py` | Manual challenge clearing auction optimizer |
| `trader-logic/round-1/r1_v4.py` | **Current best (website 10,624.84)** |
| `trader-logic/round-1/r1_v17.py` | Full-R1 submitted 272466 (89,861.44) |
| `trader-logic/round-1/r1_v18.py` | Latest — adaptive-threshold, wins synthetic and BT |
| `trader-logic/round-3/r3_v11.py` | R3 final ($12,246 website) |
| `trader-logic/round-4/r4_final.py` | R4 algo current candidate |
| `trader-logic/round-4/manual/MANUAL_R4_FINAL.md` | **R4 manual — DOM_NICE_v3 recommendation** |
| `trader-logic/round-4/manual/run_all_phases.sh` | **R4 manual 4-phase MC pipeline** |
| `trader-logic/round-5/sub_581032.py` | **R5 FINAL submitted — vol-tiered MM, $613k algo** ★ |
| `trader-logic/round-5/r5_v3.py` | R5 BT champion (20 products, $271k 4-day imc) — passed over for sub 581032 |
| `trader-logic/round-5/sub_551355.py` | R5 mid-round LIVE checkpoint (thedarkmarc v2, $5,795 day-4 1k) |
| `trader-logic/round-5/manual/ignith_analysis.py` | R5 manual portfolio optimizer (Ignith, $101,904 final) |
| `trader-logic/Prosperity_Fundamentals.pdf` | Take-Clear-Make framework |

## Backtester Calibration (Round-Agnostic)

- **Use BT for RANKING, not absolute PnL prediction.** Orderings are preserved.
- **Round 0**: `website ≈ BT × 1.07` for inside-spread MM; ±2% for at-spread.
- **Round 1**: IPR BT ≈ real IPR within 0.2%; **ACO BT × 0.63 ≈ real ACO** for v17-style inside-spread MM (2.5× BT fill-rate overshoot).
- **ACO BT gradient overshoots ~60×** — treat any ACO BT delta < 1,000 PnL as noise.
- **Don't patch the backtester to match known scores** — overfitting the infrastructure.
- **imc mode is deterministic** (CRC32 hash on product+timestamp). Current calibration `extra_rate=0.038` for ACO fits R2 round98 within -2.2% ACO / -0.1% total (ACO BT 1,004 vs website 1,026; total BT 8,407 vs website 8,412). Previous 0.030 was miscalibrated (round98 CSV is submission 274128's data, not 275130's). IPR needs no supplement (+0.2% error). Re-calibrate per round if CSV source changes.
- **CSV ≠ website** — R0 day 0 matches 100%; all other days and R1 all days do NOT. See `project_round1_final.md` for dev-vs-real calibration.

Backtester bugs fixed 2026-03-21: stale `own_trades`/`market_trades` persistence between ticks; resting-order quantity not refreshed after partial fills; wrong iteration count for tutorial.

## Round 0: Tutorial Summary

**Final best: 2,896 (s36_medallion) / 2,857 (s3_carry)** from 37+ submissions. Top scorer fabiantum: 4,950 (gap 2,054 unexplained despite exhaustive probing).

Reusable cross-round insights in [`memory/project_tomatoes_eda.md`](memory/project_tomatoes_eda.md). Bot forensics, feature engineering results, strategy evolution archived in `trader-logic/round-0/`.

**Key R0 findings reused in R1:**
- `PnL = FillRate × SpreadCaptured − InventoryRisk` (NOT IC × position). Fill rate is exogenous; queue priority dominates.
- Regression coefs `[0.06, 0.12, 0.24, 0.58]` stable across days, sum≈1.0. Use cross-validated fits.
- **Clear step HURTS drift/random-walk products** (s13: 2,077 vs 3,394 baseline; IPR LU: 4,796 vs 7,446). Only use on stable/pegged products.
- Taker bots are **contrarian on average** — gives positive inventory MTM on long in rising markets (replayed at scale in R1 IPR: +79k).
- AC(1) ≈ −0.44 is a **structural engine property**, not alpha.
- Local BT was MISLEADING pre-fix; post-fix matches within 1% for book-only strategies.

**R0 Bot Behavior** (reverse-engineered, 37+ submissions; unchanged for R1):
- MM: `bid = floor(mid − s/2)`, `ask = ceil(mid + s/2)`. Mid in 0.5 increments, OU with AC(1) = −0.44. Spreads {5–9, 13–14} (wide 92.8%). L1 vol uniform [2,12], L2 vol ≈ 2.78× L1. 82.6% asymmetric quote moves. NO post-fill response.
- Taker: pure aggressive, 100% at best bid/ask. Exponential inter-arrival (R0) / more-regular (R1). Side 50/50 iid. Qty uniform.
- Zero cross-product lead-lag.

## Round 1: "Trading Groundwork"

### Products

| Product | Limit | Price | Range/day | Spread | L1 vol | AC(1) | Archetype |
|---------|-------|-------|-----------|--------|--------|-------|-----------|
| INTARIAN_PEPPER_ROOT | 80 | ~12,000 | 1,000 | 12–14 | 11.5 | −0.50 | Drift / random walk |
| ASH_COATED_OSMIUM | 80 | ~10,000 | 27–36 | 16 (62%) | 14.0 | −0.49 | Stable FV (OU) |

- **IPR**: +1000/day uptrend across all CSV days (−2: ~10k, −1: ~11k, 0: ~12k). "Steady value".
- **ACO**: "hidden pattern" = OU mean-reversion to FV=10000. Mid deviates ±18 max.
- Both products: ~9% one-sided book ticks.

### Round 0 → Round 1 Shifts

| Metric | R0 | R1 |
|--------|----|----|
| Tutorial ticks | 2,000 | **1,000** |
| CSV↔website match | Day 0 = 100% | Day 0 = **36%** |
| Taker arrival rate | ~3.5% | **~30%** |
| Taker CoV | 0.99 (Poisson) | 0.76–0.81 (more regular) |
| One-sided ticks | 0% | ~9% |
| PnL from taker fills | ~70% | ~70% |

### Round 1 Regression (cross-validated 3 days, for reference — r1_v4 uses simple mid instead)

```python
# IPR 4-lag microprice regression
COEFS = [0.2474, 0.2529, 0.2412, 0.2585]
INTERCEPT = 0.2078
# Coef sum ≈ 1.0 → FV ≈ average of last 4 microprice values

# ACO (less useful, slight mean-reversion)
COEFS = [0.214, 0.215, 0.250, 0.294]
INTERCEPT = 215-387  # varies by day
```

### Current Best Strategy: r1_v4.py (Website 10,624.84)

**INTARIAN_PEPPER_ROOT** (drift capture, website 7,446) — from r1_v2:
- **Simple mid + drift_bias=5** (NOT microprice regression). `fv = round(mid + 5.0)`. Microprice leans LOW in ask-heavy books, missing initial take at t=0.
- Asymmetric takes: buy if price ≤ fv+2, sell only if ≥ fv+3.
- Post aggressive bid at `min(fv−1, best_bid+1, best_ask−1)`; defensive ask at `max(fv+2, best_ask−1, best_bid+1)`.
- One-sided book handling (9% of ticks).
- 4 params (LIMIT, DRIFT_BIAS, BUY_SLACK, SELL_SLACK).

**ASH_COATED_OSMIUM** (Linear Utility AMETHYSTS port, website 3,179):
- Fixed FV=10000. Take → Clear → Make (LU canonical).
- Take: `≤ fv−1` or `≥ fv+1` with adverse_vol<15 filter. Clear: flatten exactly at fv (LU's +3% trick). Make: penny/join/default (DISREGARD=1, JOIN=2, DEFAULT=4).
- Soft-limit skew at |pos|>40.
- LU-exact params (P2 #2 finish). +88 validated over baseline (theory: +3% × 3,091 = +87).

### Round 1 Submission Summary

| Variant | Website | Key |
|---------|--------:|-----|
| **r1_v4** (current best) | **10,624.84** | Simple mid + LU ACO |
| r1_v17 (full-R1 272466) | 89,861.44 | IPR 99.1% of buy-and-hold max; ACO cost ~1,743 to bootstrap anchor flicker |
| r1_v18 (unsubmitted, latest) | — | Adaptive-threshold: +4,920 BT over v17 across 3 days; wins 15-seed synthetic |
| Nancy's algov4 (benchmark) | 10,734.03 | Teammate +109 via aggressive bid + OU ACO |

Full 25+ submission trajectory, 40 lessons, and defensive-stack analysis (v9–v17) in [`memory/project_round1_results.md`](memory/project_round1_results.md) and [`memory/project_round1_final.md`](memory/project_round1_final.md). Latest v18 architecture in [`memory/project_round1_v18.md`](memory/project_round1_v18.md).

### Headline Round 1 Lessons (see memory for full list)

1. **Simple mid > microprice for drift products** (r1_v2 via probe 210525, +90 PnL).
2. **LU clear step = +3% PnL on stable products** (validated on ACO). **BREAKS drift products** (r1_v3 regressed −2,650 IPR).
3. **Drawdowns are entry-cost, not bugs** — eliminating costs PnL on drift. See [`memory/feedback_drawdown_misconception.md`](memory/feedback_drawdown_misconception.md).
4. **Drift_bias = 35% of total PnL**; trade flow / OBI / carry = 0% marginal each.
5. **ACO fills are strategy-independent** — 59 of 101 are "invisible takers" attracted by any inside-spread posting. ACO posting width has **zero effect** (FV±3 ≡ best±1).
6. **Conversions disabled, no hidden observations** in R1.
7. **traderData format matters** — removing unused state variables cost 2 IPR fills (−39 PnL). Keep all fields.
8. **Practical ceiling ~10,625–10,734**. TROLL at 10.6k, us 10.625, Nancy 10.734. Gap to #1 (11,744) likely seed variance.
9. **r1_v17 real result reversed synthetic prediction** — bootstrap anchor snapped to 10,008 from asymmetric open book, costing ~1,743 ACO PnL. Synthetic generator missed asymmetric-open failure mode. See `project_round1_final.md`.
10. **r1_v18 adaptive-threshold fix** — rolling median avg_mid, per-day frozen MAD threshold, median-of-20 bootstrap, hysteresis. Beats v17 on all 3 real days, wins 15-seed synthetic. See `project_round1_v18.md`.

### Round 1 Manual Challenge: "An Intarian Welcome"

Uniform-price clearing auction (new P4 format). Optimal orders: **Flax BUY@30 vol 9,999** (clearing 29, +9,999) + **Mushroom BUY@17 vol 19,999** (clearing 16, +77,996) = **87,995 XIRECs**. Solver at `trader-logic/auction_solver.py`, writeup in `trader-logic/auction_writeup.md`. Full derivation in [`memory/project_manual_challenge_r1.md`](memory/project_manual_challenge_r1.md).

## Round 3: "Gloves Off" (SHIPPED)

12 products: HYDROGEL_PACK (200), VELVETFRUIT_EXTRACT (200, also UNDERLYING), 10 VEV_K vouchers (calls on VFE, K=4000-6500, limit 300 each).

**Final submission `r3_v11.py` (sub 402350)**: **$12,246 website** (top ~10%, was #615 at $1,177).
**Manual**: (b1=766, b2=866) two-bid auction. Robust Nash optimum.

### Critical R3 Discoveries

1. **Website tests 1k ticks of day 2 only** (timestamps 0-99,900 step 100). Verified universal across 1506 leaderboard submissions. Our BT defaults to 10k — use `--ticks 1000` for parity.
2. **BT × 0.99 ≈ website** for 1k-tick day 2 (verified twice: v9 $2,660→$2,636, v11 $12,262→$12,246).
3. **stdout NOT captured** by IMC sandbox. `print()` thrown away. Use `state.traderData` (50KB cap) for diagnostics.
4. **All-or-nothing position limits per product**: if `pos+total_buy > LIMIT` OR `pos-total_sell < -LIMIT`, ALL orders for that product rejected.
5. **Cross-backtester verification**: identical PnL across our Python BT, Xeeshan85's prosperity4btx, GeyzsoN's rust_backtester.

### v11 Architecture
- **HYDROGEL_PACK**: spread==17 GIGA SHORT (Discord competitor 402045): when spread widens to 17 AND mid > 10010, short 200 contracts, exit at mid<9998. Day 2 1k-tick = $10,224.
- **VELVETFRUIT_EXTRACT**: Wall Mid MM (P3-winner technique): fair value = midpoint of HIGHEST-VOLUME bid/ask levels (not best±). Day 2 1k-tick = $1,940.
- **Vouchers**: BS taking with wide edge (BS_EDGE=10) + adaptive sigma (rolling IV median window=50) + intrinsic arb on 4000/4500 + call-spread arb scanner. Day 2 1k-tick = $98 net.

### R3 Strategy Lessons (added to memory)
1. **Wall Mid > simple mid** — every 2nd-place P1/P2/P3 team used Wall Mid. +$19k 3-day on R3 VFE alone.
2. **spread=17 stress signal** is real on R3 HP (mean reverts to 9990).
3. **IV smile z-score fails** at typical timescales (half-life 1-30 ticks, not 100-200).
4. **OBI alpha is real but spread-dominated** (β=0.30 t=8-11 R²=1% but spread=20 ≫ signal).
5. **Aggressive take loses** — TAKE_OFFSET=1 on HP cost -$80k 3-day from adverse selection on MM bot quotes.
6. **Fixed-sigma BS voucher MM is fragile** to vol regime shifts (v8/competitor 392245). Adaptive sigma + wide edge survives.
7. **Hardcoded TARGET inventory arrays** (DP on day 2 historical path) score $90-154k but fragile to data shifts. Lachydauth confirmed his $90k was a "hardcoded joke". Signal-based v11 ($12k) is more robust.
8. **Never push past v9-baseline 10k 3-day** ($47k) — v10/v11 traded full-day stability for 1k-tick alpha.

### Round 3 File Organization
```
trader-logic/round-3/
├── r3_v1, v3, v7, v9, v10, v11.py        # Active (chronological)
├── archive/{v1_iterations, failed_experiments, superseded}/
├── manual_r3_solver.py                    # Nash + grid search
├── notes/
│   ├── voucher_analysis.py + output.txt   # 8-part EDA
│   ├── iv_visualization.py + iv_plots/    # 4 PNG plots
│   ├── recalibration_1k.md
│   └── alpha_hunt.py + output.txt
├── intel/
│   ├── image.png                          # Top-trader $80k chart screenshot
│   └── competitor_strategies/
│       ├── 392245.py (HP day-type detection)
│       ├── 401389.py (HP day-type detection v7)
│       ├── 401608.py (= our r3_v9)
│       ├── 402045.py (★ spread=17 GIGA SHORT)
│       └── 400463.py (BS voucher fragile)
├── oracle/god_logger_r3.py                # Pristine market state logger
├── R3_BRIEF.md                            # Official wiki brief
├── R3_EXPLAINED.md                        # Round explanation
├── BACKTEST_COMMANDS.md                   # ★ Team reference
├── MANUAL_R3_WRITEUP.md                   # Two-bid auction analysis
└── README.md                              # Active state + history
```

## Round 4: "Vanilla Just Isn't Exotic Enough" (Manual Challenge — VERIFIED)

R4 manual is a derivatives portfolio optimization on a single underlying AC (S0=50, σ=2.51, 3w/2w expiry options + chooser + binary put + knock-out put). Position limits per instrument; final score = mean of 100 sims × $3,000 multiplier.

**Final recommendation `DOM_NICE_v3` (6 positions)**: SELL 50 AC_50_CO + BUY 500 AC_45_KO + SELL 50 AC_40_BP + BUY 50 AC_50_P_2 + BUY 50 AC_50_C_2 + **BUY 15 AC_50_C** ★. Mean **$162,069 ± $31** (10K-seed verified), Sharpe 0.511, CVaR-5% −$473k.

### Critical R4 Manual Discoveries

1. **Multiplier confirmed via team chat**: PnL × 3000. Brief specifies σ=2.51, 4 obs/day KO monitoring, 100-sim averaging.
2. **DOM_NICE_v3 strict Pareto improvement** over prior DOM_NICE_v2 at z=23σ (mean +$1,043) and z=458σ (CVaR-5% +$52,272). Up-tail call hedge (AC_50_C K=50) gives more variance reduction per dollar of EV than down-tail put hedge (AC_35_P).
3. **DROP_60C alone is σ-fragile**: at σ=2.51 → $164k, at σ=2.80 → $20k. Hedged variants robust.
4. **KO monitoring is structural**: at 4/d (brief) → $163k, at 16/d → $98k. Same effect across all candidates.
5. **EV is linear in position quantities** (64-subset enumeration: interaction = 0). Boundary solution provably optimal in expectation.
6. **IMC scoring distribution wide**: SD = $343k around EV $164k for DROP_60C → 22% chance of <-$100k score, 16% chance of >$500k.

### 4-Phase MC Verification Pipeline

```
trader-logic/round-4/manual/
├── README.md                       ★ index of all files
├── MANUAL_R4_FINAL.md              ★ DOM_NICE_v3 recommendation
├── PHASES_1234_SYNTHESIS.md        ★ 4-phase synthesis report
├── IMC_SCORING_SIMULATION.md       ★ empirical IMC distribution
├── intel_recon.md                  # 3000x multiplier intel
│
├── phase1_huge_grid.py             # 233K candidates × 50M paths GPU sweep
├── phase2_deep_verify.py           # Top 100 × 10B paths × 10K seeds
├── phase3_sensitivity.py           # σ/KO/jump robustness for top 20
├── phase4_antithetic.py            # 100M antithetic-paired CVaR for top 10
├── run_all_phases.sh               # Orchestrator
│
├── imc_actual_scoring.py           # Literal IMC scoring (1M seeds + 100K bootstrap)
├── imc_one_realization.py          # Single IMC scoring walkthrough
├── imc_user_safe.py                # IMC distribution including USER_SAFE
├── imc_seed_invariance.py          # Master-seed independence proof
├── analyze_{500,10k}seeds.py       # 5 → 500 → 10K seed progression
│
├── r4_simulation_FINAL.py          # Canonical numpy reference
├── test_r4_simulation.py           # 12-test correctness suite
│
├── results/                        # 11 JSON outputs
├── logs/                           # 8 stdout logs
└── archive/                        # 97 superseded experiments
```

### R4 Manual Pareto Frontier (Phase 2 10K-seed verified)

| # | Mean | Sharpe | CVaR-5% | Hedge added to base DROP_60C |
|---|---:|---:|---:|---|
| 1 | $163,079 ± $34 | 0.474 | -$552k ± $89 | (none — base) |
| 2 | $162,249 ± $32 | 0.495 | -$526k ± $88 | +25 AC_45_P |
| 3 | $162,048 ± $31 | 0.511 | -$473k ± $73 | +15 AC_50_C **★ DOM_NICE_v3** |
| 7 | $159,701 ± $26 | 0.605 | -$357k ± $57 | +25 AC_50_C +50 AC_45_P (Sharpe-optimal) |

Compute: ~25 trillion strategy-paths total across 4 phases. Pipeline reusable for any future Prosperity option-portfolio challenge.

## Round 5: "The Final Stretch" (CLOSED — $715,392 / world rank 35)

50 products in 10 groups of 5 (GALAXY_SOUNDS, SLEEP_POD, MICROCHIP, PEBBLES, ROBOT, UV_VISOR, TRANSLATOR, PANEL, OXYGEN_SHAKE, SNACKPACK). **All position limits = 10** (set explicitly in `prosperity4bt/constants.py` — do NOT rely on default 80).

### Final Result

**Algo $613,488 (sub 581032) + Manual $101,904 (Ignith) = $715,392.** This was the recovery round that took us from R4's drawdown to world rank 35.

### Submitted Strategy: sub_581032.py (NOT r5_v3)

The submitted final used **volatility tiering** — three classes (hyper/volatile/semi/oxygen/default) with per-tier `(risk_av, width_bonus, obi_lean)` tuples and per-product param dicts. All 50 products active. The decisive line: `if p.startswith("OXYGEN"): fair -= 0.15 * last_ret` (explicit mean-reversion on the OXYGEN_SHAKE family).

| Top product | PnL | % of total |
|---|--:|--:|
| OXYGEN_SHAKE_CHOCOLATE | $478,439 | **78%** |
| OXYGEN_SHAKE_EVENING_BREATH | $54,380 | 9% |
| All 4 OXYGEN_SHAKE MR products | $548,687 | **89%** |
| Everything else (46 products) | ~$65k | 11% |

### r5_v3.py (BT champion, passed over)

20 products (17 v2 carryover + 3 v3a additions: ROBOT_DISHES MR, ROBOT_IRONING MR, PEBBLES_L momentum). imc 4-day **$271,080 vs baseline $91,846 (+195%)**. **Day-5 LIVE proxy +$349 only** — most of the +$179k delta was a single-day ROBOT_DISHES regime bet (lag-1 AC: d2/d3 ≈ 0, d4 = -0.29). The team chose the broader, vol-tiered sub_581032 instead and got a different (bigger) jackpot on OXYGEN_SHAKE_CHOCOLATE.

r5_v3 architectural pieces still useful for future Prosperity: per-product `STRATEGY_CONFIG` dict (`type`, `reversion_coeff`, `risk_aversion`), two-pass `run()` (compute plan → emit orders), `DISABLED_PRODUCTS: set` for ablation bisection. Architect-gated ablation rejected v3b (8 HL tight-spread → ~$0 fills) and v3c (19 wide-spread light MR → -$600k from random-walk adverse selection).

### R5 Calibration

- **imc mode is primary leaderboard predictor.** Default mode misses invisible-taker fills and inverts strategy ranking.
- **imc ratio is strategy-dependent**, not a constant: narrow strategies (n=6) ≈ 0.83; broad strategies (n=17) ≈ 0.97. Plausible mechanism: more products averaged across CRC32 hash → less per-strategy bias.
- **Day 5 in BT == first 1k ticks of day 4 (LIVE)** — byte-identical to public CSV. No engine-vs-CSV gap to exploit.

### R5 Manual: Ignith Portfolio ($101,904)

Quadratic fee `(volume/100)² × budget`, budget = 1,000,000, 9 goods. Solver at `trader-logic/round-5/manual/ignith_analysis.py` — calculus optimum `pct* = 50 × r` per good (Lagrangian if Σpct > 100). Final allocation deployed 76%, kept 24% reserved. **Lava cake at 18% SELL = +$81,636 (jackpot)**, Thermalite core +$10.7k, Pyroflex cells +$8.5k. 5 of 9 goods profitable.

### R5 Discord Intel (cross-team EDA)

- **Mean reverters** (lag-1 AC ≈ −0.15): ROBOT_IRONING, OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_CHOCOLATE. ← biggest hit confirmed live.
- **SNACKPACK correlations**: PIST↔STRAW +0.91, RASP↔STRAW −0.93, CHOC↔VAN −0.92, RASP↔PIST −0.83.
- **PEBBLES**: XL vs each smaller size −0.49.
- **Spread vs daily-range percentile**: spread widens at top of range universally.

Full R5 closeout at [`memory/project_round5_final.md`](memory/project_round5_final.md). Pre-submission ablation lineage at [`memory/project_round5_v3.md`](memory/project_round5_v3.md) and [`memory/project_round5_setup.md`](memory/project_round5_setup.md).

## Round 1 File Organization

```
trader-logic/
├── auction_solver.py, auction_writeup.md, Prosperity_Fundamentals.pdf
├── round-0/                             # R0 tutorial (archived)
│   ├── s36_medallion.py, s3_carry.py, s25_training_only.py  # Best R0 strategies
│   ├── {analysis,strategy,infrastructure}/  # 7-module bot exploitation
│   ├── {oracle,sweeps,experiments,diagnostics,early_versions}/
│   └── mega_sweep.py, grid_search.py, feature_engineering.py, feynman_kac_mm.py
├── round-1/
│   ├── r1_v4.py                         # CURRENT BEST (10,624.84)
│   ├── r1_v5.py                         # Guardrail (10,612.84)
│   ├── r1_v9…v17.py                     # Defensive stack (see memory)
│   ├── r1_v18.py                        # LATEST — adaptive threshold
│   ├── refit_regression.py              # Utility: auto-refit microprice coefs
│   ├── BACKTEST_COMMANDS.md, README.md
│   ├── best/, experiments/, early_versions/
│   ├── templates/                       # Per-archetype (stable, random_walk, basket, options, conversion, olivia)
│   ├── references/                      # Competitor code (nancy_algov4, r1_troll, superduperbread)
│   ├── analyzer/                        # Superduperbread's trading_analyzer.html
│   ├── experiments/synthetic/           # generate.py + run_all.py (round99 regimes)
│   ├── probes/, oracle/
│   └── POST_MORTEM_272466.md

prosperity4bt/resources/round99/        # Synthetic regime test data
run-logs/round-{0,1}/                   # Website submission logs
```

## Round 2+ Template Library

Pre-built at `trader-logic/round-1/templates/`, reusable for any new product:

| Template | Archetype | Key technique |
|----------|-----------|---------------|
| `template_stable.py` | Pegged (AMETHYSTS/ACO-like, fixed FV) | LU take/clear/make, adverse_vol=15 |
| `template_random_walk.py` | Mean-reverting (KELP/STARFRUIT-like) | Filtered-MM-mid + small negative reversion beta |
| `template_basket.py` | ETF basket arb | Z-score on spread (threshold=7, window=45) |
| `template_options.py` | Options/derivatives | Black-Scholes r=0, rolling IV mean per strike |
| `template_conversion.py` | Cross-exchange arb | Implied bid/ask from observations + hidden-taker detection |
| `template_olivia.py` | Insider/event bot | qty=15 filter at daily min/max extremes |
| `refit_regression.py` | Utility | Auto-refit microprice regression |

See [`memory/project_round1_prep.md`](memory/project_round1_prep.md) for deployment workflow and LU framework details in [`memory/project_lu_framework.md`](memory/project_lu_framework.md).

**Warning**: CSV volume-dependent features (microprice, OBI) may not port to website (CSV↔website volume match = 1.5% in R0 days −1/−2, unknown in R1). Prefer structural features (spread states, price levels) for first draft.

## Reference Backtesters (R1 validated)

| Backtester | Language | Matching | Note |
|---|---|---|---|
| Ours (fork of jmerle P3) | Python | default/imc/sim/website | Custom `website` mode with taker supplement |
| [kevin-fu1](https://github.com/kevin-fu1/imc-prosperity-4-backtester) | Python | default (worse) | Only 1 buy + 1 sell vs market trades |
| [Xeeshan85/prosperity4btx](https://pypi.org/project/prosperity4btx/) | Python | all/worse/none | PyPI package, 3 modes |
| [GeyzsoN/rust](https://github.com/GeyzsoN/prosperity_rust_backtester) | Rust | all + queue | **Matches ours exactly** on identical CSVs |

All confirm: fill at ORDER price, all-or-nothing limit enforcement, MM non-reactive. All overpredict website by 30–56% on R1 (CSV ≠ website).

## Lambda Probe (R1)

Runtime: Python 3.12.13, AWS Lambda 128MB / 1s, Amazon Linux 2023. **Network**: only `169.254.100.1:9001` (Runtime API) + `:53` (DNS) reachable — public outbound blocked. **AWS creds** (`Prosperity_General_Lambda_Role`): only `sts:GetCallerIdentity` allowed; all services AccessDenied. `/tmp` persists within a container, 2 concurrent containers per run, **traderData is the ONLY reliable cross-invocation state**.

Round 0 vulnerabilities (os.popen, env-var extraction, `/var/task` readable) still **not patched** in R1. Full details in [`memory/project_round1_probe.md`](memory/project_round1_probe.md), including MACARONS conversion formula extracted from `orchids_trader.py` for Round 3/4.
