# Round 1 Experiments (Failed or Abandoned)

Kept for lessons-learned. Do not submit these without re-validation.

| File | Website | What it tried | Why it failed |
|------|--------:|---------------|---------------|
| r1_v3.py | **7,974.84** | Full Linear Utility framework on BOTH products (filtered-mm-mid + take_width=1 + penny/join) | IPR regressed -2,650. LU's `take_width=1` assumes present-value FV; drift products need future-value FV. Threshold `fv-1` at t=0 = 11997, missing ask at 12006. |
| r1_hybrid.py | 10,107 | Seed-fingerprint detection + passive-bid accumulation during known drawdown window | Correctly detected seed match, but passive bids at 11992-11996 had **zero fills** across 59 ticks. No taker sells existed below 12006 during the drawdown. Also IPR PnL went negative at t=6000 (delayed drawdown after handoff). |
| r1_adaptive.py | (not submitted) | Drift-adaptive strategy robust to direction changes | Exploratory only; drift direction is structurally fixed in Prosperity markets, so adaptation adds complexity without upside. |
| r1_medallion_dp.py | (not submitted) | DP-based variant of r1_medallion | Experimental; DP oracle on Round 0 scored WORSE than simple strategy (2,523 DP vs 2,857 simple), so this was shelved. |

## Lessons distilled

1. **LU framework must NOT be applied to drift products.** The take_width parameter assumes FV is accurate; drift means FV is always lagging.
2. **Drawdowns are not bugs to fix.** MTM drawdown on a drift trade is the cost of early entry — eliminating it requires entering later, which costs more.
3. **Seed-detection is validated but useless** — we CAN detect the seed with certainty, but hardcoded orders need a counterparty, and none exists at favorable prices during the drawdown.
