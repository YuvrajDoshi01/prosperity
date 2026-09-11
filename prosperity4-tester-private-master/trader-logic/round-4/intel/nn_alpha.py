"""nn_alpha.py — train tiny linear + MLP forecaster for HP/VFE forward returns.

Offline only. Uses numpy/pandas/sklearn. Outputs hard-coded weight constants
that get pasted into r4_v5_nn.py.

Features per tick (HP and VFE separately):
  f0  L1 OBI = (bv1 - av1) / (bv1+av1)
  f1  L3 microprice deviation = wmid_L3 - mid
  f2  ret_5  = mid_t - mid_{t-5}
  f3  ret_20 = mid_t - mid_{t-20}
  f4  ret_100 = mid_t - mid_{t-100}
  f5  rolling std (window=50) of mid
  f6  spread (raw int)
  f7  HP only: spread one-hot 17 (else 0)
  f8  VFE drift: vfe_mid_t - vfe_mid_{t-50}
  f9  Mark-net flow last 100 ticks: sum(qty if buyer in flowmarks else -qty if seller in flowmarks)

Targets:
  y10  forward 10-tick mid return: mid_{t+10} - mid_t
  y100 forward 100-tick mid return: mid_{t+100} - mid_t

Walk-forward: leave-one-day-out. Report R^2, RMSE, sign-accuracy.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / "prosperity4bt" / "resources" / "round4"
INTEL = Path(__file__).resolve().parent

DAYS = [1, 2, 3]
FLOW_MARKS = ("Mark 22", "Mark 49", "Mark 55", "Mark 67")


def load_day(day: int):
    px = pd.read_csv(RES / f"prices_round_4_day_{day}.csv", sep=";")
    tr = pd.read_csv(RES / f"trades_round_4_day_{day}.csv", sep=";")
    return px, tr


def build_features(px: pd.DataFrame, tr: pd.DataFrame, product: str):
    p = px[px["product"] == product].sort_values("timestamp").reset_index(drop=True)
    bv = p[[f"bid_volume_{i}" for i in (1, 2, 3)]].fillna(0).values
    av = p[[f"ask_volume_{i}" for i in (1, 2, 3)]].fillna(0).values
    bp = p[[f"bid_price_{i}" for i in (1, 2, 3)]].fillna(0).values
    ap = p[[f"ask_price_{i}" for i in (1, 2, 3)]].fillna(0).values

    bv1 = bv[:, 0]; av1 = av[:, 0]
    sum1 = np.where((bv1 + av1) > 0, bv1 + av1, 1)
    obi1 = (bv1 - av1) / sum1

    bv_sum = bv.sum(axis=1); av_sum = av.sum(axis=1)
    bw = (bp * bv).sum(axis=1) / np.where(bv_sum > 0, bv_sum, 1)
    aw = (ap * av).sum(axis=1) / np.where(av_sum > 0, av_sum, 1)
    wmid_L3 = 0.5 * (bw + aw)
    mid = p["mid_price"].values.astype(float)
    micro_dev = wmid_L3 - mid

    spread = p["ask_price_1"].values - p["bid_price_1"].values

    ret_5   = np.concatenate([np.zeros(5),   mid[5:]   - mid[:-5]])
    ret_20  = np.concatenate([np.zeros(20),  mid[20:]  - mid[:-20]])
    ret_100 = np.concatenate([np.zeros(100), mid[100:] - mid[:-100]])

    s = pd.Series(mid)
    vol50 = s.rolling(50, min_periods=10).std().fillna(0).values

    spread17 = (spread == 17).astype(float) if product == "HYDROGEL_PACK" else np.zeros_like(spread, dtype=float)

    # VFE drift cross-feature (HP gate input)
    vp = px[px["product"] == "VELVETFRUIT_EXTRACT"].sort_values("timestamp").reset_index(drop=True)
    vfe_mid = vp["mid_price"].values.astype(float)
    vfe_drift_50 = np.concatenate([np.zeros(50), vfe_mid[50:] - vfe_mid[:-50]])
    if len(vfe_drift_50) >= len(mid):
        vfe_drift_50 = vfe_drift_50[: len(mid)]
    else:
        vfe_drift_50 = np.concatenate([vfe_drift_50, np.zeros(len(mid) - len(vfe_drift_50))])

    # Counterparty net flow over rolling 100 ticks
    tr_p = tr[tr["symbol"] == product].copy()
    tr_p["net"] = 0.0
    is_buyer_flow = tr_p["buyer"].isin(FLOW_MARKS)
    is_seller_flow = tr_p["seller"].isin(FLOW_MARKS)
    tr_p.loc[is_buyer_flow, "net"] += tr_p.loc[is_buyer_flow, "quantity"].astype(float)
    tr_p.loc[is_seller_flow, "net"] -= tr_p.loc[is_seller_flow, "quantity"].astype(float)
    tr_g = tr_p.groupby("timestamp")["net"].sum().reindex(p["timestamp"].values, fill_value=0).values
    flow_roll = pd.Series(tr_g).rolling(100, min_periods=1).sum().values

    feats = np.column_stack([
        obi1, micro_dev, ret_5, ret_20, ret_100, vol50, spread, spread17, vfe_drift_50, flow_roll
    ])
    feats = np.nan_to_num(feats, nan=0, posinf=0, neginf=0)

    y10  = np.concatenate([mid[10:]  - mid[:-10],  np.zeros(10)])
    y100 = np.concatenate([mid[100:] - mid[:-100], np.zeros(100)])

    return feats, y10, y100, mid


FEATURE_NAMES = ["obi1", "micro_dev", "ret_5", "ret_20", "ret_100", "vol50", "spread", "spread17", "vfe_drift_50", "flow100"]


def train_linear(X, y):
    # Ridge with intercept, closed form
    Xa = np.column_stack([np.ones(len(X)), X])
    lam = 1.0
    A = Xa.T @ Xa
    A[1:, 1:] += lam * np.eye(X.shape[1])
    w = np.linalg.solve(A, Xa.T @ y)
    return w  # [bias, w...]


def predict_linear(w, X):
    return w[0] + X @ w[1:]


def train_mlp(X, y, hidden=8, lr=0.01, epochs=200, seed=0):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Xn = (X - mu) / sd
    ymu = y.mean(); ysd = y.std() + 1e-9
    yn = (y - ymu) / ysd

    W1 = rng.normal(0, 0.3, size=(d, hidden))
    b1 = np.zeros(hidden)
    W2 = rng.normal(0, 0.3, size=(hidden,))
    b2 = 0.0

    for ep in range(epochs):
        z1 = Xn @ W1 + b1
        a1 = np.tanh(z1)
        yhat = a1 @ W2 + b2
        err = yhat - yn
        dW2 = a1.T @ err / n
        db2 = err.mean()
        d_a1 = np.outer(err, W2)
        d_z1 = d_a1 * (1 - a1 * a1)
        dW1 = Xn.T @ d_z1 / n
        db1 = d_z1.mean(0)
        W1 -= lr * dW1; b1 -= lr * db1
        W2 -= lr * dW2; b2 -= lr * db2

    return {"mu": mu, "sd": sd, "ymu": float(ymu), "ysd": float(ysd),
            "W1": W1, "b1": b1, "W2": W2, "b2": float(b2)}


def predict_mlp(m, X):
    Xn = (X - m["mu"]) / m["sd"]
    a1 = np.tanh(Xn @ m["W1"] + m["b1"])
    return (a1 @ m["W2"] + m["b2"]) * m["ysd"] + m["ymu"]


def metrics(y, yhat):
    ss_res = ((y - yhat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum() + 1e-9
    r2 = 1 - ss_res / ss_tot
    rmse = float(np.sqrt(((y - yhat) ** 2).mean()))
    sgn = float((np.sign(y) == np.sign(yhat)).mean())
    return r2, rmse, sgn


def fit_product(product: str):
    print(f"\n=== {product} ===")
    Xs, y10s, y100s, days = [], [], [], []
    for d in DAYS:
        px, tr = load_day(d)
        X, y10, y100, _ = build_features(px, tr, product)
        Xs.append(X); y10s.append(y10); y100s.append(y100); days.append(np.full(len(X), d))
    X_all = np.vstack(Xs); y10_all = np.concatenate(y10s); y100_all = np.concatenate(y100s)
    days_all = np.concatenate(days)

    # leave-one-out by day
    summary = {"product": product, "feature_names": FEATURE_NAMES}
    oos_rows = []
    for hold in DAYS:
        train_mask = days_all != hold
        test_mask = days_all == hold
        Xtr = X_all[train_mask]; ytr = y10_all[train_mask]
        Xte = X_all[test_mask]; yte = y10_all[test_mask]

        # trim ends for proper forward target (last 100 are zero-padded)
        valid_tr = np.arange(len(Xtr))
        valid_te = np.arange(len(Xte))

        w_lin = train_linear(Xtr, ytr)
        yhat_lin = predict_linear(w_lin, Xte)
        r2_l, rmse_l, sgn_l = metrics(yte, yhat_lin)

        m_mlp = train_mlp(Xtr, ytr, hidden=8, epochs=300)
        yhat_mlp = predict_mlp(m_mlp, Xte)
        r2_m, rmse_m, sgn_m = metrics(yte, yhat_mlp)
        print(f"  hold day {hold}: lin R2={r2_l:.4f} rmse={rmse_l:.3f} sgn={sgn_l:.3f}  | mlp R2={r2_m:.4f} rmse={rmse_m:.3f} sgn={sgn_m:.3f}")
        oos_rows.append({"hold": hold, "lin_r2": r2_l, "lin_sgn": sgn_l, "mlp_r2": r2_m, "mlp_sgn": sgn_m})
    summary["oos"] = oos_rows

    # Final fit on ALL days for deployment
    w_lin_full = train_linear(X_all, y10_all)
    m_mlp_full = train_mlp(X_all, y10_all, hidden=8, epochs=400)

    # Coef report
    coef_strs = [f"{n}={w_lin_full[i+1]:+.5f}" for i, n in enumerate(FEATURE_NAMES)]
    print(f"  Linear bias={w_lin_full[0]:+.5f}  " + "  ".join(coef_strs))

    summary["linear"] = {"bias": float(w_lin_full[0]),
                          "weights": {n: float(w_lin_full[i+1]) for i, n in enumerate(FEATURE_NAMES)}}
    summary["mlp"] = {"mu": m_mlp_full["mu"].tolist(), "sd": m_mlp_full["sd"].tolist(),
                       "ymu": m_mlp_full["ymu"], "ysd": m_mlp_full["ysd"],
                       "W1": m_mlp_full["W1"].tolist(), "b1": m_mlp_full["b1"].tolist(),
                       "W2": m_mlp_full["W2"].tolist(), "b2": m_mlp_full["b2"]}

    # In-sample sign accuracy on full data, for sizing sanity
    yhat_in = predict_linear(w_lin_full, X_all)
    r2, rmse, sgn = metrics(y10_all, yhat_in)
    print(f"  IN-sample lin: R2={r2:.4f} rmse={rmse:.3f} sgn={sgn:.3f}")

    return summary


def main():
    out = {}
    for prod in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"):
        out[prod] = fit_product(prod)
    (INTEL / "nn_alpha_weights.json").write_text(json.dumps(out, indent=2))
    print(f"\nSaved -> {INTEL / 'nn_alpha_weights.json'}")


if __name__ == "__main__":
    main()
