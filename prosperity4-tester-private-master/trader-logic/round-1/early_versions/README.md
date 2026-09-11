# Round 1 Early Versions

Superseded by [../r1_v4.py](../r1_v4.py). Kept for historical reference and ablation studies.

| File | Website | Summary |
|------|--------:|---------|
| trader.py | 4,934 | Baseline combined trader — before drift bias was discovered |
| r1_medallion.py | 10,445-10,468 | Added drift bias of 5-6. Microprice 4-lag regression for IPR FV. Second-best overall |
| r1_v2.py | 10,536.81 | Replaced microprice regression with simple mid. 4 params only. Base of current v4 |

These files still run against the backtester. Useful for:
- Ablation studies (what if we remove the clear step? → use r1_v2 as the no-clear baseline)
- Regression testing infrastructure changes
- Teaching/explaining the strategy evolution
