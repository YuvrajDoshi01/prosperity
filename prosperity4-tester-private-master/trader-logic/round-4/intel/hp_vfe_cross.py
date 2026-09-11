"""HP x VFE cross-product alpha hunt for Round 4.

Examines correlation, Granger causality, basket cointegration, and a 2D regime
detector to refine the existing VFE-CRASH gate on HP S17.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester")
RES = ROOT / "prosperity4bt/resources/round4"


def load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(RES / f"prices_round_4_day_{day}.csv", sep=";")
    df = df[df["product"].isin(["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"])]
    piv = df.pivot_table(
        index="timestamp", columns="product", values="mid_price", aggfunc="first"
    ).dropna()
    piv.columns = ["HP", "VFE"]
    return piv


def lag_corr(x: pd.Series, y: pd.Series, max_lag: int = 100) -> dict:
    """Cross-correlation: corr(x_t, y_{t+k}) for k in [-max_lag, max_lag]."""
    out = {}
    for k in [-1000, -500, -100, -50, -10, 0, 10, 50, 100, 500, 1000]:
        if abs(k) >= len(x):
            continue
        if k >= 0:
            c = np.corrcoef(x[:-k or None], y[k:])[0, 1]
        else:
            c = np.corrcoef(x[-k:], y[:k])[0, 1]
        out[k] = c
    return out


def granger_test(y: np.ndarray, x: np.ndarray, p: int = 5) -> float:
    """F-stat for x Granger-causing y (does x add info beyond y's own lags?)."""
    n = len(y)
    Y = y[p:]
    L_y = np.column_stack([y[p - i - 1 : n - i - 1] for i in range(p)])
    L_x = np.column_stack([x[p - i - 1 : n - i - 1] for i in range(p)])
    # restricted: y on lags of y
    Xr = np.column_stack([np.ones(len(Y)), L_y])
    br, *_ = np.linalg.lstsq(Xr, Y, rcond=None)
    rss_r = float(((Y - Xr @ br) ** 2).sum())
    # unrestricted: y on lags of y AND x
    Xu = np.column_stack([np.ones(len(Y)), L_y, L_x])
    bu, *_ = np.linalg.lstsq(Xu, Y, rcond=None)
    rss_u = float(((Y - Xu @ bu) ** 2).sum())
    df_n = p
    df_d = len(Y) - 2 * p - 1
    if rss_u <= 0 or df_d <= 0:
        return 0.0
    F = ((rss_r - rss_u) / df_n) / (rss_u / df_d)
    return float(F)


def adf_pvalue_proxy(s: pd.Series) -> float:
    """Quick stationarity proxy: AR(1) coef. <1 means mean-reverting."""
    s = s.dropna().values
    y = s[1:] - s[:-1]
    x = s[:-1] - s[:-1].mean()
    beta = np.dot(x, y) / np.dot(x, x)
    return float(beta)  # negative = mean reverting


def basket_spread(hp: pd.Series, vfe: pd.Series) -> tuple[float, pd.Series]:
    """OLS hedge ratio alpha minimizing var(HP - alpha*VFE)."""
    cov = np.cov(hp, vfe)[0, 1]
    var = np.var(vfe)
    alpha = cov / var
    spread = hp - alpha * vfe
    return float(alpha), spread


def regime_features(df: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["hp_mid"] = df["HP"]
    out["vfe_mid"] = df["VFE"]
    out["hp_vol"] = df["HP"].rolling(window).std()
    out["vfe_drift"] = df["VFE"] - df["VFE"].rolling(window).mean()
    out["vfe_drift_legacy"] = df["VFE"] - df["VFE"].rolling(window).apply(
        lambda s: s.iloc[:25].mean(), raw=False
    )
    out["hp_dev_mid"] = df["HP"] - 9990
    return out.dropna()


def s17_gate_test(df: pd.DataFrame, day: int, gate_fn, label: str) -> dict:
    """Approximate S17 PnL impact: count blocked-vs-allowed entries.

    Real S17 needs spread==17 in the engine. Here we just count *opportunities*
    where the gate would have fired, segmented by HP outcome 200 ticks later.
    """
    feat = regime_features(df)
    blocked = []
    allowed = []
    for ts, row in feat.iterrows():
        if ts + 20000 > df.index.max():
            continue
        hp_now = row["hp_mid"]
        if hp_now <= 10010:  # S17 only fires above 10010
            continue
        hp_future = df["HP"].loc[ts + 20000] if ts + 20000 in df.index else hp_now
        rev_pnl = hp_now - hp_future  # short PnL if HP drops
        if gate_fn(row):
            blocked.append(rev_pnl)
        else:
            allowed.append(rev_pnl)
    return {
        "day": day,
        "gate": label,
        "n_allowed": len(allowed),
        "allowed_mean_pnl": float(np.mean(allowed)) if allowed else 0.0,
        "n_blocked": len(blocked),
        "blocked_mean_pnl": float(np.mean(blocked)) if blocked else 0.0,
    }


def main():
    print("=" * 70)
    print("HP x VFE CROSS-PRODUCT ANALYSIS — Round 4")
    print("=" * 70)

    days = {d: load_day(d) for d in (1, 2, 3)}

    # 1) Cross-correlation
    print("\n[1] Lag cross-corr  corr(HP_t, VFE_{t+k}) — k in ticks (1 tick=100ms)")
    print(f"{'day':>4} {'-1000':>8} {'-500':>8} {'-100':>8} {'-50':>8} {'-10':>8} "
          f"{'0':>8} {'10':>8} {'50':>8} {'100':>8} {'500':>8} {'1000':>8}")
    for d, df in days.items():
        cc = lag_corr(df["HP"], df["VFE"], max_lag=1000)
        row = " ".join(f"{cc.get(k, np.nan):>8.3f}" for k in
                       [-1000, -500, -100, -50, -10, 0, 10, 50, 100, 500, 1000])
        print(f"{d:>4} {row}")

    # Cross-correlation on RETURNS (more robust to drift)
    print("\n[1b] Lag cross-corr on returns  corr(dHP_t, dVFE_{t+k})")
    for d, df in days.items():
        dh, dv = df["HP"].diff().dropna(), df["VFE"].diff().dropna()
        idx = dh.index.intersection(dv.index)
        cc = lag_corr(dh.loc[idx], dv.loc[idx], max_lag=1000)
        row = " ".join(f"{cc.get(k, np.nan):>8.3f}" for k in
                       [-100, -50, -10, 0, 10, 50, 100])
        print(f"{d:>4} {row}")

    # 2) Granger causality (returns)
    print("\n[2] Granger F-stat (p=5 lags) on returns")
    print(f"{'day':>4}  {'VFE→HP':>10}  {'HP→VFE':>10}  {'F_crit_5%':>10}")
    for d, df in days.items():
        dh = df["HP"].diff().dropna().values
        dv = df["VFE"].diff().dropna().values
        n = min(len(dh), len(dv))
        f1 = granger_test(dh[:n], dv[:n], p=5)
        f2 = granger_test(dv[:n], dh[:n], p=5)
        print(f"{d:>4}  {f1:>10.3f}  {f2:>10.3f}  {'~2.21':>10}")

    # 3) Basket spread
    print("\n[3] OLS basket  HP - alpha*VFE  (test stationarity per day)")
    for d, df in days.items():
        a, sp = basket_spread(df["HP"], df["VFE"])
        beta = adf_pvalue_proxy(sp)
        rng = float(sp.max() - sp.min())
        print(f"  day {d}: alpha={a:+.4f}  AR1_coef(spread_diff)={beta:+.4f}  "
              f"range={rng:.1f}  std={float(sp.std()):.2f}")
    # Pooled
    big = pd.concat([days[d] for d in (1, 2, 3)], ignore_index=True)
    a, sp = basket_spread(big["HP"], big["VFE"])
    print(f"  pooled: alpha={a:+.4f}  spread range across days={float(sp.max()-sp.min()):.1f}")

    # 4) VFE crash → HP regime change
    print("\n[4] Conditional: when VFE drifts < -5 in 200-tick window, "
          "what does HP do next 200 ticks?")
    for d, df in days.items():
        feat = regime_features(df, window=200)
        vfe_crash = feat["vfe_drift"] < -5
        hp_fwd = df["HP"].shift(-2000) - df["HP"]  # 2000 ticks ahead
        hp_fwd = hp_fwd.reindex(feat.index)
        if vfe_crash.sum() == 0:
            print(f"  day {d}: NO VFE-crash ticks (VFE stable)")
            continue
        m_crash = float(hp_fwd[vfe_crash].mean())
        m_calm = float(hp_fwd[~vfe_crash].mean())
        print(f"  day {d}: n_crash={int(vfe_crash.sum())}  "
              f"HP_fwd200|crash={m_crash:+.2f}  HP_fwd200|calm={m_calm:+.2f}  "
              f"diff={m_crash - m_calm:+.2f}")

    # 5) Simple gate comparison: legacy vs HP-vol-aware
    print("\n[5] Gate comparison on PROXY S17 opportunities (HP>10010)")
    legacy = lambda r: r["vfe_drift_legacy"] < -5.0
    tighter = lambda r: r["vfe_drift"] < -3.0
    twoD = lambda r: (r["vfe_drift"] < -3.0) or (r["hp_vol"] < 3.0 and r["vfe_drift"] < 0)
    for d, df in days.items():
        for label, fn in [("legacy_-5_first25", legacy),
                           ("tighter_drift_-3", tighter),
                           ("2D_drift+lowvol", twoD)]:
            r = s17_gate_test(df, d, fn, label)
            print(f"  day {d:>1} {label:>22}: "
                  f"allow_n={r['n_allowed']:>4} pnl={r['allowed_mean_pnl']:+.2f}  "
                  f"block_n={r['n_blocked']:>4} pnl={r['blocked_mean_pnl']:+.2f}")


if __name__ == "__main__":
    main()
