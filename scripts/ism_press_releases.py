#!/usr/bin/env python3
"""Extract the eight required ISM indexes, preserving each release's vintage.

This collects observed table entries only. It neither interpolates missing
months nor claims that the latest collected vintage is the latest ISM revision.
Requires pandas, beautifulsoup4; workbook cross-check additionally uses openpyxl.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MANUFACTURING = {
    "Manufacturing PMI": "NAPMC@USECON",
    "Production": "NAPMOI@USECON",
    "Employment": "NAPMEI@USECON",
    "New Orders": "NAPMNI@USECON",
    "Inventories": "NAPMII@USECON",
    "Supplier Deliveries": "NAPMVDI@USECON",
    "Prices": "NAPMPI@USECON",
}
SERVICES = "NMFC@SURVEYS"
TICKERS = list(MANUFACTURING.values()) + [SERVICES]
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[®†*]", "", text)).strip()


def month_key(text: str) -> str | None:
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})", clean(text))
    if match and match[1][:3].lower() in MONTHS:
        return f"{match[2]}-{MONTHS[match[1][:3].lower()]:02d}"
    return None


def parse_release(html: bytes, source: dict) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    title = clean(" ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])))
    report_month = pd.Period(source["report_month"], freq="M")
    expected_title = report_month.strftime("%B %Y")
    if expected_title.lower() not in title.lower() or source["sector"] not in title.lower():
        raise ValueError(f"{source['id']}: wrong report date/sector or unavailable content: {title}")
    published = soup.find("meta", attrs={"name": "date"})
    if published and published.get("content", "")[:10] != source["release_date"]:
        raise ValueError(f"{source['id']}: publication date disagrees with manifest")
    data: dict[tuple[str, str], dict] = {}

    def add(ticker: str, month: str, value: str, table_index: int):
        number = float(value)
        if not 0 <= number <= 100 or month > str(report_month):
            raise ValueError(f"Invalid index observation: {ticker}, {month}, {value}")
        adjustment = "SA"
        if ticker in {"NAPMVDI@USECON", "NAPMPI@USECON"}:
            adjustment = "NSA"
        elif ticker in {"NAPMC@USECON", SERVICES}:
            adjustment = "composite_of_adjusted_and_unadjusted_subindexes"
        row = {
            "reference_month": month, "ticker": ticker, "value": number,
            "unit": "diffusion_index", "seasonal_adjustment": adjustment,
            "report_month": source["report_month"],
            "report_release_date": source["release_date"],
            "source_id": source["id"], "source_url": source["url"],
            "table_index_zero_based": table_index,
            "observation_role": "current_month" if month == str(report_month) else "retrospective_table",
        }
        key = (ticker, month)
        if key in data and data[key]["value"] != number:
            raise ValueError(f"Conflicting values within {source['id']}: {key}")
        data[key] = row

    for table_index, table in enumerate(soup.find_all("table")):
        rows = [[clean(c.get_text(" ", strip=True)) for c in r.find_all(["td", "th"])]
                for r in table.find_all("tr")]
        if not rows or not rows[0]:
            continue
        header = rows[0]
        # Twelve-month PMI histories are laid out in either one or two pairs.
        if header[0] == "Month" and any("PMI" in c or "NMI" in c for c in header):
            ticker = SERVICES if source["sector"] == "services" else "NAPMC@USECON"
            for row in rows[1:]:
                for i in range(len(row) - 1):
                    month = month_key(row[i])
                    if month:
                        add(ticker, month, row[i + 1], table_index)
        # Services reports also contain manufacturing comparison columns;
        # do not mistake their services subindexes for manufacturing data.
        elif source["sector"] == "manufacturing" and header[0] in MANUFACTURING and header[-1] == "Index":
            for row in rows[1:]:
                month = month_key(row[0]) if row else None
                if month:
                    add(MANUFACTURING[header[0]], month, row[-1], table_index)
    expected = {SERVICES} if source["sector"] == "services" else set(MANUFACTURING.values())
    current = {ticker for ticker, month in data if month == str(report_month)}
    if current != expected:
        raise ValueError(f"{source['id']}: missing current-month series {expected - current}")
    return list(data.values())


def select_latest_collected(observations: pd.DataFrame, cutoff: str | None = None) -> pd.DataFrame:
    observations = observations.copy()
    if cutoff:
        observations = observations.loc[observations.report_release_date <= cutoff]
    conflicts = observations.groupby(["ticker", "reference_month", "report_release_date"]).value.nunique()
    if (conflicts > 1).any():
        raise ValueError("Sources disagree on the same series/month/release date; review before selecting.")
    return (observations.sort_values(["report_release_date", "source_id"])
            .drop_duplicates(["ticker", "reference_month"], keep="last")
            .sort_values(["reference_month", "ticker"]))


def workbook_check(latest: pd.DataFrame, workbook: Path, outdir: Path) -> dict:
    from gdpnow_full_model import load_wide_sheet
    raw = load_wide_sheet(workbook, "InventoryRaw")
    rows = []
    for row in latest.itertuples():
        code = row.ticker.replace("@", "_")
        month = pd.Period(row.reference_month, freq="M").to_timestamp(how="end").normalize()
        if code in raw and month in raw.index and pd.notna(raw.loc[month, code]):
            value = float(raw.loc[month, code])
            rows.append({"reference_month": row.reference_month, "ticker": row.ticker,
                         "release_value": row.value, "workbook_value": value,
                         "difference": row.value - value, "source_id": row.source_id})
    result = pd.DataFrame(rows)
    result.to_csv(outdir / "workbook_crosscheck.csv", index=False)
    recent = result.loc[result.reference_month >= "2026-01"]
    return {"workbook": str(workbook), "overlap_observations": len(result),
            "all_overlap_differing_values": int((result.difference.abs() > 1e-9).sum()),
            "2026_overlap_observations": len(recent),
            "2026_differing_values": int((recent.difference.abs() > 1e-9).sum())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/ism/releases.json")
    parser.add_argument("--outdir", type=Path, default=ROOT / "data/ism")
    parser.add_argument("--fetch-missing", action="store_true", help="Download only missing manifest sources")
    parser.add_argument("--as-of-date", help="Limit selected release vintages to YYYY-MM-DD")
    parser.add_argument("--workbook", type=Path, help="Cross-check the three overlapping InventoryRaw series")
    args = parser.parse_args()
    if args.as_of_date:
        args.as_of_date = datetime.strptime(args.as_of_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    args.outdir.mkdir(parents=True, exist_ok=True)
    sources = json.loads(args.manifest.read_text())
    records, provenance = [], []
    for source in sources:
        path = args.manifest.parent / "raw" / f"{source['id']}.html"
        if not path.exists() and args.fetch_missing:
            path.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(Request(source["url"], headers={"User-Agent": "GDPNow research data collection"}), timeout=30) as response:
                html = response.read()
            parse_release(html, source)  # Never cache a removed page as a valid report.
            path.write_bytes(html)
        html = path.read_bytes()
        parsed = parse_release(html, source)
        records.extend(parsed)
        provenance.append({**source, "raw_file": str(path), "sha256": hashlib.sha256(html).hexdigest(),
                           "cached_file_mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                           "observations": len(parsed)})
    observations = pd.DataFrame(records).sort_values(["report_release_date", "reference_month", "ticker"])
    observations.to_csv(args.outdir / "observations_by_release.csv", index=False)
    latest = select_latest_collected(observations, args.as_of_date)
    latest.to_csv(args.outdir / "latest_collected_with_sources.csv", index=False)
    wide = latest.pivot(index="reference_month", columns="ticker", values="value").reindex(columns=TICKERS)
    wide.to_csv(args.outdir / "latest_collected.csv")
    complete = wide.dropna()
    complete.to_csv(args.outdir / "complete_eight_series_months.csv")
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "as_of_release_cutoff": args.as_of_date,
        "reports_parsed": len(sources), "observations_including_release_vintages": len(observations),
        "unique_series_months": len(latest), "complete_eight_series_months": len(complete),
        "complete_months": complete.index.tolist(),
        "series_months_with_multiple_published_values": int((observations.groupby(["ticker", "reference_month"]).value.nunique() > 1).sum()),
        "coverage_by_series": latest.groupby("ticker").reference_month.agg(["min", "max", "count"]).to_dict("index"),
        "selection_rule": "Latest release among collected sources, on/before cutoff; not necessarily the latest revision published by ISM.",
        "limitations": ["Incomplete historical coverage; no interpolation or synthetic backfill.",
                        "Retrospective table values were available on their report release date, not necessarily on the original month release date.",
                        "Older releases mix seasonal-adjustment vintages; preserve vintages for replication.",
                        "This dataset is not yet connected to the GDPNow approximation."],
    }
    if args.workbook:
        summary["workbook_crosscheck"] = workbook_check(latest, args.workbook, args.outdir)
    (args.outdir / "source_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    (args.outdir / "coverage_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
