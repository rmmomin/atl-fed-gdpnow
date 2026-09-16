import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ism_press_releases as ism


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {s["id"]: s for s in json.loads((ROOT / "data/ism/releases.json").read_text())}

    def parse(self, source_id, override=None):
        source = {**self.sources[source_id], **(override or {})}
        html = (ROOT / "data/ism/raw" / f"{source_id}.html").read_bytes()
        return pd.DataFrame(ism.parse_release(html, source))

    def test_manufacturing_extracts_correct_index_column(self):
        rows = self.parse("manufacturing_2026-08")
        current = rows.loc[rows.reference_month == "2026-08"].set_index("ticker").value.to_dict()
        # Independently read from the report's at-a-glance table, not its
        # rolling history tables used by the parser.
        self.assertEqual(current, {
            "NAPMC@USECON": 54.6, "NAPMOI@USECON": 58.3,
            "NAPMEI@USECON": 51.2, "NAPMNI@USECON": 53.7,
            "NAPMII@USECON": 50.6, "NAPMVDI@USECON": 59.3,
            "NAPMPI@USECON": 71.1,
        })

    def test_services_does_not_import_manufacturing_comparison_columns(self):
        rows = self.parse("services_2026-08")
        self.assertEqual(set(rows.ticker), {"NMFC@SURVEYS"})
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows.set_index("reference_month").loc["2026-08", "value"], 55.4)

    def test_reused_month_url_cannot_silently_become_another_year(self):
        with self.assertRaisesRegex(ValueError, "wrong report date"):
            self.parse("manufacturing_2026-08", {"report_month": "2025-08"})

    def test_preserves_revision_and_uses_publication_cutoff(self):
        rows = pd.concat([self.parse("manufacturing_2025-11"), self.parse("manufacturing_2026-02")])
        row_filter = lambda d: d.loc[(d.ticker == "NAPMC@USECON") & (d.reference_month == "2025-11"), "value"].iloc[0]
        self.assertEqual(row_filter(ism.select_latest_collected(rows, "2025-12-31")), 48.2)
        self.assertEqual(row_filter(ism.select_latest_collected(rows, "2026-03-02")), 48.0)
        # November's row is not yet known before its December release.
        self.assertTrue(ism.select_latest_collected(rows, "2025-11-30").empty)
        self.assertEqual(set(rows.loc[(rows.ticker == "NAPMC@USECON") & (rows.reference_month == "2025-11"), "value"]), {48.0, 48.2})


if __name__ == "__main__":
    unittest.main()
