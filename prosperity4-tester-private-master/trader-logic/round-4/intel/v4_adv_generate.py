"""Synthetic R4 day-4 generator (block-bootstrap from real days 1/2/3).

For seed S and batch B in [0..N//14):
  - Bootstrap 10 blocks of 1000 ticks each from concatenated days 1/2/3 (30k ticks).
  - For each tick, take the *whole* per-product cross-section (all 12 products) so
    cross-product correlations are preserved within a block.
  - Re-stamp timestamps to 0..999900 (step 100).
  - Carry over `day` field as 1/2/3 (cosmetic — engine ignores).
  - Write synthetic day to prosperity4bt/resources/round99/prices_round_99_day_{batch}.csv
    and trades_round_99_day_{batch}.csv (using the matching real-trade slices).

Adversarial knobs (off by default; toggle via env or args):
  --vfe-shock M     additive constant shifted into VFE mid (e.g. -100 for crash).
  --hp-mute        downscale HP S17 frequency (drop S17-spread blocks).
  --no-spread17    hard-zero all S17 events in HP.
  --noise-bp B      add basis-point gaussian noise to mid for each product.

Usage:
  python intel/v4_adv_generate.py --seed 42 --batch 0
"""

import argparse
import random
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "prosperity4bt" / "resources" / "round4"
OUT = REPO / "prosperity4bt" / "resources" / "round99"
OUT.mkdir(parents=True, exist_ok=True)

PRODUCTS = [
    "HYDROGEL_PACK", "VELVETFRUIT_EXTRACT",
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200",
    "VEV_5300", "VEV_5400", "VEV_5500", "VEV_6000", "VEV_6500",
]

TICKS = 10_000
BLOCK = 1000  # tick block size
N_BLOCKS = TICKS // BLOCK


def load_real():
    prices = []
    trades = []
    for d in (1, 2, 3):
        prices.append(pd.read_csv(SRC / f"prices_round_4_day_{d}.csv", sep=";"))
        trades.append(pd.read_csv(SRC / f"trades_round_4_day_{d}.csv", sep=";"))
    return prices, trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--batch", type=int, required=True, help="round99 day index 0..13")
    ap.add_argument("--vfe-shock", type=float, default=0.0)
    ap.add_argument("--hp-mute", action="store_true")
    ap.add_argument("--no-spread17", action="store_true")
    ap.add_argument("--noise", type=float, default=0.0)
    args = ap.parse_args()

    rng = random.Random(args.seed * 1000 + args.batch)
    prices, trades = load_real()

    # Pool of (day_idx, start_tick) candidates. Each block is BLOCK contiguous ticks.
    pool = []
    for di in range(3):
        max_start = 10_000 - BLOCK
        for s in range(0, max_start, 50):  # stride 50 ticks
            pool.append((di, s))

    chosen = [rng.choice(pool) for _ in range(N_BLOCKS)]

    out_p_rows = []
    out_t_rows = []
    out_tick_idx = 0
    for (di, start) in chosen:
        df_p = prices[di]
        df_t = trades[di]
        # Block ticks: start..start+BLOCK
        ts_lo = start * 100
        ts_hi = (start + BLOCK) * 100
        block_p = df_p[(df_p.timestamp >= ts_lo) & (df_p.timestamp < ts_hi)].copy()
        block_t = df_t[(df_t.timestamp >= ts_lo) & (df_t.timestamp < ts_hi)].copy()

        # Re-stamp timestamps
        offset = (out_tick_idx * 100) - ts_lo
        block_p["timestamp"] = block_p["timestamp"] + offset
        block_t["timestamp"] = block_t["timestamp"] + offset
        block_p["day"] = 1  # uniform

        # Adversarial transforms
        if args.hp_mute:
            # Replace HP rows with low-spread version: tighten artificially
            mask = block_p["product"] == "HYDROGEL_PACK"
            spread = block_p.loc[mask, "ask_price_1"] - block_p.loc[mask, "bid_price_1"]
            heavy = spread >= 17
            # For heavy-spread rows, shrink to spread 16 by widening bid +1
            block_p.loc[mask & heavy.reindex(block_p.index, fill_value=False), "bid_price_1"] += 1
        if args.no_spread17:
            mask = block_p["product"] == "HYDROGEL_PACK"
            spread = block_p.loc[mask, "ask_price_1"] - block_p.loc[mask, "bid_price_1"]
            heavy = (spread == 17)
            idx = block_p.loc[mask].index[heavy.values]
            block_p.loc[idx, "bid_price_1"] += 1  # shrink to 16
        if args.vfe_shock != 0.0:
            for p in ["VELVETFRUIT_EXTRACT"]:
                mask = block_p["product"] == p
                for col in ["bid_price_1", "bid_price_2", "bid_price_3",
                            "ask_price_1", "ask_price_2", "ask_price_3", "mid_price"]:
                    block_p.loc[mask, col] = block_p.loc[mask, col] + args.vfe_shock
        if args.noise > 0.0:
            for p in PRODUCTS:
                mask = block_p["product"] == p
                # Per-product gaussian shock applied identically to bids/asks (preserves spread)
                shocks = [rng.gauss(0, args.noise) for _ in range(mask.sum())]
                shocks = pd.Series(shocks, index=block_p.loc[mask].index)
                for col in ["bid_price_1", "bid_price_2", "bid_price_3",
                            "ask_price_1", "ask_price_2", "ask_price_3", "mid_price"]:
                    block_p.loc[mask, col] = block_p.loc[mask, col] + shocks

        out_p_rows.append(block_p)
        out_t_rows.append(block_t)
        out_tick_idx += BLOCK

    out_p = pd.concat(out_p_rows, ignore_index=True)
    out_t = pd.concat(out_t_rows, ignore_index=True)

    # Coerce price/volume cols to int (engine requires int).
    int_cols = [c for c in out_p.columns
                if c.startswith(("bid_price", "bid_volume", "ask_price", "ask_volume"))]
    for c in int_cols:
        out_p[c] = pd.to_numeric(out_p[c], errors="coerce").round().astype("Int64")
    out_p["mid_price"] = pd.to_numeric(out_p["mid_price"], errors="coerce").round(1)

    # Sort by (timestamp, product) for safety
    out_p = out_p.sort_values(["timestamp", "product"]).reset_index(drop=True)
    out_t = out_t.sort_values(["timestamp"]).reset_index(drop=True)

    pp = OUT / f"prices_round_99_day_{args.batch}.csv"
    tp = OUT / f"trades_round_99_day_{args.batch}.csv"
    out_p.to_csv(pp, sep=";", index=False)
    out_t.to_csv(tp, sep=";", index=False)
    print(f"wrote {pp.name} ({len(out_p)} rows) {tp.name} ({len(out_t)} rows) | seed={args.seed} batch={args.batch}")


if __name__ == "__main__":
    main()
