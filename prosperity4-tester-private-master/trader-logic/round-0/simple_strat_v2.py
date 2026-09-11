import json
import math
from typing import Dict, List, Any

class Order:
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

class Trader:
    def __init__(self):
        # General
        self.pos_limit = 80

        # Tomatoes Config
        self.vol_threshold = 15
        self.spread = 3
        self.taking_edge = 0.5

        # Emeralds Config
        self.EMERALD_LIMIT = 80
        self.EMERALD_FV = 10000
        self.EMERALD_AGGRESSION_THRESHOLD = 10
        self.LIQUIDATION_WINDOW = 10
        self.emerald_limit_history = []

    def run(self, state: Any):
        result = {}
        
        tick_data = {
            "timestamp": getattr(state, 'timestamp', 0),
            "metrics": {},
            "orders": {}
        }

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            bids_raw = order_depth.buy_orders
            asks_raw = order_depth.sell_orders
            
            if not bids_raw or not asks_raw:
                continue

            current_pos = state.position.get(product, 0)
            
            # --- EMERALDS ROUTE ---
            if product == "EMERALDS":
                em_orders = []
                pos = current_pos
                buy_capacity = self.EMERALD_LIMIT - pos
                sell_capacity = self.EMERALD_LIMIT + pos
                
                bids = sorted(bids_raw.items(), reverse=True)
                asks = sorted(asks_raw.items())

                self.emerald_limit_history.append(abs(pos) == self.EMERALD_LIMIT)
                if len(self.emerald_limit_history) > self.LIQUIDATION_WINDOW:
                    self.emerald_limit_history = self.emerald_limit_history[-self.LIQUIDATION_WINDOW:]
                
                at_limit_soft = (len(self.emerald_limit_history) == self.LIQUIDATION_WINDOW
                                and sum(self.emerald_limit_history) >= 5
                                and self.emerald_limit_history[-1])
                at_limit_hard = (len(self.emerald_limit_history) == self.LIQUIDATION_WINDOW
                                and all(self.emerald_limit_history))

                max_buy_price = self.EMERALD_FV if pos <= self.EMERALD_AGGRESSION_THRESHOLD else self.EMERALD_FV - 1
                min_sell_price = self.EMERALD_FV if pos >= -self.EMERALD_AGGRESSION_THRESHOLD else self.EMERALD_FV + 1

                for price, vol in asks:
                    if buy_capacity > 0 and price <= max_buy_price:
                        qty = min(buy_capacity, -vol)
                        em_orders.append(Order("EMERALDS", price, qty))
                        buy_capacity -= qty

                if buy_capacity > 0 and at_limit_hard:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", self.EMERALD_FV, qty))
                    buy_capacity -= qty
                if buy_capacity > 0 and at_limit_soft:
                    qty = buy_capacity // 2
                    em_orders.append(Order("EMERALDS", self.EMERALD_FV - 2, qty))
                    buy_capacity -= qty

                if buy_capacity > 0:
                    bid_price = min(self.EMERALD_FV - 1, bids[0][0] + 1)
                    em_orders.append(Order("EMERALDS", bid_price, buy_capacity))

                for price, vol in bids:
                    if sell_capacity > 0 and price >= min_sell_price:
                        qty = min(sell_capacity, vol)
                        em_orders.append(Order("EMERALDS", price, -qty))
                        sell_capacity -= qty

                if sell_capacity > 0 and at_limit_hard:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", self.EMERALD_FV, -qty))
                    sell_capacity -= qty
                if sell_capacity > 0 and at_limit_soft:
                    qty = sell_capacity // 2
                    em_orders.append(Order("EMERALDS", self.EMERALD_FV + 2, -qty))
                    sell_capacity -= qty

                if sell_capacity > 0:
                    ask_price = max(self.EMERALD_FV + 1, asks[0][0] - 1)
                    em_orders.append(Order("EMERALDS", ask_price, -sell_capacity))

                result["EMERALDS"] = em_orders
                
                tick_data["orders"]["EMERALDS"] = [{"price": o.price, "qty": o.quantity} for o in em_orders]
                tick_data["metrics"]["EMERALDS"] = {"fair_value": self.EMERALD_FV, "position": pos}

            # --- TOMATOES ROUTE ---
            elif product == "TOMATOES":
                orders = []
                best_bid = max(bids_raw.keys())
                best_ask = min(asks_raw.keys())

                valid_bids = {p: v for p, v in bids_raw.items() if v >= self.vol_threshold}
                valid_asks = {p: -v for p, v in asks_raw.items() if -v >= self.vol_threshold}

                if not valid_bids or not valid_asks:
                    fair_value = (best_bid + best_ask) / 2.0
                else:
                    total_bid_vol = sum(valid_bids.values())
                    total_ask_vol = sum(valid_asks.values())
                    
                    avg_bid = sum(p * v for p, v in valid_bids.items()) / total_bid_vol
                    avg_ask = sum(p * v for p, v in valid_asks.items()) / total_ask_vol

                    # Micro-price VWAP calculation
                    fair_value = (avg_bid * total_ask_vol + avg_ask * total_bid_vol) / (total_bid_vol + total_ask_vol)

                tick_data["metrics"]["TOMATOES"] = {
                    "fair_value": round(fair_value, 2),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "position": current_pos
                }

                take_buy_qty = 0
                take_sell_qty = 0

                # Opportunistic Taking
                if best_ask <= fair_value - self.taking_edge:
                    take_buy_qty = min(-asks_raw[best_ask], self.pos_limit - current_pos)
                    if take_buy_qty > 0:
                        orders.append(Order("TOMATOES", best_ask, take_buy_qty))
                        current_pos += take_buy_qty

                if best_bid >= fair_value + self.taking_edge:
                    take_sell_qty = min(bids_raw[best_bid], self.pos_limit + current_pos)
                    if take_sell_qty > 0:
                        orders.append(Order("TOMATOES", best_bid, -take_sell_qty))
                        current_pos -= take_sell_qty

                # Dynamic Pennying for Market Making
                min_edge = self.spread / 2.0
                my_bid_price = min(math.floor(fair_value - min_edge), best_bid + 1)
                my_ask_price = max(math.ceil(fair_value + min_edge), best_ask - 1)

                make_buy_qty = self.pos_limit - current_pos
                make_sell_qty = self.pos_limit + current_pos

                # Send passive orders, strictly avoiding crossing the book
                if make_buy_qty > 0 and my_bid_price < best_ask:
                    orders.append(Order("TOMATOES", my_bid_price, make_buy_qty))
                    
                if make_sell_qty > 0 and my_ask_price > best_bid:
                    orders.append(Order("TOMATOES", my_ask_price, -make_sell_qty))

                result["TOMATOES"] = orders
                tick_data["orders"]["TOMATOES"] = [{"price": o.price, "qty": o.quantity} for o in orders]

        trader_data = json.dumps(tick_data, separators=(',', ':'))

        return result, 0, trader_data