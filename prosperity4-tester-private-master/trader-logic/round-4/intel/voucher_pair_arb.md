# Voucher-Pair Stat Arb — R4 (30k ticks, days 1-3)

**Verdict: NO displayed-quote arb across 10 strikes. Do NOT scale `V_ARB_SIZE`. Drop the call-spread arb scanner — it is dead code.**

## 1. Vertical spread (ask_lo − bid_hi)
Across all 45 (K_lo, K_hi) pairs × 30,000 ticks: **0 violations.** Minimum edge is the closest pair:

| Pair | min edge | p1 | median |
|---|---:|---:|---:|
| 5400/5500 | 4 | 4 | 9 |
| 5500/6000 | 1 | 2 | 5 |
| 6000/6500 | 1 | 1 | 1 |
| 5000/4500 | 494 | 501 | 508 |

Market makers post their L1 with ≥1 tick of convexity slack everywhere. `V_ARB_SIZE` in `r4_final_v2.py` will never trigger on top of book.

## 2. Butterfly / convexity (long w1·K1 − 1·K2 + w3·K3, payoff ≥ 0)
All 120 ordered triples × 30k ticks: **0 violations.** Tightest:

| K1/K2/K3 | min cost | p1 | median |
|---|---:|---:|---:|
| 5500/6000/6500 | +1.0 | +1.5 | +3.0 |
| 5400/5500/6000 | +3.3 | +3.5 | +7.2 |
| 4500/5000/5100 | +6.0 | +9.8 | +13.5 |

Convexity holds with ≥1 tick of margin even in the tightest deep-OTM region.

## 3. Smile / forward-vol kinks
Mid-price monotonicity violations (C(K_lo) < C(K_hi)): **0 across all 45 pairs.** Forward-implied vol is smooth — voucher_alpha was right that the smile is flat; it is also internally consistent (no exploitable kink).

## 4. Capacity
L1 displayed sizes (median bid+ask, voucher limit 300):
- Deep ITM (4000/4500/5000): 9-11 contracts each side
- ATM (5100-5500): 22-25
- Far OTM (6000/6500): 13-22

Even if a 1-tick edge appeared, max round-trip ≈ min(L1_lo, L1_hi) ≈ 9 contracts × 1 tick = $9 per opportunity. Per-pair edge frequency is 0%, so expected PnL = $0.

## 5. Recommendation

1. **Remove `V_ARB_SIZE=10` call-spread scanner from `r4_final_v2.py`.** Zero hits in 30k ticks → no live PnL, only adds latency + a non-zero crash risk on stale-book ghost arbs.
2. **Do NOT add butterfly detection.** Same negative result, larger surface area for bugs (3-leg execution, fractional weights round to integers and break payoff non-negativity).
3. **Reallocate the slot.** If we want voucher PnL, the post-mortem (`memory/project_round3_final_postmortem.md`) flagged delta-hedged voucher MM as the missing alpha — Seven Deuce's $345k came from intraday round-trip MM, not arb. Build a per-strike inventory-aware quoter and hedge net delta on VFE; do not chase displayed-quote arb that does not exist.
4. **Keep arb scanner OFF unless we observe live trade-prints crossing book** (different from displayed quotes — taker bots may print at off-book levels). Add a one-line logger on `state.market_trades[V]` flagging cross-strike print pairs at violating prices; revisit only if signal appears.

Falsification: re-run after R4 day-1 live submission; if crossings observed in own_trades or market_trades not visible in CSV books, reconsider.

Files: `intel/voucher_pair_arb.py`, this doc.
