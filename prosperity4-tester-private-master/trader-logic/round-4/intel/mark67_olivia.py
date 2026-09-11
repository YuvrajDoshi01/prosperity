"""Mark 67 Olivia-analog reverse engineering.

Tests:
1. Daily-extrema concentration (P3 Olivia traded at daily lows)
2. Cluster / inter-arrival distribution
3. Pre-position predictors (1-100 ticks BEFORE each Mark 67 trade)
4. Post-mark forward return (true momentum vs trade impact)
5. Cross-Mark joint signal (Mark 67 buys + Mark 49 sells)
"""
from __future__ import annotations

import csv
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

DATA = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/prosperity4bt/resources/round4")
OUT = Path("C:/Users/gurms/PycharmProjects/imc-prosperity-4-backtester/trader-logic/round-4/intel")


def load_mids(day: int) -> dict[int, float]:
    """timestamp -> VFE mid"""
    mids = {}
    with open(DATA / f"prices_round_4_day_{day}.csv") as f:
        rd = csv.DictReader(f, delimiter=";")
        for row in rd:
            if row["product"] != "VELVETFRUIT_EXTRACT":
                continue
            ts = int(row["timestamp"])
            mid = float(row["mid_price"]) if row["mid_price"] else None
            if mid is not None:
                mids[ts] = mid
    return mids


def load_book(day: int) -> dict[int, dict]:
    """ts -> {bb, ba, bv1, av1, spread, mid}"""
    books = {}
    with open(DATA / f"prices_round_4_day_{day}.csv") as f:
        rd = csv.DictReader(f, delimiter=";")
        for row in rd:
            if row["product"] != "VELVETFRUIT_EXTRACT":
                continue
            ts = int(row["timestamp"])
            try:
                bb = int(row["bid_price_1"]); ba = int(row["ask_price_1"])
                bv = int(row["bid_volume_1"]); av = int(row["ask_volume_1"])
            except ValueError:
                continue
            books[ts] = {"bb": bb, "ba": ba, "bv": bv, "av": av,
                         "spread": ba - bb, "mid": (bb + ba) / 2.0}
    return books


def load_mark_trades(day: int, mark: str, sym: str = "VELVETFRUIT_EXTRACT"):
    out = []
    with open(DATA / f"trades_round_4_day_{day}.csv") as f:
        rd = csv.DictReader(f, delimiter=";")
        for row in rd:
            if row["symbol"] != sym:
                continue
            buyer, seller = row["buyer"], row["seller"]
            ts = int(row["timestamp"])
            qty = int(row["quantity"])
            px = float(row["price"])
            if buyer == mark:
                out.append((ts, +1, qty, px))   # +1 = buy
            elif seller == mark:
                out.append((ts, -1, qty, px))   # -1 = sell
    return sorted(out)


def daily_extrema(mids: dict[int, float], trades_buy: list[tuple]):
    """% of buy-trades in bottom-X% of day's mid distribution."""
    sorted_mids = sorted(mids.values())
    n = len(sorted_mids)
    p10 = sorted_mids[int(0.10 * n)]
    p25 = sorted_mids[int(0.25 * n)]
    p50 = sorted_mids[int(0.50 * n)]
    p75 = sorted_mids[int(0.75 * n)]
    p90 = sorted_mids[int(0.90 * n)]
    cnt10 = cnt25 = cnt50 = cnt75 = cnt90 = 0
    for ts, side, qty, px in trades_buy:
        m = mids.get(ts)
        if m is None: continue
        if m <= p10: cnt10 += 1
        if m <= p25: cnt25 += 1
        if m <= p50: cnt50 += 1
        if m <= p75: cnt75 += 1
        if m <= p90: cnt90 += 1
    n_t = len(trades_buy)
    return {"n": n_t, "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90,
            "frac_in_bottom10": cnt10/n_t if n_t else 0,
            "frac_in_bottom25": cnt25/n_t if n_t else 0,
            "frac_in_bottom50": cnt50/n_t if n_t else 0,
            "frac_in_top25": (n_t-cnt75)/n_t if n_t else 0,
            "frac_in_top10": (n_t-cnt90)/n_t if n_t else 0}


def inter_arrival(trades):
    if len(trades) < 2: return None
    ts_list = [t[0] for t in trades]
    diffs = [(ts_list[i+1]-ts_list[i])//100 for i in range(len(ts_list)-1)]
    if not diffs: return None
    mean_iat = st.mean(diffs)
    sd_iat = st.stdev(diffs) if len(diffs) > 1 else 0
    cov = sd_iat / mean_iat if mean_iat > 0 else 0
    # Burst metric: fraction of inter-arrivals < 0.5 * mean
    bursts = sum(1 for d in diffs if d < 0.5 * mean_iat) / len(diffs)
    # Longest burst = consecutive trades within 5 ticks
    burst_lens = []
    cur = 1
    for d in diffs:
        if d <= 5:
            cur += 1
        else:
            if cur > 1: burst_lens.append(cur)
            cur = 1
    if cur > 1: burst_lens.append(cur)
    return {"n_trades": len(trades), "mean_iat_ticks": mean_iat, "sd": sd_iat,
            "cov": cov, "frac_short_iat": bursts, "n_bursts": len(burst_lens),
            "max_burst_len": max(burst_lens) if burst_lens else 0,
            "mean_burst_len": st.mean(burst_lens) if burst_lens else 0}


def post_trade_returns(books, trades, horizons=(1, 5, 10, 25, 50, 100)):
    """For each Mark 67 trade, compute mid(t+h) - mid(t) per horizon."""
    out = {h: [] for h in horizons}
    sorted_ts = sorted(books.keys())
    for ts, side, qty, px in trades:
        if side != +1: continue
        m0 = books.get(ts, {}).get("mid")
        if m0 is None: continue
        for h in horizons:
            t1 = ts + h * 100
            m1 = books.get(t1, {}).get("mid")
            if m1 is not None:
                out[h].append(m1 - m0)
    return {h: {"n": len(v), "mean": st.mean(v) if v else 0,
                "tstat": (st.mean(v)/(st.stdev(v)/math.sqrt(len(v)))) if len(v) > 1 and st.stdev(v) > 0 else 0,
                "win_rate": sum(1 for x in v if x > 0)/len(v) if v else 0}
            for h, v in out.items()}


def joint_mark_signal(books, m67_buys, m49_sells, window=5):
    """When Mark 67 buys within ±window ticks of Mark 49 sell, fwd return?"""
    m49_set = {ts // 100 for ts, _, _, _ in m49_sells}
    co_buys = []
    iso_buys = []
    for ts, side, qty, px in m67_buys:
        idx = ts // 100
        co = any((idx + d) in m49_set for d in range(-window, window+1))
        m0 = books.get(ts, {}).get("mid")
        m10 = books.get(ts + 10*100, {}).get("mid")
        if m0 is None or m10 is None: continue
        ret = m10 - m0
        if co:
            co_buys.append(ret)
        else:
            iso_buys.append(ret)
    def stats(arr):
        if not arr: return {"n": 0}
        return {"n": len(arr), "mean": st.mean(arr),
                "tstat": st.mean(arr)/(st.stdev(arr)/math.sqrt(len(arr))) if len(arr)>1 and st.stdev(arr)>0 else 0}
    return {"co": stats(co_buys), "iso": stats(iso_buys)}


def pre_trade_features(books, trades, lookback=10):
    """For each Mark 67 buy, look at OBI/spread/recent_ret L-ticks BEFORE."""
    out = []
    for ts, side, qty, px in trades:
        if side != +1: continue
        # pre-feature: OBI at t-lookback, mid_now - mid_pre
        m_pre = books.get(ts - lookback*100, {}).get("mid")
        b_pre = books.get(ts - lookback*100)
        m_now = books.get(ts, {}).get("mid")
        if m_pre is None or b_pre is None or m_now is None: continue
        bv, av = b_pre["bv"], b_pre["av"]
        obi = (bv - av) / (bv + av) if (bv + av) > 0 else 0
        out.append({"ret_pre": m_now - m_pre, "obi_pre": obi, "spread_pre": b_pre["spread"]})
    if not out: return {}
    return {"n": len(out),
            "mean_ret_pre": st.mean(x["ret_pre"] for x in out),
            "mean_obi_pre": st.mean(x["obi_pre"] for x in out),
            "frac_neg_ret_pre": sum(1 for x in out if x["ret_pre"] < 0)/len(out),
            "frac_neg_obi_pre": sum(1 for x in out if x["obi_pre"] < 0)/len(out)}


def main():
    lines = []
    lines.append("# Mark 67 Olivia-Analog Forensics (R4 VFE)\n")
    lines.append("Data: round4 days 1-3.\n\n")

    all_m67_buys = []
    all_m49_sells = []
    daily_extrema_results = []
    daily_iat = []
    pre_features = []

    for day in (1, 2, 3):
        mids = load_mids(day)
        books = load_book(day)
        m67 = load_mark_trades(day, "Mark 67")
        m49 = load_mark_trades(day, "Mark 49")
        m67_buys = [t for t in m67 if t[1] == +1]
        m49_sells = [t for t in m49 if t[1] == -1]
        all_m67_buys.extend([(day,)+t for t in m67_buys])
        all_m49_sells.extend([(day,)+t for t in m49_sells])

        ext = daily_extrema(mids, m67_buys)
        ext["day"] = day
        daily_extrema_results.append(ext)

        iat = inter_arrival(m67_buys)
        if iat: iat["day"] = day; daily_iat.append(iat)

        pre = pre_trade_features(books, m67_buys, lookback=10)
        if pre: pre["day"] = day; pre_features.append(pre)

        # Post-trade fwd
        fwd = post_trade_returns(books, m67_buys)
        joint = joint_mark_signal(books, m67_buys, m49_sells, window=5)

        lines.append(f"## Day {day}\n")
        lines.append(f"- Mark 67 trades: {len(m67)} (buys: {len(m67_buys)}, sells: {len(m67)-len(m67_buys)})\n")
        lines.append(f"- Mark 49 sells: {len(m49_sells)}\n")
        lines.append(f"- Daily extrema (Mark 67 buys vs day's mid distribution):\n")
        lines.append(f"    bottom10%={ext['frac_in_bottom10']*100:.1f}%  bottom25%={ext['frac_in_bottom25']*100:.1f}%  "
                     f"bottom50%={ext['frac_in_bottom50']*100:.1f}%  top25%={ext['frac_in_top25']*100:.1f}%  top10%={ext['frac_in_top10']*100:.1f}%\n")
        if iat:
            lines.append(f"- Inter-arrival (ticks): mean={iat['mean_iat_ticks']:.1f}  cov={iat['cov']:.2f}  "
                         f"frac<0.5*mean={iat['frac_short_iat']*100:.1f}%  bursts={iat['n_bursts']}  "
                         f"max_burst_len={iat['max_burst_len']}\n")
        if pre:
            lines.append(f"- Pre-trade features (10 ticks before): mean_ret={pre['mean_ret_pre']:.2f}  "
                         f"mean_OBI={pre['mean_obi_pre']:.2f}  frac_neg_ret={pre['frac_neg_ret_pre']*100:.1f}%  "
                         f"frac_neg_OBI={pre['frac_neg_obi_pre']*100:.1f}%\n")
        lines.append(f"- Post-trade forward return (mid drift, BUY trades):\n")
        for h, v in fwd.items():
            lines.append(f"    h={h:>3}: n={v['n']:>3}  mean={v['mean']:+.2f}  t={v['tstat']:+.2f}  win={v['win_rate']*100:.1f}%\n")
        lines.append(f"- Joint Mark 67 buy + Mark 49 sell within ±5 ticks (h=10 fwd):\n")
        lines.append(f"    co-occurring n={joint['co'].get('n',0)} mean={joint['co'].get('mean',0):+.2f} t={joint['co'].get('tstat',0):+.2f}\n")
        lines.append(f"    isolated     n={joint['iso'].get('n',0)} mean={joint['iso'].get('mean',0):+.2f} t={joint['iso'].get('tstat',0):+.2f}\n\n")

    # Aggregate
    lines.append("## Aggregate (3 days pooled)\n")
    lines.append(f"- Total Mark 67 buys: {len(all_m67_buys)}, Mark 49 sells: {len(all_m49_sells)}\n")
    e = {k: st.mean([d[k] for d in daily_extrema_results])
         for k in ("frac_in_bottom10","frac_in_bottom25","frac_in_bottom50","frac_in_top25","frac_in_top10")}
    lines.append(f"- Pooled extrema concentration: bottom10%={e['frac_in_bottom10']*100:.1f}%  "
                 f"bottom25%={e['frac_in_bottom25']*100:.1f}%  bottom50%={e['frac_in_bottom50']*100:.1f}%  "
                 f"top25%={e['frac_in_top25']*100:.1f}%  top10%={e['frac_in_top10']*100:.1f}%\n")
    if daily_iat:
        lines.append(f"- Pooled IAT: mean={st.mean(d['mean_iat_ticks'] for d in daily_iat):.1f} ticks  "
                     f"cov={st.mean(d['cov'] for d in daily_iat):.2f}  "
                     f"max_burst_len={max(d['max_burst_len'] for d in daily_iat)}\n")

    out_md = OUT / "mark67_olivia.md"
    out_md.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {out_md}")
    print("".join(lines))


if __name__ == "__main__":
    main()
