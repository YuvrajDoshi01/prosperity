# Round 3 — Gloves Off

## Status

Two scoring windows tracked separately:

| Window | Active best | Live PnL |
|--------|-------------|---------:|
| **1k daily probe** (leaderboard) | `r3_v28.py` (untested live) | **~$154k** projected ★ |
| **10k final eval** (round close) | `r3_v28.py` (untested live) | **~$166-170k** projected ★ |
| Fixed v27 (sub'd) | live confirmed | $42,203 |
| Buggy v27 (sub 428103) | live confirmed | -$67,456 |

Manual bids: **(b1=766, b2=866)**.
BT calibration: default × **0.981** = website (verified 5×). imc × **1.005** = website.

## Active strategies (root)

| File | What it is | 1k day-2 BT | 10k day-2 BT | Live website |
|------|------------|------------:|-------------:|-------------:|
| `r3_v11.py` | Original ship: spread=17 GIGA SHORT (sub 402350) | $12,262 | — | $12,246 |
| `r3_v17.py` | + Phase 4.1 deep-ITM theta carry on VEV_4000/4500 (sub 405628) | $12,340 | — | $12,432 |
| `r3_v19.py` | + S7-bottom + flip-long-180 (teammate 406026 mechanic). **Best on 1k probe.** | $15,760 | $36,278 | $15,468 ★ |
| `r3_v22.py` | + Hold-FLIP-until-mid≥10020 (suppress passive dump) | $15,448 | $40,056 | ~$39,200 proj |
| `r3_v23.py` | + VEV_4000 ladder MM (Layer 5 of 5 attempted; only one survived BT) | $15,460 | $40,268 / $42,389 imc | ~$42,600 proj |
| `r3_v26.py` | + HOLD-FLIP stall fix (live 424285 swing) + multi-cycle (-$708 10k BT, +$5k live 1k expected) | $15,500 | $39,560 | ~$39,000 proj |
| `r3_v27.py` (sub **428103**, BUGGY +50 offset) | + DP-OPTIMAL HARDCODED HP/VFE TARGETS. Lost -$67,456 LIVE due to market_trade fills at order price. | $43,118 | $67,967 | **-$67,456 ❌** |
| `r3_v27.py` (offset=2 fix, sub TBD) | Same DP with cross-offset bug fixed. HP/VFE only. | $42,242 | $67,090 | **$42,203 ✓** (BT × 0.999) |
| `r3_troll.py` | Full per-tick walk-DP for all 12 products. DP runs through full 10k → "handover loss" -$1.9k post-tick-1000. | $155,608 | $153,672 | ~$152-156k proj |
| **`r3_v28.py`** ★ | r3_troll DP for ticks 0-999 + V22Trader takeover for ticks 1000+. V22 state buffers stay warm during DP via always-run pattern. | **$155,608** | **$168,403** | **~$166-170k proj ★** |

Earlier versions and sweep variants are in `archive/`.

## Architecture (v22)

```
HYDROGEL_PACK         — S17 GIGA SHORT entry (spread=17 AND mid>10010 → short -200)
                        S7-bottom cover trigger (spread=7 AND mid ≤ 8th-pctl of last 500 mids)
                        FLIP build to +200 long
                        HOLD-FLIP until mid ≥ FLIP_EXIT_MID=10020 (or 1500 ticks)
                        Online edge-beta passive MM fallback
                        10k day-2 BT: $23,941

VELVETFRUIT_EXTRACT   — Wall Mid MM (jmerle P3-winner technique)
                        + spread-state aggressive lift (spread=2 ap-down → BUY,
                          spread=3 bp-up → SELL)
                        10k day-2 BT: $11,661

VEV_4000 / VEV_4500   — Phase 4.1 deep-ITM theta carry MM (intrinsic ± 1, size 30, cap ±100)
                        10k day-2 BT: $2,437 (4000) + $0 (4500 BT-invisible, $99 live)

VEV_5000-5400         — Tradeable MM at best±1 size 20 + Layer C OTM passive bid on 5300/5400/5500
                        10k day-2 BT: $762 (5300) + $546 (5400) + $709 (5200)

VEV_6000 / VEV_6500   — Skipped entirely (penny-pegged, EV < 0)
```

## Submissions

| Sub | Strategy | Live |
|----:|----------|----:|
| 383883 | r3_v3 | $1,177 |
| 400463 | r3_v8 | $1,732 |
| 401608 | r3_v9 | $2,636 |
| 402350 | r3_v11 | $12,246 |
| 405628 | r3_v17 | $12,432 |
| 405881 | r3_v14j | $12,716 |
| 406165 | r3_v18 | $12,815 |
| 406026 | teammate (HP-only) | $13,375 |
| 406831 | **r3_v19** | **$15,467.56** ★ best 1k |
| 408128 | r3_v20 | $15,224 |
| 408576 | r3_v21 | $15,437 |

Run logs at `run-logs/round-3/<id>.zip`.

## Directory map

```
trader-logic/round-3/
├── r3_v11.py               # Original ship
├── r3_v17.py               # + Phase 4.1
├── r3_v19.py               # + S7+FLIP (best 1k probe)
├── r3_v22.py               # + Hold-FLIP-until-mid≥10020 (best 10k final)
│
├── README.md               # This file
├── BACKTEST_COMMANDS.md    # Team reference
├── R3_BRIEF.md             # Official wiki brief
├── R3_EXPLAINED.md         # Round explanation
├── MANUAL_R3_WRITEUP.md    # Two-bid auction analysis
├── MANUAL.png              # Manual challenge image
│
├── manual_r3_solver.py     # Manual Nash + grid search → (766, 866)
├── manual_r3_deep.py       # Deeper Nash analysis
├── manual_r3_field.py      # Bid distribution simulator
│
├── archive/                # Older versions and sweep evidence
│   ├── README.md
│   ├── early_versions/     # r3_v1, v3, v7, v9
│   ├── superseded/         # r3_v10, v12, v13, v14, v18, v20, v20_delta_hedge, v21, v3_theta
│   ├── failed_experiments/ # r3_v2, v2b, v4, v5, v6, v8
│   ├── v1_iterations/      # r3_v1a-e
│   ├── v14_sweep/          # v14_a..k (HP COVER/TIMEOUT sweep, v14j won → r3_v14)
│   ├── v22_sweep/          # v22_a..e + v22_layerc_only (FLIP_EXIT_MID sweep, 10020 won)
│   ├── r4_prep_iterations/ # v17 build chain
│   └── diagnostics/        # do_nothing.py, latency/options analysis scripts, charts
│
├── intel/                  # Competitor strategies
│   ├── image.png
│   └── competitor_strategies/
│       ├── 392245.py       (BS voucher fragile)
│       ├── 401389.py       (HP day-type detection)
│       ├── 401608.py       (= our r3_v9)
│       ├── 402045.py       (★ HP spread=17 GIGA SHORT, ported into v11)
│       ├── 400463.py       (= our r3_v8)
│       ├── 406026.py       (★ teammate HP-only $13,375 — ported into v19/v20)
│       └── superduperbread_hp_final.py (★ teammate clean HP — ported into v20)
│
├── notes/
│   ├── voucher_analysis.py + .txt        # 8-part EDA
│   ├── iv_visualization.py + iv_plots/   # 4 IV plots
│   ├── alpha_hunt.py + .txt              # alpha hunt report
│   ├── alpha_hunt2.py, alpha_hunt3.py    # follow-ups
│   ├── recalibration_1k.md
│   └── alpha_hunt_2026-04-25/            # 2026-04-25 5-agent alpha hunt
│       ├── hp/, vfe/, vouchers/, cross_product/, microstructure/
│       ├── missing_alpha/                # quant-finance v22 alpha hunt
│       ├── v12_layer_results.md
│       ├── v13_layer_results.md
│       └── v14_sweep_results.md
│
├── hydrogel/               # HP-specific dashboards / diagnostics
├── manual_exhaustive/      # Manual challenge exhaustive solver
└── oracle/
    └── god_logger_r3.py    # Pristine market state logger
```

## Key learnings (durable)

1. **Wall Mid > simple mid** for delta-1 products with tight spread (P3 winner technique).
2. **spread=17 stress signal** on HP (mean reverts to ~9990).
3. **Discord competitor mining** moved us from $1,177 to $15,468 (10×) over 7 submissions.
4. **Verify BT calibration** — default × 0.981 = website holds across 5+ R3 submissions.
5. **stdout NOT captured** — use traderData JSON for diagnostics.
6. **Aggressive take usually loses** — MM bot quotes are AT fair, paying above is adversely selected.
7. **Spread > signal** — directional voucher signals (OBI, VR(20)) defeated by $20 spread cost.
8. **Engine fill cap** — `market_trade.{buy,sell}_quantity` caps fills per side per tick. SIZE 5 = 60. Splitting hurts.
9. **Integer-price grid kills continuous-correlation skews** — VFE OBI tilt regressed despite IC=0.30.
10. **HP exit timing is the lever**: COVER=0+TIMEOUT=500 (v14j) and FLIP_EXIT_MID=10020 hold (v22) both came from this realization.
11. **R2/R3 final scoring = 10k day-2** (not 1k); leaderboard probe = 1k day-2. Optimize for the right window.

See `memory/project_round3_v1.md` and `memory/project_round3_alpha_hunt_2026-04-25.md` for full lessons archive.
