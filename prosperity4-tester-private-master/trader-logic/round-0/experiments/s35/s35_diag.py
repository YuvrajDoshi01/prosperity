import json
from datamodel import Order, TradingState

"""Diagnostic: prints PnL curve to identify drawdown episodes."""

PHI1, PHI2, EMA_ALPHA = -0.44, -0.20, 0.3
W_AR2, W_VWAP, OBI_K = 0.5, 0.3, 2.0
HALF_SPREAD_T, VWAP_WINDOW = 3, 10
FV_EM, HALF_SPREAD_E, LIMIT = 10000, 7, 80


class Trader:
    def __init__(self):
        self.mids = []; self.ema = None; self.vwap_buf = []
        self.em_cash = 0.0; self.em_peak = 0.0; self.em_last_pos = 0
        self.tom_cash = 0.0; self.tom_last_pos = 0; self.tick = 0
        self.max_combined = 0.0

    def bid(self): return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.mids=td.get("m",[]); self.ema=td.get("e"); self.vwap_buf=td.get("vt",[])
            self.em_cash=td.get("ec",0.0); self.em_peak=td.get("pk",0.0); self.em_last_pos=td.get("lp",0)
            self.tom_cash=td.get("tc2",0.0); self.tom_last_pos=td.get("tp",0); self.tick=td.get("tk",0)
            self.max_combined=td.get("mx",0.0)

        orders = {}; conversions = 0; self.tick += 1
        tom_mid = None; em_mid = None

        # ════ TOMATOES ════
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []; bb = max(od.buy_orders); ba = min(od.sell_orders)
                mid = (bb + ba) * 0.5; tom_mid = mid
                pos = state.position.get("TOMATOES", 0)

                # PnL tracking
                pd = pos - self.tom_last_pos
                if pd != 0: self.tom_cash -= pd * mid

                self.mids.append(mid)
                if len(self.mids) > 3: self.mids = self.mids[-3:]
                if len(self.mids) >= 3:
                    ar2_pred = mid + PHI1*(self.mids[-1]-self.mids[-2]) + PHI2*(self.mids[-2]-self.mids[-3])
                else: ar2_pred = mid
                if self.ema is None: self.ema = ar2_pred
                else: self.ema = EMA_ALPHA * ar2_pred + (1 - EMA_ALPHA) * self.ema

                trades = state.market_trades.get("TOMATOES", [])
                for t in trades: self.vwap_buf.append([t.price, t.quantity])
                self.vwap_buf = self.vwap_buf[-VWAP_WINDOW:]
                if self.vwap_buf:
                    fv_vwap = sum(p*q for p,q in self.vwap_buf) / sum(q for _,q in self.vwap_buf)
                else: fv_vwap = mid

                bv = sum(od.buy_orders.values()); av = sum(-v for v in od.sell_orders.values())
                obi = (bv-av)/(bv+av) if (bv+av)>0 else 0.0
                fv = W_AR2*self.ema + W_VWAP*fv_vwap + 0.2*mid + obi*OBI_K
                tv = round(fv); tb = LIMIT-pos; ts = LIMIT+pos

                for p,v in sorted(od.sell_orders.items()):
                    if tb>0 and p<=tv: q=min(tb,-v); to.append(Order("TOMATOES",p,q)); tb-=q
                for p,v in sorted(od.buy_orders.items(), reverse=True):
                    if ts>0 and p>=tv: q=min(ts,v); to.append(Order("TOMATOES",p,-q)); ts-=q
                pos_skew = 0
                if abs(pos) > 30: pos_skew = min(2, (abs(pos) - 30) // 20)
                if pos > 0: bh=HALF_SPREAD_T+pos_skew; ah=max(1,HALF_SPREAD_T-pos_skew)
                elif pos < 0: bh=max(1,HALF_SPREAD_T-pos_skew); ah=HALF_SPREAD_T+pos_skew
                else: bh=HALF_SPREAD_T; ah=HALF_SPREAD_T
                if tb>0: to.append(Order("TOMATOES", min(tv-bh, ba-1), tb))
                if ts>0: to.append(Order("TOMATOES", max(tv+ah, bb+1), -ts))
                orders["TOMATOES"] = to; self.tom_last_pos = pos

        # ════ EMERALDS ════
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []; bb = max(od.buy_orders); ba = min(od.sell_orders)
                mid = (bb+ba)*0.5; em_mid = mid; pos = state.position.get("EMERALDS", 0)

                pd = pos - self.em_last_pos
                if pd != 0: self.em_cash -= pd * mid
                total_pnl = self.em_cash + pos * mid
                self.em_peak = max(self.em_peak, total_pnl)
                drawdown = max(0.0, self.em_peak - total_pnl)

                if drawdown<50: skew=0; agg=False
                elif drawdown<150: skew=1; agg=False
                elif drawdown<300: skew=2; agg=False
                else: skew=3; agg=True

                if pos>0: bo=HALF_SPREAD_E+skew; ao=HALF_SPREAD_E-skew
                elif pos<0: bo=HALF_SPREAD_E-skew; ao=HALF_SPREAD_E+skew
                else: bo=HALF_SPREAD_E; ao=HALF_SPREAD_E
                bo=max(1,bo); ao=max(1,ao)

                tb=LIMIT-pos; ts=LIMIT+pos
                for p,v in sorted(od.sell_orders.items()):
                    if tb>0 and p<=FV_EM: q=min(tb,-v); eo.append(Order("EMERALDS",p,q)); tb-=q
                for p,v in sorted(od.buy_orders.items(), reverse=True):
                    if ts>0 and p>=FV_EM: q=min(ts,v); eo.append(Order("EMERALDS",p,-q)); ts-=q

                if agg and abs(pos)>20:
                    if pos>0 and ts>0:
                        for p,v in sorted(od.buy_orders.items(), reverse=True):
                            if ts>0 and p>=FV_EM-2: q=min(ts,v,pos); eo.append(Order("EMERALDS",p,-q)); ts-=q
                    elif pos<0 and tb>0:
                        for p,v in sorted(od.sell_orders.items()):
                            if tb>0 and p<=FV_EM+2: q=min(tb,-v,-pos); eo.append(Order("EMERALDS",p,q)); tb-=q

                if tb>0: eo.append(Order("EMERALDS", min(FV_EM-bo, ba-1), tb))
                if ts>0: eo.append(Order("EMERALDS", max(FV_EM+ao, bb+1), -ts))
                orders["EMERALDS"] = eo; self.em_last_pos = pos

                # ── DIAGNOSTIC ──
                tom_pos = state.position.get("TOMATOES", 0)
                tom_pnl = self.tom_cash + tom_pos * tom_mid if tom_mid else 0
                em_pnl = total_pnl
                combined = tom_pnl + em_pnl
                self.max_combined = max(self.max_combined, combined)
                cdd = self.max_combined - combined

                if self.tick % 50 == 0 or cdd > 200 or abs(pos) > 60 or abs(tom_pos) > 60:
                    print(f"t={state.timestamp:>7} TOM={tom_pnl:>7.0f} p={tom_pos:>4} | EM={em_pnl:>6.0f} p={pos:>4} dd={drawdown:>5.0f} sk={skew} | C={combined:>7.0f} cdd={cdd:>6.0f}")

        return orders, conversions, json.dumps(
            {"m":self.mids,"e":self.ema,"vt":self.vwap_buf,
             "ec":round(self.em_cash,2),"pk":round(self.em_peak,2),"lp":self.em_last_pos,
             "tc2":round(self.tom_cash,2),"tp":self.tom_last_pos,"tk":self.tick,
             "mx":round(self.max_combined,2)}, separators=(",",":"))
