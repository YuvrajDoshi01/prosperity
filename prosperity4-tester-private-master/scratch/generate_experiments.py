import re
import os

BASE_FILE = "/home/mmaliar/prosperity4-tester-private/trader-logic/round-3/408576.py"
OUT_DIR = "/home/mmaliar/prosperity4-tester-private/trader-logic/round-3"

def extract_base_code():
    with open(BASE_FILE, "r") as f:
        content = f.read()
    
    # Split the file right before run_vouchers definition
    part1, rest = content.split("def run_vouchers(state, vstate):", 1)
    
    # Find the end of run_vouchers, which is right before Trader class
    # Actually it's right before '# ── v11 Trader'
    run_vouchers_body, part2 = rest.split("# ── v11 Trader", 1)
    
    # Turn off hydrogel by commenting out the execution assignment
    part2 = part2.replace('orders[Product.HYDROGEL_PACK] = hydrogel_orders', '# orders[Product.HYDROGEL_PACK] = hydrogel_orders  # Turned off by user request')
    
    # We will replace run_vouchers body with our custom one
    return part1, "# ── v11 Trader" + part2

part1, part2 = extract_base_code()

def write_experiment(filename, logic_body):
    full_code = part1 + "def run_vouchers(state, vstate):\n    orders = {}\n    timestamp = state.timestamp\n" + logic_body + "\n    return orders\n\n\n\n\n" + part2
    with open(os.path.join(OUT_DIR, filename), "w") as f:
        f.write(full_code)

# Exp 1: Butterfly Arb
exp1_logic = """
    for mid_k in [5100, 5200, 5300, 5400]:
        lo_k = mid_k - 100
        hi_k = mid_k + 100
        sym_lo = f"VEV_{lo_k}"
        sym_mid = f"VEV_{mid_k}"
        sym_hi = f"VEV_{hi_k}"
        
        od_lo = state.order_depths.get(sym_lo)
        od_mid = state.order_depths.get(sym_mid)
        od_hi = state.order_depths.get(sym_hi)
        
        if not (od_lo and od_hi and od_mid): continue
        if not (od_lo.sell_orders and od_hi.sell_orders and od_mid.buy_orders): continue
        
        ask_lo = min(od_lo.sell_orders.keys())
        ask_hi = min(od_hi.sell_orders.keys())
        bid_mid = max(od_mid.buy_orders.keys())
        
        # Cost of butterfly = ask_lo + ask_hi - 2 * bid_mid
        cost = ask_lo + ask_hi - 2 * bid_mid
        if cost < -1:  # If negative cost, we arbitage
            qty = 5
            orders[sym_lo] = [Order(sym_lo, ask_lo, qty)]
            orders[sym_hi] = [Order(sym_hi, ask_hi, qty)]
            orders[sym_mid] = [Order(sym_mid, bid_mid, -2 * qty)]
"""
write_experiment("exp1_butterfly_arb.py", exp1_logic)

# Exp 2: Vertical Monotonicity Arb
exp2_logic = """
    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    for i in range(len(strikes) - 1):
        k1 = strikes[i]
        k2 = strikes[i+1]
        sym1 = f"VEV_{k1}"
        sym2 = f"VEV_{k2}"
        
        od1 = state.order_depths.get(sym1)
        od2 = state.order_depths.get(sym2)
        
        if not (od1 and od2): continue
        if not (od1.buy_orders and od2.sell_orders): continue
        
        bid1 = max(od1.buy_orders.keys())
        ask2 = min(od2.sell_orders.keys())
        
        # Call price must decrease with strike. If C(K2) > C(K1), sell K2 buy K1
        if ask2 < bid1:  # Arb! The higher strike is cheaper than the lower strike bid
            qty = 10
            orders[sym2] = [Order(sym2, ask2, qty)]
            orders[sym1] = [Order(sym1, bid1, -qty)]
"""
write_experiment("exp2_vertical_monotonicity.py", exp2_logic)

# Exp 3: Delta Momentum
exp3_logic = """
    ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    if ve and ve.buy_orders and ve.sell_orders:
        mid_ve = (max(ve.buy_orders.keys()) + min(ve.sell_orders.keys())) / 2
        prev_mid = vstate.last_spot if vstate.last_spot else mid_ve
        
        if mid_ve - prev_mid > 2: # price jumped
            # aggressive buy VEV_5100 and VEV_5200
            for k in [5100, 5200]:
                sym = f"VEV_{k}"
                od = state.order_depths.get(sym)
                if od and od.sell_orders:
                    ask = min(od.sell_orders.keys())
                    orders[sym] = [Order(sym, ask, 10)]
        elif prev_mid - mid_ve > 2: # price dropped
            # aggressive sell VEV_5100 and VEV_5200
            for k in [5100, 5200]:
                sym = f"VEV_{k}"
                od = state.order_depths.get(sym)
                if od and od.buy_orders:
                    bid = max(od.buy_orders.keys())
                    orders[sym] = [Order(sym, bid, -10)]
        
        vstate.last_spot = mid_ve
"""
write_experiment("exp3_delta_momo.py", exp3_logic)

# Exp 4: Pure Intrinsic Arb
exp4_logic = """
    ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    if ve and ve.buy_orders and ve.sell_orders:
        mid_ve = (max(ve.buy_orders.keys()) + min(ve.sell_orders.keys())) / 2
        for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500]:
            sym = f"VEV_{k}"
            intrinsic = max(0, mid_ve - k)
            if intrinsic <= 0: continue
            
            od = state.order_depths.get(sym)
            if od and od.sell_orders:
                ask = min(od.sell_orders.keys())
                if ask < intrinsic - 0.5: # Hardcoded slightly below intrinsic
                    orders[sym] = [Order(sym, ask, 30)]  # take it all
            
            if od and od.buy_orders:
                bid = max(od.buy_orders.keys())
                if bid > mid_ve + 0.5: # Option price bounded by stock price
                    orders[sym] = [Order(sym, bid, -30)]
"""
write_experiment("exp4_pure_intrinsic.py", exp4_logic)

# Exp 5: Skew Reversion
exp5_logic = """
    # Dumb implementation: blindly sell IV rank > ATM
    ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    od_5000 = state.order_depths.get("VEV_5000")
    od_6500 = state.order_depths.get("VEV_6500")
    
    if od_5000 and od_6500 and ve:
        if od_5000.sell_orders and od_6500.buy_orders:
            ask_5000 = min(od_5000.sell_orders.keys())
            bid_6500 = max(od_6500.buy_orders.keys())
            
            # Simple threshold: if 6500 is bought > 200, it's way historically overvalued while OTM
            if bid_6500 > 150:
                orders["VEV_6500"] = [Order("VEV_6500", bid_6500, -10)]
                orders["VEV_5000"] = [Order("VEV_5000", ask_5000, 10)]
"""
write_experiment("exp5_skew_reversion.py", exp5_logic)

# Exp 6: Dumb wide-spread MM
exp6_logic = """
    strikes = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
    for k in strikes:
        sym = f"VEV_{k}"
        od = state.order_depths.get(sym)
        if od and od.buy_orders and od.sell_orders:
            bid = max(od.buy_orders.keys())
            ask = min(od.sell_orders.keys())
            spread = ask - bid
            
            if spread > 4: # Wide spread, jump in
                my_bid = bid + 1
                my_ask = ask - 1
                orders[sym] = [Order(sym, my_bid, 15), Order(sym, my_ask, -15)]
"""
write_experiment("exp6_dumb_mm.py", exp6_logic)

# Exp 7: OBI Skewed MM (VEV_5400)
exp7_logic = """
    sym = "VEV_5400"
    od = state.order_depths.get(sym)
    ve = state.order_depths.get("VELVETFRUIT_EXTRACT")
    
    if od and od.buy_orders and od.sell_orders and ve and ve.buy_orders and ve.sell_orders:
        bid = max(od.buy_orders.keys())
        ask = min(od.sell_orders.keys())
        
        # Calculate OBI on VELVETFRUIT
        ve_bid = max(ve.buy_orders.keys())
        ve_ask = min(ve.sell_orders.keys())
        bv = sum(ve.buy_orders.values()) 
        av = abs(sum(ve.sell_orders.values())) 
        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0
        
        # Default MM quotes
        my_bid = bid + 1 if spread > 1 else bid
        my_ask = ask - 1 if spread > 1 else ask
        
        # If order book strongly predicts a direction, skew aggressively
        if obi > 0.4: # Extreme buy pressure -> price likely going up -> don't sell, buy aggressively
            my_ask = ask + 5 # pull ask way back
            my_bid = min(ask - 1, bid + 1)
        elif obi < -0.4: # Extreme sell pressure -> price likely going down -> don't buy, sell aggressively
            my_bid = bid - 5 # pull bid way back
            my_ask = max(bid + 1, ask - 1)
            
        pos = state.position.get(sym, 0)
        bid_qty = min(30, 300 - pos)
        ask_qty = min(30, 300 + pos)
        
        o_list = []
        if bid_qty > 0 and my_bid > 0: o_list.append(Order(sym, my_bid, bid_qty))
        if ask_qty > 0 and my_ask > 0: o_list.append(Order(sym, my_ask, -ask_qty))
        if o_list: orders[sym] = o_list
"""
# Fix undefined variable `spread` in the string
exp7_logic = exp7_logic.replace("spread > 1", "(ask - bid) > 1")
write_experiment("exp7_obi_mm.py", exp7_logic)

print("Generated 7 experiment files with Hydrogel turned off in trader-logic/round-3/")
