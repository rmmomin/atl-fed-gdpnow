# Updated 2026 Q3 model run

Completed September 16, 2026. **The corrected approximation forecasts 3.6127% annualized real GDP growth for 2026 Q3**, compared with the Atlanta Fed's 4.4164% in the same workbook: a difference of **−0.8037 percentage points**. This is a successful execution of our approximation, not a successful exact replication of GDPNow.

## Data vintage

The newly downloaded [official workbook](https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx) is saved as `data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx`. The original February file is preserved. The new workbook's latest forecast date is **September 10**, not September 16. It does not include releases after that snapshot.

The official comparison comes from `TrackingHistory!U1` (September 10), `A2` (2026q3), and `U31` (4.4163597830737755). The saved file is unmodified; SHA-256 is `eb1ce08773a6f4f057dc6b57bb2f8479112bdb06652ad5886bc8fd97fe6e96da`. Source URL and retrieval metadata are in `data/GDPTrackingModelDataAndForecasts_2026-09-16.source.json`.

The refreshed file supplies quarterly actuals through 2026 Q2, Q3 component price forecasts, 146 monthly-level series and 148 transformed series. Of the 146 monthly series, 144 have later nonmissing endpoints than in the February file. Latest dates are June for seven series, July for 98, and August for 39. Two additional series are workbook deflator forecasts extending through December, not released observations. Model inputs dated after the forecast cutoff are masked.

## Results and code corrections

| Configuration | Model forecast | Official forecast | Difference, percentage points |
| --- | ---: | ---: | ---: |
| Corrected units, PCA 80 series | 3.612674% | 4.416360% | −0.803686 |
| Corrected units, PCA 126 series | 3.669056% | 4.416360% | −0.747304 |
| Legacy units, PCA 80; diagnostic only | 3.481104% | 4.416360% | −0.935256 |

Both corrected runs use six indicators per bridge, decay 0.98, and exclude 2020 from bridge/blend estimation. The Kalman option was not run. The 80-series setting follows the existing README baseline; the 126-series run measures sensitivity, not a confidence interval or independently selected best model. Results were not tuned to match the official headline.

Changes to `scripts/gdpnow_full_model.py`:

1. Read the active quarter from the transposed `TrackingHistory` sheet, together with archived quarters. Validate component labels and honor quarter/date filters.
2. Interpret ordinary `QtrlyActDLog` observations as `400 × log(q_t/q_{t−1})`. Reconstruct BVAR log levels correctly and convert bridge targets to compounded annual percentage growth before comparing or projecting quantities.
3. Represent inventory investment as a signed level divided by previous-quarter real GDP, as specified in [working-paper Table A1](https://fraser.stlouisfed.org/docs/historical/frbatl/wp/frbatl_wp_2014-07.pdf). Keep this ratio in levels in the BVAR and approximate bridge; multiply the forecast ratio by known Q2 real GDP for aggregation. Do not clip negative inventories as if they were percentage growth. The specialized GDPNow inventory model is still absent.
4. Exclude future-dated monthly values from monthly equation training and require previous-quarter quarterly inputs, rather than silently using an older quarter.
5. Save explicit component units, projected real levels, model/workbook hashes, snapshot dates, and limitations with the output.

The legacy result was saved before the unit corrections and is retained only to distinguish the effect of refreshing the data from correcting the implementation. Its summary lists the known unit errors. It should not be used as the final forecast.

## Why the remaining gap matters

The corrected 80-series run still differs substantially by component:

| Component | Model growth | Official growth |
| --- | ---: | ---: |
| PCE goods | 2.73% | 1.85% |
| PCE services | 3.87% | 4.35% |
| Equipment | 11.36% | 17.37% |
| Services exports | 14.95% | 5.09% |
| Services imports | −8.18% | 2.21% |
| Federal government | −2.27% | 1.97% |

These are component growth rates, not contributions to GDP or to the headline error. Offsetting trade errors can make the headline look closer than the components justify. Our inventory investment forecast is $25.534 billion in chained 2017 dollars; the official workbook's current-quarter inventory forecast is $63.158 billion (`TrackingHistory!U27`). The official previous-quarter inventory estimate also includes adjustments absent from our approximation, so that difference cannot be interpreted as a standalone GDP contribution error.

The model still uses generic correlation-selected bridges and estimated blends instead of the Fed's granular consumption, trade and inventory routines. It borrows official component price forecasts and six component blend weights. The factor panel is selected from available series rather than reconstructing the complete prescribed panel. Correcting units does not address those structural differences. The remaining work is not solely obtaining missing observations.

## Data gaps after the refresh

The workbook now supplies **812 monthly observations through August 2026** for manufacturing PMI (`NAPMC_USECON`), manufacturing inventories (`NAPMII_USECON`), and manufacturing prices (`NAPMPI_USECON`) in `InventoryRaw`. August values are 54.6, 50.6, and 71.1, respectively. These series remain outside the approximate model's factor loader.

Five ISM histories remain absent from the monthly input panels and `InventoryRaw` checked here: manufacturing production, employment, new orders, supplier deliveries, and services PMI. Reconstructing the prescribed factor panel requires those histories and the correct transformations/vintages. Missing long histories do not prevent this reduced approximation from running.

The separate public BEA gold download is already available in `data/bea/`. This rerun uses the fresh workbook's constructed trade series; it does not apply an additional manual gold subtraction or independently rebuild the gold-adjustment module.

Among the 54 monthly indicators selected by the corrected 80-series run, three July cells, 39 August cells, and all 54 September cells are missing. These are gaps in the September 10 snapshot that the monthly forecasting/fallback routines must fill, not proof that the underlying sources are inaccessible. An intraday September 16 forecast would require a later official workbook or a separately maintained source-data release pipeline. Historical replication also still requires matching release vintages.

Full coverage is recorded in `data_refresh_summary.json` and `monthly_data_coverage.csv`.

## Verification and reproduction

Nine regression tests pass, covering current/archive quarter selection, date cutoffs, malformed labels, log-growth units, signed inventory normalization, Fisher import/inventory signs, and exclusion of future monthly values. Both corrected full runs finish with finite results.

Separately, the refreshed workbook's 1,871 archived contribution rows reconcile to `ContribArchives` within 1.02e-12 percentage points. Two early 2014 rows differ from rounded `TrackingArchives` headlines, with maximum difference 0.0000310694 percentage points. This checks published arithmetic; it does not validate our forecasting equations or the current-quarter model.

Runtime: Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, openpyxl 3.1.5, statsmodels 0.15.0. Runs used `/tmp/atl-gdpnow-audit-20260916/venv/bin/python`; a durable environment can install the requirements listed in the project README.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/gdpnow_full_model.py data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx --quarter 2026Q3 --no-kalman --factor-max-series 80 --outdir outputs/2026Q3_2026-09-10/pca80
python3 scripts/gdpnow_full_model.py data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx --quarter 2026Q3 --no-kalman --factor-max-series 126 --outdir outputs/2026Q3_2026-09-10/pca126
python3 scripts/gdpnow_validate.py data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx --outdir outputs/2026Q3_2026-09-10/archive_reconciliation
```

The main result is in `pca80/gdpnow_full_model_summary.json`; its component comparison is `pca80/gdpnow_full_model_components.csv`. `--as-of-date` selects a forecast row within the supplied snapshot but cannot undo subsequent revisions or restore historical release availability. A zero process exit indicates successful execution, not agreement with the official model.
