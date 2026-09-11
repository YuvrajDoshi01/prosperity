---
name: Backtester vs Website Reliability
description: Local backtester does NOT predict website scores. Use only for relative ranking. Quantified calibration lives in project_round1_calibration.md.
type: feedback
originSessionId: b564564b-4b0d-4055-a502-a5537e373617
---
Local backtester results are MISLEADING for absolute PnL.

**Why:** The matching engine uses static historical data while the website has dynamic bot interaction. Round 0 examples: s11 +1,084 locally → −915 on website. s19 +92 locally → −175 on website.

**How to apply:**
- Use local BT for RANKING, not absolute PnL prediction
- For inside-spread MM: website ≈ BT × 1.07 (R0) or BT × 0.3 (R1 full-day)
- Trust IPR BT gradient (direction AND magnitude)
- Trust ACO BT only for structural changes >1,000 PnL — ACO gradient overshoots ~60× (see project_round1_calibration.md)
- Cross-validate on BOTH training days before website submit
- Final validation MUST be on the website
