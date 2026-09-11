# Round 3 — Hydrogel diagnostic dashboard (local)

This folder is a self-contained copy of:

- `hydrogel_dashboard.py` + `hydrogel_dashboard_requirements.txt`
- `hydrogel_full_diagnostic.py` (regenerate reports if needed)
- `dashboard_r3/` precomputed diagnostic outputs (`day0`, `day1`, `day2`)

## Prereqs

Python 3 with `pip`.

## Install deps

From this directory:

```bash
cd "$(git rev-parse --show-toplevel)/trader-logic/round-3/hydrogel"
python3 -m pip install -r hydrogel_dashboard_requirements.txt
```

If you plan to regenerate diagnostics with plots:

```bash
python3 -m pip install pandas numpy matplotlib
```

## Run the Streamlit dashboard

Still in this directory:

```bash
python3 -m streamlit run hydrogel_dashboard.py -- --reports-root "./dashboard_r3"
```

Then open the local URL Streamlit prints (typically `http://localhost:8501`).

In the sidebar, use **Reports / days** to pick which report folders to load. Each run is labeled like `Day 0 — day0` so a full backtest day and a website export for the same calendar day stay distinct (different colors in plots).

## Add an IMC website log next to `day0`…`day2` (optional)

A downloaded submission (e.g. `387381.log`) is JSON with an `activitiesLog` field: the same `;`-separated shape as the official `prices_round_3_day_*.csv`. To turn that into a normal diagnostic folder the dashboard can open:

```bash
cd "$(git rev-parse --show-toplevel)/trader-logic/round-3/hydrogel"
python3 website_activities_to_report.py \
  imc_website_logs/387381.log \
  --out "./dashboard_r3/day2_log_387381" \
  --product HYDROGEL_PACK
```

Optional: `--trades /path/to/trades_round_3_day_2.csv` if you want trade-join tables for that day. The website export is often only a **prefix** of the day (e.g. first 1000 ticks), so features that need long horizons are noisier than a full `day2` report.

Then run Streamlit with the same `dashboard_r3` root; select `Day 0 — day0` … and `Day 2 — day2_log_387381` (or similar) to cross-compare.

## Regenerate `dashboard_r3` (optional)

This folder lives under the `imc` monorepo at:

`imc/resources/prosperity4-tester-private/trader-logic/round-3/hydrogel`

So the bundled Round 3 CSVs in the main `imc` checkout are reachable as:

`../../../../../algo/round3_data/…`

From this folder:

```bash
cd "$(git rev-parse --show-toplevel)/trader-logic/round-3/hydrogel"
ROOT="./dashboard_r3"
for d in 0 1 2; do
  python3 ./hydrogel_full_diagnostic.py \
    --prices "../../../../../algo/round3_data/prices_round_3_day_${d}.csv" \
    --trades "../../../../../algo/round3_data/trades_round_3_day_${d}.csv" \
    --product HYDROGEL_PACK \
    --out "${ROOT}/day${d}" \
    --make-plots
done
```

If your folder layout differs, adjust the `--prices` / `--trades` paths accordingly.

Notes:

- Report folders should be named like `day0`, `day1`, `day2` so the dashboard can label/sort days reliably.
- The dashboard reads `enriched_HYDROGEL_PACK.csv` inside each day folder.
