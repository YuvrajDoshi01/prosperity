import json
from typing import Dict, List, Tuple, Any
import math

# ==========================================
# 1. DATAMODEL DEFINITIONS
# ==========================================
Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int

class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: Product):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination

class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float, exportTariff: float, importTariff: float, sunlight: float, humidity: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sunlight = sunlight
        self.humidity = humidity

class Observation:
    def __init__(self, plainValueObservations: Dict[Product, ObservationValue], conversionObservations: Dict[Product, ConversionObservation]) -> None:
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

class Order:
 def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
    self.symbol = symbol
    self.price = price
    self.quantity = quantity

 def __str__(self) -> str:
    return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"

 def __repr__(self) -> str:
    return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"

class OrderDepth:
 def __init__(self):
    self.buy_orders: Dict[int, int] = {}
    self.sell_orders: Dict[int, int] = {}

class Trade:
 def __init__(self, symbol: Symbol, price: int, quantity: int, buyer: UserId=None, seller: UserId=None, timestamp: int=0) -> None:
    self.symbol = symbol
    self.price: int = price
    self.quantity: int = quantity
    self.buyer = buyer
    self.seller = seller
    self.timestamp = timestamp

class TradingState(object):
 def __init__(self,
 traderData: str,
 timestamp: Time,
 listings: Dict[Symbol, Listing],
 order_depths: Dict[Symbol, OrderDepth],
 own_trades: Dict[Symbol, List[Trade]],
 market_trades: Dict[Symbol, List[Trade]],
 position: Dict[Product, Position],
 observations: Observation):
    self.traderData = traderData
    self.timestamp = timestamp
    self.listings = listings
    self.order_depths = order_depths
    self.own_trades = own_trades
    self.market_trades = market_trades
    self.position = position
    self.observations = observations

# ==========================================
# 2. THE DYNAMIC PENNY MAKER ALGORITHM
# ==========================================

class Trader:
 def __init__(self):
    self.limit = 80
 
 def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], int, str]:
    result = {}
    conversions = 0 
 
    history = {}
    if state.traderData:
        try:
            history = json.loads(state.traderData)
        except Exception:
            pass
 
 # ==========================================
 # STRATEGY 1: EMERALDS (Dynamic Penny)
 # ==========================================
    product_e = "EMERALDS"
    order_depth_e = state.order_depths.get(product_e)
 
    if order_depth_e:
        position_e = state.position.get(product_e, 0)
        orders_e = []
        
        best_bid_e = max(order_depth_e.buy_orders.keys()) if order_depth_e.buy_orders else 0
        best_ask_e = min(order_depth_e.sell_orders.keys()) if order_depth_e.sell_orders else 0
        
        if best_bid_e > 0 and best_ask_e > 0:
        # 1. Calculate our Risk Target (Shift pricing by 1 tick per 20 inventory)
            shift_e = int(position_e / 20)
            target_bid_e = 9998 - shift_e
            target_ask_e = 10002 - shift_e
            
            # 2. Dynamic Pennying: Try to beat the best market price, but NEVER exceed our target
            # Also ensure we NEVER cross the spread (which incurs Taker fees)
            buy_price_e = min(target_bid_e, best_bid_e + 1, best_ask_e - 1)
            sell_price_e = max(target_ask_e, best_ask_e - 1, best_bid_e + 1)
            
            # 3. Maximize Volume: Put 100% of our capacity on the optimal line
            buy_qty_e = self.limit - position_e
            sell_qty_e = self.limit + position_e
            
            if buy_qty_e > 0:
                orders_e.append(Order(product_e, buy_price_e, buy_qty_e))
            if sell_qty_e > 0:
                orders_e.append(Order(product_e, sell_price_e, -sell_qty_e))
            
    result[product_e] = orders_e

    # ==========================================
    # STRATEGY 2: TOMATOES (SMA + Dynamic Penny)
    # ==========================================
    product_t = "TOMATOES"
    order_depth_t = state.order_depths.get(product_t)
    
    if order_depth_t:
        position_t = state.position.get(product_t, 0)
        orders_t = []
        
        best_bid_t = max(order_depth_t.buy_orders.keys()) if order_depth_t.buy_orders else 0
        best_ask_t = min(order_depth_t.sell_orders.keys()) if order_depth_t.sell_orders else 0
        
        if best_bid_t > 0 and best_ask_t > 0:
            mid_t = (best_bid_t + best_ask_t) / 2
        
        price_history = history.get("TOMATOES_PRICES", [])
        price_history.append(mid_t)
        if len(price_history) > 20:
            price_history.pop(0)
            history["TOMATOES_PRICES"] = price_history
        
        if len(price_history) == 20:
            # 1. Simple, responsive SMA
            sma = sum(price_history) / 20
            
            # 2. Calculate Risk Target (Base spread of 1.5, shifted by inventory)
            shift_t = int(position_t / 20)
            target_bid_t = math.floor(sma - 1.5 - shift_t)
            target_ask_t = math.ceil(sma + 1.5 - shift_t)
            
            # 3. Dynamic Pennying (The Magic Formula)
            buy_price_t = min(target_bid_t, best_bid_t + 1, best_ask_t - 1)
            sell_price_t = max(target_ask_t, best_ask_t - 1, best_bid_t + 1)
            
            # 4. Maximize Volume
            buy_qty_t = self.limit - position_t
            sell_qty_t = self.limit + position_t
            
            if buy_qty_t > 0:
                orders_t.append(Order(product_t, buy_price_t, buy_qty_t))
            if sell_qty_t > 0:
                orders_t.append(Order(product_t, sell_price_t, -sell_qty_t))
            
    result[product_t] = orders_t

    # Serialize memory
    traderData = json.dumps(history)
    return result, conversions, traderData