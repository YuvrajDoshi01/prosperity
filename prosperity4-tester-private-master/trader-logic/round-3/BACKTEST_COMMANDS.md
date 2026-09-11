# R3 Backtester Commands (Team Reference)

## Setup (one time)

```bash
cd C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester
export PYTHONPATH=prosperity4bt
```

If on Windows PowerShell:
```powershell
$env:PYTHONPATH="c:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt"
```

---

## Single-day 1k-tick BT (matches website test exactly)

```bash
PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/r3_v11.py 3-2 --ticks 1000 --no-out --no-progress
```

Replace `3-2` with `3-0` / `3-1` for other days. Replace strategy filename with any `r3_vN.py`.

---

## Full 3-day 10k-tick BT (final scoring proxy)

```bash
PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/r3_v11.py 3 --ticks 10000 --no-out --no-progress
```

---

## Bash one-liner — all days at both window sizes

```bash
for d in 0 1 2; do
  echo "=== Day $d 1k ==="
  PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/r3_v11.py 3-$d --ticks 1000 --no-out --no-progress | grep -E "VEV_|VELVET|HYDRO|Total"
done
echo "=== 3-day 10k ==="
PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/r3_v11.py 3 --ticks 10000 --no-out --no-progress | tail -7
```

---

## Compare two strategies head-to-head

```bash
for v in v9 v11; do
  echo "=== $v 1k day 2 ==="
  PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-3/r3_$v.py 3-2 --ticks 1000 --no-out --no-progress | tail -2
done
```

---

## CLI Flags

| Flag | Purpose |
|---|---|
| `--ticks N` | Limit simulation to N timestamps (1000 = website test window; 10000 = full day) |
| `--no-out` | Skip writing log file (faster) |
| `--no-progress` | Hide progress bar |
| `--match-mode default` | Default matching (**recommended for R3**) |
| `--match-mode imc` | IMC-calibrated matching (R2 calibration only; needs re-fit for R3) |
| `--match-trades all` | Match against all CSV trades (default) |
| `--match-trades worse` | Only match if at worse-than-quote price |
| `--match-trades none` | Skip CSV trade matching (test pure MM bot interactions) |
| `--print` | Print trader stdout (⚠ website does NOT capture stdout) |
| `--vis` | Open results in jmerle's web visualizer |
| `--out FILE` | Save log to specific file |

---

## Day Specification

| Spec | Meaning |
|---|---|
| `3` | All R3 days (0, 1, 2) |
| `3-0` | Only R3 day 0 (TTE=8 historical) |
| `3-1` | Only R3 day 1 (TTE=7 historical) |
| `3-2` | Only R3 day 2 (TTE=6 historical, **matches website test exactly**) |

---

## Calibration Constants (Verified)

| BT window | Website ratio | Verified by |
|---|---:|---|
| 1k-tick day 2 | **0.99** | v9 BT $2,660 → website $2,636; v11 BT $12,262 → website $12,246 |
| 10k 3-day | unknown | Final scoring may use this format |

**Rule of thumb**: `BT 1k-tick day 2 × 0.99 ≈ website score`. Used to project new strategies before submission.

---

## Cross-Backtester Verification

Our BT produces **identical PnL** to two reference implementations:

| Backtester | Install | Verified match |
|---|---|---|
| Xeeshan85's `prosperity4btx` | `pip install -U prosperity4btx` | ✓ identical (v3 $28,013, v7 $47,388) |
| GeyzsoN's `rust_backtester` | `cargo install rust_backtester --locked` | ✓ identical |

Run prosperity4btx with the same command:
```bash
PYTHONPATH=prosperity4bt prosperity4btx trader-logic/round-3/r3_v11.py 3 --no-out
```

---

## Active Strategy Files

| File | 1k day 2 BT | 10k 3-day BT | Notes |
|---|---:|---:|---|
| `r3_v1.py` | $1,013 | $28,013 | Pure MM baseline |
| `r3_v3.py` | $1,013 | $28,013 | + structural arb (insurance) — submitted as 383883 ($1,177) |
| `r3_v7.py` | $2,538 | $47,388 | Wall Mid for VFE breakthrough |
| `r3_v9.py` | $2,660 | $47,318 | + safe BS voucher taking — submitted as 401608 ($2,636) |
| `r3_v10.py` | $5,142 | $46,970 | + 401389's HP day-type detection |
| **`r3_v11.py`** | **$12,262** | **$46,976** | **+ 402045's spread=17 GIGA SHORT — submitted as 402350 ($12,246) ★** |

Archived experimental versions in `archive/`. See `archive/README.md`.

---

## Known Gotchas

1. **Website tests on 1,000 ticks of day 2 only** (timestamps 0-99,900 step 100). Our BT defaults to 10,000 — use `--ticks 1000` to match.
2. **Stdout NOT captured** by IMC sandbox. `print()` statements are thrown away. Use `state.traderData` (50KB cap) for diagnostics.
3. **`imc` match mode is R2-calibrated** (`extra_rate=0.038`). For R3 it underfits — gives -$170 instead of +$1,013 on day 2 1k-tick. Use `default` until re-calibrated.
4. **All-or-nothing position limits** per product. If `pos + total_buy > LIMIT` OR `pos - total_sell < -LIMIT`, **ALL** orders for that product are rejected.

---

## Run Log Analysis

To analyze a `.zip` from website submission:

```bash
# Extract
mkdir -p run-logs/round-3/SUBID && cd run-logs/round-3/SUBID
unzip -o ../SUBID.zip

# Per-product PnL breakdown
python -c "
import json
with open('SUBID.json') as f: d = json.load(f)
print('profit:', d['profit'])
log = d['activitiesLog']
header = log.split('\n')[0].split(';')
pnl_idx = header.index('profit_and_loss')
prod_idx = header.index('product')
day_idx = header.index('day')
latest = {}
for line in log.split('\n')[1:]:
    if not line: continue
    p = line.split(';')
    if len(p) <= pnl_idx: continue
    latest[(p[day_idx], p[prod_idx])] = float(p[pnl_idx]) if p[pnl_idx] else 0.0
for (day, prod), pnl in sorted(latest.items(), key=lambda x: -x[1]):
    if abs(pnl) > 0:
        print(f'  Day {day} {prod}: {pnl:.2f}')
"
```

---

## Submission Workflow

1. Edit strategy file `trader-logic/round-3/r3_vN.py`
2. Run 1k-tick day 2 BT to predict website score
3. Run 10k 3-day BT to verify no regression
4. Compare to v11 baseline ($12,262 / $46,976)
5. If 1k-tick day 2 BT ≥ $12,262 → consider submitting
6. Submit via website UI, manually re-enter `(766, 866)` for the manual challenge
7. Wait for run log zip in `run-logs/round-3/`
8. Verify website ≈ BT × 0.99

---
