"""
Ignith Manual Challenge — Portfolio Optimizer
==============================================
Fee formula: fee_per_good = (pct / 100)^2 * budget
Budget = 1,000,000
PnL = sum_over_goods(investment_i * return_i) - sum_over_goods(fee_i)
     where investment_i = pct_i / 100 * budget
     and   fee_i        = (pct_i / 100)^2 * budget

Constraint: sum(pct_i) <= 100

Optimal allocation (calculus):
For a single good with expected return r:
  profit = pct/100 * budget * r - (pct/100)^2 * budget
  d(profit)/d(pct) = budget/100 * r - 2 * budget * pct / 10000 = 0
  => pct* = 50 * r  (if |r| <= 2, else corner at 100%)

For multiple goods with returns r_i, each good is INDEPENDENT in the fee structure:
  pct_i* = 50 * r_i  (unconstrained optimum)
  Subject to: sum(pct_i) <= 100

If sum of unconstrained optima > 100, need Lagrangian with budget constraint.
"""

import numpy as np
from itertools import product as cartesian_product

BUDGET = 1_000_000

def fee(pct):
    """Fee for allocating pct% of budget to one good."""
    return (pct / 100) ** 2 * BUDGET

def investment(pct):
    """Dollar investment for pct% allocation."""
    return pct / 100 * BUDGET

def profit_per_good(pct, expected_return):
    """PnL from one good: investment * return - fee."""
    return investment(pct) * expected_return - fee(pct)

def optimal_pct_unconstrained(r):
    """Unconstrained optimal allocation for expected return r."""
    return 50.0 * r

def portfolio_pnl(allocations, returns):
    """
    allocations: dict {good: pct}
    returns: dict {good: expected_return}
    """
    total_pnl = 0
    total_fee = 0
    total_pct = 0
    for good, pct in allocations.items():
        r = returns.get(good, 0)
        inv = investment(abs(pct))
        f = fee(abs(pct))
        # If sell, return is negated (we profit when price drops)
        direction = 1 if pct > 0 else -1
        pnl = inv * r * direction - f
        total_pnl += pnl
        total_fee += f
        total_pct += abs(pct)
    return total_pnl, total_fee, total_pct


# ============================================================
# NEWS ANALYSIS -> EXPECTED RETURNS
# ============================================================
# Each article from Ashflow Alpha analyzed for price direction

news_analysis = {
    "Obsidian cutlery": {
        "headline": "Manufacturing halted after blades cut assembly line",
        "signal": "NEGATIVE (supply disruption -> less product, BUT negative sentiment + contamination + lawsuits = bad for manufacturer)",
        "direction": "AMBIGUOUS — supply cut could raise prices short-term, but contamination/halted production is bearish for the product as a going concern",
        "confidence": "LOW",
        "lean": "SELL (net negative: contamination, evacuation, regulatory risk)",
    },
    "Pyroflex cells": {
        "headline": "Tax authority ends 50% Pyroflex Cell Tax Cut effective tomorrow",
        "signal": "NEGATIVE (tax incentive removal doubles levy -> higher effective price for consumers -> reduced demand + slowed purchases)",
        "direction": "SELL — tax cut removal = demand destruction, industry pressure confirms negative impact",
        "confidence": "HIGH",
        "lean": "SELL",
    },
    "Thermalite core": {
        "headline": "Quarterly forecast: surge in Thermalite-powered smart home devices (1.42M -> 3.89M users, 16h42m daily usage)",
        "signal": "POSITIVE (2.7x user growth projection, sustained usage, strong next quarter)",
        "direction": "BUY — demand surge for Thermalite Cores directly",
        "confidence": "HIGH",
        "lean": "BUY",
    },
    "Lava cake": {
        "headline": "Traces of actual lava found in Lava Cakes, health review launched",
        "signal": "NEGATIVE (sales halted, health risks, lawsuits piling up, vendors returning stock)",
        "direction": "SELL — product recall, legal liability, reputational damage",
        "confidence": "HIGH",
        "lean": "SELL",
    },
    "Magma ink": {
        "headline": "Crowds line up for limited-edition Lava Fountain Pen with Magma Ink (post-merger)",
        "signal": "POSITIVE (high demand, merger creates integrated product, 'hot drop' hype)",
        "direction": "BUY — strong consumer demand + merger synergies",
        "confidence": "MEDIUM-HIGH",
        "lean": "BUY",
    },
    "Scoria paste": {
        "headline": "Lava D. Ray urges stockpiling, calls it 'paste that keeps Ignith together'",
        "signal": "AMBIGUOUS — influencer pump (Lava D. Ray is 'self-proclaimed market medium', not credible analyst). BUT Scoria Paste has fundamental demand (infrastructure/maintenance staple)",
        "direction": "CONTRARIAN SELL vs naive BUY. Key question: is D. Ray a reliable signal or a pump?",
        "confidence": "LOW-MEDIUM",
        "lean": "BUY (fundamental demand story) or SELL (influencer pump-and-dump)",
    },
    "Ashes of the Phoenix": {
        "headline": "Resurfaced video of controversial sourcing causes public outcry",
        "signal": "MIXED — public outrage = demand risk, BUT company claims birds are 'immortal' and method unchanged for decades. If product is popular and supply is stable, outrage may fade.",
        "direction": "SELL short-term (reputational damage, possible boycott) vs BUY if outcry is overblown",
        "confidence": "MEDIUM",
        "lean": "SELL (ESG/reputational risk dominates short-term)",
    },
    "Volcanic incense": {
        "headline": "Whiff Nostralico openly pumping; concentrated buying in narrow windows",
        "signal": "NEGATIVE — classic pump scheme. 'Follow my lead and buy' = retail manipulation. Concentrated buying = artificial. This is the most obvious pump-and-dump signal.",
        "direction": "SELL — pump will reverse when manipulator exits",
        "confidence": "HIGH (pump-and-dump pattern)",
        "lean": "SELL",
    },
    "Sulfur reactor": {
        "headline": "Sulfur Ltd. confirmed for Elemental Index 118 inclusion",
        "signal": "POSITIVE — index inclusion = passive fund buying pressure. Well-documented 'index effect' drives prices up around rebalance.",
        "direction": "BUY — index inclusion is a reliable short-term catalyst",
        "confidence": "HIGH",
        "lean": "BUY",
    },
}


# ============================================================
# PORTFOLIO A: Marc's current submission (from paste cache)
# ============================================================
portfolio_a = {
    "Obsidian cutlery":     ("BUY",  5),
    "Pyroflex cells":       ("SELL", 15),
    "Thermalite core":      ("BUY",  15),
    "Lava cake":            ("SELL", 10),
    "Magma ink":            ("BUY",  10),
    "Scoria paste":         ("SELL", 15),
    "Ashes of the Phoenix": ("BUY",  15),
    "Volcanic incense":     ("SELL", 10),
    "Sulfur reactor":       ("BUY",  5),
}

# ============================================================
# PORTFOLIO B: Proposed alternative (quant-optimized)
# ============================================================
# Based on the news analysis, let's construct an alternative that:
# 1. Concentrates on HIGH-confidence signals
# 2. Uses quadratic fee optimization (spread thin on low-confidence)
# 3. Aligns all directions with news sentiment

# High confidence signals: Pyroflex SELL, Thermalite BUY, Lava cake SELL,
#                          Volcanic incense SELL, Sulfur reactor BUY
# Medium confidence: Magma ink BUY, Ashes SELL
# Low confidence: Obsidian (ambiguous), Scoria (influencer noise)

# With quadratic fees, the optimal strategy is:
# - Allocate MORE to high-confidence signals (they have better risk/reward)
# - But not TOO much (quadratic penalty grows fast)
# - Spread remainder across medium-confidence bets


def analyze_portfolio(name, portfolio):
    """Analyze a portfolio against news signals."""
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO: {name}")
    print(f"{'='*70}")

    total_pct = 0
    total_fee = 0
    alignment_score = 0
    goods_analyzed = []

    for good, (direction, pct) in portfolio.items():
        analysis = news_analysis[good]
        inv = investment(pct)
        f = fee(pct)
        total_pct += pct
        total_fee += f

        # Check alignment with news
        news_lean = analysis["lean"].split()[0]  # First word: BUY or SELL
        aligned = direction == news_lean
        alignment_str = "ALIGNED" if aligned else "MISALIGNED"

        # Special case for ambiguous
        if "AMBIGUOUS" in analysis["signal"] or "MIXED" in analysis["signal"]:
            alignment_str = "AMBIGUOUS"
            if "BUY" in analysis["lean"] and direction == "BUY":
                alignment_str = "WEAKLY ALIGNED"
            elif "SELL" in analysis["lean"] and direction == "SELL":
                alignment_str = "WEAKLY ALIGNED"

        goods_analyzed.append({
            "good": good,
            "direction": direction,
            "pct": pct,
            "investment": inv,
            "fee": f,
            "news_lean": analysis["lean"],
            "confidence": analysis["confidence"],
            "aligned": alignment_str,
        })

        print(f"\n  {good}: {direction} {pct}%")
        print(f"    Investment: ${inv:,.0f}  Fee: ${f:,.0f}")
        print(f"    News: {analysis['lean']}")
        print(f"    Confidence: {analysis['confidence']}")
        print(f"    Alignment: {alignment_str}")

    print(f"\n  {'-'*50}")
    print(f"  Total allocated: {total_pct}%")
    print(f"  Total fees:      ${total_fee:,.0f}")
    print(f"  Unallocated:     {100 - total_pct}%")
    print(f"  Fee as % of budget: {total_fee/BUDGET*100:.1f}%")

    # Count alignments
    aligned = sum(1 for g in goods_analyzed if g["aligned"] == "ALIGNED")
    misaligned = sum(1 for g in goods_analyzed if g["aligned"] == "MISALIGNED")
    ambiguous = sum(1 for g in goods_analyzed if "AMBIGUOUS" in g["aligned"] or "WEAKLY" in g["aligned"])
    print(f"\n  Signal alignment: {aligned} aligned, {misaligned} MISALIGNED, {ambiguous} ambiguous")

    return goods_analyzed, total_fee, total_pct


def fee_efficiency_analysis():
    """Compare fee structures for different allocation strategies."""
    print(f"\n{'='*70}")
    print(f"  FEE EFFICIENCY ANALYSIS")
    print(f"{'='*70}")

    scenarios = [
        ("9 goods @ ~11.1% each", [11.1]*9),
        ("5 goods @ 20% each", [20]*5),
        ("3 goods @ 33.3% each", [33.3]*3),
        ("4 @ 15% + 5 @ 8%", [15]*4 + [8]*5),
        ("Marc's allocation", [5, 15, 15, 10, 10, 15, 15, 10, 5]),
        ("Concentrated: 2 @ 30% + 2 @ 20%", [30, 30, 20, 20]),
        ("Spread thin: 9 @ 10% + skip 10%", [10]*9),
    ]

    print(f"\n  {'Scenario':<45} {'Total %':>8} {'Total Fee':>12} {'Fee/Budget':>10}")
    print(f"  {'-'*80}")
    for label, allocs in scenarios:
        total_pct = sum(allocs)
        total_fee = sum(fee(p) for p in allocs)
        print(f"  {label:<45} {total_pct:>7.1f}% ${total_fee:>10,.0f} {total_fee/BUDGET*100:>9.1f}%")


def marginal_analysis():
    """Show the marginal fee cost of adding 1% more to each allocation level."""
    print(f"\n{'='*70}")
    print(f"  MARGINAL FEE ANALYSIS (cost of 1% more allocation)")
    print(f"{'='*70}")
    print(f"\n  {'Current %':>10} {'Fee at pct':>12} {'Fee at pct+1':>12} {'Marginal':>10} {'Investment':>12}")
    print(f"  {'-'*60}")
    for pct in [0, 5, 10, 15, 20, 25, 30]:
        f0 = fee(pct)
        f1 = fee(pct + 1)
        marg = f1 - f0
        inv = investment(1)  # 1% = 10k investment
        print(f"  {pct:>9}% ${f0:>10,.0f} ${f1:>10,.0f} ${marg:>8,.0f}   ${inv:>10,.0f}")

    print(f"\n  Key insight: marginal fee at 15% = ${fee(16)-fee(15):,.0f} per 1% more allocation")
    print(f"  vs marginal fee at 5% = ${fee(6)-fee(5):,.0f} per 1% more allocation")
    print(f"  => Spreading across more goods at lower % is fee-efficient")
    print(f"  => But only if the signal quality justifies the allocation")


def breakeven_analysis():
    """For each allocation level, what return is needed to break even?"""
    print(f"\n{'='*70}")
    print(f"  BREAKEVEN RETURN ANALYSIS")
    print(f"{'='*70}")
    print(f"\n  The return needed for PnL = 0 at each allocation level:")
    print(f"\n  {'Alloc %':>8} {'Investment':>12} {'Fee':>10} {'Breakeven Return':>16}")
    print(f"  {'-'*50}")
    for pct in [5, 8, 10, 12, 15, 20, 25, 30]:
        inv = investment(pct)
        f = fee(pct)
        # breakeven: inv * r = fee => r = fee / inv = pct/100
        be_return = f / inv if inv > 0 else float('inf')
        print(f"  {pct:>7}% ${inv:>10,.0f} ${f:>8,.0f} {be_return:>15.1%}")

    print(f"\n  Key insight: breakeven return = pct/100 (linear in allocation %)")
    print(f"  At 5% allocation, need 5% return to break even")
    print(f"  At 15% allocation, need 15% return to break even")
    print(f"  At 30% allocation, need 30% return to break even")
    print(f"  => Larger allocations need proportionally larger returns!")


def scenario_pnl_comparison(portfolios_dict, return_scenarios):
    """Compare portfolios across multiple return scenarios."""
    print(f"\n{'='*70}")
    print(f"  SCENARIO PNL COMPARISON")
    print(f"{'='*70}")

    for scenario_name, returns in return_scenarios.items():
        print(f"\n  Scenario: {scenario_name}")
        print(f"  {'-'*60}")
        for port_name, portfolio in portfolios_dict.items():
            total_pnl = 0
            total_fee = 0
            for good, (direction, pct) in portfolio.items():
                r = returns.get(good, 0)
                inv = investment(pct)
                f = fee(pct)
                dir_mult = 1 if direction == "BUY" else -1
                pnl = inv * r * dir_mult - f
                total_pnl += pnl
                total_fee += f
            print(f"    {port_name:<30} PnL: ${total_pnl:>12,.0f}  (fees: ${total_fee:>8,.0f})")


if __name__ == "__main__":
    print("=" * 70)
    print("  IGNITH MANUAL CHALLENGE — QUANT-FINANCE ANALYSIS")
    print("  Fee = (pct/100)^2 * 1,000,000")
    print("=" * 70)

    # 1. Fee structure analysis
    fee_efficiency_analysis()
    marginal_analysis()
    breakeven_analysis()

    # 2. Analyze Marc's portfolio
    marc_goods, marc_fee, marc_pct = analyze_portfolio("A: Marc's Current", portfolio_a)

    # 3. Print news summary
    print(f"\n{'='*70}")
    print(f"  NEWS SIGNAL SUMMARY")
    print(f"{'='*70}")
    for good, analysis in news_analysis.items():
        print(f"\n  {good}: {analysis['lean']}")
        print(f"    Signal: {analysis['signal'][:80]}")
        print(f"    Confidence: {analysis['confidence']}")

    # 4. Key findings
    print(f"\n{'='*70}")
    print(f"  KEY FINDINGS FOR PORTFOLIO A (Marc's)")
    print(f"{'='*70}")

    issues = []
    # Check Obsidian cutlery BUY
    if portfolio_a["Obsidian cutlery"][0] == "BUY":
        issues.append(
            "Obsidian cutlery BUY 5%: NEWS says manufacturing halted + contamination. "
            "Supply disruption could go either way, but contamination/evacuation/regulatory "
            "risk makes this a net negative. BUY is MISALIGNED. Consider SELL or SKIP."
        )

    # Check Ashes of the Phoenix BUY
    if portfolio_a["Ashes of the Phoenix"][0] == "BUY":
        issues.append(
            "Ashes of the Phoenix BUY 15%: NEWS shows public outcry over sourcing video. "
            "Even if company claims birds are 'immortal', ESG/reputational damage is real "
            "short-term. BUY at 15% (high allocation) is RISKY. Consider SELL or reduce to 5%."
        )

    # Check Scoria paste SELL
    if portfolio_a["Scoria paste"][0] == "SELL":
        issues.append(
            "Scoria paste SELL 15%: This is the MOST DEBATABLE position. "
            "Lava D. Ray is an influencer ('self-proclaimed market medium') suggesting BUY. "
            "But Scoria Paste is described as 'paste that keeps Ignith together' — a STAPLE. "
            "Influencer pumps often reverse, but fundamental demand for staples is real. "
            "SELL could work if pump reverses, but SELL on a staple is contrarian. "
            "Marc's SELL implies D. Ray is a pump-and-dump signal. REASONABLE but risky."
        )

    for i, issue in enumerate(issues, 1):
        print(f"\n  Issue {i}: {issue}")

    # 5. Optimal unconstrained allocation
    print(f"\n{'='*70}")
    print(f"  OPTIMAL ALLOCATION (unconstrained, given return estimates)")
    print(f"{'='*70}")
    print(f"\n  For a good with expected return r, optimal allocation = 50 * |r|")
    print(f"  (Direction: BUY if r > 0, SELL if r < 0)")
    print(f"\n  Example return estimates and implied optimal allocations:")
    for r_est in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
        opt = 50 * r_est
        print(f"    |r| = {r_est:.0%} -> optimal pct = {opt:.1f}%")

    print(f"\n  The CRITICAL UNKNOWN is the magnitude of returns.")
    print(f"  If returns are ~10-20%, optimal allocations are 5-10% per good.")
    print(f"  If returns are ~30-50%, optimal allocations are 15-25% per good.")
    print(f"  Marc's 15% allocations imply ~30% expected returns on those goods.")
