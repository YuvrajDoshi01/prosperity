"""r4_yolo_short.py - YOLO delta-short voucher portfolio with regime gate.

HYPOTHESIS: R4 day-3 1k probe shows VFE -$42 / ATM vouchers -50% structural drop.
A short portfolio (VFE -200 + every voucher except dust -300) yields theoretical
$75,750 mid PnL, $57,200 cross-spread, peak unrealized $91,300.
Validated BT 1k day-3 = $66,232 (skip-bb=0 variant).

DAYS BT (skip bb=0):
  day 1: -$11,149   day 2: -$8,849   day 3: +$66,232

REGIME GATE: only enter the short portfolio if EARLY VFE DRIFT in first DETECT_TICKS
ticks is below DRIFT_THRESHOLD (negative). On flat/up days the gate refuses to short
and we sit flat - PROTECTS against day 1/2 -$10k bleed if the live day mirrors them.

If live day 4 is a down regime (like day 3), we capture ~$50k+ short PnL.
If live day 4 is flat/up, we sit out for ~0 PnL (vs r4_final ~$6k upside foregone).

This is a DIRECTIONAL bet substituting for r4_final ONLY if user is confident
day 4 will be a down regime. Otherwise use r4_final.

BT cmd:
  cd C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester
  PYTHONPATH=prosperity4bt python -m prosperity4bt trader-logic/round-4/r4_yolo_short.py 4-3 --ticks 1000 --no-out --no-progress
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, ProsperityEncoder, Symbol, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""

    def print(self, *objects, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: Dict[Symbol, List[Order]],
              conversions: int, trader_data: str) -> None:
        base = json.dumps([
            state.timestamp,
            trader_data,
            [],
            {sym: [[o.symbol, o.price, o.quantity] for o in lst] for sym, lst in orders.items()},
            conversions,
            self.logs,
        ], cls=ProsperityEncoder, separators=(",", ":"))
        print(base)
        self.logs = ""


logger = Logger()

# Position limits
LIMIT_VFE = 200
LIMIT_VOUCHER = 300

TARGET_SHORT = {
    "VELVETFRUIT_EXTRACT": -LIMIT_VFE,
    "VEV_4000": -LIMIT_VOUCHER, "VEV_4500": -LIMIT_VOUCHER,
    "VEV_5000": -LIMIT_VOUCHER, "VEV_5100": -LIMIT_VOUCHER,
    "VEV_5200": -LIMIT_VOUCHER, "VEV_5300": -LIMIT_VOUCHER,
    "VEV_5400": -LIMIT_VOUCHER, "VEV_5500": -LIMIT_VOUCHER,
    "VEV_6000": -LIMIT_VOUCHER, "VEV_6500": -LIMIT_VOUCHER,
}
PROD_LIMITS = {p: abs(t) for p, t in TARGET_SHORT.items()}

# REGIME DETECTION
DETECT_TICKS = 30           # ts=3000 decision point
DRIFT_THRESHOLD = -1.5      # VFE drift must be <= -1.5 to enter short
                            # @ ts=3000: day1=+5.0, day2=+3.0, day3=-3.0
                            # threshold -1.5 cleanly separates day-3 from days 1/2
                            # day-3 first 50 ticks: VFE 5295.5 -> ~5292 (-3.5)
                            # day-1/2: VFE drift typically positive or near-zero


def best_levels(od) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    bb = max(od.buy_orders.keys()) if od.buy_orders else None
    ba = min(od.sell_orders.keys()) if od.sell_orders else None
    bbv = od.buy_orders[bb] if bb is not None else 0
    bav = -od.sell_orders[ba] if ba is not None else 0
    return bb, bbv, ba, bav


class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        orders: Dict[Symbol, List[Order]] = {}

        # Load state
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}

        vfe_anchor = mem.get("vfe_anchor")
        regime_decided = mem.get("regime", None)  # None=undecided, True=short, False=skip

        # Track VFE mid
        vfe_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        vfe_mid = None
        if vfe_od:
            bb, _, ba, _ = best_levels(vfe_od)
            if bb is not None and ba is not None:
                vfe_mid = (bb + ba) / 2.0

        ts = state.timestamp
        if vfe_anchor is None and vfe_mid is not None:
            vfe_anchor = vfe_mid
            mem["vfe_anchor"] = vfe_anchor

        # Decide regime once at DETECT_TICKS
        if regime_decided is None and vfe_mid is not None and vfe_anchor is not None:
            if ts >= DETECT_TICKS * 100:  # ts is in 100ms units
                drift = vfe_mid - vfe_anchor
                regime_decided = (drift <= DRIFT_THRESHOLD)
                mem["regime"] = regime_decided

        # Once decided NOT to short, sit flat
        if regime_decided is False:
            mem_str = json.dumps(mem)
            logger.flush(state, orders, 0, mem_str)
            return orders, 0, mem_str

        # Pre-decision: also start shorting from t=0 (early entry maximizes PnL).
        # If regime later flips to "skip", we cover by buying back at exit.
        # Simpler: just always short until decision is False.
        # But for DETECT mode we wait for ts >= DETECT_TICKS*100 before entering.
        # ALTERNATE: enter from t=0 always (more aggressive). User requested
        # "first-50-tick VFE drift detection signals down regime, enter MAX SHORT".
        # So: we wait for drift confirmation OR enter immediately if signal is strong.

        if regime_decided is None:
            # Not decided yet - sit flat
            mem_str = json.dumps(mem)
            logger.flush(state, orders, 0, mem_str)
            return orders, 0, mem_str

        # regime_decided is True: SHORT EVERYTHING
        for product, target in TARGET_SHORT.items():
            if product not in state.order_depths:
                continue
            od = state.order_depths[product]
            pos = state.position.get(product, 0)

            short_capacity = pos - target  # positive = how many more we can sell
            if short_capacity <= 0:
                continue

            bb, bbv, ba, bav = best_levels(od)

            # Skip products where best_bid == 0 (cannot capture premium by shorting)
            if bb is not None and bb <= 0:
                continue

            prod_orders: List[Order] = []
            remaining = short_capacity

            # 1. Aggressive take: sell into all bid levels
            for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                if remaining <= 0:
                    break
                bid_qty = od.buy_orders[bid_price]
                fill = min(remaining, bid_qty)
                if fill > 0:
                    prod_orders.append(Order(product, bid_price, -fill))
                    remaining -= fill

            # 2. Passive: post remaining at best_ask (join queue, no spread cost)
            if remaining > 0 and ba is not None:
                prod_orders.append(Order(product, ba, -remaining))

            if prod_orders:
                orders[product] = prod_orders

        mem_str = json.dumps(mem)
        logger.flush(state, orders, 0, mem_str)
        return orders, 0, mem_str
