# GDPNow replication audit

Audit date: September 16, 2026. This is the **pre-update audit** of the supplied February workbook and original Python implementation. No model code or source workbooks were changed during that audit. The subsequent data refresh, code corrections, and 2026 Q3 results are documented in [the updated run report](2026Q3_2026-09-10/run_report.md). Findings and code line references below describe the original implementation.

## Conclusion

The repository does not currently reproduce the GDPNow forecasting model. It successfully reconciles published GDP contributions to the published headline, and it runs a GDPNow-inspired statistical approximation. These are different accomplishments.

Missing historical data vintages are a real obstacle to replaying past forecasts. However, several substantial implementation errors and omitted model modules already explain why adding more data alone will not produce a faithful replication. Much of the information needed to reconstruct the supplied workbook's calculation is already present but unused.

## Checks executed

| Check | Result |
| --- | --- |
| Contribution reconciliation, all 1,801 archive rows | All match `ContribArchives` to numerical precision. Against `TrackingArchives`, two early rows exceed 1e-8; largest difference is 0.0000310694 percentage points. |
| README model command: PCA, 80 series | 3.5958305368100962% versus 2.9989686770822033%, a +0.596861859727893 percentage point difference. This reproduces the saved result. |
| PCA, 126 series | 3.5833031740211574% versus 2.9989686770822033%, approximately +0.584334 percentage points. Increasing the panel does not resolve the mismatch. |
| Request `--quarter 2026Q1` | Fails with `No TrackingArchives rows match requested as-of date / quarter.` |
| Validator `--fisher-check` | Skips; no historical Fisher aggregation is actually validated. |

Both model runs select February 19, 2026 and forecast 2025 Q4. The Kalman estimation option was inspected in code but was not executed in this audit. These results are a replication check against GDPNow, not a forecast-accuracy evaluation against subsequent BEA GDP.

The model's headline proximity conceals large component errors. In the 80-series run, reported annualized component growth rates are:

| Component | Clone | Official archive | Difference, percentage points |
| --- | ---: | ---: | ---: |
| PCE goods | 10.6802% | 0.8088% | +9.8714 |
| Goods exports | -20.9409% | -0.5966% | -20.3443 |
| Goods imports | -8.8335% | -0.7557% | -8.0778 |
| Federal government | -3.7252% | 1.1242% | -4.8494 |

These are component growth errors, not contributions to the headline error. Export and import errors can offset in GDP aggregation.

## Confirmed implementation problems

1. **Quarterly growth units are misread.** For 12 ordinary components, `QtrlyActDLog` contains `400 * log(current / previous)`. The program's `growth_to_log_level()` instead treats these values as compounded annual percentage growth and applies `log1p(g / 100) / 4`. For example, 2025 Q3 PCE goods is 3.000961319613 in the sheet, exactly matching annualized log growth; compounded annual percentage growth from the same levels is 3.046443996267. The bridge equations also combine these log-growth targets with compounded-growth predictors, and their forecasts are subsequently treated as compounded growth. See [conversion](/Users/rayhanmomin/code/atl-gdpnow/scripts/gdpnow_full_model.py:87), [BVAR reconstruction](/Users/rayhanmomin/code/atl-gdpnow/scripts/gdpnow_full_model.py:570), and [aggregation input](/Users/rayhanmomin/code/atl-gdpnow/scripts/gdpnow_full_model.py:852).

2. **Inventories have a different unit entirely.** `QtrlyActDLog!JJ14` is -23,942 for 2025 Q3, matching real inventory investment in millions of chained dollars in `QtrlyGDPData!JJ31`. It is not a growth rate. The same conversion incorrectly processes the inventory series and clips 43 of 267 observations to -99.9 before taking logarithms. The resulting BVAR output is 3,438.19 in what the code treats as percentage-growth units. The generic bridge is clipped to 80, and the final blend is 247.91. The specialized inventory calculations and valuation adjustments are not implemented.

3. **The bridge equations are substitutes for the actual equations.** `select_component_indicators()` picks six series by absolute historical correlation. The Fed's granular source-to-component mappings, published bridge coefficients, consumption equations, and specialized net-export/inventory routines are not reproduced. The workbook already has `BridgeEqnCoeffs`, `FactorAugARCoeffs`, `ConsFactorAugARCoeffs`, `UtilTravelCoeffs`, inventory sheets, and component calculation sheets that the clone does not use.

4. **Special blending weights are missed.** The workbook supplies weights for inventories and goods/services net-export contributions under `PTVH_USNAqtr`, `PTXNETMH_USNAqtr`, and `PTXNETSH_USNAqtr`. The program looks up inventory and separate trade growth tickers instead, so these weights never match. It estimates alternative weights and clips them to 0.05–0.95. It also applies generic blending to consumption.

5. **The target forecast and input vintage do not match.** `TrackingHistory!C1` is February 20, 2026; its current forecast is 2026 Q1, with GDPNow 3.1261025675693332% at `C31`. `CurrentQtrEvolution!A2:B2` confirms that date and quarter. The model selects only from `TrackingArchives`, obtaining February 19's 2025 Q4 forecast, while using the February 20 workbook's data, prices, and weights. The quarterly data already contain 2025 Q4 actual values. This is not a reconstruction of the information available on February 19.

6. **`--as-of-date` does not reconstruct historical information availability.** It selects an archive row and filters some observations by their month-end dates. It does not restore the values and releases actually available on the requested day. A December observation released in February remains a December-dated observation. The repository has one input workbook, rather than snapshots for every archived forecast date.

7. **Other econometric stages differ.** The factor panel is selected by nonmissing history length rather than the Fed's prescribed panel. The PCA option uses zero-imputation; the Kalman option fits a generic maximum-likelihood `DynamicFactor`. Monthly equations use fixed lag counts instead of the documented selection and pandemic-dummy specifications. The quarterly BVAR prior and estimation sample are not established as equivalent to the official implementation. Price forecasts and some blending weights are read from the Fed workbook, so this is also not an independent rebuild of every stage.

The official [working paper](https://fraser.stlouisfed.org/docs/historical/frbatl/wp/frbatl_wp_2014-07.pdf) describes granular bridges, special consumption/trade/inventory modules, and separate price forecasting. The [model modifications](https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/cqer/researchcq/gdpnow/ModificationsToGDPNowModel.pdf) add subsequent changes, including pandemic treatment, contribution-based trade/inventory blending, gold-trade adjustments, and 2025 price/data-center changes. These specifications need to be followed at the component level.

## What data are missing?

**For this workbook:** missing data are not the only or demonstrated principal blocker. The program loads 146 monthly-level series and 148 transformed series, and all 13 required quarterly component tickers are available. Its 56 selected monthly indicators have nine missing observations across the three target-quarter months, concentrated in construction and previous-vintage series. The previous quarter has none missing for those selected indicators. Missing recent monthly observations are an expected forecasting task, not proof that the whole underlying data source is absent. This limited check does not certify completeness of every input required by the official model.

**For historical replication:** the missing data are release-specific input vintages, contemporaneous model parameters and transformations, and model-version information. Archived headline/component forecasts are available, but one revised workbook cannot recover all earlier input states. The workbook's `PseudoRT*` sheets explicitly describe evaluation using revised data current as of April 26, 2016, rather than a complete archive of real-time input vintages.

**For an independently updated model:** the repository has no data-download pipeline or verified mapping from its Haver/constructed mnemonics to source series. The supplied FRED availability spreadsheet is a preliminary inventory, not an executable mapping. It labels 399 entries: 281 Yes, 69 Maybe, 44 constructed, three ISM, and two BEA gold series. It has no FRED-ID column, and some Yes entries explicitly describe predicted revisions or forecast values. Those labels should not be treated as verified downloadable series.

FRED alone is insufficient. [The St. Louis Fed removed ISM series](https://news.research.stlouisfed.org/2016/06/institute-for-supply-management-data-to-be-removed-from-fred/), so they need an appropriate alternative source. The Atlanta Fed modifications identify BEA balance-of-payments gold series `MNMGLD` and `XNMGLD`; those adjustments cannot simply be replaced with Census-basis gold totals. Constructed/spliced series and custom seasonal adjustments also need documented reconstruction or an equivalent provider. Some such values already exist in the supplied workbook; the gap is independent sourcing and reproducible transformations, not necessarily absent cells in this snapshot.

**Follow-up verification, September 16:** the BEA gold series are publicly available and have now been downloaded without authentication from [BEA's IDS-0182 current-installment ZIP](https://apps.bea.gov/international/zip/IDS0182.zip). They are not an access or licensing blocker. The [BEA source page](https://www.bea.gov/international/detailed-trade-data) dates this release September 3, 2026, and lists the next update as October 6. The two workbooks' `BP-based, SA` sheets contain `MNMGLD` and `XNMGLD` through July 2026; August and September cells are blank. July imports are 1,907.767 million dollars and exports are 5,416.679 million dollars, both monthly seasonally adjusted amounts, not annualized. The original ZIP and 38 extracted gold observations for January 2025–July 2026 are saved in `data/bea/IDS0182_release_2026-09-03.zip` and `data/bea/gold_bp_sa_release_2026-09-03.json`. Integration into the model remains to be implemented. BEA also provides historical ZIPs back to 1989, which were not downloaded in this follow-up; a revised historical series is not a complete archive of release vintages.

### ISM requirements clarified

The preliminary FRED inventory's three ISM entries are incomplete for replicating the full model. The working paper's Table A4 and this workbook's `FactorAugARCoeffs` identify seven factor inputs: manufacturing composite PMI (`NAPMC@USECON`), production (`NAPMOI@USECON`), employment (`NAPMEI@USECON`), new orders (`NAPMNI@USECON`), inventories (`NAPMII@USECON`), supplier deliveries (`NAPMVDI@USECON`), and services composite PMI (`NMFC@SURVEYS`). Table A2 additionally uses manufacturing prices (`NAPMPI@USECON`) in price forecasting, giving eight distinct ISM series overall.

`InventoryRaw` contains 805 observations each, January 1959–January 2026, for manufacturing composite PMI, inventories, and prices, under underscore-form mnemonics in rows 9, 10, and 93. Those histories can be reused, subject to vintage consistency. The other five histories are absent from the monthly input panels checked here. All seven ISM factor inputs are absent from `MonthlyLevels` and `TransformedMonthlySeries`, despite their presence in `FactorAugARCoeffs`; the current Python factor loader does not recover PMI and inventories from `InventoryRaw`.

To update the three existing series, collect February–August 2026 observations and any revisions. To independently estimate the full factor model, also obtain long histories for production, employment, new orders, supplier deliveries, and services PMI through August, covering the model's estimation window and each series' available start date. Preserve the published index levels, adjustment status, reference month, release date, and vintage. Factor inputs have transformation code 0 (levels before standardization), not percentage growth. Published current manufacturing new orders, production, employment, and inventories are seasonally adjusted; supplier deliveries and prices are not. Historical workbook descriptions label supplier deliveries SA, so reconcile metadata and observations before assuming historical adjustment equivalence.

The latest observations are publicly displayed in [ISM's August manufacturing report](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/august/) and [August services report](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/services/august/). As of September 16, both July and August readings are released. September readings are not yet available: the reports list October 1 for manufacturing and October 5 for services. These latest readings are obtainable; the remaining ISM data tasks are filling the historical gaps, updating vintages, and connecting the appropriate series to the implemented factor/inventory/price stages. No ISM observations were added to the source workbook in this audit.

## Feasibility and next steps

- **Published-output reconciliation:** achieved, to rounding/numerical precision.
- **Reconstruction of one workbook snapshot:** a reasonable next milestone, with substantial supporting data and parameters already supplied. Exact success has not been demonstrated. Fix units and target-date selection, then port the component sheets and reconcile each stage against that same snapshot.
- **Independent live GDPNow replica:** requires the official component logic plus a verified, versioned data pipeline, including non-FRED inputs and constructed series.
- **Exact replay of the historical forecast path:** cannot be established from the current repository. Acquire archived input workbooks or reconstruct each release vintage before treating a historical comparison as a valid replication test.

Atlanta Fed's [FAQ](https://www.atlantafed.org/research-and-data/data/gdpnow) says it does not share its source code, while the workbook supplies raw data, parameters, and numerical mapping details. This makes exact replication an engineering and validation task; it does not establish that replication is impossible.

Recommended order: correct units and inventory representation; support the workbook's current forecast; reproduce component equations and aggregation using published intermediate values; replace those values with independently estimated equivalents; finally validate multiple dates with matching historical inputs. More indicators or tuning the headline to 3.00% should not be the next step.

## Reproduction notes

Commands run with Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, openpyxl 3.1.5, and statsmodels 0.15.0. Missing statsmodels dependencies were installed in a temporary virtual environment. The repository does not pin dependency versions.

```sh
python scripts/gdpnow_validate.py --outdir /tmp/atl-gdpnow-audit-20260916/validation --fisher-check
python -W ignore scripts/gdpnow_full_model.py --outdir /tmp/atl-gdpnow-audit-20260916/model80 --no-kalman --factor-max-series 80
python -W ignore scripts/gdpnow_full_model.py --outdir /tmp/atl-gdpnow-audit-20260916/model126 --no-kalman --factor-max-series 126
python -W ignore scripts/gdpnow_full_model.py --quarter 2026Q1 --no-kalman --outdir /tmp/atl-gdpnow-audit-20260916/current-quarter
```

The validator returns exit code zero even with mismatches (`count_exceed_tol_tracking >= 0`), and the full model returns zero whenever its headline is finite. Successful process exit is not a replication pass.
