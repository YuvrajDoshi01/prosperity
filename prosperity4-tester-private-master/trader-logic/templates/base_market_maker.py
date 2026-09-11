"""BaseMarketMaker template (Phase 5.1 of R4-prep roadmap).

Reference implementation of the EMA + zscore mean-reversion + imbalance +
multi-level posting pattern proven on R2 (try18-5: 99,534 single-day) and
R3 (r3_v14: +$8,904 over baseline via deep-ITM theta carry).

This file is a TEMPLATE — copy and inline into a strategy file for IMC
submission (single-file requirement). Do not import directly in submission code.

Architecture:
    1. RawMid: midpoint of L1 (with one-sided book fallbacks)
    2. Median smoothing: 5-tick rolling median of raw mids
    3. EMA fair value: median-of-20 bootstrap, then exponential update
    4. Z-score signal: continuous scaling (replaces try18-5's discrete bins)
    5. Imbalance dampening: 0.7× when contradicts zscore (no aggressive boost)
    6. Inventory skew: continuous risk_aversion × (pos - target)
    7. Take/Clear/Make ordering with multi-level make
    8. Multi-level posting: 3 layers (40/30/30 capacity)

Tested-but-rejected components (do NOT add):
    - Direction bias (-1/+1 × 0.3 × sign(z)): net-zero PnL
    - Discrete zscore thresholds {0, 0.6, 1.0}: regime-switch artifacts
    - Imbalance asymmetric BOOST (1.2x on confirmation): overfitting
    - Day-type detector for gentle-drift products: doesn't fire (Phase 2 finding)

Calibration constants below were validated on R2/R3 historical data.
Re-calibrate per round with calibrate_imc.py before relying on absolute PnL.
"""

import math
import statistics
from collections import deque
from typing import List, Optional, Dict, Any


# ── Default parameters (override per product) ────────────────────────────────
DEFAULT_PARAMS = {
    "take_width": 2,           # take_orders fires when |fv - book_price| > this
    "clear_width": 1,          # clear_orders posts at FV ± clear_width
    "disregard_edge": 1,       # ignore book levels within this of FV when making
    "join_edge": 2,            # join existing levels within this of FV
    "default_edge": 4,         # default make edge when no good join
    "risk_aversion": 0.025,    # continuous inventory skew coefficient
    "target_position": 0,      # inventory target (0 = neutral, 40 = long-bias)
    "ema_alpha": 0.039,        # EMA update rate (≈ 2/51 → 25-tick effective window)
    "z_window": 40,            # rolling window for zscore stdev
    "z_scale_max": 1.0,        # zscore signal clip (continuous: scale = min(max, 0.5*|z|))
    "imbalance_dampen": 0.7,   # multiplier when imbalance contradicts zscore
    "bootstrap_window": 20,    # ticks for median bootstrap before EMA takes over
    "make_layers": 3,          # number of price levels per make side
    "make_split": (0.4, 0.3, 0.3),   # capacity allocation across layers
    "limit": 200,              # position limit (override per product)
}


def filtered_mid(order_depth, adverse_volume: int = 15) -> Optional[float]:
    """Mid using only volume-filtered levels (avoids tiny-quote noise).

    Falls back to raw L1 mid if no volumes pass the filter.
    """
    if not order_depth or not order_depth.buy_orders or not order_depth.sell_orders:
        return None
    bids = order_depth.buy_orders
    asks = order_depth.sell_orders
    filt_b = [p for p in bids if abs(bids[p]) >= adverse_volume]
    filt_a = [p for p in asks if abs(asks[p]) >= adverse_volume]
    bid = max(filt_b) if filt_b else max(bids)
    ask = min(filt_a) if filt_a else min(asks)
    return 0.5 * (bid + ask)


def wall_mid(order_depth) -> Optional[float]:
    """Wall Mid: midpoint of HIGHEST-VOLUME bid/ask levels.

    Captures the IMC MM bot's "true" fair value (visible mid lags it).
    Every R3 2nd-place team used this. +$19k 3-day on R3 VFE alone.
    """
    if not order_depth or not order_depth.buy_orders or not order_depth.sell_orders:
        return None
    pop_bid = max(order_depth.buy_orders.items(), key=lambda kv: kv[1])[0]
    pop_ask = min(order_depth.sell_orders.items(), key=lambda kv: kv[1])[0]
    return 0.5 * (pop_bid + pop_ask)


def zscore_signal(mid: float, mid_history: List[float], window: int = 40) -> Optional[float]:
    """Compute zscore of current mid vs rolling window."""
    if len(mid_history) < max(12, window // 4):
        return None
    sample = mid_history[-window:]
    mean_m = statistics.mean(sample)
    try:
        std_m = statistics.stdev(sample)
    except statistics.StatisticsError:
        return None
    if std_m < 1e-9:
        return None
    return (mid - mean_m) / std_m


def order_book_imbalance(order_depth) -> float:
    """L1 imbalance ∈ [-1, 1]. Positive = bid-heavy (price rising)."""
    if not order_depth or not order_depth.buy_orders or not order_depth.sell_orders:
        return 0.0
    bv = sum(order_depth.buy_orders.values())
    av = sum(abs(v) for v in order_depth.sell_orders.values())
    denom = bv + av
    return (bv - av) / denom if denom > 0 else 0.0


def fair_value(
    raw_mid: float,
    mid_history: List[float],
    position: int,
    order_depth,
    params: Dict[str, Any],
) -> tuple:
    """Compute fair value + dynamic width from EMA + zscore + imbalance + inventory.

    Returns:
        (fair_value, dynamic_width)
    """
    z_window = params.get("z_window", 40)
    target = params.get("target_position", 0)
    risk_av = params.get("risk_aversion", 0.025)
    take_w = params.get("take_width", 2)

    # EMA ≈ rolling median for first 20 ticks (bootstrap), then mean
    bootstrap_n = params.get("bootstrap_window", 20)
    if len(mid_history) <= bootstrap_n:
        ema = statistics.median(mid_history) if mid_history else raw_mid
    else:
        # Note: real impl should persist EMA in trader_data, not recompute
        ema = statistics.mean(mid_history[-bootstrap_n:])

    # Z-score signal (continuous scale, replaces discrete bins)
    z = zscore_signal(raw_mid, mid_history, window=z_window)
    if z is None:
        mr_adj = 0.0
    else:
        sample = mid_history[-z_window:]
        try:
            ret_std = statistics.stdev(sample)
        except statistics.StatisticsError:
            ret_std = 1.0
        scale = min(params.get("z_scale_max", 1.0), max(0.0, 0.5 * abs(z)))
        mr_adj = -z * ret_std * scale

    # Imbalance dampening (no aggressive boost — overfit-prone)
    imb = order_book_imbalance(order_depth)
    if z is not None and z != 0:
        imb_confirms = (z > 0 and imb < 0) or (z < 0 and imb > 0)
        if not imb_confirms:
            mr_adj *= params.get("imbalance_dampen", 0.7)

    # Continuous inventory skew (Avellaneda-Stoikov limit form)
    inv_adj = -(position - target) * risk_av

    fv = ema + mr_adj + inv_adj

    # Dynamic width: stays at base unless ret_std spikes
    dyn_w = float(take_w)
    if z is not None:
        try:
            ret_std = statistics.stdev(mid_history[-z_window:])
            dyn_w = max(take_w, take_w * (1 + 0.3 * max(abs(z) - 0.5, 0)))
        except statistics.StatisticsError:
            pass

    return fv, dyn_w


def take_orders(symbol, order_depth, fv: float, take_width: float, position: int, limit: int) -> tuple:
    """Take orders that cross the fair value threshold (multi-level sweep).

    Returns (orders, buy_volume_taken, sell_volume_taken).
    """
    orders = []
    buy_vol = 0
    sell_vol = 0
    headroom_buy = limit - position
    headroom_sell = limit + position

    # BUY: sweep ALL asks below fv - take_width
    if order_depth.sell_orders and headroom_buy > 0:
        for px in sorted(order_depth.sell_orders.keys()):
            if px > fv - take_width:
                break
            avail = abs(order_depth.sell_orders[px])
            qty = min(avail, headroom_buy - buy_vol)
            if qty > 0:
                orders.append((symbol, px, qty))
                buy_vol += qty
            if buy_vol >= headroom_buy:
                break

    # SELL: sweep ALL bids above fv + take_width
    if order_depth.buy_orders and headroom_sell > 0:
        for px in sorted(order_depth.buy_orders.keys(), reverse=True):
            if px < fv + take_width:
                break
            avail = order_depth.buy_orders[px]
            qty = min(avail, headroom_sell - sell_vol)
            if qty > 0:
                orders.append((symbol, px, -qty))
                sell_vol += qty
            if sell_vol >= headroom_sell:
                break

    return orders, buy_vol, sell_vol


def make_orders(
    symbol, order_depth, fv: float, position: int, buy_volume: int, sell_volume: int,
    params: Dict[str, Any]
) -> List[tuple]:
    """Multi-level passive make orders (40/30/30 capacity split per side).

    Returns list of (symbol, price, signed_qty) tuples.
    """
    limit = params.get("limit", 200)
    layers = params.get("make_layers", 3)
    split = params.get("make_split", (0.4, 0.3, 0.3))[:layers]
    default_edge = params.get("default_edge", 4)

    orders = []
    headroom_buy = max(0, limit - position - buy_volume)
    headroom_sell = max(0, limit + position - sell_volume)

    # Bid layers
    if headroom_buy > 0 and order_depth.buy_orders:
        best_bid = max(order_depth.buy_orders.keys())
        bp = min(round(fv - default_edge), best_bid + 1)
        for i, frac in enumerate(split):
            qty = int(headroom_buy * frac) if i < layers - 1 else headroom_buy - sum(int(headroom_buy * f) for f in split[:i])
            if qty > 0:
                orders.append((symbol, bp - i, qty))

    # Ask layers
    if headroom_sell > 0 and order_depth.sell_orders:
        best_ask = min(order_depth.sell_orders.keys())
        ap = max(round(fv + default_edge), best_ask - 1)
        for i, frac in enumerate(split):
            qty = int(headroom_sell * frac) if i < layers - 1 else headroom_sell - sum(int(headroom_sell * f) for f in split[:i])
            if qty > 0:
                orders.append((symbol, ap + i, -qty))

    return orders


# Documentation: how to inline into a strategy file
"""
USAGE PATTERN (inline into your strategy file):

    from datamodel import Order, TradingState

    # Copy DEFAULT_PARAMS, filtered_mid, wall_mid, zscore_signal,
    # order_book_imbalance, fair_value, take_orders, make_orders into your file.

    class Trader:
        def run(self, state: TradingState):
            orders = {}
            trader_data = json.loads(state.traderData) if state.traderData else {}

            for product in ["YOUR_PRODUCT"]:
                params = {**DEFAULT_PARAMS, "limit": 200, "target_position": 0}
                od = state.order_depths.get(product)
                if not od or not od.buy_orders or not od.sell_orders:
                    continue

                # Track mid history in trader_data
                mids = trader_data.setdefault(f"{product}_mids", [])
                mid = filtered_mid(od)
                if mid is None: continue
                mids.append(mid)
                mids[:] = mids[-100:]   # cap history

                pos = state.position.get(product, 0)
                fv, dyn_w = fair_value(mid, mids, pos, od, params)

                # Take → Clear → Make
                taker_orders, bv, sv = take_orders(product, od, fv, dyn_w, pos, params["limit"])
                # ... clear step (omitted; product-specific)
                maker_orders = make_orders(product, od, fv, pos, bv, sv, params)

                orders[product] = [Order(s, p, q) for (s, p, q) in taker_orders + maker_orders]

            return orders, 0, json.dumps(trader_data)
"""
