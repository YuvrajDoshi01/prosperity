"""
refit_regression.py — Automatically refit microprice regression from new sample data.

Run:
    python refit_regression.py <path_to_prices_csv> <product_name>

Outputs:
    - Regression coefficients and intercept for the given product
    - Cross-validates on first/second half of the day
    - Prints paste-ready values for template_random_walk.py

CSV format expected: semicolon-delimited with columns including:
    product, bid_price_1, ask_price_1, bid_volume_1, ask_volume_1,
    (optional) bid_volume_2, ask_volume_2, mid_price
"""

import csv
import sys
import math


def load_microprices(fname, product):
    """Load microprice and mid-price series from a prices CSV.

    Microprice = bb + (bv / (bv + av)) * (ba - bb)
    Uses top-2 levels of book depth when available.
    """
    mps, mids = [], []
    with open(fname) as f:
        for r in csv.DictReader(f, delimiter=';'):
            if r['product'] == product:
                bb = float(r['bid_price_1'])
                ba = float(r['ask_price_1'])
                bv = int(r['bid_volume_1'])
                av = int(r['ask_volume_1'])
                # Add second level depth if available
                if r.get('bid_volume_2'):
                    bv += int(r['bid_volume_2'])
                if r.get('ask_volume_2'):
                    av += int(r['ask_volume_2'])
                mp = bb + (bv / (bv + av)) * (ba - bb) if (bv + av) > 0 else (bb + ba) / 2
                mps.append(mp)
                mids.append(float(r['mid_price']))
    return mps, mids


def fit_regression(mps, mids, dim=4):
    """Fit OLS regression: mid[t] ~ intercept + sum(coef[j] * mp[t-dim+j])

    Uses normal equations with Gaussian elimination.
    Small ridge regularization (1e-6) for numerical stability.
    Returns (intercept, coefs, rmse).
    """
    n = len(mps)
    X, Y = [], []
    for i in range(dim, n):
        X.append(mps[i - dim:i])
        Y.append(mids[i])

    k = dim
    # Build X^T X and X^T Y (with intercept column prepended)
    XtX = [[0] * (k + 1) for _ in range(k + 1)]
    XtY = [0] * (k + 1)
    for i in range(len(X)):
        row = [1.0] + X[i]
        for j in range(k + 1):
            XtY[j] += row[j] * Y[i]
            for l in range(k + 1):
                XtX[j][l] += row[j] * row[l]

    # Ridge regularization
    for j in range(k + 1):
        XtX[j][j] += 1e-6 * len(X)

    # Gaussian elimination with partial pivoting
    aug = [XtX[j][:] + [XtY[j]] for j in range(k + 1)]
    m = k + 1
    for col in range(m):
        mr = max(range(col, m), key=lambda r: abs(aug[r][col]))
        aug[col], aug[mr] = aug[mr], aug[col]
        for row in range(m):
            if row == col:
                continue
            f = aug[row][col] / aug[col][col]
            for j in range(m + 1):
                aug[row][j] -= f * aug[col][j]

    beta = [aug[j][m] / aug[j][j] for j in range(m)]
    intercept, coefs = beta[0], beta[1:]

    # RMSE
    ss = sum(
        (Y[i] - intercept - sum(coefs[j] * X[i][j] for j in range(k))) ** 2
        for i in range(len(X))
    )
    rmse = math.sqrt(ss / len(X))

    return intercept, coefs, rmse


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python refit_regression.py <prices.csv> <PRODUCT_NAME>')
        print()
        print('Example:')
        print('  python refit_regression.py round1_prices.csv KELP')
        sys.exit(1)

    fname, product = sys.argv[1], sys.argv[2]
    mps, mids = load_microprices(fname, product)
    print(f'Loaded {len(mps)} ticks for {product}')

    if len(mps) < 10:
        print('ERROR: Not enough data points. Check product name and CSV format.')
        sys.exit(1)

    # ── Full fit ──
    intercept, coefs, rmse = fit_regression(mps, mids)
    print(f'\nFull: intercept={intercept:.6f}, coefs={[round(c, 6) for c in coefs]}, RMSE={rmse:.4f}')
    print(f'Sum of coefs: {sum(coefs):.6f}')

    # ── Cross-validation: first half train, second half test ──
    half = len(mps) // 2
    i1, c1, r1 = fit_regression(mps[:half], mids[:half])
    i2, c2, r2 = fit_regression(mps[half:], mids[half:])
    print(f'\nFirst half:  intercept={i1:.4f}, coefs={[round(c, 4) for c in c1]}, RMSE={r1:.4f}')
    print(f'Second half: intercept={i2:.4f}, coefs={[round(c, 4) for c in c2]}, RMSE={r2:.4f}')

    # ── Average (most robust to unseen data) ──
    avg_int = (i1 + i2) / 2
    avg_coefs = [(c1[j] + c2[j]) / 2 for j in range(4)]
    print(f'\nAveraged: intercept={avg_int:.6f}, coefs={[round(c, 6) for c in avg_coefs]}')

    # ── Stability check ──
    coef_diff = [abs(c1[j] - c2[j]) for j in range(4)]
    print(f'Coef stability (abs diff): {[round(d, 4) for d in coef_diff]}')
    if max(coef_diff) > 0.1:
        print('WARNING: Large coefficient instability between halves. Consider more data or fewer lags.')

    # ── Paste-ready output ──
    print(f'\n# Paste into template_random_walk.py:')
    print(f'INTERCEPT = {avg_int:.6f}')
    print(f'COEFS = {[round(c, 6) for c in avg_coefs]}')
