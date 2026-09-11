"""Test suite for r4_simulation_FINAL.py — verifies bug fixes catch the
cases the reviewer flagged. Run with: python test_r4_simulation.py
"""
import sys
import numpy as np

sys.path.insert(0, '.')
from r4_simulation_FINAL import (
    QUOTES, LIMITS, validate_strategy, run_simulation, STRATEGIES, SIMS_PER_TRIAL
)


def test_n_chunks_zero_paths_lt_chunk():
    """Bug #1 (reviewer): paths=1000, chunk=5M -> n_chunks=0, garbage memory."""
    try:
        run_simulation({"DROP_60C": STRATEGIES["DROP_60C"]},
                       total_paths=1000, chunk_size=5_000_000, seed=42)
    except ValueError as e:
        msg = str(e)
        assert "must be divisible by chunk_size" in msg, f"unexpected msg: {msg}"
        print("PASS: paths < chunk caught with divisibility error")
        return
    raise AssertionError("FAIL: paths=1000, chunk=5M should have raised ValueError")


def test_partial_fill_paths_50M_chunk_7M():
    """Bug #2 (reviewer): paths=50M, chunk=7M -> n_chunks=7, fills 49M, 1M uninitialized."""
    try:
        run_simulation({"DROP_60C": STRATEGIES["DROP_60C"]},
                       total_paths=50_000_000, chunk_size=7_000_000, seed=42)
    except ValueError as e:
        msg = str(e)
        assert "must be divisible by chunk_size" in msg, f"unexpected msg: {msg}"
        print("PASS: 50M not divisible by 7M caught")
        return
    raise AssertionError("FAIL: paths=50M, chunk=7M should have raised ValueError")


def test_chunk_not_divisible_by_sims_per_trial():
    """chunk=99 not divisible by sims_per_trial=100 -> ragged trial reshape."""
    try:
        run_simulation({"DROP_60C": STRATEGIES["DROP_60C"]},
                       total_paths=99_000, chunk_size=99, seed=42)
    except ValueError as e:
        msg = str(e)
        assert "must be divisible by sims_per_trial" in msg, f"unexpected msg: {msg}"
        print("PASS: chunk=99 not divisible by sims_per_trial=100 caught")
        return
    raise AssertionError("FAIL: chunk=99 should have raised ValueError")


def test_negative_or_zero_inputs():
    """Negative/zero sizes -> ValueError."""
    for total, chunk in [(0, 100), (100, 0), (-1, 100), (100, -1)]:
        try:
            run_simulation({"DROP_60C": STRATEGIES["DROP_60C"]},
                           total_paths=total, chunk_size=chunk, seed=42)
        except ValueError as e:
            assert "must be positive" in str(e), f"unexpected msg: {e}"
            continue
        raise AssertionError(f"FAIL: total={total}, chunk={chunk} should have raised")
    print("PASS: zero/negative sizes caught")


def test_valid_run_completes():
    """Sanity: small valid run should complete and produce sensible numbers."""
    # 100k paths in 10 chunks of 10k = 1000 trials of 100. Completes in <1s.
    results = run_simulation(
        {"DROP_60C": STRATEGIES["DROP_60C"]},
        total_paths=100_000, chunk_size=10_000, seed=42)
    r = results["DROP_60C"]
    assert r["n"] == 1000, f"expected 1000 trials, got {r['n']}"
    # Mean should be in roughly the right ballpark even at 1k trials
    # (95% CI of mean estimator at n=1000 is roughly +-21k)
    assert -50_000 < r["mean"] < 400_000, f"mean {r['mean']} wildly off"
    assert r["sd"] > 50_000, f"sd {r['sd']} suspiciously low (likely uninitialized)"
    print(f"PASS: small valid run completes, mean=${r['mean']:,.0f}, sd=${r['sd']:,.0f}")


def test_validate_strategy_aggregates_duplicates():
    """validate_strategy should catch net-position violations from duplicate symbols."""
    # Same symbol twice on same side: 30 + 25 = 55 > cap 50
    bad = [("AC_40_BP", "sell", 30), ("AC_40_BP", "sell", 25)]
    try:
        validate_strategy("dup_test", bad)
    except ValueError as e:
        assert "net |AC_40_BP|=55" in str(e), f"unexpected msg: {e}"
        print("PASS: duplicate-symbol aggregation catches net-cap violation")
        return
    raise AssertionError("FAIL: duplicate sells exceeding cap should raise")


def test_validate_strategy_offsetting_duplicates_ok():
    """Offsetting duplicates (BUY 30 + SELL 25 = NET +5) should pass since 5 <= 50."""
    # Net = +5, well within cap of 50
    ok = [("AC_40_BP", "buy", 30), ("AC_40_BP", "sell", 25)]
    validate_strategy("offset_test", ok)
    print("PASS: offsetting duplicates (net within cap) accepted")


def test_validate_strategy_unknown_symbol():
    """Unknown symbol -> ValueError."""
    try:
        validate_strategy("bad", [("WIDGET", "buy", 10)])
    except ValueError as e:
        assert "unknown instrument" in str(e)
        print("PASS: unknown symbol rejected")
        return
    raise AssertionError("FAIL: unknown symbol should raise")


def test_validate_strategy_bad_side():
    """side != 'buy'/'sell' -> ValueError."""
    try:
        validate_strategy("bad", [("AC_50_CO", "short", 10)])
    except ValueError as e:
        assert "side must be" in str(e)
        print("PASS: bad side rejected")
        return
    raise AssertionError("FAIL: bad side should raise")


def test_validate_strategy_zero_or_negative_vol():
    """vol <= 0 -> ValueError."""
    for bad_vol in [0, -1, -50]:
        try:
            validate_strategy("bad", [("AC_50_CO", "sell", bad_vol)])
        except ValueError as e:
            assert "vol must be positive" in str(e)
            continue
        raise AssertionError(f"FAIL: vol={bad_vol} should raise")
    print("PASS: zero/negative vol rejected")


def test_user_greedy_55bp_caught():
    """The original USER_GREEDY had AC_40_BP=-55 > cap 50 — should be caught."""
    user_greedy_bad = [
        ("AC_50_CO", "sell", 15),
        ("AC_40_BP", "sell", 55),  # exceeds cap 50
        ("AC_45_KO", "buy",  75),
    ]
    try:
        validate_strategy("USER_GREEDY", user_greedy_bad)
    except ValueError as e:
        assert "AC_40_BP" in str(e) and "55" in str(e)
        print("PASS: USER_GREEDY's BP=-55 caught (the original reviewer's bug)")
        return
    raise AssertionError("FAIL: BP=-55 should have raised")


def test_all_recommended_strategies_pass():
    """All shipped strategies must pass validation."""
    for name, strat in STRATEGIES.items():
        validate_strategy(name, strat)
    print(f"PASS: all {len(STRATEGIES)} canonical strategies validated")


if __name__ == "__main__":
    print("="*70)
    print("R4 simulation correctness test suite")
    print("="*70)
    tests = [
        test_n_chunks_zero_paths_lt_chunk,
        test_partial_fill_paths_50M_chunk_7M,
        test_chunk_not_divisible_by_sims_per_trial,
        test_negative_or_zero_inputs,
        test_valid_run_completes,
        test_validate_strategy_aggregates_duplicates,
        test_validate_strategy_offsetting_duplicates_ok,
        test_validate_strategy_unknown_symbol,
        test_validate_strategy_bad_side,
        test_validate_strategy_zero_or_negative_vol,
        test_user_greedy_55bp_caught,
        test_all_recommended_strategies_pass,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as e:
            failures.append((t.__name__, e))
            print(f"FAIL: {t.__name__}: {e}")
    print("="*70)
    if failures:
        print(f"{len(failures)}/{len(tests)} FAILED")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")
