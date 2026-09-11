# Round 5 — "The Final Stretch"

50 products in 10 groups of 5, **all position limit = 10**. Days 2/3/4 historical, IMC live runs day 4 1k as the leaderboard probe.

## Files

| Path | Role |
|---|---|
| `r5_v3.py` ★ | **NEW BEST BT** — 20 products. imc 4-day **$271,080 (+$179k vs baseline)**. Day 5 LIVE proxy $6,308 (+$349). Adds ROBOT_DISHES + ROBOT_IRONING + PEBBLES_L. Architect-gated ablation. |
| `sub_551355.py` | Current best LIVE — thedarkmarc v2, 17-product. Live $5,795 day-4 1k. imc BT $5,959 → 0.97 ratio. |
| `thedarkmarc_do_nothing.py` | thedarkmarc v1 — 6-product. Live sub 551021 = $1,725. imc BT $1,433 → 0.83 ratio. |
| `oracle/god_logger_r5.py` | Zero-order trader using standard Logger.flush — submit to capture pristine live state. |
| `r5_v3_alphas.txt` | Per-product AC(1) statistics (computed from R5 days 2/3/4). |
| `archive/lab_v1_to_v11/` | Earlier all-50-product penny-MM iterations with `LIMIT=80` bug. Reference only. |

## Live calibration (n=2 datapoints, 2026-04-29)

| Sub | Strategy | Products | Live | imc BT | imc ratio | default BT | default ratio |
|---|---|--:|--:|--:|--:|--:|--:|
| 551021 | thedarkmarc v1 | 6 | $1,725 | $1,433 | 0.83 | $433 | 0.25 |
| 551355 | thedarkmarc v2 | 17 | $5,795 | $5,959 | **0.97** ★ | -$2,404 | -0.41 |

**imc mode is calibrated within 3% on the broader strategy.** Calibration ratio is not constant — narrow-coverage strategies sit at 0.83, broad-coverage strategies at 0.97. Plausible mechanism: more products averaged across CRC32 hash → less per-strategy bias; broader edges → fewer marginal fills where the calibration matters.

**Use `--match-mode imc` as primary R5 leaderboard predictor.** Default mode is unusable — missing invisible-taker fills inverts strategy ranking (default would say 551355 < 551021, live says 551355 > 551021 by 3.4×).

`r4_v8c.py` lesson echoes here: trust imc mode for strategy ranking; absolute PnL is approximate.

## Run commands

```bash
export PYTHONPATH='C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt'

# Day 4 1k probe (matches IMC live leaderboard scope)
python -m prosperity4bt trader-logic/round-5/thedarkmarc_do_nothing.py 5-4 --ticks 1000 --no-out --no-progress --match-mode imc

# Full 3-day (sanity benchmark)
python -m prosperity4bt trader-logic/round-5/thedarkmarc_do_nothing.py 5 --no-progress --no-out --match-mode imc

# Capture live state (submit to IMC; BT also works for consistency check)
python -m prosperity4bt trader-logic/round-5/oracle/god_logger_r5.py 5-4 --ticks 1000

# Extract any submitted run-log triplet (prices + trades + observations)
python run-logs/round-5/extract_live_csv.py 551283
```

## Live datasets captured

Per submission `run-logs/round-5/<id>/{prices,trades,observations}_live.csv`:

| Submission | Trader | Profit | Trades 1k d4 |
|---|---|--:|--:|
| 551021 | thedarkmarc v1 (6 products) | $1,725 | 1,425 |
| 551283 | god_logger_r5 ★ | $0 | 1,416 |
| 551355 | thedarkmarc v2 (17 products) | $5,795 | 1,433 |

The 551283 god-logger CSVs were also wired into the BT as **`round 5 day 5`**:
```
prosperity4bt/resources/round5/prices_round_5_day_5.csv
prosperity4bt/resources/round5/trades_round_5_day_5.csv
data_reader.available_days(5) → [2, 3, 4, 5]
```
Run with `python -m prosperity4bt <trader> 5-5`.

**Verification — day 5 (LIVE) ≡ first 1k ticks of day 4 (PUBLIC):**
- Public CSV first 1k ticks: 1,415 trades.
- Live CSV from sub 551283: 1,415 trades.
- thedarkmarc PnL: $433 / $1,433 (default / imc) on **both** `5-5` and `5-4 --ticks 1000` — byte-identical.

Conclusion: IMC's public R5 CSV release **already is** the live engine output. There's no live-vs-CSV divergence within the available data. (My earlier "18% more taker-active live" was a bogus uniform-distribution scaling — actual trade density is front-loaded.) The `day_5` slot is therefore mostly a redundant reference, but stays useful as:
- Direct ground-truth check for any future submission whose run differs from the public CSV (engine drift across the round).
- Pristine market_trades stream with zero own-fill contamination (god logger only).
- Storage slot for additional god-logger submissions on later live days.

**Full 4-day sweep results (thedarkmarc):**
| Day | default | imc |
|---|--:|--:|
| 2 | 59,847 | 14,944 |
| 3 | 31,514 | 11,788 |
| 4 (10k) | 48,932 | -3,375 |
| 5 (1k LIVE) | 433 | 1,433 |
| **Total** | **140,727** | **24,790** |

R5 has **no observations data** (state.observations empty). Ignith / Ashflow Alpha arrives via the manual UI, not the algo runtime.

## thedarkmarc strategy summary

R1 ASH/PEPPER template ported, trades 6 of 50 products:
- **MEAN_REVERSION** (revert 25% of last return): SNACKPACK_CHOCOLATE, ROBOT_IRONING, OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_CHOCOLATE
- **MOMENTUM** (skew toward daily-range percentile): PEBBLES_XL
- **HIDDEN_LIQUIDITY** (penny inside spread): ROBOT_LAUNDRY
- All other 44 products: skipped, no orders.

3-day BT (default / imc):
| Day | default | imc |
|---|--:|--:|
| 2 | 59,847 | 14,944 |
| 3 | 31,514 | 11,788 |
| 4 | 48,932 | -3,375 |
| **Total** | **140,294** | **23,357** |

Default mode matches teammate's reported live "69/31/49" (off only on day 2). imc mode is more conservative. Live d4 1k probe came in at $1,725 vs imc-BT $1,433 → calibration ratio ~1.20.

## Discord intel (cross-team EDA, 2026-04-28/29)

- **Mean reverters** (1-lag AC ≈ −0.15): ROBOT_IRONING, OXYGEN_SHAKE_EVENING_BREATH, OXYGEN_SHAKE_CHOCOLATE.
- **SNACKPACK correlations**: PIST↔STRAW +0.91, RASP↔STRAW −0.93, CHOC↔VAN −0.92, RASP↔PIST −0.83.
- **PEBBLES**: XL vs each smaller size −0.49.
- **Spread vs daily-range percentile**: spread widens at top of daily range universally (PEBBLES_XL 12.7→17.0 ticks bottom→top).
- **K-means trade archetypes** (4 clusters): whale-sellers at high-price/wide-spread (cluster 0), weak-hand sellers at low-price/tight-spread (cluster 2), standard buyers, HFT bursts. Suggests fade-the-weak-hand mean reversion.
- **SNACKPACK_CHOCOLATE spread regime**: visibly different at spread=18 vs spread=16 (Superduperbread, undocumented detail).

## Round 5 brief

50 products in 10 groups of 5: GALAXY_SOUNDS, SLEEP_POD, MICROCHIP, PEBBLES, ROBOT, UV_VISOR, TRANSLATOR, PANEL, OXYGEN_SHAKE, SNACKPACK. All position limits = 10.

Manual: Ignith portfolio. Quadratic fee `(volume/100)² × budget`. Budget = 1,000,000. Use Ashflow Alpha news. 9 goods.
