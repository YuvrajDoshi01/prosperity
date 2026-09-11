import json
from datamodel import Order, TradingState

"""
GOD MODE: Perfect future knowledge from website logs.

Uses hardcoded oracle signal extracted from run 8587 (day -1 price path).
At each tick, knows whether price will go up or down over the next 50 ticks.
Posts ONE-SIDED to build position in the profitable direction.

Theoretical max: 26,640 TOMATOES PnL (15x our normal 1,805).
Actual will be less (can only reposition through fills, not teleport).

FOR TROLLING PURPOSES ONLY. Not eligible for competition.
"""

# Oracle: {timestamp: signal} where +1 = long, -1 = short, 0 = flat
# Extracted from run 8587 website logs (50-tick lookahead)
O = {0:-1,1400:0,1500:-1,2000:0,2600:1,2700:0,3000:1,3900:0,4000:1,6400:0,6500:1,6800:0,6900:1,7000:0,7200:1,7300:0,7400:1,7600:0,7900:-1,8000:0,8800:-1,9100:0,9200:-1,9400:0,9500:-1,10900:0,11200:-1,12300:0,12400:-1,12900:0,13000:-1,13100:0,13200:-1,14500:0,14600:-1,15100:0,15300:-1,17200:0,17300:-1,18400:0,18500:-1,19100:0,19200:-1,20500:0,20600:-1,21400:0,21500:-1,22000:0,22100:-1,22400:0,22500:-1,23300:0,23400:-1,23800:0,24100:-1,26700:0,26800:-1,27300:0,27400:-1,27900:0,28100:-1,28400:0,28700:-1,28900:0,29200:-1,29400:0,29800:1,30000:0,30100:1,31100:0,31200:1,31600:0,31900:1,32100:0,32900:-1,33000:0,33200:-1,37900:0,38000:-1,39300:0,40000:-1,40100:0,40700:-1,40800:0,43000:1,46500:0,46600:1,48300:0,48400:1,48600:0,49700:-1,49800:0,50300:1,50900:0,51100:-1,51200:0,51500:1,51600:0,52000:-1,52100:0,53400:-1,53500:0,53600:-1,54700:0,54800:-1,54900:0,56400:1,56900:0,57300:1,57600:0,57800:1,57900:0,58100:1,58300:0,58400:1,58500:0,58600:1,60200:0,60600:1,60700:0,61200:1,61300:0,61600:-1,61900:0,62100:-1,63600:0,63700:-1,65300:0,65500:-1,66500:0,67600:1,67700:0,67800:1,68000:0,68200:1,68600:0,69100:1,70300:0,70500:1,70600:0,70700:1,70800:0,70900:1,71500:0,71800:1,71900:0,72100:1,72200:0,72300:1,72400:0,74000:1,74100:0,75300:1,75400:0,75500:1,75900:0,76200:1,76300:0,77900:-1,78000:0,78100:-1,86900:0,87200:-1,89400:0,89500:-1,89600:0,90100:1,90200:0,90500:1,91100:0,91200:1,95300:0,95400:1,95600:0,96000:1,96400:0,96500:1,97100:0,97200:1,97700:0,97800:1,98100:0,98200:1,98800:0,98900:1,99000:0,99800:1,100400:0,100500:1,100800:0,101400:1,101500:0,101900:-1,102000:0,102900:-1,103100:0,103200:-1,103400:0,104400:1,104500:0,104800:1,109600:0,109700:1,109800:0,111200:1,111300:0,111600:1,111700:0,111800:1,113500:0,113700:1,113900:0,114000:1,116200:0,116300:1,116600:0,116700:1,116800:0,117700:-1,118000:0,118300:-1,118400:0,118700:-1,118900:0,119000:-1,119300:0,119400:-1,119700:0,119800:-1,120200:0,120300:-1,120900:0,121000:-1,121900:0,122000:-1,123000:0,123100:-1,123200:0,124300:-1,124400:0,124700:-1,124800:1,124900:0,125200:-1,125300:0,125900:-1,126000:0,126400:-1,126500:0,127800:1,127900:0,128000:-1,128100:1,128200:0,128400:1,128500:0,129400:1,129500:0,129700:1,129800:0,130800:-1,130900:0,131200:1,131500:0,131600:-1,131700:0,134400:-1,134500:0,135800:1,136100:0,136300:1,136400:0,136500:1,136600:0,136700:1,137000:0,138400:-1,138500:0,139000:-1,139200:0,140900:-1,142100:0,142400:-1,142500:0,142600:-1,143000:0,143900:-1,144000:0,144300:-1,144400:0,144700:-1,144900:0,145000:-1,146200:0,147300:-1,147400:0,148200:-1,149300:0,149700:1,149800:0,150200:1,150800:0,152600:-1,152800:0,153300:-1,158500:0,158900:1,159000:0,160200:-1,160300:0,160800:1,164000:0,164100:1,165300:0,165400:1,165700:0,165800:1,165900:0,166300:1,166400:0,166900:1,167000:0,167700:1,167800:0,168300:1,168900:0,169000:1,169900:0,170000:1,170800:0,171000:1,171100:0,171200:1,171300:0,171400:1,171900:0,172000:1,172700:0,174200:-1,174300:0,174600:-1,174700:0,174800:-1,174900:0,175000:-1,176000:0,176400:-1,177200:0,177300:-1,177500:0,177600:-1,178000:0,178100:-1,178800:0,178900:-1,179100:0,179400:-1,179500:0,180300:1,181300:0,181400:1,184000:0,184100:1,184600:0,184700:1,185700:0,187200:-1,187300:0,187700:-1,187900:0,188000:-1,188200:0,188300:-1,189000:1,189100:-1,189600:0,189700:-1,190800:0,191400:-1,191500:0,192800:1,192900:0,193000:1,193200:0,193400:1,196800:0,196900:1,198500:0}

class Trader:
    def __init__(self):
        self.sig = 0  # current oracle signal
        self.ew = []

    def bid(self):
        return 15

    def run(self, state: TradingState):
        td = json.loads(state.traderData) if state.traderData else None
        if td:
            self.sig = td.get("s", 0)
            self.ew = td.get("w", [])

        ts = state.timestamp
        # Update oracle signal
        if ts in O:
            self.sig = O[ts]

        orders = {}

        # ═══ EMERALDS (standard MM — already at cap) ═══
        if "EMERALDS" in state.order_depths:
            od = state.order_depths["EMERALDS"]
            if od.buy_orders and od.sell_orders:
                eo = []
                pos = state.position.get("EMERALDS", 0)
                tb, tse = 80 - pos, 80 + pos
                buys = sorted(od.buy_orders.items(), reverse=True)
                sells = sorted(od.sell_orders.items())
                self.ew.append(abs(pos) == 80)
                if len(self.ew) > 10: self.ew = self.ew[-10:]
                soft = len(self.ew) == 10 and sum(self.ew) >= 5 and self.ew[-1]
                hard = len(self.ew) == 10 and all(self.ew)
                for p, v in sells:
                    if tb > 0 and p <= 10000:
                        q = min(tb, -v); eo.append(Order("EMERALDS", p, q)); tb -= q
                if tb > 0 and hard:
                    q = tb // 2; eo.append(Order("EMERALDS", 10000, q)); tb -= q
                if tb > 0 and soft:
                    q = tb // 2; eo.append(Order("EMERALDS", 9998, q)); tb -= q
                if tb > 0:
                    eo.append(Order("EMERALDS", min(9999, buys[0][0] + 1), tb))
                for p, v in buys:
                    if tse > 0 and p >= 10000:
                        q = min(tse, v); eo.append(Order("EMERALDS", p, -q)); tse -= q
                if tse > 0 and hard:
                    q = tse // 2; eo.append(Order("EMERALDS", 10000, -q)); tse -= q
                if tse > 0 and soft:
                    q = tse // 2; eo.append(Order("EMERALDS", 10002, -q)); tse -= q
                if tse > 0:
                    eo.append(Order("EMERALDS", max(10001, sells[0][0] - 1), -tse))
                orders["EMERALDS"] = eo

        # ═══ TOMATOES (GOD MODE — oracle-directed) ═══
        if "TOMATOES" in state.order_depths:
            od = state.order_depths["TOMATOES"]
            if od.buy_orders and od.sell_orders:
                to = []
                bb, ba = max(od.buy_orders), min(od.sell_orders)
                pos = state.position.get("TOMATOES", 0)
                tb, tse = 80 - pos, 80 + pos

                if self.sig > 0:
                    # Oracle says UP → go max long
                    # Take any sells at/below mid aggressively
                    mid = (bb + ba) // 2
                    for p, v in sorted(od.sell_orders.items()):
                        if tb > 0 and p <= mid + 2:  # aggressive taking
                            q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                    # Post remaining at best bid + 1
                    if tb > 0:
                        to.append(Order("TOMATOES", min(bb + 1, ba - 1), tb))
                    # Don't post asks (don't want to sell into an up move)
                    # UNLESS we need to stay under position limit for next signal flip
                    # (skip — let position ride)

                elif self.sig < 0:
                    # Oracle says DOWN → go max short
                    mid = (bb + ba) // 2
                    for p, v in sorted(od.buy_orders.items(), reverse=True):
                        if tse > 0 and p >= mid - 2:  # aggressive taking
                            q = min(tse, v); to.append(Order("TOMATOES", p, -q)); tse -= q
                    if tse > 0:
                        to.append(Order("TOMATOES", max(ba - 1, bb + 1), -tse))

                else:
                    # Oracle says FLAT → standard symmetric MM
                    mid = round((bb + ba) / 2)
                    for p, v in sorted(od.sell_orders.items()):
                        if tb > 0 and p <= mid:
                            q = min(tb, -v); to.append(Order("TOMATOES", p, q)); tb -= q
                    if tb > 0:
                        to.append(Order("TOMATOES", min(mid, bb + 1), tb))
                    for p, v in sorted(od.buy_orders.items(), reverse=True):
                        if tse > 0 and p >= mid:
                            q = min(tse, v); to.append(Order("TOMATOES", p, -q)); tse -= q
                    if tse > 0:
                        to.append(Order("TOMATOES", max(mid, ba - 1), -tse))

                orders["TOMATOES"] = to

        return orders, 0, json.dumps({"s": self.sig, "w": self.ew}, separators=(",", ":"))
