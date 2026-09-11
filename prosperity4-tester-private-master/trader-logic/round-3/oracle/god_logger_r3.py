"""R3 GOD LOGGER — places zero orders, captures pristine market state.

Use to:
  - Verify MM bot non-reactivity on R3 products (should post fresh quotes
    independent of our activity — same as R0/R1/R2).
  - Measure voucher/underlying book behavior without our footprint.
  - Compare website log to local BT for CSV-vs-website divergence.
  - Record observation fields (sunlightIndex, sugarPrice etc.) in case R3
    exposes any — spec doesn't mention them but worth checking.

Submit this, download the website log zip, and diff against BT run on same
day to quantify where the 30-56% overshoot comes from.

Output format (one line per product per tick):
    GOD|ts|product|bid=p:v,p:v,...|ask=p:v,...|pos=N|mt=p:v,...|ot=p:v,...

For observations (single extra line if present):
    OBS|ts|product|key1=val1|key2=val2|...

Parse later with:
    grep GOD log.log | awk -F'|' '$3=="VEV_5200" {print $2, $4, $5}'
"""
import json
from datamodel import Order, TradingState


BID_VALUE = 800  # R3 manual is UI-submitted; bid() is unused but required


R3_PRODUCTS = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500",
]


class Trader:
    def __init__(self):
        self.tick = 0

    def bid(self):
        return BID_VALUE

    def run(self, state: TradingState):
        # Per-product compact book dump
        for product in sorted(state.order_depths.keys()):
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            bids = ",".join(f"{p}:{v}" for p, v in sorted(od.buy_orders.items(), reverse=True))
            asks = ",".join(f"{p}:{abs(v)}" for p, v in sorted(od.sell_orders.items()))
            mt = state.market_trades.get(product, []) or []
            mt_str = ",".join(f"{t.price}:{t.quantity}" for t in mt)
            ot = state.own_trades.get(product, []) or []
            ot_str = ",".join(f"{t.price}:{t.quantity}" for t in ot)
            print(f"GOD|{state.timestamp}|{product}|bid={bids}|ask={asks}|pos={pos}|mt={mt_str}|ot={ot_str}")

        # Observations (MACARONS-style fields — unlikely in R3 but capture if present)
        obs = getattr(state, "observations", None)
        if obs is not None:
            conv_obs = getattr(obs, "conversionObservations", None) or {}
            for prod, co in conv_obs.items():
                fields = []
                for attr in ("bidPrice", "askPrice", "transportFees",
                             "exportTariff", "importTariff",
                             "sugarPrice", "sunlightIndex"):
                    v = getattr(co, attr, None)
                    if v is not None:
                        fields.append(f"{attr}={v}")
                if fields:
                    print(f"OBS|{state.timestamp}|{prod}|" + "|".join(fields))
            plain_obs = getattr(obs, "plainValueObservations", None) or {}
            for prod, v in plain_obs.items():
                print(f"PLN|{state.timestamp}|{prod}|{v}")

        self.tick += 1
        return {}, 0, ""
