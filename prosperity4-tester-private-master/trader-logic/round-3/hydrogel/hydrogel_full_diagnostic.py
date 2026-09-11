#!/usr/bin/env python3
"""
Full diagnostic scanner for IMC order-book data.
Default target: HYDROGEL_PACK.

This script writes a complete research report with CSV tables and optional PNG plots.

Basic run:
  python3 hydrogel_full_diagnostic.py \
    --prices prices_round_3_day_0.csv \
    --trades trades_round_3_day_0.csv \
    --product HYDROGEL_PACK \
    --out hydrogel_day0_report

With plots:
  python3 hydrogel_full_diagnostic.py \
    --prices prices_round_3_day_0.csv \
    --trades trades_round_3_day_0.csv \
    --product HYDROGEL_PACK \
    --out hydrogel_day0_report \
    --make-plots
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


HORIZONS = [1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000]
WINDOWS = [10, 20, 50, 100, 200, 500, 1000]
LEVELS = [1, 2, 3]

PRICE_REQUIRED = {
    "day", "timestamp", "product",
    "bid_price_1", "bid_volume_1", "ask_price_1", "ask_volume_1",
    "mid_price",
}
TRADE_REQUIRED = {"timestamp", "symbol", "price", "quantity"}


# =============================================================================
# 0. Utilities
# =============================================================================

def mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_csv_auto(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    if len(df.columns) == 1:
        df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    return df


def save_csv(df: pd.DataFrame, path: Path) -> None:
    mkdir(path.parent)
    df.to_csv(path, index=False)


def save_json(obj: dict, path: Path) -> None:
    mkdir(path.parent)
    with path.open("w") as f:
        json.dump(obj, f, indent=2, default=str)


def finite_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def describe_series(name: str, s: pd.Series) -> dict:
    x = finite_series(s).dropna()
    if len(x) == 0:
        return {"metric": name, "count": 0}
    return {
        "metric": name,
        "count": int(x.count()),
        "missing": int(s.isna().sum()),
        "mean": float(x.mean()),
        "median": float(x.median()),
        "std": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
        "min": float(x.min()),
        "p01": float(x.quantile(0.01)),
        "p05": float(x.quantile(0.05)),
        "p10": float(x.quantile(0.10)),
        "p25": float(x.quantile(0.25)),
        "p75": float(x.quantile(0.75)),
        "p90": float(x.quantile(0.90)),
        "p95": float(x.quantile(0.95)),
        "p99": float(x.quantile(0.99)),
        "max": float(x.max()),
        "n_unique": int(x.nunique()),
    }


def corr_np(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return np.nan
    x = x[mask]
    y = y[mask]
    vx = np.var(x)
    vy = np.var(y)
    if vx <= 0 or vy <= 0:
        return np.nan
    return float(np.mean((x - x.mean()) * (y - y.mean())) / math.sqrt(vx * vy))


def slope_np(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return np.nan
    x = x[mask]
    y = y[mask]
    vx = np.var(x)
    if vx <= 0:
        return np.nan
    return float(np.mean((x - x.mean()) * (y - y.mean())) / vx)


def qbucket(s: pd.Series, n: int = 10) -> pd.Series:
    x = finite_series(s)
    try:
        return pd.qcut(x, q=n, duplicates="drop")
    except Exception:
        try:
            return pd.cut(x, bins=n, duplicates="drop")
        except Exception:
            return pd.Series([np.nan] * len(s), index=s.index)


# =============================================================================
# 1. Load and enrich book
# =============================================================================

def load_prices(path: Path, product: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = read_csv_auto(path)
    missing = sorted(PRICE_REQUIRED - set(raw.columns))
    if missing:
        raise ValueError(f"Price file missing required columns: {missing}")
    df = raw[raw["product"] == product].copy()
    if df.empty:
        products = sorted(raw["product"].dropna().unique().tolist())
        raise ValueError(f"No rows for product={product}. Available products: {products}")
    df = df.sort_values("timestamp").reset_index(drop=True)
    for c in df.columns:
        if c != "product":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return raw, df


def enrich_book(df: pd.DataFrame, horizons: list[int], windows: list[int]) -> pd.DataFrame:
    base = df.copy()
    f: dict[str, pd.Series | np.ndarray | float] = {}

    f["best_bid"] = base["bid_price_1"]
    f["best_ask"] = base["ask_price_1"]
    f["computed_mid"] = (base["bid_price_1"] + base["ask_price_1"]) / 2.0
    f["mid_error"] = base["mid_price"] - f["computed_mid"]
    f["spread"] = base["ask_price_1"] - base["bid_price_1"]
    f["half_spread"] = f["spread"] / 2.0

    for lvl in LEVELS:
        bp = f"bid_price_{lvl}"
        ap = f"ask_price_{lvl}"
        bv = f"bid_volume_{lvl}"
        av = f"ask_volume_{lvl}"
        if bp not in base:
            base[bp] = np.nan
        if ap not in base:
            base[ap] = np.nan
        if bv not in base:
            base[bv] = np.nan
        if av not in base:
            base[av] = np.nan
        f[f"bid_size_{lvl}"] = base[bv].abs().fillna(0.0)
        f[f"ask_size_{lvl}"] = base[av].abs().fillna(0.0)

    f["bid_gap_12"] = base["bid_price_1"] - base["bid_price_2"]
    f["bid_gap_23"] = base["bid_price_2"] - base["bid_price_3"]
    f["ask_gap_12"] = base["ask_price_2"] - base["ask_price_1"]
    f["ask_gap_23"] = base["ask_price_3"] - base["ask_price_2"]

    for depth in LEVELS:
        bid_depth = sum(f[f"bid_size_{i}"] for i in range(1, depth + 1))
        ask_depth = sum(f[f"ask_size_{i}"] for i in range(1, depth + 1))
        denom = bid_depth + ask_depth
        f[f"bid_depth_L{depth}"] = bid_depth
        f[f"ask_depth_L{depth}"] = ask_depth
        f[f"total_depth_L{depth}"] = denom
        f[f"imbalance_L{depth}"] = np.where(denom > 0, (bid_depth - ask_depth) / denom, np.nan)

    denom1 = f["bid_size_1"] + f["ask_size_1"]
    f["microprice_L1"] = np.where(
        denom1 > 0,
        (base["ask_price_1"] * f["bid_size_1"] + base["bid_price_1"] * f["ask_size_1"]) / denom1,
        base["mid_price"],
    )
    f["micro_edge_L1"] = f["microprice_L1"] - base["mid_price"]

    for depth in LEVELS:
        bid_num = sum(base[f"bid_price_{i}"].fillna(0.0) * f[f"bid_size_{i}"] for i in range(1, depth + 1))
        ask_num = sum(base[f"ask_price_{i}"].fillna(0.0) * f[f"ask_size_{i}"] for i in range(1, depth + 1))
        bid_den = sum(f[f"bid_size_{i}"] for i in range(1, depth + 1))
        ask_den = sum(f[f"ask_size_{i}"] for i in range(1, depth + 1))
        f[f"bid_wap_L{depth}"] = np.where(bid_den > 0, bid_num / bid_den, np.nan)
        f[f"ask_wap_L{depth}"] = np.where(ask_den > 0, ask_num / ask_den, np.nan)
        f[f"book_wap_mid_L{depth}"] = (f[f"bid_wap_L{depth}"] + f[f"ask_wap_L{depth}"]) / 2.0
        f[f"book_wap_edge_L{depth}"] = f[f"book_wap_mid_L{depth}"] - base["mid_price"]

    f["mid_change"] = base["mid_price"].diff()
    f["bid_change"] = base["bid_price_1"].diff()
    f["ask_change"] = base["ask_price_1"].diff()
    f["spread_change"] = pd.Series(f["spread"]).diff()
    f["bid_size_1_change"] = pd.Series(f["bid_size_1"]).diff()
    f["ask_size_1_change"] = pd.Series(f["ask_size_1"]).diff()

    f["mid_changed"] = pd.Series(f["mid_change"]).fillna(0).ne(0).astype(int)
    f["bid_changed"] = pd.Series(f["bid_change"]).fillna(0).ne(0).astype(int)
    f["ask_changed"] = pd.Series(f["ask_change"]).fillna(0).ne(0).astype(int)
    f["spread_changed"] = pd.Series(f["spread_change"]).fillna(0).ne(0).astype(int)
    f["bid_size_1_changed"] = pd.Series(f["bid_size_1_change"]).fillna(0).ne(0).astype(int)
    f["ask_size_1_changed"] = pd.Series(f["ask_size_1_change"]).fillna(0).ne(0).astype(int)

    for h in horizons:
        f[f"past_ret_{h}"] = base["mid_price"].diff(h)
        f[f"future_ret_{h}"] = base["mid_price"].shift(-h) - base["mid_price"]
        f[f"future_abs_ret_{h}"] = pd.Series(f[f"future_ret_{h}"]).abs()
        f[f"future_up_{h}"] = (pd.Series(f[f"future_ret_{h}"]) > 0).astype(int)

    for w in windows:
        minp = max(3, min(20, w // 5))
        roll_mean = base["mid_price"].rolling(w, min_periods=minp).mean()
        roll_med = base["mid_price"].rolling(w, min_periods=minp).median()
        roll_std = base["mid_price"].rolling(w, min_periods=minp).std(ddof=1)
        ema = base["mid_price"].ewm(span=w, adjust=False, min_periods=minp).mean()
        f[f"roll_mean_{w}"] = roll_mean
        f[f"roll_median_{w}"] = roll_med
        f[f"roll_std_mid_{w}"] = roll_std
        f[f"roll_vol_ret1_{w}"] = pd.Series(f["mid_change"]).rolling(w, min_periods=minp).std(ddof=1)
        f[f"dev_roll_mean_{w}"] = base["mid_price"] - roll_mean
        f[f"dev_roll_median_{w}"] = base["mid_price"] - roll_med
        f[f"z_roll_mean_{w}"] = np.where(roll_std > 0, (base["mid_price"] - roll_mean) / roll_std, np.nan)
        f[f"ema_{w}"] = ema
        f[f"dev_ema_{w}"] = base["mid_price"] - ema

    gm = base["mid_price"].mean()
    gs = base["mid_price"].std(ddof=1)
    f["global_mean"] = gm
    f["dev_global_mean"] = base["mid_price"] - gm
    f["z_global_mean"] = f["dev_global_mean"] / gs if gs > 0 else np.nan

    n = len(base)
    f["row_index"] = np.arange(n)
    f["time_bucket_10"] = pd.cut(np.arange(n), bins=10, labels=False, include_lowest=True)
    f["time_bucket_20"] = pd.cut(np.arange(n), bins=20, labels=False, include_lowest=True)

    features = pd.DataFrame(f, index=base.index)
    out = pd.concat([base, features], axis=1)
    return out.replace([np.inf, -np.inf], np.nan)


# =============================================================================
# 2. Reports
# =============================================================================

def run_info(raw: pd.DataFrame, df: pd.DataFrame, prices: Path, trades: Path | None, product: str) -> dict:
    ts = df["timestamp"]
    d = ts.diff().dropna()
    step = float(d.mode().iloc[0]) if len(d) else np.nan
    return {
        "product": product,
        "prices_file": str(prices),
        "trades_file": str(trades) if trades else None,
        "raw_rows": int(len(raw)),
        "product_rows": int(len(df)),
        "available_products": sorted(raw["product"].dropna().unique().tolist()),
        "day_values": sorted([int(x) for x in df["day"].dropna().unique().tolist()]),
        "timestamp_min": int(ts.min()),
        "timestamp_max": int(ts.max()),
        "timestamp_unique": int(ts.nunique()),
        "timestamp_duplicates": int(ts.duplicated().sum()),
        "most_common_timestamp_step": step,
        "step_gaps_count": int(((d / step) > 1).sum()) if step and not np.isnan(step) else 0,
        "start_mid": float(df["mid_price"].iloc[0]),
        "end_mid": float(df["mid_price"].iloc[-1]),
        "net_mid_change": float(df["mid_price"].iloc[-1] - df["mid_price"].iloc[0]),
    }


def missingness(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(df)
    for c in df.columns:
        rows.append({
            "column": c,
            "dtype": str(df[c].dtype),
            "missing_count": int(df[c].isna().sum()),
            "missing_pct": float(df[c].isna().mean()),
            "present_pct": float(df[c].notna().mean()),
            "n_unique": int(df[c].nunique(dropna=True)),
        })
    return pd.DataFrame(rows)


def summary_table(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame([describe_series(c, df[c]) for c in cols if c in df.columns])


def spread_counts(df: pd.DataFrame) -> pd.DataFrame:
    vc = df["spread"].value_counts(dropna=False).sort_index()
    out = vc.rename_axis("spread").reset_index(name="count")
    out["pct"] = out["count"] / len(df)
    return out


def level_presence(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lvl in LEVELS:
        rows.append({
            "level": lvl,
            "bid_price_present_pct": float(df[f"bid_price_{lvl}"].notna().mean()),
            "ask_price_present_pct": float(df[f"ask_price_{lvl}"].notna().mean()),
            "bid_size_positive_pct": float((df[f"bid_size_{lvl}"] > 0).mean()),
            "ask_size_positive_pct": float((df[f"ask_size_{lvl}"] > 0).mean()),
            "avg_bid_size": float(df[f"bid_size_{lvl}"].mean()),
            "avg_ask_size": float(df[f"ask_size_{lvl}"].mean()),
        })
    return pd.DataFrame(rows)


def return_summary(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for h in horizons:
        col = f"past_ret_{h}"
        r = describe_series(col, df[col])
        x = df[col].dropna()
        r.update({
            "horizon": h,
            "positive_pct": float((x > 0).mean()) if len(x) else np.nan,
            "negative_pct": float((x < 0).mean()) if len(x) else np.nan,
            "zero_pct": float((x == 0).mean()) if len(x) else np.nan,
            "mean_abs": float(x.abs().mean()) if len(x) else np.nan,
        })
        rows.append(r)
    return pd.DataFrame(rows)


def autocorr_report(df: pd.DataFrame, max_lag: int = 100) -> pd.DataFrame:
    x = df["past_ret_1"].to_numpy(dtype=float)
    rows = []
    for lag in range(1, max_lag + 1):
        rows.append({"series": "past_ret_1", "lag": lag, "autocorr": corr_np(x[lag:], x[:-lag])})
    return pd.DataFrame(rows)


def feature_cols(windows: list[int]) -> list[str]:
    cols = [
        "spread", "half_spread",
        "bid_size_1", "ask_size_1", "bid_size_2", "ask_size_2", "bid_size_3", "ask_size_3",
        "bid_depth_L1", "ask_depth_L1", "bid_depth_L2", "ask_depth_L2", "bid_depth_L3", "ask_depth_L3",
        "total_depth_L1", "total_depth_L2", "total_depth_L3",
        "imbalance_L1", "imbalance_L2", "imbalance_L3",
        "micro_edge_L1", "book_wap_edge_L1", "book_wap_edge_L2", "book_wap_edge_L3",
        "bid_gap_12", "ask_gap_12", "bid_gap_23", "ask_gap_23",
        "mid_change", "bid_change", "ask_change", "spread_change", "bid_size_1_change", "ask_size_1_change",
        "dev_global_mean", "z_global_mean",
        "past_ret_1", "past_ret_2", "past_ret_3", "past_ret_5", "past_ret_10", "past_ret_20", "past_ret_50",
    ]
    for w in windows:
        cols += [
            f"roll_vol_ret1_{w}",
            f"dev_roll_mean_{w}", f"dev_roll_median_{w}", f"z_roll_mean_{w}", f"dev_ema_{w}",
        ]
    return cols


def signal_scan(df: pd.DataFrame, features: list[str], horizons: list[int]) -> pd.DataFrame:
    rows = []
    y_by_h = {h: df[f"future_ret_{h}"].to_numpy(dtype=float) for h in horizons}
    for feat in features:
        if feat not in df.columns:
            continue
        x_all = finite_series(df[feat]).to_numpy(dtype=float)
        mask_x = np.isfinite(x_all)
        if np.unique(x_all[mask_x]).size <= 1:
            continue
        for h, y_all in y_by_h.items():
            mask = mask_x & np.isfinite(y_all)
            if mask.sum() < 30:
                continue
            x = x_all[mask]
            y = y_all[mask]
            q10 = np.quantile(x, 0.10)
            q90 = np.quantile(x, 0.90)
            low = y[x <= q10]
            high = y[x >= q90]
            rows.append({
                "feature": feat,
                "horizon": h,
                "n": int(mask.sum()),
                "corr": corr_np(x, y),
                "abs_corr": abs(corr_np(x, y)) if np.isfinite(corr_np(x, y)) else np.nan,
                "slope_ticks_per_feature_unit": slope_np(x, y),
                "feature_mean": float(np.mean(x)),
                "feature_std": float(np.std(x, ddof=1)),
                "future_ret_mean": float(np.mean(y)),
                "future_abs_ret_mean": float(np.mean(np.abs(y))),
                "bottom_10pct_feature_cutoff": float(q10),
                "bottom_10pct_future_ret_mean": float(np.mean(low)) if len(low) else np.nan,
                "bottom_10pct_hit_up": float(np.mean(low > 0)) if len(low) else np.nan,
                "top_10pct_feature_cutoff": float(q90),
                "top_10pct_future_ret_mean": float(np.mean(high)) if len(high) else np.nan,
                "top_10pct_hit_up": float(np.mean(high > 0)) if len(high) else np.nan,
                "top_minus_bottom_future_ret": float(np.mean(high) - np.mean(low)) if len(high) and len(low) else np.nan,
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["horizon", "abs_corr"], ascending=[True, False])
    return out


def bucket_scan(df: pd.DataFrame, features: list[str], horizons: list[int], bins: int) -> pd.DataFrame:
    rows = []
    for feat in features:
        if feat not in df.columns or df[feat].dropna().nunique() <= 1:
            continue
        tmp = pd.DataFrame({feat: df[feat]})
        tmp["bucket"] = qbucket(df[feat], bins)
        for h in horizons:
            tmp[f"future_ret_{h}"] = df[f"future_ret_{h}"]
        tmp = tmp.dropna(subset=["bucket"])
        for b, g in tmp.groupby("bucket", observed=True):
            row = {
                "feature": feat,
                "bucket": str(b),
                "count": int(len(g)),
                "feature_min": float(g[feat].min()),
                "feature_mean": float(g[feat].mean()),
                "feature_max": float(g[feat].max()),
            }
            for h in horizons:
                fr = g[f"future_ret_{h}"].dropna()
                row[f"future_ret_{h}_mean"] = float(fr.mean()) if len(fr) else np.nan
                row[f"future_ret_{h}_hit_up"] = float((fr > 0).mean()) if len(fr) else np.nan
                row[f"future_abs_ret_{h}_mean"] = float(fr.abs().mean()) if len(fr) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def spread_conditional(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for sp, g in df.groupby("spread", dropna=False):
        row = {
            "spread": sp,
            "count": int(len(g)),
            "pct": float(len(g) / len(df)),
            "mid_mean": float(g["mid_price"].mean()),
            "mid_std": float(g["mid_price"].std(ddof=1)),
            "imbalance_L1_mean": float(g["imbalance_L1"].mean()),
            "micro_edge_L1_mean": float(g["micro_edge_L1"].mean()),
        }
        x = g["imbalance_L1"].to_numpy(dtype=float)
        for h in horizons:
            y = g[f"future_ret_{h}"].to_numpy(dtype=float)
            row[f"future_ret_{h}_mean"] = float(np.nanmean(y))
            row[f"future_abs_ret_{h}_mean"] = float(np.nanmean(np.abs(y)))
            row[f"imbalance_corr_future_ret_{h}"] = corr_np(x, y)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("spread")


def time_conditional(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for b, g in df.groupby("time_bucket_20"):
        row = {
            "bucket": int(b),
            "count": int(len(g)),
            "timestamp_min": int(g["timestamp"].min()),
            "timestamp_max": int(g["timestamp"].max()),
            "mid_start": float(g["mid_price"].iloc[0]),
            "mid_end": float(g["mid_price"].iloc[-1]),
            "mid_mean": float(g["mid_price"].mean()),
            "mid_std": float(g["mid_price"].std(ddof=1)),
            "spread_mean": float(g["spread"].mean()),
            "ret1_std": float(g["past_ret_1"].std(ddof=1)),
            "imbalance_L1_mean": float(g["imbalance_L1"].mean()),
        }
        for h in horizons:
            row[f"future_abs_ret_{h}_mean"] = float(g[f"future_abs_ret_{h}"].mean())
            row[f"imbalance_corr_future_ret_{h}"] = corr_np(g["imbalance_L1"].to_numpy(dtype=float), g[f"future_ret_{h}"].to_numpy(dtype=float))
            if "dev_roll_mean_500" in g:
                row[f"dev500_corr_future_ret_{h}"] = corr_np(g["dev_roll_mean_500"].to_numpy(dtype=float), g[f"future_ret_{h}"].to_numpy(dtype=float))
        rows.append(row)
    return pd.DataFrame(rows)


def quote_change_report(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    conditions = {
        "mid_changed": df["mid_changed"] == 1,
        "bid_changed": df["bid_changed"] == 1,
        "ask_changed": df["ask_changed"] == 1,
        "spread_changed": df["spread_changed"] == 1,
        "size_changed_no_price_change": ((df["bid_size_1_changed"] == 1) | (df["ask_size_1_changed"] == 1)) & (df["bid_changed"] == 0) & (df["ask_changed"] == 0),
        "bid_up": df["bid_change"] > 0,
        "bid_down": df["bid_change"] < 0,
        "ask_up": df["ask_change"] > 0,
        "ask_down": df["ask_change"] < 0,
        "spread_tightened": df["spread_change"] < 0,
        "spread_widened": df["spread_change"] > 0,
        "bid_size_increased": df["bid_size_1_change"] > 0,
        "ask_size_increased": df["ask_size_1_change"] > 0,
    }
    rows = []
    for name, mask in conditions.items():
        g = df[mask.fillna(False)]
        row = {"condition": name, "count": int(len(g)), "pct": float(len(g) / len(df))}
        for h in horizons:
            fr = g[f"future_ret_{h}"].dropna()
            row[f"future_ret_{h}_mean"] = float(fr.mean()) if len(fr) else np.nan
            row[f"future_ret_{h}_hit_up"] = float((fr > 0).mean()) if len(fr) else np.nan
            row[f"future_abs_ret_{h}_mean"] = float(fr.abs().mean()) if len(fr) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def corr_matrix(df: pd.DataFrame, features: list[str], horizons: list[int]) -> pd.DataFrame:
    cols = [c for c in features if c in df.columns]
    cols += [f"future_ret_{h}" for h in horizons]
    cols += [f"past_ret_{h}" for h in horizons]
    cols = list(dict.fromkeys(cols))
    return df[cols].corr(numeric_only=True)


def event_study(df: pd.DataFrame, horizons: list[int], lookback: int, lookahead: int, max_events: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    masks = {}
    masks["tight_spread_bottom_10pct"] = df["spread"] <= df["spread"].quantile(0.10)
    masks["wide_spread_top_10pct"] = df["spread"] >= df["spread"].quantile(0.90)
    masks["high_bid_imbalance_top_10pct"] = df["imbalance_L1"] >= df["imbalance_L1"].quantile(0.90)
    masks["high_ask_imbalance_bottom_10pct"] = df["imbalance_L1"] <= df["imbalance_L1"].quantile(0.10)
    move = df["mid_change"].abs().quantile(0.95)
    masks["large_up_move"] = df["mid_change"] >= move
    masks["large_down_move"] = df["mid_change"] <= -move
    masks["spread_tightened"] = df["spread_change"] < 0
    masks["spread_widened"] = df["spread_change"] > 0
    masks["bid_size_increased"] = df["bid_size_1_change"] > 0
    masks["ask_size_increased"] = df["ask_size_1_change"] > 0
    if "z_roll_mean_500" in df:
        masks["z500_above_2"] = df["z_roll_mean_500"] >= 2
        masks["z500_below_minus_2"] = df["z_roll_mean_500"] <= -2

    summary_rows = []
    path_rows = []
    mid = df["mid_price"].to_numpy(dtype=float)
    rels = np.arange(-lookback, lookahead + 1)

    for name, mask in masks.items():
        idxs = np.where(mask.fillna(False).to_numpy())[0]
        usable = idxs[(idxs >= lookback) & (idxs < len(df) - lookahead)]
        if len(usable) > max_events:
            sample = usable[np.linspace(0, len(usable) - 1, max_events).astype(int)]
        else:
            sample = usable

        row = {"event": name, "count_all": int(mask.sum()), "count_usable": int(len(usable)), "count_sampled": int(len(sample))}
        g = df.iloc[usable] if len(usable) else pd.DataFrame()
        for h in horizons:
            fr = g[f"future_ret_{h}"].dropna() if len(g) else pd.Series(dtype=float)
            row[f"future_ret_{h}_mean"] = float(fr.mean()) if len(fr) else np.nan
            row[f"future_ret_{h}_hit_up"] = float((fr > 0).mean()) if len(fr) else np.nan
            row[f"future_abs_ret_{h}_mean"] = float(fr.abs().mean()) if len(fr) else np.nan
        summary_rows.append(row)

        if len(sample):
            idx_grid = sample[:, None] + rels[None, :]
            paths = mid[idx_grid] - mid[sample][:, None]
            avg = np.nanmean(paths, axis=0)
            for r, v in zip(rels, avg):
                path_rows.append({"event": name, "rel_step": int(r), "avg_mid_minus_event_mid": float(v)})

    return pd.DataFrame(summary_rows), pd.DataFrame(path_rows)


# =============================================================================
# 3. Trades
# =============================================================================

def analyze_trades(trades_path: Path | None, product: str, df: pd.DataFrame, out_dir: Path, horizons: list[int]) -> None:
    tdir = out_dir / "tables" / "trades"
    mkdir(tdir)
    if trades_path is None or not trades_path.exists():
        save_json({"status": "no trades file provided"}, tdir / "trades_info.json")
        return
    raw = read_csv_auto(trades_path)
    missing = sorted(TRADE_REQUIRED - set(raw.columns))
    if missing:
        save_json({"status": "trades file missing columns", "missing": missing}, tdir / "trades_info.json")
        return
    tr = raw[raw["symbol"] == product].copy()
    if tr.empty:
        save_json({"status": "no trades for product", "product": product}, tdir / "trades_info.json")
        return
    for c in ["timestamp", "price", "quantity"]:
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.sort_values("timestamp")

    book_cols = ["timestamp", "mid_price", "best_bid", "best_ask", "spread", "imbalance_L1", "microprice_L1", "micro_edge_L1"]
    book_cols += [f"future_ret_{h}" for h in horizons]
    joined = pd.merge_asof(tr, df[book_cols].sort_values("timestamp"), on="timestamp", direction="backward")
    joined["trade_vs_mid"] = joined["price"] - joined["mid_price"]
    joined["trade_vs_microprice"] = joined["price"] - joined["microprice_L1"]
    joined["side_guess"] = np.select(
        [joined["price"] >= joined["best_ask"], joined["price"] <= joined["best_bid"]],
        ["buyer_initiated", "seller_initiated"],
        default="inside_or_unknown",
    )
    joined["signed_qty"] = np.select(
        [joined["side_guess"].eq("buyer_initiated"), joined["side_guess"].eq("seller_initiated")],
        [joined["quantity"], -joined["quantity"]],
        default=0,
    )
    save_csv(joined, tdir / "joined_trades_with_book.csv")
    save_csv(summary_table(joined, ["price", "quantity", "trade_vs_mid", "trade_vs_microprice", "signed_qty"]), tdir / "trade_summary.csv")
    side = joined["side_guess"].value_counts().rename_axis("side_guess").reset_index(name="count")
    side["pct"] = side["count"] / len(joined)
    save_csv(side, tdir / "trade_side_counts.csv")

    flow = joined.groupby("timestamp", as_index=False).agg(
        trade_count=("quantity", "count"),
        total_qty=("quantity", "sum"),
        signed_qty=("signed_qty", "sum"),
        avg_trade_price=("price", "mean"),
        avg_trade_vs_mid=("trade_vs_mid", "mean"),
    )
    flow = pd.merge_asof(flow.sort_values("timestamp"), df[["timestamp"] + [f"future_ret_{h}" for h in horizons]].sort_values("timestamp"), on="timestamp", direction="backward")
    save_csv(flow, tdir / "trade_flow_by_timestamp.csv")

    rows = []
    for feat in ["trade_count", "total_qty", "signed_qty", "avg_trade_vs_mid"]:
        x = flow[feat].to_numpy(dtype=float)
        for h in horizons:
            y = flow[f"future_ret_{h}"].to_numpy(dtype=float)
            rows.append({"feature": feat, "horizon": h, "corr": corr_np(x, y), "slope": slope_np(x, y)})
    save_csv(pd.DataFrame(rows), tdir / "trade_flow_signal_scan.csv")


# =============================================================================
# 4. Optional core plots
# =============================================================================

def plot_line(df: pd.DataFrame, x: str, ys: list[str], path: Path, title: str) -> None:
    mkdir(path.parent)
    xv = finite_series(df[x]).to_numpy(dtype=float)
    plt.figure(figsize=(13, 6))
    for y in ys:
        if y in df.columns:
            plt.plot(xv, finite_series(df[y]).to_numpy(dtype=float), label=y)
    plt.title(title)
    plt.xlabel(x)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=110)
    plt.close()


def plot_hist(s: pd.Series, path: Path, title: str, bins: int = 80) -> None:
    mkdir(path.parent)
    x = finite_series(s).dropna().to_numpy(dtype=float)
    if len(x) == 0:
        return
    plt.figure(figsize=(9, 5))
    plt.hist(x, bins=bins)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(path, dpi=110)
    plt.close()


def make_plots(df: pd.DataFrame, out_dir: Path) -> None:
    p = out_dir / "plots"
    plot_line(df, "timestamp", ["mid_price", "roll_mean_100", "roll_mean_500", "roll_mean_1000"], p / "mid_with_rolling_means.png", "Mid with rolling means")
    plot_line(df, "timestamp", ["best_bid", "mid_price", "best_ask"], p / "bid_mid_ask.png", "Best bid, mid, best ask")
    plot_line(df, "timestamp", ["spread"], p / "spread_over_time.png", "Spread over time")
    plot_hist(df["spread"], p / "spread_hist.png", "Spread histogram")
    plot_line(df, "timestamp", ["imbalance_L1", "imbalance_L2", "imbalance_L3"], p / "imbalance_over_time.png", "Imbalance over time")
    plot_hist(df["imbalance_L1"], p / "imbalance_L1_hist.png", "L1 imbalance histogram")
    plot_line(df, "timestamp", ["micro_edge_L1"], p / "micro_edge_L1.png", "Microprice edge L1")
    plot_line(df, "timestamp", ["roll_vol_ret1_50", "roll_vol_ret1_100", "roll_vol_ret1_500"], p / "rolling_volatility.png", "Rolling volatility")
    plot_line(df, "timestamp", ["dev_roll_mean_100", "dev_roll_mean_500", "dev_roll_mean_1000"], p / "rolling_mean_deviation.png", "Mid minus rolling mean")
    plot_line(df, "timestamp", ["z_roll_mean_100", "z_roll_mean_500", "z_roll_mean_1000"], p / "rolling_zscore.png", "Rolling z-score")
    plot_line(df, "timestamp", ["bid_size_1", "ask_size_1"], p / "l1_sizes.png", "L1 bid/ask sizes")
    plot_line(df, "timestamp", ["bid_depth_L1", "ask_depth_L1", "bid_depth_L2", "ask_depth_L2"], p / "depth.png", "Book depth")
    for h in [1, 5, 10, 50, 100]:
        plot_hist(df[f"past_ret_{h}"], p / f"ret_{h}_hist.png", f"{h}-row return histogram")


# =============================================================================
# 5. Main
# =============================================================================

def write_readme(out_dir: Path, product: str) -> None:
    txt = f"""# {product} diagnostic report

Read in this order:

1. `run_info.json`
2. `tables/summary/mid_spread_depth_summary.csv`
3. `tables/summary/spread_value_counts.csv`
4. `tables/signals/signal_scan.csv`
5. `tables/buckets/bucket_scan.csv`
6. `tables/conditional/spread_conditional.csv`
7. `tables/conditional/time_conditional.csv`
8. `tables/conditional/quote_change_report.csv`
9. `tables/events/event_summary.csv`
10. `tables/trades/` if trades exist

`enriched_{product}.csv` is the full per-row dataset with all features and future returns.
"""
    (out_dir / "README.md").write_text(txt)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--trades", default=None)
    ap.add_argument("--product", default="HYDROGEL_PACK")
    ap.add_argument("--out", default="hydrogel_report")
    ap.add_argument("--horizons", nargs="+", type=int, default=HORIZONS)
    ap.add_argument("--windows", nargs="+", type=int, default=WINDOWS)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--event-lookback", type=int, default=20)
    ap.add_argument("--event-lookahead", type=int, default=80)
    ap.add_argument("--event-max", type=int, default=200)
    ap.add_argument("--make-plots", action="store_true")
    args = ap.parse_args()

    prices_path = Path(args.prices)
    trades_path = Path(args.trades) if args.trades else None
    out_dir = Path(args.out)
    mkdir(out_dir)
    write_readme(out_dir, args.product)

    raw, prices = load_prices(prices_path, args.product)
    df = enrich_book(prices, args.horizons, args.windows)

    save_json(run_info(raw, df, prices_path, trades_path, args.product), out_dir / "run_info.json")
    save_csv(df, out_dir / f"enriched_{args.product}.csv")

    summary_dir = out_dir / "tables" / "summary"
    save_csv(missingness(df), summary_dir / "missingness.csv")
    save_csv(level_presence(df), summary_dir / "level_presence.csv")
    save_csv(spread_counts(df), summary_dir / "spread_value_counts.csv")

    core_cols = [
        "mid_price", "computed_mid", "mid_error", "best_bid", "best_ask", "spread", "half_spread",
        "bid_size_1", "ask_size_1", "bid_size_2", "ask_size_2", "bid_size_3", "ask_size_3",
        "bid_depth_L1", "ask_depth_L1", "bid_depth_L2", "ask_depth_L2", "bid_depth_L3", "ask_depth_L3",
        "imbalance_L1", "imbalance_L2", "imbalance_L3", "microprice_L1", "micro_edge_L1",
        "bid_gap_12", "ask_gap_12", "bid_gap_23", "ask_gap_23", "dev_global_mean", "z_global_mean",
    ]
    save_csv(summary_table(df, core_cols), summary_dir / "mid_spread_depth_summary.csv")
    save_csv(return_summary(df, args.horizons), summary_dir / "return_summary.csv")
    save_csv(autocorr_report(df), summary_dir / "autocorr_ret1.csv")
    rolling_cols = []
    for w in args.windows:
        rolling_cols += [f"roll_mean_{w}", f"roll_std_mid_{w}", f"roll_vol_ret1_{w}", f"dev_roll_mean_{w}", f"z_roll_mean_{w}", f"ema_{w}", f"dev_ema_{w}"]
    save_csv(summary_table(df, rolling_cols), summary_dir / "rolling_summary.csv")

    features = feature_cols(args.windows)
    sig = signal_scan(df, features, args.horizons)
    save_csv(sig, out_dir / "tables" / "signals" / "signal_scan.csv")
    if not sig.empty:
        top = sig.sort_values("abs_corr", ascending=False).groupby("horizon", as_index=False).head(20)
        save_csv(top, out_dir / "tables" / "signals" / "top_20_per_horizon.csv")

    bucket_features = [
        "spread", "imbalance_L1", "imbalance_L2", "imbalance_L3", "micro_edge_L1",
        "bid_size_1", "ask_size_1", "bid_depth_L2", "ask_depth_L2",
        "past_ret_1", "past_ret_5", "past_ret_10", "past_ret_20",
        "dev_global_mean", "z_global_mean", "dev_roll_mean_50", "dev_roll_mean_100", "dev_roll_mean_500", "dev_roll_mean_1000",
        "z_roll_mean_50", "z_roll_mean_100", "z_roll_mean_500", "z_roll_mean_1000",
        "roll_vol_ret1_50", "roll_vol_ret1_100", "roll_vol_ret1_500",
    ]
    save_csv(bucket_scan(df, bucket_features, args.horizons, args.bins), out_dir / "tables" / "buckets" / "bucket_scan.csv")

    save_csv(spread_conditional(df, args.horizons), out_dir / "tables" / "conditional" / "spread_conditional.csv")
    save_csv(time_conditional(df, args.horizons), out_dir / "tables" / "conditional" / "time_conditional.csv")
    save_csv(quote_change_report(df, args.horizons), out_dir / "tables" / "conditional" / "quote_change_report.csv")

    cm = corr_matrix(df, features, args.horizons).reset_index().rename(columns={"index": "feature"})
    save_csv(cm, out_dir / "tables" / "correlations" / "correlation_matrix.csv")

    ev_sum, ev_paths = event_study(df, args.horizons, args.event_lookback, args.event_lookahead, args.event_max)
    save_csv(ev_sum, out_dir / "tables" / "events" / "event_summary.csv")
    save_csv(ev_paths, out_dir / "tables" / "events" / "event_average_paths.csv")

    analyze_trades(trades_path, args.product, df, out_dir, args.horizons)

    if args.make_plots:
        make_plots(df, out_dir)

    print("DONE")
    print(f"Product: {args.product}")
    print(f"Rows: {len(df)}")
    print(f"Output: {out_dir}")
    print("\nMid summary:")
    print(summary_table(df, ["mid_price"]).to_string(index=False))
    print("\nSpread counts:")
    print(spread_counts(df).to_string(index=False))
    if not sig.empty:
        print("\nTop signal correlations:")
        cols = ["feature", "horizon", "corr", "top_minus_bottom_future_ret", "n"]
        print(sig.sort_values("abs_corr", ascending=False).head(15)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
