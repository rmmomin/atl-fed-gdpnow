# ISM data reconstructed from monthly releases

**Yes: the eight required indexes can be recovered from public monthly releases.** This initial collection demonstrates extraction, joins overlapping reports, preserves revisions, and checks overlap with the GDPNow workbook. It does not establish complete long-run coverage or exact reproduction of the September 2026 historical vintage.

As collected September 16, 2026:

- Seven reports parsed: manufacturing January 2020, November 2025, February/May/August 2026; services February/August 2026.
- 204 observations including repeated release vintages; 153 unique series/month pairs.
- **All eight series are present for 13 consecutive months, August 2025–August 2026.** Older entries are sparse and must not be read as a continuous 2019–2026 dataset.
- All 24 January–August 2026 values overlapping the workbook's three existing series (manufacturing PMI, inventories, prices) match exactly.
- Twelve series/month pairs have different values in different collected releases. Twenty of the 67 total overlapping values differ from the September 10 GDPNow workbook; all 20 are before 2026. These are flagged rather than overwritten.

## How the releases help

The [August manufacturing release](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/august/) supplies all seven required manufacturing indexes. Its detailed subindex tables each show four months; its headline PMI history shows twelve. The [August services release](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/services/august/) supplies a twelve-month services composite history. For recent coverage, downloading every monthly release is therefore unnecessary.

ISM's February and May manufacturing HTML pages are currently removed, but ISM-issued releases remain on PR Newswire. The [February 2026 manufacturing release](https://www.prnewswire.com/news-releases/manufacturing-pmi-at-52-4-february-2026-ism-manufacturing-pmi-report-302699883.html) and [May release](https://www.prnewswire.com/news-releases/manufacturing-pmi-at-54-may-2026-ism-manufacturing-pmi-report-302786165.html) fill the recent gap. The [January 2020 release](https://www.prnewswire.com/news-releases/pmi-at-50-9-gdp-growing-at-2-4-january-2020-manufacturing-ism-report-on-business-300997110.html) demonstrates that older detailed tables also survive. This sample does not prove that every earlier release is obtainable.

The parser takes the reported Index column, not the raw percentage reporting higher or lower activity. It keeps services composite PMI separate from business activity and from the manufacturing comparison columns embedded in services reports.

## Revisions and seasonal adjustment

The [November 2025 release](https://www.prnewswire.com/news-releases/manufacturing-pmi-at-48-2-november-2025-ism-manufacturing-pmi-report-302626979.html) reports manufacturing PMI of **48.2**. The February 2026 release's historical table reports the same reference month as **48.0**. Both observations are retained with their publication dates. Selecting the November value by its reference month alone would conceal the revision and could introduce information unavailable at the original forecast date.

ISM's [annual-adjustment announcement](https://www.prnewswire.com/news-releases/ism-makes-annual-adjustments-to-seasonal-factors-for-manufacturing-pmi-non-manufacturing-nmi-and-diffusion-indexes-300992545.html) documents multi-year revisions and the formula combining adjusted subindexes. In the releases parsed here, manufacturing new orders, production, employment and inventories are seasonally adjusted; supplier deliveries and prices are unadjusted. PMI composites combine adjusted and unadjusted subindexes. Older periods require their own methodology checks.

`latest_collected` means the latest publication **among these collected reports**, not a certified latest-revised ISM history. For example, August–October 2025 inventories still come from the November 2025 release and differ from the later GDPNow workbook. The 13-month panel has full coverage but mixes publication vintages. To reproduce September 2026 GDPNow exactly, we must obtain the applicable revised history, or reconstruct it with adequate underlying data and matching adjustment factors. Raw survey percentages printed to one decimal are not guaranteed to recover exact revised indexes.

## Files

| File | Purpose |
| --- | --- |
| `complete_eight_series_months.csv` | The 13-month, eight-series panel; mixed vintages as described above |
| `latest_collected.csv` | All collected reference months, with explicit blanks for missing series |
| `latest_collected_with_sources.csv` | Same selected observations, retaining source and release-date metadata |
| `observations_by_release.csv` | All values by publication vintage, including revisions |
| `workbook_crosscheck.csv` | Comparison against the three overlapping workbook series |
| `coverage_summary.json` | Coverage, revision counts and validation results |
| `releases.json` | Source URLs, report months and release dates |
| `source_provenance.json` | Source metadata and cached HTML hashes |
| `raw/` | Retrieved release HTML |

The collector is `scripts/ism_press_releases.py`. Add a verified URL, sector, report month and release date to `releases.json` to extend coverage. It rejects pages with an unexpected month/year or sector, missing current-month indexes, inconsistent within-report values, and conflicting same-date observations. Release dates for the current ISM pages are verified against the [official calendar](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/); PR Newswire publication metadata are checked directly.

```sh
python3 -m pip install pandas beautifulsoup4 openpyxl statsmodels
python3 scripts/ism_press_releases.py --fetch-missing --workbook data/GDPTrackingModelDataAndForecasts_2026-09-16.xlsx
python3 -m unittest discover -s tests -v
```

For a historical information cutoff, pass `--as-of-date YYYY-MM-DD` and a separate `--outdir`. The filter uses **report publication date**. It cannot supply releases or revisions that have not been collected. Current ISM URLs may later change or disappear; cached files and hashes preserve this collection.

## Remaining work for GDPNow

Continue backfilling manufacturing production, employment, new orders and supplier deliveries, plus services composite PMI, over the required estimation sample. Reconcile seasonal-adjustment vintages and historical series definitions. Keep the three long workbook histories for PMI, inventories and prices, using the release collection as a validation/update source. Then connect the completed histories to the prescribed factor and other model inputs and validate the resulting model.

This collection has not been wired into the approximation or used to rerun GDP growth. Thirteen recent months do not provide the long estimation history required by the missing factor inputs. The previous 3.61% Q3 result is unchanged.
