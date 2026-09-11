#!/usr/bin/env python3
"""
Interactive Streamlit dashboard for Hydrogel diagnostic outputs.

Expected input folder structure:

reports/
  hydrogel_day0_report/
    enriched_HYDROGEL_PACK.csv
    run_info.json
    tables/...
  hydrogel_day1_report/
    enriched_HYDROGEL_PACK.csv
    run_info.json
    tables/...
  hydrogel_day2_report/
    enriched_HYDROGEL_PACK.csv
    run_info.json
    tables/...

Run:
  streamlit run hydrogel_dashboard.py -- --reports-root reports

Install deps if needed:
  pip install streamlit plotly pandas numpy
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# -----------------------------
# CLI / config helpers
# -----------------------------

PRODUCT_DEFAULT = "HYDROGEL_PACK"
DEFAULT_REPORTS_ROOT = "reports"


def cli_value(flag: str, default: str) -> str:
    """Tiny CLI parser compatible with `streamlit run app.py -- --flag value`."""
    if flag not in sys.argv:
        return default
    idx = sys.argv.index(flag)
    if idx + 1 >= len(sys.argv):
        return default
    return sys.argv[idx + 1]


# -----------------------------
# Styling
# -----------------------------

st.set_page_config(
    page_title="Hydrogel Diagnostic Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.25rem; padding-bottom: 3rem;}
      div[data-testid="stMetricValue"] {font-size: 1.45rem;}
      .small-note {color: #6b7280; font-size: 0.9rem;}
      .section-note {color: #4b5563; font-size: 0.95rem; margin-top: -0.5rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Data models
# -----------------------------

@dataclass(frozen=True)
class ReportInfo:
    label: str
    day_sort: int
    path: str
    product: str


TABLE_PATHS = {
    "missingness": "tables/summary/missingness.csv",
    "level_presence": "tables/summary/level_presence.csv",
    "spread_value_counts": "tables/summary/spread_value_counts.csv",
    "mid_spread_depth_summary": "tables/summary/mid_spread_depth_summary.csv",
    "return_summary": "tables/summary/return_summary.csv",
    "autocorr_ret1": "tables/summary/autocorr_ret1.csv",
    "rolling_summary": "tables/summary/rolling_summary.csv",
    "signal_scan": "tables/signals/signal_scan.csv",
    "top_20_per_horizon": "tables/signals/top_20_per_horizon.csv",
    "bucket_scan": "tables/buckets/bucket_scan.csv",
    "spread_conditional": "tables/conditional/spread_conditional.csv",
    "time_conditional": "tables/conditional/time_conditional.csv",
    "quote_change_report": "tables/conditional/quote_change_report.csv",
    "correlation_matrix": "tables/correlations/correlation_matrix.csv",
    "event_summary": "tables/events/event_summary.csv",
    "event_average_paths": "tables/events/event_average_paths.csv",
    "joined_trades_with_book": "tables/trades/joined_trades_with_book.csv",
    "trade_summary": "tables/trades/trade_summary.csv",
    "trade_side_counts": "tables/trades/trade_side_counts.csv",
    "trade_flow_by_timestamp": "tables/trades/trade_flow_by_timestamp.csv",
    "trade_flow_signal_scan": "tables/trades/trade_flow_signal_scan.csv",
}


# -----------------------------
# Generic helpers
# -----------------------------


def natural_day_label(path: Path) -> Tuple[str, int]:
    """Extract a clean label and sort key from a report folder name."""
    name = path.name
    m = re.search(r"day\s*[_-]?(\d+)|day(\d+)", name, flags=re.I)
    if m:
        d = int(next(g for g in m.groups() if g is not None))
        return f"Day {d}", d

    # If no day found, fall back to folder name.
    return name, 10_000


def numeric_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def existing_cols(df: pd.DataFrame, cols: Sequence[str]) -> List[str]:
    return [c for c in cols if c in df.columns]


def first_existing(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def sort_cols_by_suffix(cols: Iterable[str]) -> List[str]:
    def key(c: str) -> Tuple[int, str]:
        m = re.search(r"(\d+)$", c)
        return (int(m.group(1)) if m else 10**9, c)
    return sorted(cols, key=key)


def format_num(x, digits: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        if pd.isna(x):
            return "n/a"
        xf = float(x)
        if abs(xf) >= 1000:
            return f"{xf:,.{digits}f}"
        return f"{xf:.{digits}f}"
    except Exception:
        return str(x)


def downsample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if df.empty or len(df) <= max_points:
        return df
    step = max(1, math.ceil(len(df) / max_points))
    return df.iloc[::step].copy()


def add_day_prefix_to_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Create plot_x so combined days don't visually overlap unless desired."""
    if df.empty or "timestamp" not in df.columns:
        return df
    out = df.copy()
    if "__day_sort" in out.columns:
        # IMC timestamps run 0..999900. Add a little spacing between days.
        max_ts = pd.to_numeric(out["timestamp"], errors="coerce").max()
        if pd.notna(max_ts):
            out["plot_x"] = out["timestamp"] + out["__day_sort"] * (max_ts + 100_000)
        else:
            out["plot_x"] = out["timestamp"]
    else:
        out["plot_x"] = out["timestamp"]
    return out


def safe_read_csv(path: Path, nrows: Optional[int] = None) -> pd.DataFrame:
    """Read generated diagnostic CSVs. Handles empty/missing files gracefully."""
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, nrows=nrows)
    except Exception:
        # Fallback for unusual delimiter, just in case someone points dashboard at raw data.
        try:
            return pd.read_csv(path, sep=";", nrows=nrows)
        except Exception:
            return pd.DataFrame()


# -----------------------------
# Cached loading
# -----------------------------

@st.cache_data(show_spinner=False)
def discover_reports(root_str: str, product: str) -> List[ReportInfo]:
    root = Path(root_str).expanduser().resolve()
    if not root.exists():
        return []

    candidates: List[Path] = []

    # Case 1: root itself is a report folder.
    if (root / f"enriched_{product}.csv").exists():
        candidates.append(root)

    # Case 2: root contains report folders.
    for p in root.glob("**/enriched_*.csv"):
        if p.name == f"enriched_{product}.csv":
            candidates.append(p.parent)

    # Deduplicate while preserving sorted order. Multiple runs for the same calendar day
    # (e.g. full backtest CSV vs a website activities export) need distinct labels and
    # `day_sort` keys or Streamlit's multiselect and stitched plots conflate them.
    unique = sorted(
        set(candidates),
        key=lambda p: (natural_day_label(p)[1], natural_day_label(p)[0], str(p)),
    )
    reports: List[ReportInfo] = []
    for i, p in enumerate(unique):
        base_label, base_sort = natural_day_label(p)
        label = f"{base_label} — {p.name}"
        day_sort = base_sort * 1_000 + i
        reports.append(ReportInfo(label=label, day_sort=day_sort, path=str(p), product=product))
    return reports


@st.cache_data(show_spinner=True)
def load_enriched(report_path: str, product: str, label: str, day_sort: int) -> pd.DataFrame:
    df = safe_read_csv(Path(report_path) / f"enriched_{product}.csv")
    if df.empty:
        return df
    df["__day"] = label
    df["__day_sort"] = day_sort
    df["__report"] = Path(report_path).name

    # Make sure important columns are numeric.
    for c in df.columns:
        if c.startswith("__") or c in ("product",):
            continue
        if df[c].dtype == object:
            maybe = pd.to_numeric(df[c], errors="ignore")
            df[c] = maybe
    return df


@st.cache_data(show_spinner=False)
def load_table(report_path: str, table_key: str, label: str, day_sort: int) -> pd.DataFrame:
    rel = TABLE_PATHS.get(table_key)
    if rel is None:
        return pd.DataFrame()
    df = safe_read_csv(Path(report_path) / rel)
    if df.empty:
        return df
    df["__day"] = label
    df["__day_sort"] = day_sort
    df["__report"] = Path(report_path).name
    return df


@st.cache_data(show_spinner=False)
def load_run_info(report_path: str) -> Dict:
    p = Path(report_path) / "run_info.json"
    if not p.exists():
        return {}
    try:
        with p.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def concat_tables(reports: Sequence[ReportInfo], table_key: str) -> pd.DataFrame:
    frames = [load_table(r.path, table_key, r.label, r.day_sort) for r in reports]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# -----------------------------
# Plot helpers
# -----------------------------


def line_chart(
    df: pd.DataFrame,
    y_cols: Sequence[str],
    title: str,
    x_col: str = "timestamp",
    color_by_day: bool = True,
    max_points: int = 15_000,
) -> go.Figure:
    plot_df = df.copy()
    if "timestamp" in plot_df.columns and x_col == "plot_x":
        plot_df = add_day_prefix_to_timestamp(plot_df)
    plot_df = downsample(plot_df, max_points)

    fig = go.Figure()
    group_cols = ["__day"] if color_by_day and "__day" in plot_df.columns else [None]
    groups = plot_df.groupby("__day", sort=False) if group_cols[0] else [(None, plot_df)]

    for day, g in groups:
        for y in y_cols:
            if y not in g.columns:
                continue
            trace_name = f"{day} · {y}" if day is not None and len(y_cols) > 1 else (str(day) if day is not None else y)
            if day is not None and len(y_cols) == 1:
                trace_name = str(day)
            elif day is not None:
                trace_name = f"{day} · {y}"
            fig.add_trace(
                go.Scattergl(
                    x=g[x_col] if x_col in g.columns else g.index,
                    y=g[y],
                    mode="lines",
                    name=trace_name,
                    hovertemplate=f"{y}: %{{y}}<br>x: %{{x}}<extra>{trace_name}</extra>",
                )
            )
    fig.update_layout(title=title, height=460, margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(title=x_col)
    return fig


def hist_chart(df: pd.DataFrame, col: str, title: str, nbins: int = 80) -> go.Figure:
    if col not in df.columns:
        return go.Figure()
    plot_df = df[[col, "__day"]].dropna() if "__day" in df.columns else df[[col]].dropna()
    fig = px.histogram(plot_df, x=col, color="__day" if "__day" in plot_df.columns else None, nbins=nbins, barmode="overlay", title=title)
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, color: Optional[str] = None) -> go.Figure:
    if df.empty or x not in df.columns or y not in df.columns:
        return go.Figure()
    fig = px.bar(df, x=x, y=y, color=color if color in df.columns else None, title=title)
    fig.update_layout(height=450, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def scatter_chart(df: pd.DataFrame, x: str, y: str, title: str, color: Optional[str] = "__day", max_points: int = 15_000) -> go.Figure:
    if df.empty or x not in df.columns or y not in df.columns:
        return go.Figure()
    plot_df = downsample(df[[c for c in [x, y, color] if c and c in df.columns]].dropna(), max_points)
    fig = px.scatter(plot_df, x=x, y=y, color=color if color in plot_df.columns else None, opacity=0.55, title=title)
    fig.update_traces(marker=dict(size=5))
    fig.update_layout(height=480, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def heatmap_from_corr(corr_df: pd.DataFrame, features: Optional[List[str]] = None, max_vars: int = 45) -> go.Figure:
    if corr_df.empty or "feature" not in corr_df.columns:
        return go.Figure()

    cdf = corr_df.copy()
    cdf = cdf.drop_duplicates(subset=["feature"])
    cdf = cdf.set_index("feature", drop=True)

    # Drop metadata columns if present.
    cdf = cdf.drop(columns=[c for c in ["__day", "__day_sort", "__report"] if c in cdf.columns], errors="ignore")
    cdf = cdf.apply(pd.to_numeric, errors="coerce")

    if features:
        keep = [f for f in features if f in cdf.index and f in cdf.columns]
        cdf = cdf.loc[keep, keep]
    else:
        # Prefer a future-return centered subset if the matrix is too large.
        cols = list(cdf.columns)
        priority = [c for c in cols if c.startswith("future_ret_")]
        rest = [c for c in cols if c not in priority]
        keep = (priority + rest)[:max_vars]
        keep = [c for c in keep if c in cdf.index and c in cdf.columns]
        cdf = cdf.loc[keep, keep]

    fig = px.imshow(
        cdf,
        zmin=-1,
        zmax=1,
        color_continuous_scale="RdBu_r",
        aspect="auto",
        title="Correlation Matrix",
    )
    fig.update_layout(height=760, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def show_table(df: pd.DataFrame, label: str, height: int = 360) -> None:
    if df.empty:
        st.info(f"No `{label}` table found for this selection.")
    else:
        st.dataframe(df, use_container_width=True, height=height)


# -----------------------------
# Sidebar load controls
# -----------------------------

initial_root = cli_value("--reports-root", DEFAULT_REPORTS_ROOT)
initial_product = cli_value("--product", PRODUCT_DEFAULT)

st.title("📈 Hydrogel Full Diagnostic Dashboard")
st.caption("Interactive viewer for the CSV outputs generated by `hydrogel_full_diagnostic.py`.")

with st.sidebar:
    st.header("Data")
    reports_root = st.text_input("Reports root", value=initial_root, help="Folder containing hydrogel_dayX_report folders.")
    product = st.text_input("Product", value=initial_product)
    max_points = st.slider("Max points per line/scatter plot", 1_000, 50_000, 15_000, step=1_000)
    x_mode = st.radio("Combined x-axis", ["Overlay timestamps", "Stitch days sequentially"], index=0)

reports = discover_reports(reports_root, product)

if not reports:
    st.error(
        f"No reports found under `{reports_root}` for product `{product}`. "
        f"Expected files like `hydrogel_day0_report/enriched_{product}.csv`."
    )
    st.stop()

with st.sidebar:
    all_labels = [r.label for r in reports]
    selected_labels = st.multiselect("Reports / days", all_labels, default=all_labels)
    selected_reports = [r for r in reports if r.label in selected_labels]
    if not selected_reports:
        st.warning("Select at least one report/day.")
        st.stop()
    st.divider()
    st.write("Detected reports")
    for r in reports:
        st.caption(f"{r.label}: `{Path(r.path).name}`")

# Load selected enriched data.
frames = [load_enriched(r.path, r.product, r.label, r.day_sort) for r in selected_reports]
frames = [f for f in frames if not f.empty]
if not frames:
    st.error("Could not load any enriched CSVs from the selected reports.")
    st.stop()

data = pd.concat(frames, ignore_index=True)
if x_mode == "Stitch days sequentially":
    data = add_day_prefix_to_timestamp(data)
    main_x = "plot_x"
else:
    main_x = "timestamp"

selected_day_text = ", ".join([r.label for r in selected_reports])
st.markdown(f"<div class='small-note'>Loaded <b>{len(data):,}</b> enriched rows across: {selected_day_text}</div>", unsafe_allow_html=True)


# -----------------------------
# Tabs
# -----------------------------

tabs = st.tabs(
    [
        "Overview",
        "Price / Spread",
        "Returns / Volatility",
        "Book / Liquidity",
        "Signals",
        "Buckets",
        "Regimes",
        "Events",
        "Correlations",
        "Trades",
        "Data Explorer",
    ]
)


# -----------------------------
# Overview tab
# -----------------------------

with tabs[0]:
    st.subheader("Overview")
    st.markdown("<div class='section-note'>Quick sanity checks and high-level market shape.</div>", unsafe_allow_html=True)

    mid = pd.to_numeric(data.get("mid_price"), errors="coerce") if "mid_price" in data else pd.Series(dtype=float)
    spread = pd.to_numeric(data.get("spread"), errors="coerce") if "spread" in data else pd.Series(dtype=float)
    rows = len(data)
    ts_min = data["timestamp"].min() if "timestamp" in data else np.nan
    ts_max = data["timestamp"].max() if "timestamp" in data else np.nan

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Rows", f"{rows:,}")
    c2.metric("Mid mean", format_num(mid.mean()))
    c3.metric("Mid std", format_num(mid.std()))
    c4.metric("Mid range", format_num(mid.max() - mid.min()))
    c5.metric("Spread median", format_num(spread.median()))
    c6.metric("Timestamp", f"{format_num(ts_min, 0)} → {format_num(ts_max, 0)}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mid min", format_num(mid.min()))
    c2.metric("Mid max", format_num(mid.max()))
    c3.metric("Spread mean", format_num(spread.mean()))
    c4.metric("Spread min/max", f"{format_num(spread.min(),0)} / {format_num(spread.max(),0)}")

    st.divider()
    left, right = st.columns([1.2, 1])
    with left:
        summary = concat_tables(selected_reports, "mid_spread_depth_summary")
        st.markdown("#### Summary stats table")
        show_table(summary, "mid_spread_depth_summary", height=380)
    with right:
        lvl = concat_tables(selected_reports, "level_presence")
        st.markdown("#### Level presence")
        show_table(lvl, "level_presence", height=180)
        miss = concat_tables(selected_reports, "missingness")
        st.markdown("#### Missingness")
        if not miss.empty:
            # Show worst missingness first if a missing pct column exists.
            pct_cols = [c for c in miss.columns if "pct" in c.lower() or "missing" in c.lower()]
            sort_col = pct_cols[-1] if pct_cols else None
            if sort_col and pd.api.types.is_numeric_dtype(miss[sort_col]):
                miss = miss.sort_values(["__day", sort_col], ascending=[True, False])
        show_table(miss, "missingness", height=240)

    st.divider()
    st.markdown("#### Raw run info")
    infos = []
    for r in selected_reports:
        info = load_run_info(r.path)
        if info:
            info["__day"] = r.label
            info["__report"] = Path(r.path).name
            infos.append(info)
    if infos:
        st.json(infos, expanded=False)
    else:
        st.info("No run_info.json files found.")


# -----------------------------
# Price / Spread tab
# -----------------------------

with tabs[1]:
    st.subheader("Price / Spread")
    st.markdown("<div class='section-note'>Mid movement, bid/ask envelope, spread stability, and rolling anchors.</div>", unsafe_allow_html=True)

    roll_cols = sort_cols_by_suffix([c for c in data.columns if c.startswith("roll_mean_")])
    default_rolls = [c for c in ["roll_mean_100", "roll_mean_500", "roll_mean_1000"] if c in roll_cols]
    selected_rolls = st.multiselect("Rolling means to overlay", roll_cols, default=default_rolls)

    fig = line_chart(data, ["mid_price"] + selected_rolls, "Mid Price + Rolling Means", x_col=main_x, color_by_day=True, max_points=max_points)
    st.plotly_chart(fig, use_container_width=True)

    cols = existing_cols(data, ["bid_price_1", "mid_price", "ask_price_1"])
    if cols:
        fig = line_chart(data, cols, "Best Bid / Mid / Best Ask", x_col=main_x, color_by_day=True, max_points=max_points)
        st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = line_chart(data, ["spread"], "Spread Over Time", x_col=main_x, color_by_day=True, max_points=max_points)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.plotly_chart(hist_chart(data, "spread", "Spread Histogram", nbins=50), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        svc = concat_tables(selected_reports, "spread_value_counts")
        st.markdown("#### Spread value counts")
        show_table(svc, "spread_value_counts", height=360)
    with c2:
        if not svc.empty:
            xcol = first_existing(svc, ["spread", "value", "metric"])
            ycol = first_existing(svc, ["count", "n"])
            if xcol and ycol:
                st.plotly_chart(bar_chart(svc, xcol, ycol, "Spread Counts", color="__day"), use_container_width=True)

    st.markdown("#### Mid distribution")
    st.plotly_chart(hist_chart(data, "mid_price", "Mid Price Histogram", nbins=100), use_container_width=True)


# -----------------------------
# Returns / Volatility tab
# -----------------------------

with tabs[2]:
    st.subheader("Returns / Volatility")
    st.markdown("<div class='section-note'>Return distributions, autocorrelation, rolling volatility, and move-size behavior.</div>", unsafe_allow_html=True)

    past_ret_cols = sort_cols_by_suffix([c for c in data.columns if c.startswith("past_ret_")])
    future_ret_cols = sort_cols_by_suffix([c for c in data.columns if c.startswith("future_ret_") and not c.startswith("future_ret_abs")])
    abs_ret_cols = sort_cols_by_suffix([c for c in data.columns if c.startswith("future_abs_ret_")])
    ret_choice = st.selectbox("Return column", past_ret_cols + future_ret_cols, index=0 if past_ret_cols else 0)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(line_chart(data, [ret_choice], f"{ret_choice} Over Time", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)
    with c2:
        st.plotly_chart(hist_chart(data, ret_choice, f"{ret_choice} Histogram", nbins=120), use_container_width=True)

    roll_vol_cols = sort_cols_by_suffix([c for c in data.columns if c.startswith("roll_vol_ret1_")])
    default_vol = [c for c in ["roll_vol_ret1_50", "roll_vol_ret1_100", "roll_vol_ret1_500"] if c in roll_vol_cols]
    selected_vols = st.multiselect("Rolling volatility columns", roll_vol_cols, default=default_vol)
    if selected_vols:
        st.plotly_chart(line_chart(data, selected_vols, "Rolling Volatility", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        ret_summary = concat_tables(selected_reports, "return_summary")
        st.markdown("#### Return summary")
        show_table(ret_summary, "return_summary", height=400)
    with c2:
        ac = concat_tables(selected_reports, "autocorr_ret1")
        st.markdown("#### Autocorrelation")
        show_table(ac, "autocorr_ret1", height=400)

    st.markdown("#### Absolute future move distributions")
    abs_choice = st.selectbox("Abs future return", abs_ret_cols, index=min(3, len(abs_ret_cols)-1) if abs_ret_cols else 0)
    if abs_choice:
        st.plotly_chart(hist_chart(data, abs_choice, f"{abs_choice} Histogram", nbins=100), use_container_width=True)


# -----------------------------
# Book / Liquidity tab
# -----------------------------

with tabs[3]:
    st.subheader("Book / Liquidity")
    st.markdown("<div class='section-note'>Depth, bid/ask sizes, imbalance, microprice, WAP edge, and book gaps.</div>", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        size_cols_1 = existing_cols(data, ["bid_size_1", "ask_size_1"])
        if size_cols_1:
            st.plotly_chart(line_chart(data, size_cols_1, "L1 Bid/Ask Sizes", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)
    with c2:
        size_cols_2 = existing_cols(data, ["bid_size_2", "ask_size_2"])
        if size_cols_2:
            st.plotly_chart(line_chart(data, size_cols_2, "L2 Bid/Ask Sizes", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)

    depth_cols = existing_cols(data, ["total_depth_L1", "total_depth_L2", "total_depth_L3"])
    if depth_cols:
        st.plotly_chart(line_chart(data, depth_cols, "Total Depth by Level", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)

    imbalance_cols = existing_cols(data, ["imbalance_L1", "imbalance_L2", "imbalance_L3"])
    c1, c2 = st.columns(2)
    with c1:
        if imbalance_cols:
            imb_choice = st.selectbox("Imbalance to plot", imbalance_cols, index=0)
            st.plotly_chart(line_chart(data, [imb_choice], f"{imb_choice} Over Time", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)
    with c2:
        if imbalance_cols:
            st.plotly_chart(hist_chart(data, imb_choice, f"{imb_choice} Histogram", nbins=80), use_container_width=True)

    edge_cols = existing_cols(data, ["micro_edge_L1", "book_wap_edge_L1", "book_wap_edge_L2", "book_wap_edge_L3"])
    if edge_cols:
        selected_edges = st.multiselect("Micro/WAP edge columns", edge_cols, default=edge_cols[:2])
        if selected_edges:
            st.plotly_chart(line_chart(data, selected_edges, "Microprice / WAP Edges", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)

    gap_cols = existing_cols(data, ["bid_gap_12", "ask_gap_12", "bid_gap_23", "ask_gap_23"])
    if gap_cols:
        gap_choice = st.selectbox("Book gap distribution", gap_cols, index=0)
        st.plotly_chart(hist_chart(data, gap_choice, f"{gap_choice} Histogram", nbins=80), use_container_width=True)

    st.markdown("#### Custom microstructure scatter")
    feature_options = [c for c in numeric_cols(data) if not c.startswith("future_up_")]
    x_feat = st.selectbox("X feature", feature_options, index=feature_options.index("imbalance_L1") if "imbalance_L1" in feature_options else 0)
    y_candidates = [c for c in future_ret_cols if c in data.columns] + ["mid_change"]
    y_feat = st.selectbox("Y target", y_candidates, index=0)
    st.plotly_chart(scatter_chart(data, x_feat, y_feat, f"{x_feat} vs {y_feat}", max_points=max_points), use_container_width=True)


# -----------------------------
# Signals tab
# -----------------------------

with tabs[4]:
    st.subheader("Signals")
    st.markdown("<div class='section-note'>Linear signal scan: current feature versus future return at each horizon.</div>", unsafe_allow_html=True)

    sig = concat_tables(selected_reports, "signal_scan")
    if sig.empty:
        st.info("No signal_scan.csv found.")
    else:
        horizons = sorted(pd.to_numeric(sig["horizon"], errors="coerce").dropna().astype(int).unique().tolist()) if "horizon" in sig.columns else []
        h = st.selectbox("Horizon", horizons, index=0 if horizons else None)
        if "n" in sig.columns:
            _nmax = pd.to_numeric(sig["n"], errors="coerce").max()
            max_n = int(_nmax) if pd.notna(_nmax) and _nmax >= 0 else 1_000_000
        else:
            max_n = 1_000_000
        # Cap at 1000, align to step=100, and never exceed max_n
        _want = min(1000, max_n)
        default_min_n = (_want // 100) * 100
        min_n = st.number_input(
            "Minimum sample size",
            min_value=0,
            max_value=max_n,
            value=default_min_n,
            step=100,
        )
        search = st.text_input("Feature name contains", value="")

        filt = sig.copy()
        if horizons and h is not None:
            filt = filt[pd.to_numeric(filt["horizon"], errors="coerce") == h]
        if "n" in filt.columns:
            filt = filt[pd.to_numeric(filt["n"], errors="coerce") >= min_n]
        if search and "feature" in filt.columns:
            filt = filt[filt["feature"].astype(str).str.contains(search, case=False, na=False)]
        if "abs_corr" in filt.columns:
            filt = filt.sort_values("abs_corr", ascending=False)

        c1, c2 = st.columns([1.1, 1])
        with c1:
            st.markdown("#### Signal scan table")
            show_table(filt, "signal_scan", height=520)
        with c2:
            topn = st.slider("Top N signals", 5, 50, 20)
            top = filt.head(topn)
            if not top.empty and {"feature", "corr"}.issubset(top.columns):
                st.plotly_chart(bar_chart(top.iloc[::-1], "corr", "feature", f"Top {topn} correlations @ horizon {h}", color="__day"), use_container_width=True)

        st.markdown("#### Inspect one signal")
        if not filt.empty and "feature" in filt.columns:
            feature_to_plot = st.selectbox("Signal feature", filt["feature"].dropna().astype(str).unique().tolist())
            target_col = f"future_ret_{h}"
            if feature_to_plot in data.columns and target_col in data.columns:
                c1, c2 = st.columns(2)
                with c1:
                    st.plotly_chart(scatter_chart(data, feature_to_plot, target_col, f"{feature_to_plot} vs {target_col}", max_points=max_points), use_container_width=True)
                with c2:
                    st.plotly_chart(line_chart(data, [feature_to_plot], f"{feature_to_plot} Over Time", x_col=main_x, color_by_day=True, max_points=max_points), use_container_width=True)
            else:
                st.info(f"`{feature_to_plot}` or `{target_col}` was not found in enriched data.")

        st.markdown("#### Top 20 per horizon")
        top20 = concat_tables(selected_reports, "top_20_per_horizon")
        show_table(top20, "top_20_per_horizon", height=360)


# -----------------------------
# Buckets tab
# -----------------------------

with tabs[5]:
    st.subheader("Buckets")
    st.markdown("<div class='section-note'>Nonlinear buckets: useful for thresholds, not just correlation.</div>", unsafe_allow_html=True)

    b = concat_tables(selected_reports, "bucket_scan")
    if b.empty:
        st.info("No bucket_scan.csv found.")
    else:
        features = sorted(b["feature"].dropna().astype(str).unique().tolist()) if "feature" in b else []
        default_feature = "imbalance_L1" if "imbalance_L1" in features else (features[0] if features else None)
        feat = st.selectbox("Bucketed feature", features, index=features.index(default_feature) if default_feature in features else 0)

        possible_h = sorted({int(m.group(1)) for c in b.columns for m in [re.match(r"future_ret_(\d+)_mean", c)] if m})
        h = st.selectbox("Future horizon", possible_h, index=min(3, len(possible_h)-1) if possible_h else 0)
        mean_col = f"future_ret_{h}_mean"
        hit_col = f"future_ret_{h}_hit_up"
        abs_col = f"future_abs_ret_{h}_mean"

        bf = b[b["feature"].astype(str) == feat].copy()
        if "bucket" in bf.columns:
            bf["bucket"] = bf["bucket"].astype(str)

        c1, c2 = st.columns([1.1, 1])
        with c1:
            show_table(bf, "bucket_scan", height=530)
        with c2:
            if mean_col in bf.columns:
                fig = px.bar(bf, x="bucket", y=mean_col, color="__day" if "__day" in bf.columns else None, title=f"{feat}: Avg future return @ {h}")
                fig.update_layout(height=360, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)
            if hit_col in bf.columns:
                fig = px.line(bf, x="bucket", y=hit_col, color="__day" if "__day" in bf.columns else None, markers=True, title=f"{feat}: Hit-up rate @ {h}")
                fig.update_layout(height=330, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)
            if abs_col in bf.columns:
                fig = px.bar(bf, x="bucket", y=abs_col, color="__day" if "__day" in bf.columns else None, title=f"{feat}: Avg abs move @ {h}")
                fig.update_layout(height=330, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)


# -----------------------------
# Regimes tab
# -----------------------------

with tabs[6]:
    st.subheader("Regimes")
    st.markdown("<div class='section-note'>Spread regimes, time-of-day regimes, and quote-change regimes.</div>", unsafe_allow_html=True)

    possible_h = sorted({int(re.search(r"future_ret_(\d+)_mean", c).group(1)) for c in data.columns if re.match(r"future_ret_(\d+)_mean", c)})
    # Better infer from spread_conditional columns.
    spread_cond = concat_tables(selected_reports, "spread_conditional")
    time_cond = concat_tables(selected_reports, "time_conditional")
    quote_cond = concat_tables(selected_reports, "quote_change_report")

    all_regime_cols = list(spread_cond.columns) + list(time_cond.columns) + list(quote_cond.columns)
    horizons = sorted({int(m.group(1)) for c in all_regime_cols for m in [re.match(r"future_ret_(\d+)_mean", c)] if m})
    h = st.selectbox("Regime horizon", horizons, index=min(3, len(horizons)-1) if horizons else 0)
    mean_col = f"future_ret_{h}_mean"
    abs_col = f"future_abs_ret_{h}_mean"
    hit_col = f"future_ret_{h}_hit_up"
    corr_col = f"imbalance_corr_future_ret_{h}"
    dev_corr_col = f"dev500_corr_future_ret_{h}"

    st.markdown("#### Spread conditional")
    if spread_cond.empty:
        st.info("No spread_conditional.csv found.")
    else:
        c1, c2 = st.columns([1, 1])
        with c1:
            show_table(spread_cond, "spread_conditional", height=420)
        with c2:
            xcol = "spread" if "spread" in spread_cond.columns else spread_cond.columns[0]
            plot_cols = [c for c in [mean_col, abs_col, corr_col] if c in spread_cond.columns]
            if plot_cols:
                melted = spread_cond.melt(id_vars=[xcol, "__day"] if "__day" in spread_cond.columns else [xcol], value_vars=plot_cols, var_name="metric", value_name="value")
                fig = px.line(melted, x=xcol, y="value", color="metric", line_dash="__day" if "__day" in melted.columns else None, markers=True, title=f"Spread regime metrics @ {h}")
                fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Time-of-day conditional")
    if time_cond.empty:
        st.info("No time_conditional.csv found.")
    else:
        c1, c2 = st.columns([1, 1])
        with c1:
            show_table(time_cond, "time_conditional", height=420)
        with c2:
            xcol = "bucket" if "bucket" in time_cond.columns else time_cond.columns[0]
            plot_cols = [c for c in ["mid_mean", "spread_mean", "ret1_std", mean_col, abs_col, corr_col, dev_corr_col] if c in time_cond.columns]
            metric = st.selectbox("Time regime metric", plot_cols, index=0 if plot_cols else None)
            if metric:
                fig = px.line(time_cond, x=xcol, y=metric, color="__day" if "__day" in time_cond.columns else None, markers=True, title=f"Time bucket: {metric}")
                fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Quote-change conditional")
    if quote_cond.empty:
        st.info("No quote_change_report.csv found.")
    else:
        c1, c2 = st.columns([1, 1])
        with c1:
            show_table(quote_cond, "quote_change_report", height=420)
        with c2:
            xcol = "condition" if "condition" in quote_cond.columns else quote_cond.columns[0]
            plot_cols = [c for c in [mean_col, abs_col, hit_col] if c in quote_cond.columns]
            if plot_cols:
                melted = quote_cond.melt(id_vars=[xcol, "__day"] if "__day" in quote_cond.columns else [xcol], value_vars=plot_cols, var_name="metric", value_name="value")
                fig = px.bar(melted, x=xcol, y="value", color="metric", barmode="group", facet_col="__day" if "__day" in melted.columns and len(selected_reports) > 1 else None, title=f"Quote-change metrics @ {h}")
                fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)


# -----------------------------
# Events tab
# -----------------------------

with tabs[7]:
    st.subheader("Events")
    st.markdown("<div class='section-note'>Event studies: what happens after extreme spread, imbalance, z-score, or jump events.</div>", unsafe_allow_html=True)

    ev = concat_tables(selected_reports, "event_summary")
    paths = concat_tables(selected_reports, "event_average_paths")
    if ev.empty:
        st.info("No event_summary.csv found.")
    else:
        horizons = sorted({int(m.group(1)) for c in ev.columns for m in [re.match(r"future_ret_(\d+)_mean", c)] if m})
        h = st.selectbox("Event horizon", horizons, index=min(3, len(horizons)-1) if horizons else 0)
        mean_col = f"future_ret_{h}_mean"
        abs_col = f"future_abs_ret_{h}_mean"
        hit_col = f"future_ret_{h}_hit_up"

        st.markdown("#### Event summary")
        show_table(ev, "event_summary", height=420)

        c1, c2 = st.columns(2)
        with c1:
            if mean_col in ev.columns:
                fig = px.bar(ev, x="event", y=mean_col, color="__day" if "__day" in ev.columns else None, title=f"Event avg future return @ {h}")
                fig.update_layout(height=450, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            if hit_col in ev.columns:
                fig = px.bar(ev, x="event", y=hit_col, color="__day" if "__day" in ev.columns else None, title=f"Event hit-up rate @ {h}")
                fig.update_layout(height=450, margin=dict(l=10, r=10, t=50, b=10))
                fig.update_xaxes(tickangle=35)
                st.plotly_chart(fig, use_container_width=True)

    if paths.empty:
        st.info("No event_average_paths.csv found.")
    else:
        st.markdown("#### Average normalized price paths around events")
        events = sorted(paths["event"].dropna().astype(str).unique().tolist()) if "event" in paths else []
        default_events = events[: min(5, len(events))]
        chosen_events = st.multiselect("Events to plot", events, default=default_events)
        pf = paths[paths["event"].isin(chosen_events)].copy() if chosen_events else paths.head(0)
        if not pf.empty and {"rel_step", "avg_mid_minus_event_mid"}.issubset(pf.columns):
            fig = px.line(
                pf,
                x="rel_step",
                y="avg_mid_minus_event_mid",
                color="event",
                line_dash="__day" if "__day" in pf.columns and len(selected_reports) > 1 else None,
                title="Average mid path around event",
            )
            fig.add_vline(x=0, line_dash="dash")
            fig.update_layout(height=520, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, use_container_width=True)
        show_table(paths, "event_average_paths", height=300)


# -----------------------------
# Correlations tab
# -----------------------------

with tabs[8]:
    st.subheader("Correlations")
    st.markdown("<div class='section-note'>Cross-feature structure and feature-vs-future-return correlations.</div>", unsafe_allow_html=True)

    corr = concat_tables(selected_reports, "correlation_matrix")
    if corr.empty:
        st.info("No correlation_matrix.csv found.")
    else:
        if len(selected_reports) > 1:
            day_for_corr = st.selectbox("Correlation matrix day", [r.label for r in selected_reports], index=0)
            corr_plot = corr[corr["__day"] == day_for_corr].copy()
        else:
            corr_plot = corr.copy()

        available = [c for c in corr_plot.columns if c not in ["feature", "__day", "__day_sort", "__report"]]
        defaults = [c for c in available if c.startswith("future_ret_")][:6]
        defaults += [c for c in ["imbalance_L1", "imbalance_L2", "micro_edge_L1", "book_wap_edge_L3", "spread", "dev_roll_mean_500", "past_ret_1"] if c in available]
        defaults = list(dict.fromkeys(defaults))[:25]
        selected_features = st.multiselect("Features in heatmap", available, default=defaults)
        st.plotly_chart(heatmap_from_corr(corr_plot, features=selected_features), use_container_width=True)

        st.markdown("#### Raw correlation matrix")
        show_table(corr_plot, "correlation_matrix", height=420)

        st.markdown("#### Find highest correlations to a target")
        target = st.selectbox("Target column", available, index=available.index("future_ret_1") if "future_ret_1" in available else 0)
        if target in corr_plot.columns:
            tmp = corr_plot[["feature", target, "__day"] if "__day" in corr_plot.columns else ["feature", target]].copy()
            tmp[target] = pd.to_numeric(tmp[target], errors="coerce")
            tmp["abs_corr"] = tmp[target].abs()
            tmp = tmp.sort_values("abs_corr", ascending=False).head(50)
            show_table(tmp, f"top correlations to {target}", height=420)


# -----------------------------
# Trades tab
# -----------------------------

with tabs[9]:
    st.subheader("Trades")
    st.markdown("<div class='section-note'>Trade prints, inferred side, signed flow, and trade-flow signal scans.</div>", unsafe_allow_html=True)

    trade_summary = concat_tables(selected_reports, "trade_summary")
    side_counts = concat_tables(selected_reports, "trade_side_counts")
    trade_flow = concat_tables(selected_reports, "trade_flow_by_timestamp")
    trade_sig = concat_tables(selected_reports, "trade_flow_signal_scan")
    joined = concat_tables(selected_reports, "joined_trades_with_book")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Trade summary")
        show_table(trade_summary, "trade_summary", height=280)
    with c2:
        st.markdown("#### Side counts")
        show_table(side_counts, "trade_side_counts", height=280)

    st.markdown("#### Trade flow over time")
    if trade_flow.empty:
        st.info("No trade_flow_by_timestamp.csv found.")
    else:
        st.dataframe(trade_flow.head(1000), use_container_width=True, height=220)
        plot_cols = [c for c in ["signed_quantity", "buy_quantity", "sell_quantity", "trade_count", "quantity"] if c in trade_flow.columns]
        if plot_cols and "timestamp" in trade_flow.columns:
            choice = st.multiselect("Trade flow columns", plot_cols, default=plot_cols[: min(3, len(plot_cols))])
            if choice:
                st.plotly_chart(line_chart(trade_flow, choice, "Trade Flow", x_col="timestamp", color_by_day=True, max_points=max_points), use_container_width=True)

    st.markdown("#### Trade-flow signal scan")
    show_table(trade_sig, "trade_flow_signal_scan", height=360)

    st.markdown("#### Joined trades with book")
    if joined.empty:
        st.info("No joined_trades_with_book.csv found.")
    else:
        show_table(joined, "joined_trades_with_book", height=360)
        if {"timestamp", "price"}.issubset(joined.columns):
            fig = px.scatter(joined, x="timestamp", y="price", color="__day" if "__day" in joined.columns else None, size="quantity" if "quantity" in joined.columns else None, title="Trade Prices")
            fig.update_layout(height=430, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, use_container_width=True)


# -----------------------------
# Data Explorer tab
# -----------------------------

with tabs[10]:
    st.subheader("Data Explorer")
    st.markdown("<div class='section-note'>Inspect raw enriched rows and download selected slices.</div>", unsafe_allow_html=True)

    all_cols = list(data.columns)
    default_cols = existing_cols(
        data,
        [
            "__day",
            "timestamp",
            "mid_price",
            "spread",
            "bid_price_1",
            "ask_price_1",
            "bid_size_1",
            "ask_size_1",
            "imbalance_L1",
            "micro_edge_L1",
            "future_ret_1",
            "future_ret_5",
            "future_ret_10",
            "dev_roll_mean_500",
            "z_roll_mean_500",
        ],
    )
    selected_cols = st.multiselect("Columns", all_cols, default=default_cols)

    filt_df = data.copy()
    c1, c2, c3 = st.columns(3)
    with c1:
        if "timestamp" in filt_df.columns:
            ts_low = int(pd.to_numeric(filt_df["timestamp"], errors="coerce").min())
            ts_high = int(pd.to_numeric(filt_df["timestamp"], errors="coerce").max())
            ts_range = st.slider("Timestamp range", ts_low, ts_high, (ts_low, ts_high))
            filt_df = filt_df[(filt_df["timestamp"] >= ts_range[0]) & (filt_df["timestamp"] <= ts_range[1])]
    with c2:
        if "spread" in filt_df.columns:
            sp_vals = sorted(pd.to_numeric(filt_df["spread"], errors="coerce").dropna().unique().tolist())
            chosen_spreads = st.multiselect("Spread values", sp_vals, default=[])
            if chosen_spreads:
                filt_df = filt_df[filt_df["spread"].isin(chosen_spreads)]
    with c3:
        n_show = st.number_input("Rows to display", min_value=100, max_value=100_000, value=2_000, step=100)

    if selected_cols:
        display_df = filt_df[selected_cols].head(int(n_show))
    else:
        display_df = filt_df.head(int(n_show))

    st.dataframe(display_df, use_container_width=True, height=620)

    csv_bytes = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download displayed slice as CSV",
        csv_bytes,
        file_name="hydrogel_dashboard_slice.csv",
        mime="text/csv",
    )

    st.markdown("#### Available generated tables")
    table_rows = []
    for r in selected_reports:
        for key, rel in TABLE_PATHS.items():
            p = Path(r.path) / rel
            table_rows.append({"day": r.label, "table": key, "exists": p.exists(), "path": str(p)})
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, height=360)
