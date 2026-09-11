"""Compute DP-optimal HP and VFE position paths for day-2 first 1000 ticks.

Output: target_hp[chunk] and target_vfe[chunk] arrays where chunk = tick // 25.
Each target ∈ {-pos_lim, ..., +pos_lim} in 25-step grid for HP (LIMIT 200 → 17 nodes),
and {-pos_lim, ..., +pos_lim} in 25-step grid for VFE.

PnL model per chunk: position × (mid[end] - mid[start]) - crossing_cost × |Δpos|
where crossing_cost = spread/2 (typical: HP spread 16, VFE spread 5).
"""
import csv
from pathlib import Path

CSV = Path(r"C:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\prosperity4bt\resources\round3\prices_round_3_day_2.csv")

HP_SYM = "HYDROGEL_PACK"
VFE_SYM = "VELVETFRUIT_EXTRACT"

# Read mids per timestamp
hp_mids = {}
vfe_mids = {}
hp_spreads = {}
vfe_spreads = {}
with open(CSV) as f:
    reader = csv.DictReader(f, delimiter=";")
    for row in reader:
        ts = int(row["timestamp"])
        prod = row["product"]
        mid = float(row["mid_price"])
        # spread = best_ask - best_bid
        try:
            bb = float(row["bid_price_1"])
            ba = float(row["ask_price_1"])
            spread = ba - bb
        except Exception:
            spread = 1.0
        if prod == HP_SYM:
            hp_mids[ts] = mid
            hp_spreads[ts] = spread
        elif prod == VFE_SYM:
            vfe_mids[ts] = mid
            vfe_spreads[ts] = spread

# Limit to first 1000 ticks (timestamps 0..99900 step 100)
ts_list = sorted(hp_mids.keys())[:1000]
print(f"First 5 HP mids: {[hp_mids[t] for t in ts_list[:5]]}")
print(f"First 5 VFE mids: {[vfe_mids[t] for t in ts_list[:5]]}")
print(f"HP mid range over 1k: min={min(hp_mids[t] for t in ts_list):.1f} max={max(hp_mids[t] for t in ts_list):.1f}")
print(f"VFE mid range over 1k: min={min(vfe_mids[t] for t in ts_list):.1f} max={max(vfe_mids[t] for t in ts_list):.1f}")

# DP setup: 1000 ticks → 40 chunks of 25 ticks each
CHUNK = 25
N_CHUNKS = 1000 // CHUNK  # 40
LIMIT = 200
POS_GRID = list(range(-LIMIT, LIMIT + 1, 25))  # 17 nodes: -200, -175, ..., +200

def compute_dp(mids: dict, spreads: dict, ts_list: list) -> tuple[list[int], float]:
    """Returns target_per_chunk[N_CHUNKS+1] and total optimal PnL.
    target_per_chunk[i] = position to hold from chunk i to chunk i+1.
    Crossing cost is spread at the chunk-boundary tick.
    """
    n_pos = len(POS_GRID)
    # dp[chunk][pos_idx] = max PnL achievable from chunk onwards starting at this position
    INF = float('-inf')
    dp = [[INF] * n_pos for _ in range(N_CHUNKS + 1)]
    parent = [[0] * n_pos for _ in range(N_CHUNKS + 1)]
    # Terminal: at chunk N_CHUNKS, must flatten (transition to position 0)
    # Cost = |pos| * spread/2
    last_ts = ts_list[N_CHUNKS * CHUNK - 1] if N_CHUNKS * CHUNK <= len(ts_list) else ts_list[-1]
    last_spread = spreads.get(last_ts, 1.0)
    for i, p in enumerate(POS_GRID):
        dp[N_CHUNKS][i] = -abs(p) * last_spread / 2.0  # cost to flatten

    for chunk in range(N_CHUNKS - 1, -1, -1):
        chunk_start_ts = ts_list[chunk * CHUNK]
        chunk_end_idx = (chunk + 1) * CHUNK - 1
        if chunk_end_idx >= len(ts_list):
            chunk_end_idx = len(ts_list) - 1
        chunk_end_ts = ts_list[chunk_end_idx]
        mid_start = mids[chunk_start_ts]
        mid_end = mids[chunk_end_ts]
        delta_mid = mid_end - mid_start
        spread_at_end = spreads.get(chunk_end_ts, 1.0)
        for i, p in enumerate(POS_GRID):
            # Hold position p through this chunk → PnL = p * delta_mid
            hold_pnl = p * delta_mid
            # Choose best next position (transition at end of chunk)
            best = INF
            best_next = 0
            for j, p_next in enumerate(POS_GRID):
                cost = abs(p_next - p) * spread_at_end / 2.0
                v = hold_pnl - cost + dp[chunk + 1][j]
                if v > best:
                    best = v
                    best_next = j
            dp[chunk][i] = best
            parent[chunk][i] = best_next

    # Reconstruct: start at position 0
    start_idx = POS_GRID.index(0)
    targets = [0]
    cur = start_idx
    for chunk in range(N_CHUNKS):
        nxt = parent[chunk][cur]
        targets.append(POS_GRID[nxt])
        cur = nxt
    return targets, dp[0][start_idx]

print("\n=== HP DP-optimal ===")
hp_targets, hp_pnl = compute_dp(hp_mids, hp_spreads, ts_list)
print(f"Optimal PnL (with spread crossing cost): ${hp_pnl:.0f}")
print(f"Targets per chunk (first 41 = positions held during ticks 0-25, 25-50, ...):")
print(hp_targets)

print("\n=== VFE DP-optimal ===")
vfe_targets, vfe_pnl = compute_dp(vfe_mids, vfe_spreads, ts_list)
print(f"Optimal PnL (with spread crossing cost): ${vfe_pnl:.0f}")
print(f"Targets:")
print(vfe_targets)

# Output as Python lists for embedding
print("\n=== Embed in v27 ===")
print(f"HP_DP_TARGETS = {hp_targets}")
print(f"VFE_DP_TARGETS = {vfe_targets}")
print(f"# Chunk size: {CHUNK} ticks; N chunks: {N_CHUNKS}")
print(f"# Total expected PnL (1k window): HP=${hp_pnl:.0f} + VFE=${vfe_pnl:.0f} = ${hp_pnl + vfe_pnl:.0f}")
