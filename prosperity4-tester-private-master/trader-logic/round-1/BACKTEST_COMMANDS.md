# Round 1 Backtest Commands

All commands assume working directory = repo root `imc-prosperity-4-backtester/`.

## Prerequisite

```bash
# Windows PowerShell
$env:PYTHONPATH="c:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt"

# bash / zsh
export PYTHONPATH="$(pwd)/prosperity4bt"
```

## Core Commands

### 1. Tutorial simulation (1k ticks = website tutorial conditions)

```bash
# All 4 days (days -2, -1, 0, 1)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 1000 --no-out

# Single day (example: day 0)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1--0 --ticks 1000 --no-out

# With live trader stdout (useful with `print(...)` debugging)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1--0 --ticks 1000 --no-out --print
```

### 2. Full-day / competition simulation (10k ticks)

```bash
# All 4 days, 10k ticks — primary competition metric
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000 --no-out

# Day 1 only (the tutorial-matching day, only 1k ticks in CSV)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1--1 --no-out
```

### 3. Matching-mode calibration flags

```bash
# imc mode with adverse-rate calibration matches website within ±1.6% for ACO
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000 --match-mode imc --no-out

# Default (CSV replay + >= crossing — what we usually use for ranking)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000 --match-mode default --no-out

# IMC (== exact + calibrated inside-spread taker supplement; better website proxy)
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000 --match-mode imc --no-out
```

### 4. Compare all strategies at once

```bash
# Loop all variants on 10k ticks and capture totals
for s in r1_v2 r1_v4 r1_v5 r1_v6 r1_v6b r1_v7; do
  echo "=== $s ==="
  python -m prosperity4bt trader-logic/round-1/${s}.py 1 --ticks 10000 --no-out 2>&1 | tail -8
done

# Or individual early-versions and experiments
python -m prosperity4bt trader-logic/round-1/early_versions/r1_medallion.py 1 --ticks 10000 --no-out
python -m prosperity4bt trader-logic/round-1/early_versions/r1_v2.py 1 --ticks 10000 --no-out
python -m prosperity4bt trader-logic/round-1/experiments/r1_hybrid.py 1 --ticks 10000 --no-out
python -m prosperity4bt trader-logic/round-1/experiments/r1_v3.py 1 --ticks 10000 --no-out
```

### 5. References (teammate code for study)

```bash
# Nancy's submission (~10.7k on website)
python -m prosperity4bt trader-logic/round-1/references/nancy_algov4.py 1 --ticks 10000 --no-out
python -m prosperity4bt trader-logic/round-1/references/nancy_algov4.py 1 --ticks 1000 --no-out

# Superduperbread (~10.4k on website)
python -m prosperity4bt trader-logic/round-1/references/superduperbread_round1_26.py 1 --ticks 10000 --no-out

# TROLL (~10.6k, more overfit)
python -m prosperity4bt trader-logic/round-1/references/r1_troll.py 1 --ticks 10000 --no-out
```

## Day / Round Syntax

- `1` → all days in round 1 (tutorial=1k + full-day=10k)
- `1--2` → round 1, day -2 only
- `1---2` → **NOTE: use `1--\-2` or just `1` if the dash is confusing bash**
- `1--0` → round 1, day 0
- `1--1` → round 1, day 1

## Key Flags Reference

| Flag | What it does | Default |
|------|--------------|---------|
| `--ticks N` | Max ticks to simulate (1000 = tutorial, 10000 = full day) | full CSV length |
| `--match-trades {all\|worse\|none}` | Trade matching mode | `all` |
| `--match-mode {default\|imc}` | ACO fill calibration | `default` |
| `--no-out` | Skip saving .log file | writes log |
| `--no-progress` | Hide progress bars | shows bars |
| `--print` | Show trader stdout (for `print()` debug) | suppressed |
| `--iterations N` | run() called N times per day (legacy, don't use) | matches ticks |

## Match Mode Matters

**Default mode is conservative (CSV-replay only). IMC mode adds calibrated invisible-taker fills.**

| Mode | When to use |
|------|-------------|
| `default` | Ranking strategies, bug detection (CSV replay only) |
| `imc` | Website-calibrated absolute PnL (see BACKTESTER_GUIDE.md §7 for current rates) |

**Add `--match-mode imc` for website-calibrated numbers:**
```bash
python -m prosperity4bt trader-logic/round-1/r1_v4.py 1 --ticks 10000 --match-mode imc --no-out
```

## Latest Results (2026-04-17, 10k-tick full-day, default mode)

| Strategy | Day -2 | Day -1 | Day 0 | Day 1 | Total | Website |
|----------|-------:|-------:|------:|------:|------:|--------:|
| r1_medallion | 92,619 | 96,019 | 93,259 | 27,652 | 309,549 | 10,468 |
| r1_v2 | 92,665 | 95,926 | 93,275 | 26,981 | 308,847 | 10,536.81 |
| **r1_v4** | **93,241** | 95,879 | **93,860** | 26,706 | **309,686** | **10,624.84** |
| r1_v5 (guardrail) | 93,215 | 95,873 | 93,727 | 26,849 | 309,664 | *(untested)* |
| r1_v6 (ACO wall-mid) | 92,859 | 91,246 | 90,605 | 24,201 | 298,911 | *rejected* |
| **r1_v6b** (IPR wall-mid) | 93,269 | 95,766 | 93,879 | **31,100** | **314,014** | *(untested, +4,328 BT)* |
| **r1_v7** (v5 + v6b) | 93,293 | 95,734 | 93,795 | 31,086 | **313,908** | *(untested, +4,222 BT)* |

## IMC-mode Results (website-calibrated for ACO ±1.6%)

| Strategy | Day -2 | Day -1 | Day 0 | Day 1 | Total | Notes |
|----------|-------:|-------:|------:|------:|------:|-------|
| **r1_v4** | 100,998 | 106,175 | 102,788 | 10,565 | **320,526** | Our current best |
| TROLL 211578 | 100,301 | 105,608 | 102,011 | 10,477 | 318,397 | IPR identical, LU ACO wins +2,129 |

**Key finding:** On imc-calibrated mode, TROLL's IPR is byte-identical to ours on day 0 (79,440 both). Entire gap is ACO — our LU clear step beats his glitch sniper approach by ~777/day. Scales to +2,400-3,000 over full 4-day scoring.

## What to Submit Next

1. **r1_v7** (combined wall-mid + guardrail) — highest BT expected, also has tail protection
2. **r1_v6b** (pure wall-mid, no guardrail) — if v7 regresses, fall back to this to isolate which change helps
3. Caveat: backtester is INVERSE-indicator for IPR framework changes. Don't trust the +4,328 BT delta until confirmed on website.

## Log Output Location

When `--no-out` is omitted, log files go to:

```
backtests/<YYYY-MM-DD_HH-MM-SS>.log
```

These can be loaded in the [Prosperity Visualiser](https://jmerle.github.io/imc-prosperity-3-visualizer/) for graphical inspection.
