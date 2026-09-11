"""Diagnose: at S17-entry-eligible ticks, what does NN predict?"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / "prosperity4bt" / "resources" / "round4"

NN_HP_BIAS = 0.22527359
NN_HP_W = np.array([+0.80071417, +0.99305321, +0.00989019, -0.00645525,
                    -0.01014200, -0.04312217, +0.00139216, -0.72232414,
                    +0.00324287, -0.00635016])

for d in (1, 2, 3):
    px = pd.read_csv(RES / f"prices_round_4_day_{d}.csv", sep=";")
    p = px[px["product"] == "HYDROGEL_PACK"].sort_values("timestamp").reset_index(drop=True)
    bv1 = p["bid_volume_1"].fillna(0).values
    av1 = p["ask_volume_1"].fillna(0).values
    s = bv1 + av1
    obi = np.where(s > 0, (bv1 - av1) / np.where(s > 0, s, 1), 0)
    bv = p[[f"bid_volume_{i}" for i in (1, 2, 3)]].fillna(0).values
    av = p[[f"ask_volume_{i}" for i in (1, 2, 3)]].fillna(0).values
    bp = p[[f"bid_price_{i}"  for i in (1, 2, 3)]].fillna(0).values
    ap = p[[f"ask_price_{i}"  for i in (1, 2, 3)]].fillna(0).values
    bvs = bv.sum(1); avs = av.sum(1)
    bw = (bp * bv).sum(1) / np.where(bvs > 0, bvs, 1)
    aw = (ap * av).sum(1) / np.where(avs > 0, avs, 1)
    mid = p["mid_price"].values.astype(float)
    micro_dev = 0.5 * (bw + aw) - mid
    spread = p["ask_price_1"].values - p["bid_price_1"].values

    ret_5   = np.concatenate([np.zeros(5),   mid[5:]   - mid[:-5]])
    ret_20  = np.concatenate([np.zeros(20),  mid[20:]  - mid[:-20]])
    ret_100 = np.concatenate([np.zeros(100), mid[100:] - mid[:-100]])
    vol50 = pd.Series(mid).rolling(50, min_periods=10).std().fillna(0).values
    spread17 = (spread == 17).astype(float)

    vp = px[px["product"] == "VELVETFRUIT_EXTRACT"].sort_values("timestamp").reset_index(drop=True)
    vfe_mid = vp["mid_price"].values.astype(float)
    vfe_drift_50 = np.concatenate([np.zeros(50), vfe_mid[50:] - vfe_mid[:-50]])[: len(mid)]

    F = np.column_stack([obi, micro_dev, ret_5, ret_20, ret_100, vol50, spread, spread17, vfe_drift_50, np.zeros_like(mid)])
    pred = F @ NN_HP_W + NN_HP_BIAS

    # S17-entry eligible: spread==17 AND mid>10010 AND z>=2.0
    z = pd.Series(mid).rolling(500, min_periods=500).apply(
        lambda x: (x.iloc[-1] - x.mean()) / (x.std() + 1e-9), raw=False
    ).fillna(0).values
    elig = (spread == 17) & (mid > 10010) & (z >= 2.0)
    fwd = np.concatenate([mid[10:] - mid[:-10], np.zeros(10)])
    n_elig = elig.sum()
    if n_elig:
        avg_pred_at_elig = pred[elig].mean()
        avg_fwd_at_elig = fwd[elig].mean()
        below_zero = (pred[elig] <= 0).mean()
        below_neg05 = (pred[elig] <= -0.5).mean()
        print(f"day {d}: eligible_ticks={n_elig}  pred_mean={avg_pred_at_elig:+.3f}  fwd_mean={avg_fwd_at_elig:+.3f}  pred<=0:{below_zero:.2%}  pred<=-0.5:{below_neg05:.2%}")
    else:
        print(f"day {d}: no eligible ticks")
