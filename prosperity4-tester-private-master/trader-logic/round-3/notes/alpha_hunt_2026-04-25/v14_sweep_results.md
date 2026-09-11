# v14 HP Exit Parameter Sweep — 2026-04-25

## Goal
Find COVER_TARGET / TIMEOUT settings that capture more of the day-2 1k-tick HP downtrend
(open mid 10011, tick-1000 mid 9960). v12 baseline uses (9998, 200) and covers around
ts ~10,000-20,000 mid ~9990 — leaves the rest of the 30-tick decline on the table.

## Method
- Fork `r3_v12.py` to 8 variants, change ONLY `HydrogelParams.COVER_TARGET` and
  `HydrogelParams.TIMEOUT`. All other logic identical to v12.
- Backtest each on `3-2 --ticks 1000` (day-2 1k) and `3 --ticks 10000` (full 3-day).
- Position cap = -200 (short), entry trigger spread==17 AND mid > 10010 unchanged.

## Results

| Variant | COVER_TARGET | TIMEOUT | Day-2 1k HP | Day-2 1k Total | Δ vs v12 1k | 3-day Total | Δ vs v12 3-day |
|---------|-------------:|--------:|------------:|---------------:|------------:|------------:|---------------:|
| **v12 baseline** | 9998 | 200 | 10,224 | 12,410 | — | 56,654 | — |
| v14a | 9985 | 200 | 10,406 | 12,592 | +182 | 54,322 | -2,332 |
| v14b | 9970 | 200 | 10,529 | 12,714 | +304 | 53,616 | -3,038 |
| v14c | 9950 | 200 | 10,743 | 12,928 | +518 | 53,722 | -2,932 |
| v14d | 0 (disabled) | 200 | 10,788 | **12,974** | **+564** | 53,766 | -2,888 |
| v14e | 9998 | 500 | 10,224 | 12,410 | +0 | **62,308** | **+5,654** |
| v14f | 9970 | 500 | 10,495 | 12,680 | +270 | 59,256 | +2,602 |
| v14g | 9970 | 1000 | 10,495 | 12,680 | +270 | 58,878 | +2,224 |
| **v14h** ★ | 0 (disabled) | 1000 | 10,640 | 12,826 | **+416** | 57,362 | +708 |

(VFE = 1,940 and vouchers = 245 are constant across all variants. All differences are HP.)

## Per-day breakdown (10k full-day)

| Variant | Day 0 | Day 1 | Day 2 | Total |
|---------|------:|------:|------:|------:|
| v12 | 28,508 | 9,383 | 18,764 | 56,654 |
| v14a | 27,850 | 9,184 | 17,289 | 54,322 |
| v14b | 28,178 | 8,948 | 16,490 | 53,616 |
| v14c | 28,070 | 8,948 | 16,704 | 53,722 |
| v14d | 28,070 | 8,948 | 16,749 | 53,766 |
| v14e | 29,388 | 12,951 | 19,968 | **62,308** |
| v14f | 28,676 | 11,374 | 19,205 | 59,256 |
| v14g | 29,040 | 10,865 | 18,974 | 58,878 |
| v14h | 26,930 | 10,865 | 19,567 | 57,362 |

## Findings

### 1. Lowering COVER_TARGET monotonically improves 1k day-2, hurts 3-day
- COVER 9998 → 9985 → 9970 → 9950 → 0: 1k HP rises 10,224 → 10,406 → 10,529 → 10,743 → 10,788.
- BUT 3-day collapses: 56,654 → 54,322 → 53,616 → 53,722 → 53,766.
- Reason: lowering COVER prevents profitable mean-reversion exits on day 0/1 where price
  oscillates around 9990 ± 10 instead of trending all the way down. We hold the short
  through reversals, give back PnL, and TIMEOUT closes us at worse prices.

### 2. Extending TIMEOUT helps massively on 3-day, neutral-to-positive on 1k
- v14e (9998, 500): 1k unchanged ($12,410) because cover threshold hit before timeout
  on day-2, but 3-day jumps **+$5,654 to $62,308** — best in sweep.
- This confirms 200-tick timeout was too tight on days where the mean-revert takes longer.
- v14g (9970, 1000): 1k +$270, 3-day +$2,224 — looser timeout helps, but lower COVER
  partially undoes the gain.

### 3. Best 1k variant violates 3-day floor
- v14d (0, 200) is best on 1k day-2 (+$564) but 3-day = $53,766, BELOW the $54,000 floor
  by $234. Rejected per task constraint.

### 4. v14e is the global 3-day winner but adds $0 to day-2 1k
- If 3-day is the priority, ship v14e. But the task primary goal is day-2 1k capture.

## Winner Selection

Primary criterion: max day-2 1k Δ vs v12 (>$300) AND 3-day not below $54,000.

| Candidate | 1k Δ | 3-day | Pass? |
|-----------|----:|------:|:-----:|
| v14a | +182 | 54,322 | NO (1k Δ < 300) |
| v14b | +304 | 53,616 | NO (3-day < 54k) |
| v14c | +518 | 53,722 | NO (3-day < 54k) |
| v14d | +564 | 53,766 | NO (3-day < 54k) |
| v14e | +0 | 62,308 | NO (1k Δ < 300) |
| v14f | +270 | 59,256 | NO (1k Δ < 300) |
| v14g | +270 | 58,878 | NO (1k Δ < 300) |
| **v14h** | **+416** | **57,362** | **YES** |

**Winner: v14h (COVER=0, TIMEOUT=1000)** — only variant satisfying both constraints.
- Day-2 1k: $12,826 (+$416 vs v12, **+3.4%**)
- 3-day 10k: $57,362 (+$708 vs v12, **+1.2%**)
- Saved as `r3_v14.py`.

## Open question: v14e vs v14h trade-off
v14e dominates on 3-day ($62,308 vs $57,362, +$4,946) but is identical to v12 on
day-2 1k. If the website actually tests 1k day-2 (per CLAUDE.md ground truth), v14h
is the right pick. If 3-day breadth matters (e.g., for tournament round PnL), v14e would
be the better strategic choice.

Recommendation: **ship v14h** for day-2 1k website parity. Hold v14e in reserve as a
contender if competition shifts toward full-day evaluation.

## Files saved
- `trader-logic/round-3/r3_v14.py` — winner (= v14h)
- `trader-logic/round-3/v14_a.py` … `v14_h.py` — all sweep variants (kept for reference)
- `trader-logic/round-3/notes/alpha_hunt_2026-04-25/v14_sweep_results.md` — this file
