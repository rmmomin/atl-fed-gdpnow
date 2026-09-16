# Atlanta Fed GDPNow Validation

Python validation utility for the Atlanta Fed GDPNow workbook:

- Loads stored values (not formula recalculation) from `data/GDPTrackingModelDataAndForecasts.xlsx`
- Recomputes GDP nowcast from contribution components in `ContribArchives`
- Compares against official nowcast in `TrackingArchives!AB` and `ContribArchives!X`
- Writes row-level CSV and summary JSON artifacts
- Includes an approximate GDPNow-style pipeline (factor + bridge + BVAR + blend + Fisher aggregation). It is not an exact independent replication.

## Updated 2026 Q3 run

Downloaded the official workbook on September 16, 2026. Its latest forecast is dated **September 10, 2026**; downloading it today does not incorporate later releases. The February workbook remains available under its original filename.

| Run | Real GDP growth, annualized |
| --- | ---: |
| Corrected model, PCA with 80 series | 3.6127% |
| Corrected model, PCA with 126 series | 3.6691% |
| Atlanta Fed, same September 10 snapshot | 4.4164% |

The active-quarter loader and quarterly growth/inventory units have been corrected. Generic component bridges, incomplete factor inputs, borrowed price forecasts and weights, and missing specialized inventory/trade calculations still prevent exact replication. See [the run report](outputs/2026Q3_2026-09-10/run_report.md), [data coverage](outputs/2026Q3_2026-09-10/data_refresh_summary.json), and [source provenance](data/GDPTrackingModelDataAndForecasts_2026-09-16.source.json).

Reproduce the corrected 80-series run:

```bash
python3 scripts/gdpnow_full_model.py data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx \
  --quarter 2026Q3 --no-kalman --factor-max-series 80 \
  --outdir outputs/2026Q3_2026-09-10/pca80
```

The workbook is local and ignored by Git. Its official download URL and SHA-256 are in the provenance file; that live URL will eventually serve a newer vintage. Pass the dated workbook explicitly, since the default filename still refers to the original snapshot. Run regression checks with `python3 -m unittest discover -s tests -v`.

## Files

ISM backfill: [data/ism/README.md](data/ism/README.md) documents the release-based collector and recovered eight-series panel for August 2025–August 2026. Source release vintages and revision differences are preserved. This initial collection is not yet connected to the model.

- `scripts/gdpnow_validate.py`: main validation script
- `scripts/gdpnow_plot.py`: plotting utility for model vs official nowcast
- `scripts/gdpnow_full_model.py`: approximate GDPNow-style model
- `outputs/gdpnow_validation_results.csv`: row-level comparison output (generated)
- `outputs/gdpnow_validation_summary.json`: summary metrics (generated)
- `outputs/gdpnow_model_vs_official.png`: comparison chart (generated)
- `outputs/gdpnow_full_model_components.csv`: component-level full-model output (generated)
- `outputs/gdpnow_full_model_summary.json`: topline full-model summary (generated)
- `data/GDPTrackingModelDataAndForecasts.xlsx`: source workbook

## Requirements

- Python 3.11+ (recommended)
- `pandas`
- `numpy`
- `openpyxl`
- `statsmodels`

Install dependencies:

```bash
python3 -m pip install pandas numpy openpyxl statsmodels
```

## Usage

Default workbook path:

```bash
python3 scripts/gdpnow_validate.py
```

Explicit workbook and output directory:

```bash
python3 scripts/gdpnow_validate.py data/GDPTrackingModelDataAndForecasts.xlsx --outdir outputs
```

Options:

- `--tol`: absolute tolerance for mismatch counting (default: `1e-8`)
- `--outdir`: output directory for CSV/JSON artifacts (default: `outputs/`)
- `--fisher-check`: optional deeper check; script prints a clear skip message if direct mapping is not identifiable

Generate the comparison plot:

```bash
python3 scripts/gdpnow_plot.py --csv outputs/gdpnow_validation_results.csv --out outputs/gdpnow_model_vs_official.png
```

Run the approximate model on the original workbook:

```bash
python3 scripts/gdpnow_full_model.py --outdir outputs --no-kalman --factor-max-series 80
```

Full-model options:

- `--as-of-date YYYY-MM-DD`: select a forecast row on or before this date; this does not reconstruct historical data vintages
- `--quarter YYYYQn`: force a target quarter
- `--top-indicators`: monthly indicators per bridge equation (default: `6`)
- `--factor-max-series`: transformed monthly series count for factor estimation (default: `126`)
- `--no-kalman`: use PCA factor only (faster; Kalman path is default when omitted)
- `--decay`: time-decay for weighted regressions (default: `0.98`)
- `--include-pandemic-2020`: include 2020Q1–Q4 in blend/bridge weight estimation

## Validation Logic

The primary Python nowcast is:

`PCE + Fixed Investment + Government + Change in net exports + Change in inventory investment`

Compared series:

- `TrackingArchives!AB` (`GDP Nowcast`)
- `ContribArchives!X` (`GDP Nowcast`)

Key handling:

- Verifies required headers by exact Excel column letter
- Converts date keys (`Forecast Date`, `Quarter being forecasted`) to datetime
- Drops blank key rows
- Deduplicates duplicate key rows (keeps first, logs warning)
- Inner-merges on the two key columns

## Output Columns (`outputs/gdpnow_validation_results.csv`)

- `Forecast Date`
- `Quarter being forecasted`
- `GDP Nowcast (TrackingArchives AB)`
- `GDP Nowcast (Python from ContribArchives components)`
- `GDP Nowcast (ContribArchives X)`
- `diff_tracking`
- `diff_contrib`
- `abs_diff_tracking`
- `abs_diff_contrib`

## Original February Workbook Reconciliation

On the included workbook:

- `rows_total = 1801`
- `count_exceed_tol_tracking = 2` (small rounding-level differences in earliest rows)
- `count_exceed_tol_contrib = 0`

## Notes

- The script uses `openpyxl.load_workbook(..., data_only=True)` so it reads stored values only.
- It does not rely on Excel recalculation.
