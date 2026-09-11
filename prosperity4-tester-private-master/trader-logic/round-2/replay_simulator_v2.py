"""
Replay simulator v2: aggressive fills + passive fill estimation.

Improvement over v1: after aggressive matching, checks where each strategy
posts resting orders relative to best bid/ask. Uses the original submission's
per-product PnL to calibrate the passive fill rate and estimates passive PnL
for each strategy proportionally.

Key insight from 270919 analysis:
  - IPR: 96% aggressive, 4% passive → aggressive sim is sufficient
  - ACO: 21% aggressive, 79% passive → passive estimation is critical
"""

import json
import sys
import os
import importlib
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datamodel import (
    TradingState, OrderDepth, Order, Trade, Listing, Observation
)

PRODUCTS = ["INTARIAN_PEPPER_ROOT", "ASH_COATED_OSMIUM"]
POS_LIMITS = {"INTARIAN_PEPPER_ROOT": 80, "ASH_COATED_OSMIUM": 80}


def parse_activities_log(json_path):
    with open(json_path) as f:
        data = json.load(f)

    lines = data["activitiesLog"].split("\n")

    ticks = {}
    per_product_pnl = {p: {} for p in PRODUCTS}

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
        for i in range(3):
            p_str, v_str = parts[3 + i * 2], parts[4 + i * 2]
            if p_str and v_str:
                buy_orders[int(p_str)] = int(v_str)
        for i in range(3):
            p_str, v_str = parts[9 + i * 2], parts[10 + i * 2]
            if p_str and v_str:
                sell_orders[int(p_str)] = -abs(int(v_str))

        mid = float(parts[15]) if parts[15] else 0.0
        pnl = float(parts[16]) if len(parts) > 16 and parts[16] else 0.0

        ticks[ts][product] = {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "mid_price": mid,
        }
        per_product_pnl[product][ts] = pnl

    graph_pnl = {}
    if "graphLog" in data:
        for line in data["graphLog"].split("\n"):
            if line.strip() and not line.startswith("timestamp"):
                parts = line.split(";")
                if len(parts) == 2:
                    graph_pnl[int(parts[0])] = float(parts[1])

    return ticks, data.get("profit", 0), graph_pnl, per_product_pnl


def build_state(tick_data, timestamp, position, trader_data, own_trades):
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

    return TradingState(
        traderData=trader_data,
        timestamp=timestamp,
        listings=listings,
        order_depths=order_depths,
        own_trades=own_trades,
        market_trades={p: [] for p in PRODUCTS},
        position=dict(position),
        observations=Observation({}, {}),
    )


def match_orders_and_resting(orders, book_data, position, pos_limit):
    """
    Match aggressive orders AND return resting (unfilled) orders.
    Returns: fills, new_position, resting_orders
    """
    fills = []
    resting = []
    if not orders:
        return fills, position, resting

    buys = [o for o in orders if o.quantity > 0]
    sells = [o for o in orders if o.quantity < 0]

    total_buy_qty = sum(o.quantity for o in buys)
    total_sell_qty = sum(-o.quantity for o in sells)

    buy_ok = (total_buy_qty + position) <= pos_limit
    sell_ok = (total_sell_qty - position) <= pos_limit

    sell_book = book_data.get("sell_orders", {})
    buy_book = book_data.get("buy_orders", {})

    # Match buys against sell side
    ask_remaining = {p: -v for p, v in sell_book.items()}

    if buy_ok:
        for order in sorted(buys, key=lambda o: -o.price):
            remaining = order.quantity
            for ask_price in sorted(ask_remaining.keys()):
                if remaining <= 0:
                    break
                if order.price >= ask_price:
                    fill_qty = min(remaining, ask_remaining[ask_price])
                    if fill_qty > 0:
                        fills.append((ask_price, fill_qty))
                        position += fill_qty
                        remaining -= fill_qty
                        ask_remaining[ask_price] -= fill_qty
            if remaining > 0:
                resting.append(Order(order.symbol, order.price, remaining))
    else:
        # All buys rejected — they become resting (won't match)
        resting.extend(buys)

    # Match sells against buy side
    bid_remaining = dict(buy_book)

    if sell_ok:
        for order in sorted(sells, key=lambda o: o.price):
            remaining = -order.quantity
            for bid_price in sorted(bid_remaining.keys(), reverse=True):
                if remaining <= 0:
                    break
                if order.price <= bid_price:
                    fill_qty = min(remaining, bid_remaining[bid_price])
                    if fill_qty > 0:
                        fills.append((bid_price, -fill_qty))
                        position -= fill_qty
                        remaining -= fill_qty
                        bid_remaining[bid_price] -= fill_qty
            if remaining > 0:
                resting.append(Order(order.symbol, order.price, -remaining))
    else:
        resting.extend(sells)

    return fills, position, resting


def run_strategy(trader_class, ticks, strategy_name):
    trader = trader_class()
    position = {p: 0 for p in PRODUCTS}
    cash = {p: 0.0 for p in PRODUCTS}
    trader_data = ""

    pnl_curve = []
    fill_counts = {p: 0 for p in PRODUCTS}
    fill_volume = {p: 0 for p in PRODUCTS}

    # Passive fill estimation: track resting order competitiveness
    # For each tick, record if we have a resting bid at best_bid or better,
    # and a resting ask at best_ask or better.
    passive_bid_ticks = {p: 0 for p in PRODUCTS}  # ticks with competitive resting bid
    passive_ask_ticks = {p: 0 for p in PRODUCTS}  # ticks with competitive resting ask
    passive_bid_volume = {p: 0 for p in PRODUCTS}  # total vol at competitive bids
    passive_ask_volume = {p: 0 for p in PRODUCTS}  # total vol at competitive asks
    total_ticks_with_book = {p: 0 for p in PRODUCTS}

    errors = []
    timestamps = sorted(ticks.keys())
    own_trades_prev = {p: [] for p in PRODUCTS}

    for ts in timestamps:
        tick_data = ticks[ts]
        state = build_state(tick_data, ts, position, trader_data, own_trades_prev)

        try:
            result = trader.run(state)
            orders_dict, conversions, trader_data = result
        except Exception as e:
            errors.append((ts, str(e)))
            orders_dict = {}
            conversions = 0

        own_trades_this = {p: [] for p in PRODUCTS}

        for product in PRODUCTS:
            product_orders = orders_dict.get(product, [])
            book_data = tick_data.get(product, {})
            if not book_data:
                continue

            best_bid = max(book_data["buy_orders"]) if book_data["buy_orders"] else None
            best_ask = min(book_data["sell_orders"]) if book_data["sell_orders"] else None

            if best_bid is not None or best_ask is not None:
                total_ticks_with_book[product] += 1

            if not product_orders:
                continue

            fills, new_pos, resting = match_orders_and_resting(
                product_orders, book_data, position[product], POS_LIMITS[product]
            )

            for price, qty in fills:
                cash[product] -= price * qty
                fill_counts[product] += 1
                fill_volume[product] += abs(qty)
                own_trades_this[product].append(
                    Trade(product, price, abs(qty),
                          buyer="SELF" if qty > 0 else "",
                          seller="SELF" if qty < 0 else "",
                          timestamp=ts)
                )

            position[product] = new_pos

            # Analyze resting orders for passive fill estimation
            # A resting bid that's at or above best_bid is competitive
            # A resting ask that's at or below best_ask is competitive
            for ro in resting:
                if ro.quantity > 0 and best_bid is not None:
                    # Resting buy — competitive if at best_bid or above
                    if ro.price >= best_bid:
                        passive_bid_ticks[product] += 1
                        passive_bid_volume[product] += ro.quantity
                        break  # count once per tick
                elif ro.quantity < 0 and best_ask is not None:
                    if ro.price <= best_ask:
                        passive_ask_ticks[product] += 1
                        passive_ask_volume[product] += abs(ro.quantity)
                        break

        own_trades_prev = own_trades_this

        total_pnl = 0.0
        for product in PRODUCTS:
            mid = tick_data.get(product, {}).get("mid_price", 0)
            total_pnl += cash[product] + position[product] * mid
        pnl_curve.append((ts, total_pnl))

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
        "passive_bid_ticks": passive_bid_ticks,
        "passive_ask_ticks": passive_ask_ticks,
        "passive_bid_volume": passive_bid_volume,
        "passive_ask_volume": passive_ask_volume,
        "total_ticks_with_book": total_ticks_with_book,
        "errors": errors,
        "cash": dict(cash),
    }


def load_trader(module_path):
    spec = importlib.util.spec_from_file_location("trader_module", module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("datamodel", importlib.import_module("datamodel"))
    spec.loader.exec_module(mod)
    return mod.Trader


def print_results(results, original_profit, per_product_pnl):
    timestamps = sorted(per_product_pnl["INTARIAN_PEPPER_ROOT"].keys())
    last_ts = timestamps[-1]

    real_ipr = per_product_pnl["INTARIAN_PEPPER_ROOT"].get(last_ts, 0)
    real_aco = per_product_pnl["ASH_COATED_OSMIUM"].get(last_ts, 0)

    print("=" * 110)
    print(f"REPLAY COMPARISON v2 — Website profit: {original_profit:,.2f}")
    print(f"  IPR real: {real_ipr:,.2f}  |  ACO real: {real_aco:,.2f}")
    print("=" * 110)

    # Find original submission's passive metrics for calibration
    orig = next((r for r in results if r["name"] == "270919"), None)

    # Compute passive PnL for original to calibrate
    orig_passive_aco = real_aco - (orig["per_product"]["ASH_COATED_OSMIUM"] if orig else 0)
    orig_passive_ipr = real_ipr - (orig["per_product"]["INTARIAN_PEPPER_ROOT"] if orig else 0)

    # Original's passive tick counts for scaling
    orig_aco_passive_total = (
        (orig["passive_bid_ticks"]["ASH_COATED_OSMIUM"] +
         orig["passive_ask_ticks"]["ASH_COATED_OSMIUM"]) if orig else 1
    )
    orig_ipr_passive_total = (
        (orig["passive_bid_ticks"]["INTARIAN_PEPPER_ROOT"] +
         orig["passive_ask_ticks"]["INTARIAN_PEPPER_ROOT"]) if orig else 1
    )

    print()
    print("── AGGRESSIVE-ONLY PnL ──")
    print(f"{'Strategy':<12} {'Total':>10} {'IPR':>10} {'ACO':>10} "
          f"{'ACO Fills':>10} {'ACO Vol':>9}")
    print("-" * 65)

    results.sort(key=lambda r: r["total_pnl"], reverse=True)
    for r in results:
        ipr = r["per_product"].get("INTARIAN_PEPPER_ROOT", 0)
        aco = r["per_product"].get("ASH_COATED_OSMIUM", 0)
        print(f"{r['name']:<12} {r['total_pnl']:>10,.0f} {ipr:>10,.0f} {aco:>10,.0f} "
              f"{r['fill_counts'].get('ASH_COATED_OSMIUM', 0):>10} "
              f"{r['fill_volume'].get('ASH_COATED_OSMIUM', 0):>9}")

    print()
    print("── PASSIVE FILL POTENTIAL (resting orders at competitive prices) ──")
    print(f"{'Strategy':<12} {'ACO bid':>9} {'ACO ask':>9} {'ACO total':>10} "
          f"{'IPR bid':>9} {'IPR ask':>9} {'IPR total':>10} "
          f"{'ACO bidV':>9} {'ACO askV':>9}")
    print("-" * 105)

    for r in results:
        ab = r["passive_bid_ticks"]["ASH_COATED_OSMIUM"]
        aa = r["passive_ask_ticks"]["ASH_COATED_OSMIUM"]
        ib = r["passive_bid_ticks"]["INTARIAN_PEPPER_ROOT"]
        ia = r["passive_ask_ticks"]["INTARIAN_PEPPER_ROOT"]
        abv = r["passive_bid_volume"]["ASH_COATED_OSMIUM"]
        aav = r["passive_ask_volume"]["ASH_COATED_OSMIUM"]
        print(f"{r['name']:<12} {ab:>9} {aa:>9} {ab+aa:>10} "
              f"{ib:>9} {ia:>9} {ib+ia:>10} "
              f"{abv:>9} {aav:>9}")

    # Estimate total PnL with passive fills
    print()
    print("── ESTIMATED TOTAL PnL (aggressive + scaled passive) ──")
    print()
    print(f"  Calibration: 270919 passive ACO = {orig_passive_aco:,.2f} from "
          f"{orig_aco_passive_total} competitive-price ticks")
    print(f"  Calibration: 270919 passive IPR = {orig_passive_ipr:,.2f} from "
          f"{orig_ipr_passive_total} competitive-price ticks")
    if orig_aco_passive_total > 0:
        print(f"  ACO passive PnL per competitive tick = {orig_passive_aco / orig_aco_passive_total:,.2f}")
    if orig_ipr_passive_total > 0:
        print(f"  IPR passive PnL per competitive tick = {orig_passive_ipr / orig_ipr_passive_total:,.2f}")
    print()

    # Scale passive PnL by ratio of competitive ticks
    estimated = []
    for r in results:
        at = (r["passive_bid_ticks"]["ASH_COATED_OSMIUM"] +
              r["passive_ask_ticks"]["ASH_COATED_OSMIUM"])
        it = (r["passive_bid_ticks"]["INTARIAN_PEPPER_ROOT"] +
              r["passive_ask_ticks"]["INTARIAN_PEPPER_ROOT"])

        aco_passive_est = (
            orig_passive_aco * (at / orig_aco_passive_total)
            if orig_aco_passive_total > 0 else 0
        )
        ipr_passive_est = (
            orig_passive_ipr * (it / orig_ipr_passive_total)
            if orig_ipr_passive_total > 0 else 0
        )

        agg_ipr = r["per_product"].get("INTARIAN_PEPPER_ROOT", 0)
        agg_aco = r["per_product"].get("ASH_COATED_OSMIUM", 0)

        est_ipr = agg_ipr + ipr_passive_est
        est_aco = agg_aco + aco_passive_est
        est_total = est_ipr + est_aco

        estimated.append({
            "name": r["name"],
            "est_total": est_total,
            "est_ipr": est_ipr,
            "est_aco": est_aco,
            "agg_ipr": agg_ipr,
            "agg_aco": agg_aco,
            "passive_ipr": ipr_passive_est,
            "passive_aco": aco_passive_est,
        })

    estimated.sort(key=lambda e: e["est_total"], reverse=True)

    print(f"{'Strategy':<12} {'Est Total':>12} {'Est IPR':>10} {'Est ACO':>10} "
          f"{'(agg IPR':>10} {'+pass)':>8} {'(agg ACO':>10} {'+pass)':>8}")
    print("-" * 95)

    for e in estimated:
        print(f"{e['name']:<12} {e['est_total']:>12,.0f} {e['est_ipr']:>10,.0f} "
              f"{e['est_aco']:>10,.0f} "
              f"({e['agg_ipr']:>8,.0f} {'+' + str(int(e['passive_ipr'])):>7}) "
              f"({e['agg_aco']:>8,.0f} {'+' + str(int(e['passive_aco'])):>7})")

    print()
    print("── Deltas vs best estimated ──")
    best = estimated[0]
    for e in estimated[1:]:
        d = e["est_total"] - best["est_total"]
        di = e["est_ipr"] - best["est_ipr"]
        da = e["est_aco"] - best["est_aco"]
        print(f"  {e['name']:<12} Δtotal={d:>+10,.0f}  ΔIPR={di:>+8,.0f}  ΔACO={da:>+8,.0f}")

    # Sanity check: original should be close to real
    orig_est = next((e for e in estimated if e["name"] == "270919"), None)
    if orig_est:
        print()
        print(f"  Sanity: 270919 estimated={orig_est['est_total']:,.0f} vs real={original_profit:,.2f} "
              f"(Δ={orig_est['est_total'] - original_profit:+,.0f})")

    # Report errors
    for r in results:
        if r["errors"]:
            print(f"\n⚠️  {r['name']} had {len(r['errors'])} errors:")
            for ts, err in r["errors"][:3]:
                print(f"    t={ts}: {err}")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "results rd1", "270919.json")

    print("Loading 270919.json ...")
    ticks, original_profit, graph_pnl, per_product_pnl = parse_activities_log(json_path)
    print(f"  {len(ticks)} ticks, original profit: {original_profit:,.2f}")
    print()

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
        print(f"Running {name} ...", end=" ")
        try:
            TraderClass = load_trader(path)
            result = run_strategy(TraderClass, ticks, name)
            results.append(result)
            print(f"✓ agg={result['total_pnl']:,.0f}")
        except Exception as e:
            print(f"✗ {e}")
            import traceback
            traceback.print_exc()

    print()
    print_results(results, original_profit, per_product_pnl)


if __name__ == "__main__":
    main()
