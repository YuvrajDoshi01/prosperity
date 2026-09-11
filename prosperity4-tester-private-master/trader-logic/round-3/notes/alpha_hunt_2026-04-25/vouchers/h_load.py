"""Common loader for voucher alpha hunt."""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round3")
STRIKES = [4000,4500,5000,5100,5200,5300,5400,5500,6000,6500]
VOUCHERS = [f"VEV_{k}" for k in STRIKES]
UND = "VELVETFRUIT_EXTRACT"

# Time to expiry (years, 250-day calendar)
TTE = {0: 8/250, 1: 7/250, 2: 6/250}

def load_prices(day):
    return pd.read_csv(ROOT / f"prices_round_3_day_{day}.csv", sep=";")

def load_trades(day):
    return pd.read_csv(ROOT / f"trades_round_3_day_{day}.csv", sep=";")

def pivot_mid(day):
    """Wide table of mid_price per product, indexed by timestamp."""
    df = load_prices(day)
    return df.pivot(index="timestamp", columns="product", values="mid_price")

def pivot_field(day, field):
    df = load_prices(day)
    return df.pivot(index="timestamp", columns="product", values=field)

# Black-Scholes call
from math import log, sqrt, exp, erf

def norm_cdf(x):
    return 0.5*(1+erf(x/sqrt(2)))

def bs_call(S, K, T, sigma, r=0.0):
    if sigma<=0 or T<=0:
        return max(0.0, S-K)
    d1 = (log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S*norm_cdf(d1) - K*exp(-r*T)*norm_cdf(d2)

def bs_delta(S, K, T, sigma, r=0.0):
    if sigma<=0 or T<=0:
        return 1.0 if S>K else 0.0
    d1 = (log(S/K) + (r+0.5*sigma*sigma)*T) / (sigma*sqrt(T))
    return norm_cdf(d1)

def bs_vega(S, K, T, sigma, r=0.0):
    if sigma<=0 or T<=0:
        return 0.0
    d1 = (log(S/K) + (r+0.5*sigma*sigma)*T) / (sigma*sqrt(T))
    pdf = np.exp(-d1*d1/2)/np.sqrt(2*np.pi)
    return S*pdf*np.sqrt(T)

def implied_vol(C, S, K, T, r=0.0):
    """Brent root finder for IV."""
    if C <= max(0, S-K) + 1e-6 or T<=0:
        return np.nan
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid = 0.5*(lo+hi)
        if bs_call(S,K,T,mid,r) > C:
            hi = mid
        else:
            lo = mid
        if hi-lo<1e-6: break
    return 0.5*(lo+hi)
