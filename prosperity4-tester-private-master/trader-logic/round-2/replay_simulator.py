"""
Replay simulator: feeds activitiesLog order-book snapshots from a website JSON
result into arbitrary Trader classes and compares aggressive-take PnL.

LIMITATIONS (stated upfront):
  - Only aggressive fills are simulated (orders crossing the book).
  - Passive fills (taker bots hitting our resting orders) are NOT captured.
  - This means ABSOLUTE PnL will be lower than real, but RELATIVE ranking
    between strategies on the same data is valid for the aggressive component.
  - IPR drift capture is mostly aggressive, so IPR ranking is reliable.
  - ACO PnL is ~30-50% passive fills on the website, so ACO absolute values
    will be understated, but strategy ordering is still informative.

Usage:
  python replay_simulator.py
"""

import json
import sys
import os
import importlib
import math
import copy

# Add this directory to path so strategies can import datamodel
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datamodel import (
    TradingState, OrderDepth, Order, Trade, Listing, Observation
)

PRODUCTS = ["INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"]
POS_LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}


# ── Parse activitiesLog into tick-indexed order books ────────────────────────

def parse_activities_log(json_path):
    """
    Returns: dict[timestamp] -> dict[product] -> {
        'buy_orders': {price: vol, ...},
        'sell_orders': {price: vol, ...},  # volumes are NEGATIVE
        'mid_price': float
    }
    """
    with open(json_path) as f:
        data = json.load(f)

    lines = data["activitiesLog"].split("\n")
    header = lines[0].split(";")
    # day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;
    # bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;
    # ask_price_3;ask_volume_3;mid_price;profit_and_loss

    ticks = {}
    original_pnl = {}  # timestamp -> pnl from original submission

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(";")
        ts = int(parts[1])
        product = parts[2]

        if ts not in ticks:
            ticks[ts] = {}

        buy_orders = {}
        sell_orders = {}

        # Parse up to 3 bid levels
        for i in range(3):
            price_str = parts[3 + i * 2]
            vol_str = parts[4 + i * 2]
            if price_str and vol_str:
                buy_orders[int(price_str)] = int(vol_str)

        # Parse up to 3 ask levels
        for i in range(3):
            price_str = parts[9 + i * 2]
            vol_str = parts[10 + i * 2]
            if price_str and vol_str:
                sell_orders[int(price_str)] = -abs(int(vol_str))  # negative

        mid_str = parts[15]
        mid = float(mid_str) if mid_str else 0.0

        pnl_str = parts[16] if len(parts) > 16 else "0"
        pnl = float(pnl_str) if pnl_str else 0.0

        ticks[ts][product] = {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "mid_price": mid,
        }

        if product == PRODUCTS[-1]:  # last product per tick
            original_pnl[ts] = pnl

    # Extract graph PnL (the actual total PnL curve from submission)
    graph_pnl = {}
    if "graphLog" in data:
        for line in data["graphLog"].split("\n"):
            if line.strip() and not line.startswith("timestamp"):
                parts = line.split(";")
                if len(parts) == 2:
                    graph_pnl[int(parts[0])] = float(parts[1])

    return ticks, data.get("profit", 0), graph_pnl


# ── Build TradingState from parsed tick data ─────────────────────────────────

def build_state(tick_data, timestamp, position, trader_data, own_trades, market_trades):
    """Build a TradingState from tick order-book data."""
    order_depths = {}
    listings = {}

    for product in PRODUCTS:
        if product not in tick_data:
            continue

        od = OrderDepth()
        od.buy_orders = dict(tick_data[product]["buy_orders"])
        od.sell_orders = dict(tick_data[product]["sell_orders"])
        order_depths[product] = od

        listings[product] = Listing(product, product, "XIRECS")

    obs = Observation({}, {})

    state = TradingState(
        traderData=trader_data,
        timestamp=timestamp,
        listings=listings,
        order_depths=order_depths,
        own_trades=own_trades,
        market_trades=market_trades,
        position=dict(position),
        observations=obs,
    )
    return state


# ── Order matching: aggressive fills only ────────────────────────────────────

def match_orders(orders, book_data, position, pos_limit):
    """
    Match strategy orders against the order book (aggressive fills only).
    Returns: list of (price, qty) fills, updated position.

    Rules (from game engine):
    - Position limits are ALL-OR-NOTHING per product per side.
    - Buy orders: if total_buy_qty + position > limit, ALL buys rejected.
    - Sell orders: if total_sell_qty + (-position) > limit, ALL sells rejected.
    - Orders crossing the book fill at the ORDER price (taker gets their price).

    Actually, re-reading the engine: orders fill at the ORDER price when
    taking liquidity. But the quantity is limited by available book volume.
    """
    fills = []
    if not orders:
        return fills, position

    # Separate buys and sells
    buys = [o for o in orders if o.quantity > 0]
    sells = [o for o in orders if o.quantity < 0]

    total_buy_qty = sum(o.quantity for o in buys)
    total_sell_qty = sum(-o.quantity for o in sells)

    # ALL-OR-NOTHING limit check per side
    buy_ok = (total_buy_qty + position) <= pos_limit
    sell_ok = (total_sell_qty - position) <= pos_limit  # -position because sell_cap = limit + pos

    buy_orders_book = book_data.get("buy_orders", {})
    sell_orders_book = book_data.get("sell_orders", {})

    # Process buy orders (they match against sell side of book)
    if buy_ok:
        # Sort asks ascending for matching
        asks = sorted(sell_orders_book.items())  # (price, neg_vol)
        ask_remaining = {p: -v for p, v in asks}  # positive volumes

        for order in sorted(buys, key=lambda o: -o.price):  # highest price first
            remaining = order.quantity
            for ask_price in sorted(ask_remaining.keys()):
                if remaining <= 0:
                    break
                if order.price >= ask_price:  # crosses the book
                    fill_qty = min(remaining, ask_remaining[ask_price])
                    if fill_qty > 0:
                        fills.append((ask_price, fill_qty))
                        position += fill_qty
                        remaining -= fill_qty
                        ask_remaining[ask_price] -= fill_qty

    # Process sell orders (they match against buy side of book)
    if sell_ok:
        # Sort bids descending for matching
        bids = sorted(buy_orders_book.items(), reverse=True)
        bid_remaining = {p: v for p, v in bids}

        for order in sorted(sells, key=lambda o: o.price):  # lowest price first
            remaining = -order.quantity  # positive
            for bid_price in sorted(bid_remaining.keys(), reverse=True):
                if remaining <= 0:
                    break
                if order.price <= bid_price:  # crosses the book
                    fill_qty = min(remaining, bid_remaining[bid_price])
                    if fill_qty > 0:
                        fills.append((bid_price, -fill_qty))
                        position -= fill_qty
                        remaining -= fill_qty
                        bid_remaining[bid_price] -= fill_qty

    return fills, position


# ── Run a single strategy through the replay ─────────────────────────────────

def run_strategy(trader_class, ticks, strategy_name):
    """
    Run a Trader class against the tick data and return results.
    """
    trader = trader_class()
    position = {p: 0 for p in PRODUCTS}
    cash = {p: 0.0 for p in PRODUCTS}
    trader_data = ""

    # Track per-tick data
    pnl_curve = []
    position_curve = {p: [] for p in PRODUCTS}
    fill_counts = {p: 0 for p in PRODUCTS}
    fill_volume = {p: 0 for p in PRODUCTS}
    errors = []

    timestamps = sorted(ticks.keys())

    own_trades_prev = {p: [] for p in PRODUCTS}

    for ts in timestamps:
        tick_data = ticks[ts]

        # Build state
        state = build_state(
            tick_data, ts, position, trader_data,
            own_trades_prev, {p: [] for p in PRODUCTS}
        )

        # Call trader
        try:
            result = trader.run(state)
            orders_dict, conversions, trader_data = result
        except Exception as e:
            errors.append((ts, str(e)))
            orders_dict = {}
            conversions = 0
            trader_data = trader_data  # keep old

        # Match orders per product
        own_trades_this_tick = {p: [] for p in PRODUCTS}

        for product in PRODUCTS:
            product_orders = orders_dict.get(product, [])
            if not product_orders:
                continue

            book_data = tick_data.get(product, {})
            if not book_data:
                continue

            fills, new_pos = match_orders(
                product_orders, book_data, position[product], POS_LIMITS[product]
            )

            for price, qty in fills:
                cash[product] -= price * qty  # buy: qty>0, cash decreases
                fill_counts[product] += 1
                fill_volume[product] += abs(qty)
                own_trades_this_tick[product].append(
                    Trade(product, price, abs(qty),
                          buyer="SELF" if qty > 0 else "",
                          seller="SELF" if qty < 0 else "",
                          timestamp=ts)
                )

            position[product] = new_pos

        own_trades_prev = own_trades_this_tick

        # Calculate mark-to-market PnL
        total_pnl = 0.0
        for product in PRODUCTS:
            mid = tick_data.get(product, {}).get("mid_price", 0)
            total_pnl += cash[product] + position[product] * mid

        pnl_curve.append((ts, total_pnl))
        for product in PRODUCTS:
            position_curve[product].append((ts, position[product]))

    # Final PnL breakdown
    final_pnl = {}
    for product in PRODUCTS:
        mid = ticks[timestamps[-1]].get(product, {}).get("mid_price", 0)
        final_pnl[product] = cash[product] + position[product] * mid

    return {
        "name": strategy_name,
        "total_pnl": sum(final_pnl.values()),
        "per_product": final_pnl,
        "final_position": dict(position),
        "fill_counts": fill_counts,
        "fill_volume": fill_volume,
        "pnl_curve": pnl_curve,
        "position_curve": position_curve,
        "errors": errors,
        "cash": dict(cash),
    }


# ── Load strategy module dynamically ─────────────────────────────────────────

def load_trader(module_path):
    """Load a Trader class from a .py file."""
    spec = importlib.util.spec_from_file_location("trader_module", module_path)
    mod = importlib.util.module_from_spec(spec)

    # Ensure datamodel is available
    sys.modules.setdefault("datamodel", importlib.import_module("datamodel"))

    spec.loader.exec_module(mod)
    return mod.Trader


# ── Pretty print results ─────────────────────────────────────────────────────

def print_results(results, original_profit, graph_pnl):
    """Print comparison table."""
    print("=" * 100)
    print(f"REPLAY COMPARISON — Original submission profit: {original_profit:,.2f}")
    print("=" * 100)
    print()
    print("⚠️  NOTE: Only AGGRESSIVE fills simulated (orders crossing the book).")
    print("    Passive fills (taker bots hitting our resting quotes) are NOT included.")
    print("    IPR ranking is reliable (drift = aggressive entry).")
    print("    ACO absolute values are understated but ordering is informative.")
    print()

    # Sort by total PnL
    results.sort(key=lambda r: r["total_pnl"], reverse=True)

    # Header
    print(f"{'Strategy':<12} {'Total PnL':>12} {'IPR PnL':>12} {'ACO PnL':>12} "
          f"{'IPR Pos':>8} {'ACO Pos':>8} {'IPR Fills':>10} {'ACO Fills':>10} "
          f"{'IPR Vol':>9} {'ACO Vol':>9} {'Errors':>7}")
    print("-" * 120)

    for r in results:
        ipr_pnl = r["per_product"].get("INTARIAN_PEPPER_ROOT", 0)
        aco_pnl = r["per_product"].get("ASH_COATED_OSMIUM", 0)
        ipr_pos = r["final_position"].get("INTARIAN_PEPPER_ROOT", 0)
        aco_pos = r["final_position"].get("ASH_COATED_OSMIUM", 0)
        ipr_fills = r["fill_counts"].get("INTARIAN_PEPPER_ROOT", 0)
        aco_fills = r["fill_counts"].get("ASH_COATED_OSMIUM", 0)
        ipr_vol = r["fill_volume"].get("INTARIAN_PEPPER_ROOT", 0)
        aco_vol = r["fill_volume"].get("ASH_COATED_OSMIUM", 0)

        print(f"{r['name']:<12} {r['total_pnl']:>12,.2f} {ipr_pnl:>12,.2f} {aco_pnl:>12,.2f} "
              f"{ipr_pos:>8} {aco_pos:>8} {ipr_fills:>10} {aco_fills:>10} "
              f"{ipr_vol:>9} {aco_vol:>9} {len(r['errors']):>7}")

    # Delta table
    print()
    print("── Deltas vs best strategy ──")
    best = results[0]
    for r in results[1:]:
        delta = r["total_pnl"] - best["total_pnl"]
        ipr_delta = r["per_product"].get("INTARIAN_PEPPER_ROOT", 0) - best["per_product"].get("INTARIAN_PEPPER_ROOT", 0)
        aco_delta = r["per_product"].get("ASH_COATED_OSMIUM", 0) - best["per_product"].get("ASH_COATED_OSMIUM", 0)
        print(f"  {r['name']:<12} Δtotal={delta:>+10,.2f}  ΔIPR={ipr_delta:>+10,.2f}  ΔACO={aco_delta:>+10,.2f}")

    # PnL at key timestamps
    print()
    print("── PnL curve snapshots ──")
    checkpoints = [0, 100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000, 900000, 999900]
    header = f"{'Timestamp':>10}"
    for r in results:
        header += f" {r['name']:>12}"
    if graph_pnl:
        header += f" {'Original':>12}"
    print(header)
    print("-" * (10 + 13 * (len(results) + (1 if graph_pnl else 0))))

    for cp in checkpoints:
        line = f"{cp:>10}"
        for r in results:
            # Find closest timestamp
            pnl_dict = {ts: pnl for ts, pnl in r["pnl_curve"]}
            val = pnl_dict.get(cp, 0)
            line += f" {val:>12,.2f}"
        if graph_pnl:
            orig = graph_pnl.get(cp, 0)
            line += f" {orig:>12,.2f}"
        print(line)

    # Report any errors
    for r in results:
        if r["errors"]:
            print(f"\n⚠️  {r['name']} had {len(r['errors'])} errors:")
            for ts, err in r["errors"][:5]:
                print(f"    t={ts}: {err}")
            if len(r["errors"]) > 5:
                print(f"    ... and {len(r['errors']) - 5} more")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "results rd1", "270919.json")

    print("Loading order book data from 270919.json ...")
    ticks, original_profit, graph_pnl = parse_activities_log(json_path)
    print(f"  Loaded {len(ticks)} ticks, 2 products, original profit: {original_profit:,.2f}")
    print()

    # Strategy files to compare
    strategies = {
        "270919":   os.path.join(base_dir, "results rd1", "270919.py"),
        "r2_v9":    os.path.join(base_dir, "r2_v9.py"),
        "r2_v10":   os.path.join(base_dir, "r2_v10.py"),
        "r2_v11":   os.path.join(base_dir, "r2_v11.py"),
        "r2_v12":   os.path.join(base_dir, "r2_v12.py"),
        "r2_v13":   os.path.join(base_dir, "r2_v13.py"),
        "r2_v14":   os.path.join(base_dir, "r2_v14.py"),
    }

    results = []
    for name, path in strategies.items():
        print(f"Running {name} ...")
        try:
            TraderClass = load_trader(path)
            result = run_strategy(TraderClass, ticks, name)
            results.append(result)
            print(f"  ✓ {name}: PnL = {result['total_pnl']:,.2f}")
        except Exception as e:
            print(f"  ✗ {name}: FAILED — {e}")
            import traceback
            traceback.print_exc()

    print()
    print_results(results, original_profit, graph_pnl)


if __name__ == "__main__":
    main()
