# Atlanta Fed GDPNow Validation

Python validation utility for the Atlanta Fed GDPNow workbook:

- Loads stored values (not formula recalculation) from `data/GDPTrackingModelDataAndForecasts.xlsx`
- Recomputes GDP nowcast from contribution components in `ContribArchives`
- Compares against official nowcast in `TrackingArchives!AB` and `ContribArchives!X`
- Writes row-level CSV and summary JSON artifacts
- Includes a full GDPNow-style model clone pipeline (factor + bridge + BVAR + constrained blend + Fisher aggregation)

## Files

- `scripts/gdpnow_validate.py`: main validation script
- `scripts/gdpnow_plot.py`: plotting utility for model vs official nowcast
- `scripts/gdpnow_full_model.py`: full GDPNow-style model clone
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

Run the full GDPNow-style model clone:

```bash
python3 scripts/gdpnow_full_model.py --outdir outputs --no-kalman --factor-max-series 80
```

Full-model options:

- `--as-of-date YYYY-MM-DD`: run model as of a specific forecast date
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

## Current Run Snapshot

On the included workbook:

- `rows_total = 1801`
- `count_exceed_tol_tracking = 2` (small rounding-level differences in earliest rows)
- `count_exceed_tol_contrib = 0`

## Notes

- The script uses `openpyxl.load_workbook(..., data_only=True)` so it reads stored values only.
- It does not rely on Excel recalculation.
