"""nn_7marks.py — train numpy/sklearn forecaster combining ALL 7 Marks for R4 v6.

Features per tick (per product, HP and VFE):
  Per-mark rolling 100-tick volumes (14 features):
    f0..f6   buy_vol_{Mark 01,14,22,38,49,55,67}    (Mark as buyer)
    f7..f13  sell_vol_{Mark 01,14,22,38,49,55,67}   (Mark as seller)
  Microstructure (4 features):
    f14 OBI L1 = (bv1 - av1)/(bv1+av1)
    f15 microprice deviation = wmid_L3 - mid
    f16 spread (raw int)
    f17 ret_5 = mid_t - mid_{t-5}

Target: forward 50-tick mid return  y50 = mid_{t+50} - mid_t

Models: Linear, Ridge(alpha=1), Ridge(alpha=10), MLP(hidden=8, ReLU).

Walk-forward: train on {1,2}/{1,3}/{2,3} hold {3}/{2}/{1}.
Compare via OOS R^2, sign accuracy, RMSE. Pick best by mean OOS sign.
Export winning weights as Python constants (printed + JSON).

Outputs:
  intel/nn_7marks_weights.json   -- full weight dump for both products
  intel/nn_7marks_summary.txt    -- printed metric tables
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
MARKS = ["Mark 01", "Mark 14", "Mark 22", "Mark 38", "Mark 49", "Mark 55", "Mark 67"]
ROLL = 100
FWD_HORIZON = 50

# ---------------------------------------------------------------------------
# Data loading + feature engineering
# ---------------------------------------------------------------------------

def load_day(day: int):
    px = pd.read_csv(RES / f"prices_round_4_day_{day}.csv", sep=";")
    tr = pd.read_csv(RES / f"trades_round_4_day_{day}.csv", sep=";")
    return px, tr


def build_features(px: pd.DataFrame, tr: pd.DataFrame, product: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    p = px[px["product"] == product].sort_values("timestamp").reset_index(drop=True)
    n = len(p)

    bv = p[[f"bid_volume_{i}" for i in (1, 2, 3)]].fillna(0).values.astype(float)
    av = p[[f"ask_volume_{i}" for i in (1, 2, 3)]].fillna(0).values.astype(float)
    bp = p[[f"bid_price_{i}" for i in (1, 2, 3)]].fillna(0).values.astype(float)
    ap = p[[f"ask_price_{i}" for i in (1, 2, 3)]].fillna(0).values.astype(float)

    bv1, av1 = bv[:, 0], av[:, 0]
    sum1 = np.where((bv1 + av1) > 0, bv1 + av1, 1)
    obi1 = (bv1 - av1) / sum1

    bv_sum, av_sum = bv.sum(1), av.sum(1)
    bw = (bp * bv).sum(1) / np.where(bv_sum > 0, bv_sum, 1)
    aw = (ap * av).sum(1) / np.where(av_sum > 0, av_sum, 1)
    wmid_L3 = 0.5 * (bw + aw)
    mid = p["mid_price"].values.astype(float)
    micro_dev = wmid_L3 - mid
    spread = (p["ask_price_1"].values - p["bid_price_1"].values).astype(float)
    ret_5 = np.concatenate([np.zeros(5), mid[5:] - mid[:-5]])

    # Per-mark rolling-100 volumes for THIS product.
    tr_p = tr[tr["symbol"] == product].copy()
    ts_index = p["timestamp"].values
    mark_buy = np.zeros((n, len(MARKS)))
    mark_sell = np.zeros((n, len(MARKS)))
    if len(tr_p):
        for i, m in enumerate(MARKS):
            buy_g = (tr_p[tr_p["buyer"] == m].groupby("timestamp")["quantity"].sum()
                     .reindex(ts_index, fill_value=0).values.astype(float))
            sell_g = (tr_p[tr_p["seller"] == m].groupby("timestamp")["quantity"].sum()
                      .reindex(ts_index, fill_value=0).values.astype(float))
            # rolling window=100
            mark_buy[:, i] = pd.Series(buy_g).rolling(ROLL, min_periods=1).sum().values
            mark_sell[:, i] = pd.Series(sell_g).rolling(ROLL, min_periods=1).sum().values

    feats = np.column_stack([mark_buy, mark_sell, obi1, micro_dev, spread, ret_5])
    feats = np.nan_to_num(feats, nan=0, posinf=0, neginf=0)

    y = np.concatenate([mid[FWD_HORIZON:] - mid[:-FWD_HORIZON], np.zeros(FWD_HORIZON)])
    valid = np.zeros(n, dtype=bool)
    valid[ROLL : n - FWD_HORIZON] = True
    return feats, y, valid


FEATURE_NAMES = (
    [f"buy_{m.replace(' ', '')}" for m in MARKS]
    + [f"sell_{m.replace(' ', '')}" for m in MARKS]
    + ["obi", "micro_dev", "spread", "ret5"]
)
assert len(FEATURE_NAMES) == 18

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def fit_ridge(X, y, lam=1.0):
    Xa = np.column_stack([np.ones(len(X)), X])
    A = Xa.T @ Xa
    A[1:, 1:] += lam * np.eye(X.shape[1])
    return np.linalg.solve(A, Xa.T @ y)


def predict_linear(w, X):
    return w[0] + X @ w[1:]


def fit_mlp(X, y, hidden=8, lr=0.005, epochs=400, seed=0, l2=1e-4):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1
    Xn = (X - mu) / sd
    ymu = y.mean(); ysd = y.std() + 1e-9
    yn = (y - ymu) / ysd

    W1 = rng.normal(0, np.sqrt(2.0 / d), size=(d, hidden))
    b1 = np.zeros(hidden)
    W2 = rng.normal(0, np.sqrt(2.0 / hidden), size=(hidden,))
    b2 = 0.0

    for ep in range(epochs):
        z1 = Xn @ W1 + b1
        a1 = np.maximum(z1, 0)
        yhat = a1 @ W2 + b2
        err = yhat - yn
        dW2 = a1.T @ err / n + l2 * W2
        db2 = err.mean()
        d_a1 = np.outer(err, W2)
        d_z1 = d_a1 * (z1 > 0).astype(float)
        dW1 = Xn.T @ d_z1 / n + l2 * W1
        db1 = d_z1.mean(0)
        W1 -= lr * dW1; b1 -= lr * db1
        W2 -= lr * dW2; b2 -= lr * db2

    return {"mu": mu, "sd": sd, "ymu": float(ymu), "ysd": float(ysd),
            "W1": W1, "b1": b1, "W2": W2, "b2": float(b2)}


def predict_mlp(m, X):
    Xn = (X - m["mu"]) / m["sd"]
    a1 = np.maximum(Xn @ m["W1"] + m["b1"], 0)
    return (a1 @ m["W2"] + m["b2"]) * m["ysd"] + m["ymu"]


def metrics(y, yhat):
    if len(y) == 0:
        return 0.0, 0.0, 0.0
    ss_res = ((y - yhat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum() + 1e-9
    r2 = 1 - ss_res / ss_tot
    rmse = float(np.sqrt(((y - yhat) ** 2).mean()))
    nz = y != 0
    sgn = float((np.sign(y[nz]) == np.sign(yhat[nz])).mean()) if nz.any() else 0.0
    return float(r2), rmse, sgn


# ---------------------------------------------------------------------------
# Per-product walk-forward + final fit
# ---------------------------------------------------------------------------

def fit_product(product: str, lines: list[str]) -> dict:
    lines.append(f"\n=== {product} (target: forward {FWD_HORIZON}-tick mid return) ===")
    Xs, Ys, Vs, Ds = [], [], [], []
    for d in DAYS:
        px, tr = load_day(d)
        X, y, valid = build_features(px, tr, product)
        Xs.append(X); Ys.append(y); Vs.append(valid); Ds.append(np.full(len(X), d))
    X_all = np.vstack(Xs); y_all = np.concatenate(Ys)
    valid_all = np.concatenate(Vs); days_all = np.concatenate(Ds)

    summary = {"product": product, "feature_names": FEATURE_NAMES,
               "horizon": FWD_HORIZON, "oos": []}

    # Walk-forward leave-one-day-out
    model_scores = {"lin": [], "ridge1": [], "ridge10": [], "mlp": []}
    for hold in DAYS:
        tr_mask = (days_all != hold) & valid_all
        te_mask = (days_all == hold) & valid_all
        Xtr, ytr = X_all[tr_mask], y_all[tr_mask]
        Xte, yte = X_all[te_mask], y_all[te_mask]

        w_lin = fit_ridge(Xtr, ytr, lam=1e-4)
        w_r1 = fit_ridge(Xtr, ytr, lam=1.0)
        w_r10 = fit_ridge(Xtr, ytr, lam=10.0)
        m_mlp = fit_mlp(Xtr, ytr, hidden=8, epochs=400, seed=0)

        scores = {}
        for name, pred in (("lin", predict_linear(w_lin, Xte)),
                           ("ridge1", predict_linear(w_r1, Xte)),
                           ("ridge10", predict_linear(w_r10, Xte)),
                           ("mlp", predict_mlp(m_mlp, Xte))):
            r2, rmse, sgn = metrics(yte, pred)
            model_scores[name].append((r2, sgn))
            scores[name] = (r2, rmse, sgn)

        lines.append(
            f"  hold {hold}: " + "  ".join(
                f"{k} R2={v[0]:+.4f} sgn={v[2]:.3f}" for k, v in scores.items()
            )
        )
        summary["oos"].append({"hold": hold, "scores": scores})

    # Aggregate
    agg = {k: (np.mean([s[0] for s in v]), np.mean([s[1] for s in v]))
           for k, v in model_scores.items()}
    lines.append("  --- mean OOS ---")
    for k, (r2, sgn) in agg.items():
        lines.append(f"    {k}: R2={r2:+.4f} sgn={sgn:.3f}")

    # Pick winner: prioritize sign accuracy (PnL proxy), tie-break R^2.
    winner = max(agg.items(), key=lambda kv: (kv[1][1], kv[1][0]))[0]
    lines.append(f"  >>> winner: {winner}")

    # Final fit on all 3 days (for deployment).
    valid_full = valid_all
    Xf, yf = X_all[valid_full], y_all[valid_full]

    w_lin_f = fit_ridge(Xf, yf, lam=1e-4)
    w_r1_f = fit_ridge(Xf, yf, lam=1.0)
    w_r10_f = fit_ridge(Xf, yf, lam=10.0)
    m_mlp_f = fit_mlp(Xf, yf, hidden=8, epochs=500, seed=0)

    summary["models"] = {
        "lin": {"bias": float(w_lin_f[0]),
                "weights": {n: float(w_lin_f[i+1]) for i, n in enumerate(FEATURE_NAMES)}},
        "ridge1": {"bias": float(w_r1_f[0]),
                   "weights": {n: float(w_r1_f[i+1]) for i, n in enumerate(FEATURE_NAMES)}},
        "ridge10": {"bias": float(w_r10_f[0]),
                    "weights": {n: float(w_r10_f[i+1]) for i, n in enumerate(FEATURE_NAMES)}},
        "mlp": {"mu": m_mlp_f["mu"].tolist(), "sd": m_mlp_f["sd"].tolist(),
                "ymu": m_mlp_f["ymu"], "ysd": m_mlp_f["ysd"],
                "W1": m_mlp_f["W1"].tolist(), "b1": m_mlp_f["b1"].tolist(),
                "W2": m_mlp_f["W2"].tolist(), "b2": m_mlp_f["b2"]},
    }
    summary["winner"] = winner

    # In-sample sanity for winner.
    if winner == "mlp":
        yhat = predict_mlp(m_mlp_f, Xf)
    else:
        wmap = {"lin": w_lin_f, "ridge1": w_r1_f, "ridge10": w_r10_f}
        yhat = predict_linear(wmap[winner], Xf)
    r2, rmse, sgn = metrics(yf, yhat)
    lines.append(f"  in-sample {winner}: R2={r2:+.4f} sgn={sgn:.3f} rmse={rmse:.3f}")

    # Top 5 features by |weight| for ridge1 (most interpretable).
    w_pairs = sorted(
        ((n, w_r1_f[i+1]) for i, n in enumerate(FEATURE_NAMES)),
        key=lambda kv: abs(kv[1]), reverse=True,
    )[:8]
    lines.append("  ridge1 top-8 features: " + ", ".join(f"{n}={w:+.5f}" for n, w in w_pairs))
    return summary


def main():
    lines: list[str] = [f"nn_7marks training, horizon={FWD_HORIZON}, roll={ROLL}"]
    out = {}
    for prod in ("HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"):
        out[prod] = fit_product(prod, lines)
    (INTEL / "nn_7marks_weights.json").write_text(json.dumps(out, indent=2))
    summary = "\n".join(lines)
    (INTEL / "nn_7marks_summary.txt").write_text(summary)
    print(summary)
    print(f"\nSaved -> {INTEL / 'nn_7marks_weights.json'}")
    print(f"Saved -> {INTEL / 'nn_7marks_summary.txt'}")


if __name__ == "__main__":
    main()
