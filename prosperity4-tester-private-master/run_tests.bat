@echo off
REM Run all strategies under calibrated backtester (website-like conditions)
REM Execute from: c:\Users\gurms\PycharmProjects\imc-prosperity-4-backtester\

echo ============================================
echo IMC Prosperity 4 — Strategy Comparison
echo Calibrated backtester: 2k ticks, 1000 iterations
echo ============================================
echo.

for %%f in (s2_tradeflow s3_tight_only s3_carry s3_aggressive) do (
    echo --- %%f ---
    python -m prosperity4bt "trader-logic/round-0/%%f.py" 0--1 --no-out --no-progress --ticks 2000 --iterations 1000 2>&1 | findstr /C:"TOMATOES" /C:"EMERALDS" /C:"Total"
    echo.
)

echo ============================================
echo Diagnostics (also run these on WEBSITE)
echo ============================================
echo.

for %%f in (diag_tight diag_conversions) do (
    echo --- %%f ---
    python -m prosperity4bt "trader-logic/round-0/%%f.py" 0--1 --no-out --no-progress --ticks 2000 --iterations 1000 2>&1 | findstr /C:"TOMATOES" /C:"EMERALDS" /C:"Total"
    echo.
)

echo Done. Now submit diag_tight.py to website and compare fill counts.
