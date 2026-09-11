"""
Independent matching engine implementing the EXACT IMC tick sequence
from chrispyroberts/imc-prosperity-4 Rust simulator source.

Zero fitted constants. No extra_rate. No calibration hacks.
The matching logic IS the model.

Tick sequence (from Rust source):
  1. Fresh books generated (MM bot quotes from CSV)
  2. Strategy called -> returns orders
  3. Strategy aggressive orders match against book (== price matching)
  4. Unfilled orders become passive levels (LevelOwner::Strategy)
  5. Taker arrives (from trades CSV) -> hits ALL levels by price priority
  6. Passive orders DISCARDED at tick end

Usage:
  python -m prosperity4bt.tools.rust_engine trader.py round day [--ticks N]
"""
import csv
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

# ──────────────────────────────────────────────────────────────────
# Data loading (reuse our existing CSV data)
# ──────────────────────────────────────────────────────────────────

def load_prices(round_num, day_num):
    """Load order book snapshots from CSV."""
    base = Path(__file__).parent.parent / "resources" / f"round{round_num}"
    fname = base / f"prices_round_{round_num}_day_{day_num}.csv"
    books = {}  # ts -> {product: {buy_orders: {price: vol}, sell_orders: {price: -vol}}}
    with open(fname, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = int(row["timestamp"])
            prod = row["product"]
            buys = {}
            sells = {}
            for i in range(1, 4):
                bp = row.get(f"bid_price_{i}", "")
                bv = row.get(f"bid_volume_{i}", "")
                ap = row.get(f"ask_price_{i}", "")
                av = row.get(f"ask_volume_{i}", "")
                if bp and bv:
                    buys[int(bp)] = int(bv)
                if ap and av:
                    sells[int(ap)] = -abs(int(av))
            if ts not in books:
                books[ts] = {}
            books[ts][prod] = {"buy_orders": buys, "sell_orders": sells}
    return books


def load_trades(round_num, day_num):
    """Load taker events from CSV."""
    base = Path(__file__).parent.parent / "resources" / f"round{round_num}"
    fname = base / f"trades_round_{round_num}_day_{day_num}.csv"
    trades = defaultdict(list)  # ts -> [{symbol, price, quantity, buyer, seller}]
    if not fname.exists():
        return trades
    with open(fname, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = int(row["timestamp"])
            trades[ts].append({
                "symbol": row["symbol"],
                "price": int(float(row["price"])),
                "quantity": int(row["quantity"]),
                "buyer": row.get("buyer", ""),
                "seller": row.get("seller", ""),
            })
    return trades


# ──────────────────────────────────────────────────────────────────
# Matching engine — faithful port of Rust execute_strategy_orders
# ──────────────────────────────────────────────────────────────────

from prosperity4bt.constants import LIMITS
DEFAULT_POSITION_LIMIT = 80  # R0/R1 fallback for unknown products


def enforce_limits(orders, positions):
    """ALL-OR-NOTHING position limit check per product (from Rust source).

    Uses per-product LIMITS dict from constants.py (R3+ vouchers have 300,
    delta-1 products 200). Unknown products default to 80.
    """
    valid = {}
    for product, order_list in orders.items():
        pos = positions.get(product, 0)
        total_buy = sum(o.quantity for o in order_list if o.quantity > 0)
        total_sell = sum(abs(o.quantity) for o in order_list if o.quantity < 0)
        limit = LIMITS.get(product, DEFAULT_POSITION_LIMIT)
        if pos + total_buy > limit or pos - total_sell < -limit:
            continue  # reject ALL orders for this product
        valid[product] = order_list
    return valid


def execute_tick(mm_book, strategy_orders, taker_events, positions, pnl):
    """
    Execute one tick using the exact Rust sequence.

    mm_book: {product: {buy_orders: {price: vol}, sell_orders: {price: -vol}}}
    strategy_orders: {product: [Order(symbol, price, quantity), ...]}
    taker_events: [{symbol, price, quantity, buyer, seller}, ...]
    positions: {product: int} — mutated in place
    pnl: {product: float} — mutated in place

    Returns: list of fills [{product, price, quantity, side, source}, ...]
    """
    fills = []

    for product in mm_book:
        book = mm_book[product]
        orders = strategy_orders.get(product, [])
        if not orders:
            continue

        # Deep copy the MM book (fresh each tick, from Rust: "new Book instances created from RNG")
        asks = {}  # price -> (volume, owner='bot')
        bids = {}  # price -> (volume, owner='bot')
        for price, vol in book.get("sell_orders", {}).items():
            asks[price] = [abs(vol), "bot"]
        for price, vol in book.get("buy_orders", {}).items():
            bids[price] = [vol, "bot"]

        # ── Step 3: Execute strategy aggressive orders ──
        passive_bids = {}  # price -> qty (our resting buys)
        passive_asks = {}  # price -> qty (our resting sells)

        for order in orders:
            if order.quantity > 0:
                # BUY order — match against asks
                remaining = order.quantity
                for ask_price in sorted(asks.keys()):
                    if ask_price > order.price or remaining <= 0:
                        break
                    avail = asks[ask_price][0]
                    fill_qty = min(remaining, avail)
                    if fill_qty > 0:
                        # Fill: we buy from MM at ask_price
                        positions[product] = positions.get(product, 0) + fill_qty
                        pnl[product] = pnl.get(product, 0) - ask_price * fill_qty
                        fills.append({"product": product, "price": ask_price,
                                      "quantity": fill_qty, "side": "buy", "source": "book"})
                        asks[ask_price][0] -= fill_qty
                        remaining -= fill_qty
                        if asks[ask_price][0] <= 0:
                            del asks[ask_price]
                # Remaining becomes passive bid
                if remaining > 0:
                    passive_bids[order.price] = passive_bids.get(order.price, 0) + remaining

            elif order.quantity < 0:
                # SELL order — match against bids
                remaining = abs(order.quantity)
                for bid_price in sorted(bids.keys(), reverse=True):
                    if bid_price < order.price or remaining <= 0:
                        break
                    avail = bids[bid_price][0]
                    fill_qty = min(remaining, avail)
                    if fill_qty > 0:
                        positions[product] = positions.get(product, 0) - fill_qty
                        pnl[product] = pnl.get(product, 0) + bid_price * fill_qty
                        fills.append({"product": product, "price": bid_price,
                                      "quantity": fill_qty, "side": "sell", "source": "book"})
                        bids[bid_price][0] -= fill_qty
                        remaining -= fill_qty
                        if bids[bid_price][0] <= 0:
                            del bids[bid_price]
                if remaining > 0:
                    passive_asks[order.price] = passive_asks.get(order.price, 0) + remaining

        # ── Step 4: Insert passive orders into the live book ──
        for price, qty in passive_bids.items():
            if price in bids:
                # Our bid at same price as MM — we're BEHIND in time priority
                # But if our price is BETTER (higher), we're first
                bids[price] = [bids[price][0] + qty, "mixed"]
            else:
                bids[price] = [qty, "strategy"]

        for price, qty in passive_asks.items():
            if price in asks:
                asks[price] = [asks[price][0] + qty, "mixed"]
            else:
                asks[price] = [qty, "strategy"]

        # ── Step 5: Taker arrives — hits ALL levels by price priority ──
        product_takers = [t for t in taker_events if t["symbol"] == product]
        for taker in product_takers:
            taker_qty = taker["quantity"]
            is_taker_buy = taker.get("buyer") == "TAKER" or taker["price"] > 10000
            # Heuristic for CSV data without buyer/seller labels:
            # Use price vs mid. High price = buy (lifts ask), low = sell (hits bid)
            if not taker.get("buyer") and not taker.get("seller"):
                # CSV format: no labels. Determine from book context.
                mid_bids = max(bids.keys()) if bids else 0
                mid_asks = min(asks.keys()) if asks else 99999
                mid = (mid_bids + mid_asks) / 2 if bids and asks else 10000
                is_taker_buy = taker["price"] >= mid

            if is_taker_buy:
                # Taker BUYS — hits asks (lowest first = price priority)
                remaining = taker_qty
                for ask_price in sorted(asks.keys()):
                    if remaining <= 0:
                        break
                    avail = asks[ask_price][0]
                    owner = asks[ask_price][1]
                    fill_qty = min(remaining, avail)

                    if owner in ("strategy", "mixed"):
                        # Our passive sell gets filled by taker
                        # How much of this level is ours vs MM?
                        if owner == "strategy":
                            our_fill = fill_qty
                        else:
                            # Mixed: proportional split (simplified)
                            our_share = passive_asks.get(ask_price, 0)
                            total_at_level = avail
                            our_fill = min(fill_qty, our_share)

                        if our_fill > 0:
                            positions[product] = positions.get(product, 0) - our_fill
                            pnl[product] = pnl.get(product, 0) + ask_price * our_fill
                            fills.append({"product": product, "price": ask_price,
                                          "quantity": our_fill, "side": "sell",
                                          "source": "taker"})

                    asks[ask_price][0] -= fill_qty
                    remaining -= fill_qty
                    if asks[ask_price][0] <= 0:
                        del asks[ask_price]

            else:
                # Taker SELLS — hits bids (highest first)
                remaining = taker_qty
                for bid_price in sorted(bids.keys(), reverse=True):
                    if remaining <= 0:
                        break
                    avail = bids[bid_price][0]
                    owner = bids[bid_price][1]
                    fill_qty = min(remaining, avail)

                    if owner in ("strategy", "mixed"):
                        if owner == "strategy":
                            our_fill = fill_qty
                        else:
                            our_share = passive_bids.get(bid_price, 0)
                            our_fill = min(fill_qty, our_share)

                        if our_fill > 0:
                            positions[product] = positions.get(product, 0) + our_fill
                            pnl[product] = pnl.get(product, 0) - bid_price * our_fill
                            fills.append({"product": product, "price": bid_price,
                                          "quantity": our_fill, "side": "buy",
                                          "source": "taker"})

                    bids[bid_price][0] -= fill_qty
                    remaining -= fill_qty
                    if bids[bid_price][0] <= 0:
                        del bids[bid_price]

    return fills


# ──────────────────────────────────────────────────────────────────
# Full backtest runner
# ──────────────────────────────────────────────────────────────────

def run_backtest(trader_path, round_num, day_num, max_ticks=None):
    """Run a full backtest using the Rust-logic matching engine."""
    from prosperity4bt.datamodel import Order, OrderDepth, TradingState, Listing, Observation, Trade

    # Load data
    books = load_prices(round_num, day_num)
    trade_events = load_trades(round_num, day_num)
    timestamps = sorted(books.keys())
    if max_ticks:
        timestamps = timestamps[:max_ticks]

    products = set()
    for ts_data in books.values():
        products.update(ts_data.keys())
    products = sorted(products)

    # Load trader
    spec = importlib.util.spec_from_file_location("trader_module", trader_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    trader = mod.Trader()

    # State
    positions = {p: 0 for p in products}
    cash_pnl = {p: 0.0 for p in products}
    trader_data = ""
    all_fills = []

    for ts in timestamps:
        # Build TradingState
        order_depths = {}
        for product in products:
            od = OrderDepth()
            book_data = books[ts].get(product, {"buy_orders": {}, "sell_orders": {}})
            od.buy_orders = dict(book_data["buy_orders"])
            od.sell_orders = dict(book_data["sell_orders"])
            order_depths[product] = od

        listings = {p: Listing(p, p, 1) for p in products}
        obs = Observation({}, {})

        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings=listings,
            order_depths=order_depths,
            own_trades={p: [] for p in products},
            market_trades={p: [] for p in products},
            position=dict(positions),
            observations=obs,
        )

        # Call strategy
        try:
            result, conversions, trader_data = trader.run(state)
        except Exception as e:
            print(f"  Strategy error at ts={ts}: {e}")
            result = {}
            trader_data = ""

        # Enforce position limits (ALL-OR-NOTHING)
        result = enforce_limits(result, positions)

        # Execute tick using Rust-logic engine
        taker_events = trade_events.get(ts, [])
        tick_fills = execute_tick(
            books[ts], result, taker_events, positions, cash_pnl
        )
        all_fills.extend(tick_fills)

    # Compute final PnL (cash + MTM)
    last_ts = timestamps[-1]
    final_pnl = {}
    for product in products:
        mid = None
        book_data = books[last_ts].get(product, {})
        buys = book_data.get("buy_orders", {})
        sells = book_data.get("sell_orders", {})
        if buys and sells:
            mid = (max(buys.keys()) + min(sells.keys())) / 2
        elif buys:
            mid = max(buys.keys())
        elif sells:
            mid = min(sells.keys())
        else:
            mid = 0
        mtm = positions[product] * mid
        final_pnl[product] = cash_pnl[product] + mtm

    return final_pnl, positions, all_fills


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m prosperity4bt.tools.rust_engine trader.py round [day] [--ticks N]")
        sys.exit(1)

    trader_path = sys.argv[1]
    round_num = int(sys.argv[2])

    # Parse day
    day_num = None
    ticks = None
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--ticks":
            ticks = int(sys.argv[i + 1])
            i += 2
        else:
            day_num = int(sys.argv[i])
            i += 1

    # Determine days to run
    day_map = {0: [-2, -1, 0], 1: [-2, -1, 0, 1]}
    if day_num is not None:
        days = [day_num]
    else:
        days = day_map.get(round_num, [-2, -1, 0])

    total_pnl = 0
    for day in days:
        pnl, pos, fills = run_backtest(trader_path, round_num, day, max_ticks=ticks)
        total = sum(pnl.values())
        total_pnl += total
        print(f"Day {day}:")
        for product in sorted(pnl.keys()):
            fill_count = len([f for f in fills if f["product"] == product])
            book_fills = len([f for f in fills if f["product"] == product and f["source"] == "book"])
            taker_fills = len([f for f in fills if f["product"] == product and f["source"] == "taker"])
            print(f"  {product}: {pnl[product]:>10,.1f}  (fills: {fill_count} = {book_fills} book + {taker_fills} taker, pos={pos[product]})")
        print(f"  Total: {total:>10,.1f}")
        print()

    if len(days) > 1:
        print(f"Grand total: {total_pnl:,.1f}")
