# Atlanta Fed GDPNow Validation

Python validation utility for the Atlanta Fed GDPNow workbook:

- Loads stored values (not formula recalculation) from `data/GDPTrackingModelDataAndForecasts.xlsx`
- Recomputes GDP nowcast from contribution components in `ContribArchives`
- Compares against official nowcast in `TrackingArchives!AB` and `ContribArchives!X`
- Writes row-level CSV and summary JSON artifacts

## Files

- `scripts/gdpnow_validate.py`: main validation script
- `scripts/gdpnow_plot.py`: plotting utility for model vs official nowcast
- `outputs/gdpnow_validation_results.csv`: row-level comparison output (generated)
- `outputs/gdpnow_validation_summary.json`: summary metrics (generated)
- `outputs/gdpnow_model_vs_official.png`: comparison chart (generated)
- `data/GDPTrackingModelDataAndForecasts.xlsx`: source workbook

## Requirements

- Python 3.11+ (recommended)
- `pandas`
- `numpy`
- `openpyxl`

Install dependencies:

```bash
python3 -m pip install pandas numpy openpyxl
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
