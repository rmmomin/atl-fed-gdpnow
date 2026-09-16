"""Regression checks for snapshot selection and the workbook's mixed units."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gdpnow_full_model as model


class TrackingSelectionTests(unittest.TestCase):
    def setUp(self):
        self.archive = pd.DataFrame([{
            "Forecast Date": pd.Timestamp("2026-07-28"),
            "Quarter being forecasted": pd.Timestamp("2026-06-30"),
            "GDP Nowcast": 1.5,
        }])
        labels = ["GDP Nowcast", "2- PCE Goods**", "3- PCE Services**",
                  "7- Equipment**", "8- Intellectual Property Products**",
                  "9- Structures**", "10- Residential**", "12- Federal**",
                  "13- State and Local**", "15- Goods**", "16- Services**",
                  "18- Goods**", "19- Services**"]
        self.history = pd.DataFrame([
            [None, None, pd.Timestamp("2026-09-03"), pd.Timestamp("2026-09-10")],
            ["Evolution of GDP nowcast and components for 2026q3", None, None, None],
            *[[None, label, 4.7, 4.4] for label in labels],
        ])

    def load(self, cutoff=None, quarter=None):
        def read(path, sheet_name, **kwargs):
            return (self.archive if sheet_name == "TrackingArchives" else self.history).copy()
        with patch.object(model.pd, "read_excel", side_effect=read):
            return model.load_tracking_latest(
                Path("fixture.xlsx"), pd.Timestamp(cutoff) if cutoff else None,
                pd.Period(quarter, "Q") if quarter else None,
            )

    def test_default_uses_active_quarter(self):
        row = self.load()
        self.assertEqual(row["tracking_sheet"], "TrackingHistory")
        self.assertEqual(row["Quarter being forecasted"], pd.Timestamp("2026-09-30"))
        self.assertEqual(row["GDP Nowcast"], 4.4)

    def test_date_cutoff_applies_to_active_quarter(self):
        row = self.load("2026-09-05", "2026Q3")
        self.assertEqual(row["Forecast Date"], pd.Timestamp("2026-09-03"))
        self.assertEqual(row["GDP Nowcast"], 4.7)

    def test_archived_quarter_remains_selectable(self):
        self.assertEqual(self.load(quarter="2026Q2")["tracking_sheet"], "TrackingArchives")

    def test_unavailable_quarter_fails(self):
        with self.assertRaisesRegex(ValueError, "No TrackingArchives or TrackingHistory"):
            self.load(quarter="2026Q4")

    def test_changed_labels_fail_instead_of_silent_mismapping(self):
        self.history.iloc[3, 1] = "Unexpected goods label"
        with self.assertRaisesRegex(ValueError, "Expected one TrackingHistory row"):
            self.load()


class UnitTests(unittest.TestCase):
    def test_log_growth_matches_independently_computed_level_growth(self):
        quantities = pd.Series([100.0, 125.0, 80.0, 100.0])
        native = 400.0 * np.log(quantities / quantities.shift())
        levels = model.growth_to_log_level(native)
        np.testing.assert_allclose(np.exp(levels.iloc[1:]), quantities.iloc[1:] / 100.0)
        annual_percent = 100.0 * np.expm1(native / 100.0)
        np.testing.assert_allclose(annual_percent.iloc[1:],
                                  100.0 * ((quantities / quantities.shift()).iloc[1:] ** 4 - 1))

    def test_inventory_uses_signed_level_divided_by_lagged_gdp(self):
        dates = pd.date_range("2025-03-31", periods=4, freq="QE")
        native = pd.DataFrame(4.0, index=dates, columns=model.COMPONENT_TICKERS)
        native[model.INVENTORY_TICKER] = [-100.0, -50.0, 0.0, 100.0]
        real = pd.DataFrame({"GDPZ_USNA": [1000.0, 2000.0, 4000.0, 8000.0]}, index=dates)
        targets, states = model.prepare_quarterly_inputs(native, real)
        np.testing.assert_allclose(targets[model.INVENTORY_TICKER].iloc[1:], [-0.05, 0.0, 0.025])
        pd.testing.assert_series_equal(states[model.INVENTORY_TICKER], targets[model.INVENTORY_TICKER])
        self.assertAlmostEqual(targets[model.INVENTORY_TICKER].iloc[-1] * real["GDPZ_USNA"].iloc[-2], 100.0)
        self.assertAlmostEqual(targets["CTGZ_USNAqtr"].iloc[0], 100 * np.expm1(0.04))

    def test_fisher_accepts_negative_inventory_and_subtracts_imports(self):
        previous = dict.fromkeys(model.COMPONENT_TICKERS, 100.0)
        previous[model.INVENTORY_TICKER] = -20.0
        current = {**previous, model.INVENTORY_TICKER: 10.0}
        prices = dict.fromkeys(model.COMPONENT_TICKERS, 1.0)
        actual = model.fisher_growth_saar(previous, current, prices, prices)
        # Twelve ordinary components, with two imports subtracted: 800.
        self.assertAlmostEqual(actual, 100 * ((810 / 780) ** 4 - 1))

    def test_monthly_forecast_ignores_all_values_after_cutoff(self):
        dates = pd.date_range("2010-01-31", "2026-12-31", freq="ME")
        x = np.arange(len(dates), dtype=float)
        levels = pd.Series(np.exp(4 + 0.001*x + 0.004*np.sin(x)), index=dates)
        cutoff = pd.Timestamp("2026-09-10")
        factor = pd.Series(np.cos(x / 6), index=dates).loc[:cutoff]
        clean = levels.copy()
        clean.loc[clean.index > cutoff] = np.nan
        contaminated = levels.copy()
        contaminated.loc[contaminated.index > cutoff] = 1e12
        args = dict(factor=factor, target_quarter=pd.Period("2026Q3"), as_of_date=cutoff)
        a = model.forecast_indicator_quarterly_growth(clean, **args)
        b = model.forecast_indicator_quarterly_growth(contaminated, **args)
        self.assertTrue(np.isfinite(a.quarterly_growth))
        self.assertAlmostEqual(a.quarterly_growth, b.quarterly_growth)


if __name__ == "__main__":
    unittest.main()
