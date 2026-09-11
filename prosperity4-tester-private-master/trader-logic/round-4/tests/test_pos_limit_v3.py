"""Position-limit tail-risk test for r4_final_v3.

Simulates extreme position scenarios and verifies no submitted-order set
violates IMC's per-product all-or-nothing limit:
    pos + sum(buys) <= LIMIT  AND  pos - sum(sells) >= -LIMIT

If ANY product fails, IMC rejects ALL its orders that tick.
"""
import os
import sys
import importlib.util

ROOT = r"C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester"
sys.path.insert(0, os.path.join(ROOT, "prosperity4bt"))

from datamodel import Order, OrderDepth, TradingState, Listing


def _load(path: str):
    spec = importlib.util.spec_from_file_location("trader_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_od(bids, asks):
    od = OrderDepth()
    od.buy_orders = dict(bids)
    od.sell_orders = {p: -v for p, v in asks.items()}
    return od


def make_state(positions, depths, ts=0, traderData=""):
    listings = {sym: Listing(sym, sym, "SEASHELLS") for sym in depths}
    return TradingState(
        traderData=traderData,
        timestamp=ts,
        listings=listings,
        order_depths=depths,
        own_trades={s: [] for s in depths},
        market_trades={s: [] for s in depths},
        position=dict(positions),
        observations=type("Obs", (), {"plainValueObservations": {}, "conversionObservations": {}})(),
    )


def check_limits(orders_by_sym, positions, limits, label):
    fails = []
    for sym, ords in orders_by_sym.items():
        pos = positions.get(sym, 0)
        lim = limits.get(sym, 999)
        bsum = sum(o.quantity for o in ords if o.quantity > 0)
        ssum = sum(-o.quantity for o in ords if o.quantity < 0)
        if pos + bsum > lim:
            fails.append((sym, "BUY_OVERFLOW", pos, bsum, lim, [(o.price, o.quantity) for o in ords]))
        if pos - ssum < -lim:
            fails.append((sym, "SELL_OVERFLOW", pos, ssum, lim, [(o.price, o.quantity) for o in ords]))
    if fails:
        print(f"FAIL [{label}]: {len(fails)} violations")
        for f in fails:
            print("  ", f)
    return fails


def main():
    mod = _load(os.path.join(ROOT, "trader-logic/round-4/r4_final_v3.py"))
    Trader = mod.Trader

    LIMITS = {
        "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
        **{f"VEV_{k}": 300 for k in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]},
    }

    # Standard depth pieces (varies by product type)
    hp_od = make_od({9990: 30, 9989: 50}, {10007: 30, 10008: 50})  # spread 17, mid 9998.5
    hp_od_high = make_od({10015: 30}, {10032: 30})                  # spread 17 mid 10023
    vfe_od = make_od({5275: 25, 5274: 30}, {5277: 25, 5278: 30})    # spread 2

    voucher_depths = {}
    spot = 5276
    for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]:
        intr = max(spot - K, 0)
        # Reasonable ITM/OTM book
        if intr > 0:
            voucher_depths[f"VEV_{K}"] = make_od({int(intr) - 1: 50}, {int(intr) + 5: 50})
        else:
            voucher_depths[f"VEV_{K}"] = make_od({1: 100}, {3: 100})

    # ── Test 1: HP at -200 short, S17 setup ──────────────────────────────────
    depths = {"HYDROGEL_PACK": hp_od_high, "VELVETFRUIT_EXTRACT": vfe_od, **voucher_depths}
    pos = {"HYDROGEL_PACK": -200}
    t = Trader()
    o, _, td = t.run(make_state(pos, depths, ts=0))
    fails1 = check_limits(o, pos, LIMITS, "HP_at_-200_S17")

    # ── Test 2: HP at +200 long, attempt S17 entry ───────────────────────────
    pos = {"HYDROGEL_PACK": 200}
    t = Trader()
    o, _, td = t.run(make_state(pos, depths, ts=0))
    fails2 = check_limits(o, pos, LIMITS, "HP_at_+200")

    # ── Test 3: VFE at -200 short, momo signals exit + Layer E buy ───────────
    # First warm up with traderData so momo_short_entry fires.
    pos = {"VELVETFRUIT_EXTRACT": -200}
    # Use ba<prev_ap1 so layer E spread==2 buy fires.
    vfe_od_e = make_od({5275: 25}, {5276: 25})  # spread 1 → won't trigger E (need spread==2)
    vfe_od_eb = make_od({5275: 25}, {5277: 25}) # spread 2 → E buy if ba dropped
    # Pre-seed traderData with prev_ap1=5278 (so 5277 < 5278 fires E buy)
    # Pre-seed momo short entry at 5290 (so MTM positive → cover triggered)
    import json as _json
    td_seed = _json.dumps({
        "v9": {
            "p_ap": 5278, "p_bp": 5275,
            "vfe_momo_buf": [5290.0] * 60,
            "vfe_momo_short_entry": 5290.0, "vfe_momo_fired": True,
        }
    })
    depths = {"HYDROGEL_PACK": hp_od, "VELVETFRUIT_EXTRACT": vfe_od_eb, **voucher_depths}
    o, _, td = Trader().run(make_state(pos, depths, ts=1000, traderData=td_seed))
    fails3 = check_limits(o, pos, LIMITS, "VFE_-200_momo_cover_+_layerE_buy")

    # ── Test 4: VFE at +200, layer E sell + (no momo since fired and no entry path open) ─
    pos = {"VELVETFRUIT_EXTRACT": 200}
    vfe_od_es = make_od({5277: 25}, {5280: 25})  # spread 3 → E sell if bp1 raised
    td_seed4 = _json.dumps({
        "v9": {"p_ap": 5278, "p_bp": 5275, "vfe_momo_buf": [], "vfe_momo_fired": True}
    })
    depths = {"HYDROGEL_PACK": hp_od, "VELVETFRUIT_EXTRACT": vfe_od_es, **voucher_depths}
    o, _, td = Trader().run(make_state(pos, depths, ts=1000, traderData=td_seed4))
    fails4 = check_limits(o, pos, LIMITS, "VFE_+200_layerE_sell")

    # ── Test 5: Voucher VEV_5200 at +300 (max long), with strong BS taking pull ──
    # spot well above strike 5200 → BS buy edge active.
    pos = {f"VEV_{K}": 300 for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]}
    depths = {"HYDROGEL_PACK": hp_od, "VELVETFRUIT_EXTRACT": vfe_od, **voucher_depths}
    o, _, td = Trader().run(make_state(pos, depths, ts=0))
    fails5 = check_limits(o, pos, LIMITS, "all_vouchers_+300")

    # ── Test 6: All vouchers at -300 ──────────────────────────────────────────
    pos = {f"VEV_{K}": -300 for K in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]}
    o, _, td = Trader().run(make_state(pos, depths, ts=0))
    fails6 = check_limits(o, pos, LIMITS, "all_vouchers_-300")

    # ── Test 7: Bunch of mixed near-limit positions everything-on ────────────
    pos = {"HYDROGEL_PACK": -195, "VELVETFRUIT_EXTRACT": -180,
           "VEV_4000": 290, "VEV_4500": 290,
           "VEV_5000": -290, "VEV_5100": -290, "VEV_5200": -290,
           "VEV_5300": 290, "VEV_5400": 290, "VEV_5500": 290,
           "VEV_6000": 290, "VEV_6500": 290}
    depths = {"HYDROGEL_PACK": hp_od_high, "VELVETFRUIT_EXTRACT": vfe_od_eb, **voucher_depths}
    o, _, td = Trader().run(make_state(pos, depths, ts=2000, traderData=td_seed))
    fails7 = check_limits(o, pos, LIMITS, "mixed_near_limit_full_stack")

    # ── Test 8: HP at -180, z>2.25 → directional short (z-block fires) ──────
    # Need 500-tick history. Seed mid_buf_500 with low values then current high.
    pos = {"HYDROGEL_PACK": -180}
    td_seed_z = _json.dumps({
        "hg": {
            "buf500": [9990.0] * 500, "buf100": [9990.0] * 100,
            "row": 500, "edgeb": [], "retb": [],
        }
    })
    depths = {"HYDROGEL_PACK": hp_od_high, "VELVETFRUIT_EXTRACT": vfe_od, **voucher_depths}
    o, _, td = Trader().run(make_state(pos, depths, ts=50000, traderData=td_seed_z))
    fails8 = check_limits(o, pos, LIMITS, "HP_-180_z_short_signal")

    all_fails = fails1 + fails2 + fails3 + fails4 + fails5 + fails6 + fails7 + fails8
    print()
    if all_fails:
        print(f"TOTAL: {len(all_fails)} violations across {sum(1 for f in [fails1,fails2,fails3,fails4,fails5,fails6,fails7,fails8] if f)} test cases")
        sys.exit(1)
    else:
        print("ALL 8 TESTS PASS — no position-limit overflows detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
