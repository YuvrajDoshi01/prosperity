# Round 1+ Product Archetype Templates

Starter templates for common product types. Use as scaffolding when a new product drops.

| File | Archetype | Example products |
|------|-----------|------------------|
| template_stable.py | Pegged / fixed-FV | RAINFOREST_RESIN, AMETHYSTS, ASH_COATED_OSMIUM |
| template_random_walk.py | Mean-reverting walk | KELP, STARFRUIT |
| template_basket.py | ETF/basket arbitrage | PICNIC_BASKET (P3), with component hedging |
| template_options.py | Black-Scholes options | VOLCANIC_ROCK_VOUCHER_* (P3) |
| template_conversion.py | Cross-exchange arb | MAGNIFICENT_MACARONS (P3 R4), implied bid/ask |
| template_olivia.py | Insider bot copy-trade | SQUID_INK (P3), qty=15 filter at extremes |

## Deployment workflow when Round 2+ drops

1. Download sample CSV + confirm product behavior (stable vs random walk vs basket vs options)
2. Copy the matching template → customize FV, LIMIT, product name
3. Integrate into a multi-product dispatcher in [../r1_v4.py](../r1_v4.py) (or clone to r2_v1.py)
4. Submit, ablate, iterate

## Key parameters by archetype

- **Stable**: fixed FV (often 10000), apply Linear Utility framework verbatim (take_width=1, clear_width=0, disregard=1, join=2, default=4, adverse_vol=15)
- **Random walk**: filtered-MM-mid (vol≥15) + small mean-reversion coefficient (~-0.229). LU's STARFRUIT params.
- **Basket**: z-score threshold=7 on 45-tick rolling window (jmerle P2 9th)
- **Options**: r=0, statistics.NormalDist for BS, per-strike rolling IV mean, no delta hedge
- **Conversion**: implied bid/ask from observations, hidden taker bot detection
- **Olivia**: qty=15 filter at daily min/max extremes, cross-product signal gate

See [../../../imc_prosperity_playbook.md](../../../imc_prosperity_playbook.md) for detailed exact formulas per archetype.
