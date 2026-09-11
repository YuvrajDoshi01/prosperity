# P3 Voucher Winners → R4 Patterns

TimoDiehm #2 $1.43M · chrispyroberts #7 $1.26M · CarterT27 #9 $1.19M. P3 R3: VOLCANIC_ROCK + 5 strikes, ~7d. R4: VFE + 10 strikes, TTE=4. Mechanic identical (calls); 2x strikes → wider smile; lower TTE → vega↓ gamma↑ → tighter MM, hedge optional.

## 1. TimoDiehm: Poly smile + EMA theo-diff

Fit poly on `m_t = log(K/S)/sqrt(TTE)`. Per tick: `theo_diff = mid − BS(poly_iv)`, EMA-norm per strike (W=20), quote when dev > **THR_OPEN=0.5**. Tighten by `+0.5` if vega≤1. Hedge rock via its own EMA mean-reversion, not per-tick.

```python
coeffs = [0.27362531, 0.01007566, 0.14876677]   # v_t = a*m^2 + b*m + c
def get_iv(S, K, TTE):
    m = np.log(K/S) / TTE**0.5
    return np.poly1d(coeffs)(m)
```

R4: refit poly on R4 csv days 0-2; skip VFE mean-reversion (no clean OU); keep `THR_OPEN=0.5`, `LOW_VEGA_ADJ=0.5`.

## 2. chrispyroberts: Rolling-IV-mean MM + ±1σ band — THE HEADLINE

Chris quote: "Using the mean of this rolling window instead of the quadratic fit as the fair IV model made our backtester PNL shoot up from 80k to 200k per day."

```python
self.iv_hist[v].append(current_iv)
self.iv_hist[v] = self.iv_hist[v][-WINDOW:]   # WINDOW = 50-100
mu, sd = np.mean(self.iv_hist[v]), np.std(self.iv_hist[v])
high = bs_call(S, K, TTE, mu+sd); fair = bs_call(S,K,TTE,mu); low = bs_call(S, K, TTE, mu-sd)
if (high - low) < 1.0: continue                # band-width gate
bid = int(math.floor(fair + 0.1)); ask = int(math.ceil(fair - 0.1))
```

R4: partial in `r4_voucher_alpha.py`. Upgrade: per-strike WINDOW (deep OTM=100, ATM=30). **Drop hedging at TTE=4** — Chris abandoned it (spread cost > position risk). `(high-low)<1.0` gate skips dead strikes.

## 3. CarterT27: Newton-Raphson IV + integer-rounded BS

Newton 50-iter (`sigma=0.5` start, clamp `[0.01,2.0]`), fallback `mean_volatility`. Quote `floor(theo)` / `ceil(theo+1)`.

```python
def implied_vol(price, S, K, T, r=0):
    sigma = 0.5
    for _ in range(50):
        diff = price - bs_call(S, K, T, r, sigma)
        if abs(diff) < 1e-5: break
        sigma += diff / bs_vega(S, K, T, r, sigma)
        sigma = max(0.01, min(sigma, 2.0))
    return sigma
```

R4: fallback; cache `iv_{S}_{K}_{T}_{r}` keys (CarterT27) to stay under IMC 1s budget.

## 4. Chris R4 "hidden taker" — just observation

Chris quote: "a bot aggressively taking orders on the local island near the mid-price of Pristine Island" → he posted sells near mid, converted post-fill. **No pattern recognition.** R4-voucher analog: scan `state.market_trades[v]` for trades hitting our prior-tick best±1, track per-strike invisible-taker rate. ≥10 fills/100 ticks → MM-profitable regardless of IV edge (engine step 5).

## Three concrete drops for `r4_final_v2.py`

**(A) Rolling-IV-mean MM (chris, headline 2.5x BT):**
```python
WINDOW = {4000:100, 4500:80, 5000:50, 5500:30, 6000:30, 6500:50, 7000:80}
for K, sym in voucher_strikes.items():
    iv = newton_iv(mid[sym], S, K, TTE)
    hist[K].append(iv); hist[K] = hist[K][-WINDOW[K]:]
    if len(hist[K]) < 10: continue
    mu, sd = np.mean(hist[K]), np.std(hist[K])
    fair = bs_call(S, K, TTE, mu)
    if bs_call(S,K,TTE,mu+sd) - bs_call(S,K,TTE,mu-sd) < 1.0: continue
    orders.append(Order(sym, math.floor(fair+0.1),  LIM - pos[sym]))
    orders.append(Order(sym, math.ceil(fair-0.1), -LIM - pos[sym]))
```

**(B) EMA theo-diff threshold (timo, layered alpha):**
```python
theo_diff = mid[sym] - bs_call(S, K, TTE, poly_iv(K, S, TTE))
ema = alpha*theo_diff + (1-alpha)*ema_prev   # alpha = 2/(20+1)
low_vega_adj = 0.5 if vega[sym] <= 1 else 0.0
if theo_diff - ema >=  (THR_OPEN + low_vega_adj): orders.append(Order(sym, best_bid, -max_sell))
if theo_diff - ema <= -(THR_OPEN + low_vega_adj): orders.append(Order(sym, best_ask,  max_buy))
```

**(C) Invisible-taker counter (R4-novel, validate first):**
```python
# Persist last_bid/last_ask per voucher in trader_data.
# Each tick, count market_trades[v] where price in {last_bid, last_ask}; that's fill estimate.
# After 200 ticks, scale MM size 2x on strikes with ratio > 0.10.
```

**Keep:** BS r=0; integer rounding; per-strike limits; hedge OFF at TTE=4. **Change:** cache IVs (10 vs 5 strikes); refit poly on R4 days 0-2; raise WINDOW for deep OTM/ITM.
