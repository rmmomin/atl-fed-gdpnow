#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

import numpy as np
warnings.filterwarnings(
    "ignore",
    message=r"Pandas requires version .* of 'numexpr'.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Pandas requires version .* of 'bottleneck'.*",
    category=UserWarning,
)
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, get_column_letter


KEY_COLUMNS = ["Forecast Date", "Quarter being forecasted"]
TRACKING_REQUIRED_COLUMNS = {
    "A": "Forecast Date",
    "B": "Quarter being forecasted",
    "AB": "GDP Nowcast",
}
CONTRIB_REQUIRED_COLUMNS = {
    "A": "Forecast Date",
    "B": "Quarter being forecasted",
    "C": "PCE",
    "G": "Fixed Investment",
    "M": "Government",
    "V": "Change in net exports",
    "W": "Change in inventory investment",
    "X": "GDP Nowcast",
}
CONTRIB_COMPONENT_COLUMNS = [
    "PCE",
    "Fixed Investment",
    "Government",
    "Change in net exports",
    "Change in inventory investment",
]
HEADER_WHITESPACE_RE = re.compile(r"\s+")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK_PATH = PROJECT_ROOT / "data" / "GDPTrackingModelDataAndForecasts.xlsx"
DEFAULT_OUTDIR = PROJECT_ROOT / "outputs"


def normalize_headers(values: Iterable[Any]) -> list[str]:
    """Return case-folded, trimmed, single-space headers for robust matching."""
    normalized: list[str] = []
    for value in values:
        if value is None:
            normalized.append("")
            continue
        text = HEADER_WHITESPACE_RE.sub(" ", str(value).strip())
        normalized.append(text.casefold())
    return normalized


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def load_sheet(
    workbook_path: Path,
    sheet_name: str,
    required_columns: Mapping[str, str],
    trailing_blank_break: int = 200,
) -> pd.DataFrame:
    """
    Load selected columns from an Excel sheet using stored formula results only.

    - Verifies required headers at exact Excel column letters.
    - Stops after a long trailing blank streak to avoid scanning large empty tails.
    """
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"Sheet '{sheet_name}' not found in workbook.")
        sheet = workbook[sheet_name]

        ordered = [(column_index_from_string(col), expected) for col, expected in required_columns.items()]
        min_col = min(idx for idx, _ in ordered)
        max_col = max(idx for idx, _ in ordered)
        header_row = next(
            sheet.iter_rows(
                min_row=1,
                max_row=1,
                min_col=min_col,
                max_col=max_col,
                values_only=True,
            )
        )

        for col_idx, expected_header in ordered:
            actual_header = header_row[col_idx - min_col]
            expected_norm = normalize_headers([expected_header])[0]
            actual_norm = normalize_headers([actual_header])[0]
            if expected_norm != actual_norm:
                col_letter = get_column_letter(col_idx)
                raise ValueError(
                    f"Header mismatch in '{sheet_name}' at {col_letter}1: "
                    f"expected '{expected_header}', got '{actual_header}'."
                )

        records: list[Dict[str, Any]] = []
        blank_streak = 0
        for row in sheet.iter_rows(
            min_row=2,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        ):
            record = {name: row[col_idx - min_col] for col_idx, name in ordered}
            if all(_is_blank(value) for value in record.values()):
                blank_streak += 1
                if blank_streak >= trailing_blank_break:
                    break
                continue
            blank_streak = 0
            records.append(record)

        df = pd.DataFrame(records, columns=[name for _, name in ordered])
        return df
    finally:
        workbook.close()


def clean_and_dedupe_sheet(df: pd.DataFrame, sheet_name: str) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Coerce datatypes, drop blank key rows, and deduplicate key collisions."""
    cleaned = df.copy()

    for col in KEY_COLUMNS:
        cleaned[col] = pd.to_datetime(cleaned[col], errors="coerce")

    numeric_cols = [col for col in cleaned.columns if col not in KEY_COLUMNS]
    for col in numeric_cols:
        cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")

    rows_raw = len(cleaned)
    cleaned = cleaned.loc[cleaned["Forecast Date"].notna()].copy()
    dropped_missing_forecast_date = rows_raw - len(cleaned)

    duplicate_mask = cleaned.duplicated(subset=KEY_COLUMNS, keep="first")
    duplicate_count = int(duplicate_mask.sum())
    if duplicate_count:
        print(
            f"WARNING: {sheet_name} has {duplicate_count} duplicate key row(s); "
            "keeping first occurrence.",
            file=sys.stderr,
        )
        cleaned = cleaned.loc[~duplicate_mask].copy()

    diagnostics = {
        "rows_raw": rows_raw,
        "rows_after_drop_forecast_date": len(cleaned),
        "dropped_missing_forecast_date": dropped_missing_forecast_date,
        "duplicate_key_rows_removed": duplicate_count,
    }
    return cleaned, diagnostics


def compute_nowcast_from_contrib(df: pd.DataFrame) -> pd.Series:
    """Primary nowcast from contribution components."""
    return df[CONTRIB_COMPONENT_COLUMNS].sum(axis=1, min_count=len(CONTRIB_COMPONENT_COLUMNS))


def _compute_diff(left: pd.Series, right: pd.Series) -> pd.Series:
    diff = left - right
    valid = left.notna() & right.notna()
    diff.loc[~valid] = np.nan
    return diff


def _diff_stats(diff: pd.Series, tol: float) -> Dict[str, float | int]:
    valid = diff.dropna()
    if valid.empty:
        return {
            "rows_compared": 0,
            "max_abs_diff": float("nan"),
            "mean_abs_diff": float("nan"),
            "median_abs_diff": float("nan"),
            "count_exceed_tol": 0,
        }
    abs_diff = valid.abs()
    return {
        "rows_compared": int(valid.shape[0]),
        "max_abs_diff": float(abs_diff.max()),
        "mean_abs_diff": float(abs_diff.mean()),
        "median_abs_diff": float(abs_diff.median()),
        "count_exceed_tol": int((abs_diff > tol).sum()),
    }


def _format_float(value: float) -> str:
    if pd.isna(value):
        return "nan"
    return f"{value:.12g}"


def compare_and_report(
    merged: pd.DataFrame,
    tol: float,
    outdir: Path,
    dropped_left_keys: int,
    dropped_right_keys: int,
) -> Tuple[pd.DataFrame, Dict[str, Any], Path]:
    merged = merged.copy()

    merged["GDP Nowcast (Python from ContribArchives components)"] = compute_nowcast_from_contrib(merged)
    merged["diff_tracking"] = _compute_diff(
        merged["GDP Nowcast (Python from ContribArchives components)"],
        merged["GDP Nowcast (TrackingArchives AB)"],
    )
    merged["diff_contrib"] = _compute_diff(
        merged["GDP Nowcast (Python from ContribArchives components)"],
        merged["GDP Nowcast (ContribArchives X)"],
    )
    merged["abs_diff_tracking"] = merged["diff_tracking"].abs()
    merged["abs_diff_contrib"] = merged["diff_contrib"].abs()

    results = merged[
        [
            "Forecast Date",
            "Quarter being forecasted",
            "GDP Nowcast (TrackingArchives AB)",
            "GDP Nowcast (Python from ContribArchives components)",
            "GDP Nowcast (ContribArchives X)",
            "diff_tracking",
            "diff_contrib",
            "abs_diff_tracking",
            "abs_diff_contrib",
        ]
    ].copy()
    results = results.sort_values(["Forecast Date", "Quarter being forecasted"], kind="stable")

    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "gdpnow_validation_results.csv"
    results.to_csv(csv_path, index=False, date_format="%Y-%m-%d")

    tracking_stats = _diff_stats(results["diff_tracking"], tol)
    contrib_stats = _diff_stats(results["diff_contrib"], tol)
    summary: Dict[str, Any] = {
        "rows_total": int(results.shape[0]),
        "rows_compared_tracking": tracking_stats["rows_compared"],
        "rows_compared_contrib": contrib_stats["rows_compared"],
        "rows_dropped_due_to_key_mismatch_tracking_only": dropped_left_keys,
        "rows_dropped_due_to_key_mismatch_contrib_only": dropped_right_keys,
        "max_abs_diff_tracking": tracking_stats["max_abs_diff"],
        "mean_abs_diff_tracking": tracking_stats["mean_abs_diff"],
        "median_abs_diff_tracking": tracking_stats["median_abs_diff"],
        "max_abs_diff_contrib": contrib_stats["max_abs_diff"],
        "mean_abs_diff_contrib": contrib_stats["mean_abs_diff"],
        "median_abs_diff_contrib": contrib_stats["median_abs_diff"],
        "count_exceed_tol_tracking": tracking_stats["count_exceed_tol"],
        "count_exceed_tol_contrib": contrib_stats["count_exceed_tol"],
        "tolerance": tol,
        "csv_path": str(csv_path),
    }

    print("\nGDPNow Validation Report")
    print("========================")
    print(f"rows_total: {summary['rows_total']}")
    print(f"rows_compared_tracking: {summary['rows_compared_tracking']}")
    print(f"rows_compared_contrib: {summary['rows_compared_contrib']}")
    print(f"rows_dropped_due_to_key_mismatch_tracking_only: {dropped_left_keys}")
    print(f"rows_dropped_due_to_key_mismatch_contrib_only: {dropped_right_keys}")

    print("\nTracking comparison (Python vs TrackingArchives!AB)")
    print(f"max_abs_diff_tracking: { _format_float(summary['max_abs_diff_tracking']) }")
    print(f"mean_abs_diff_tracking: { _format_float(summary['mean_abs_diff_tracking']) }")
    print(f"median_abs_diff_tracking: { _format_float(summary['median_abs_diff_tracking']) }")
    print(f"count_exceed_tol_tracking: {summary['count_exceed_tol_tracking']}")

    print("\nContrib sheet comparison (Python vs ContribArchives!X)")
    print(f"max_abs_diff_contrib: { _format_float(summary['max_abs_diff_contrib']) }")
    print(f"mean_abs_diff_contrib: { _format_float(summary['mean_abs_diff_contrib']) }")
    print(f"median_abs_diff_contrib: { _format_float(summary['median_abs_diff_contrib']) }")
    print(f"count_exceed_tol_contrib: {summary['count_exceed_tol_contrib']}")

    mismatches = (
        results.loc[results["abs_diff_tracking"] > tol]
        .sort_values("abs_diff_tracking", ascending=False, kind="stable")
        .head(20)
        .copy()
    )
    if mismatches.empty:
        print(f"\nNo tracking mismatches above tolerance ({tol:g}).")
    else:
        print(f"\nTop {len(mismatches)} mismatches by abs(diff_tracking):")
        display_cols = [
            "Forecast Date",
            "Quarter being forecasted",
            "GDP Nowcast (TrackingArchives AB)",
            "GDP Nowcast (Python from ContribArchives components)",
            "diff_tracking",
            "abs_diff_tracking",
        ]
        mismatches.loc[:, "Forecast Date"] = mismatches["Forecast Date"].dt.strftime("%Y-%m-%d")
        mismatches.loc[:, "Quarter being forecasted"] = mismatches["Quarter being forecasted"].dt.strftime(
            "%Y-%m-%d"
        )
        print(mismatches[display_cols].to_string(index=False))

    summary_path = outdir / "gdpnow_validation_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved row-level CSV: {csv_path}")
    print(f"Saved summary JSON: {summary_path}")

    return results, summary, summary_path


def run_fisher_check(workbook_path: Path) -> None:
    """
    Optional deeper Fisher chain-weight validation.
    """
    required_sheets = [
        "NomQtrlyComps",
        "QtrlyPriceForecasts",
        "QtrlyBVARForecasts",
        "dLogQtrlyGrowth",
        "QtrlyActDLog",
    ]
    workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        missing = [sheet for sheet in required_sheets if sheet not in workbook.sheetnames]
    finally:
        workbook.close()

    if missing:
        print(
            "\nFisher check skipped: workbook is missing required sheet(s): "
            + ", ".join(missing)
        )
        return

    print(
        "\nFisher check requested, but skipped: exact per-archive mapping from "
        "Forecast Date/Quarter rows to component-level quantity and price vectors "
        "is not directly identifiable from these sheets without additional model "
        "metadata."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GDPNow nowcast by recomputing from contribution components."
    )
    parser.add_argument(
        "workbook_path",
        nargs="?",
        default=str(DEFAULT_WORKBOOK_PATH),
        help=f"Path to GDPTrackingModelDataAndForecasts.xlsx (default: {DEFAULT_WORKBOOK_PATH})",
    )
    parser.add_argument(
        "--tol",
        type=float,
        default=1e-8,
        help="Absolute tolerance for mismatch counting (default: 1e-8).",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help=f"Output directory for CSV/summary artifacts (default: {DEFAULT_OUTDIR}).",
    )
    parser.add_argument(
        "--fisher-check",
        action="store_true",
        help="Attempt optional Fisher chain-weight validation (may skip with message).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook_path = Path(args.workbook_path).expanduser().resolve()

    if not workbook_path.exists():
        print(f"Workbook not found: {workbook_path}", file=sys.stderr)
        return 2

    tracking_raw = load_sheet(
        workbook_path=workbook_path,
        sheet_name="TrackingArchives",
        required_columns=TRACKING_REQUIRED_COLUMNS,
    )
    contrib_raw = load_sheet(
        workbook_path=workbook_path,
        sheet_name="ContribArchives",
        required_columns=CONTRIB_REQUIRED_COLUMNS,
    )

    tracking, tracking_diag = clean_and_dedupe_sheet(tracking_raw, "TrackingArchives")
    contrib, contrib_diag = clean_and_dedupe_sheet(contrib_raw, "ContribArchives")

    tracking = tracking.rename(columns={"GDP Nowcast": "GDP Nowcast (TrackingArchives AB)"})
    contrib = contrib.rename(columns={"GDP Nowcast": "GDP Nowcast (ContribArchives X)"})

    key_status = tracking[KEY_COLUMNS].merge(
        contrib[KEY_COLUMNS],
        on=KEY_COLUMNS,
        how="outer",
        indicator=True,
    )
    dropped_left_keys = int((key_status["_merge"] == "left_only").sum())
    dropped_right_keys = int((key_status["_merge"] == "right_only").sum())

    merged = tracking.merge(contrib, on=KEY_COLUMNS, how="inner")
    if merged.empty:
        print(
            "No overlapping rows after merge on keys "
            f"{KEY_COLUMNS}; cannot run validation.",
            file=sys.stderr,
        )
        return 3

    _, summary, _ = compare_and_report(
        merged=merged,
        tol=args.tol,
        outdir=args.outdir,
        dropped_left_keys=dropped_left_keys,
        dropped_right_keys=dropped_right_keys,
    )

    print("\nLoad/clean diagnostics:")
    print(json.dumps({"TrackingArchives": tracking_diag, "ContribArchives": contrib_diag}, indent=2))

    if args.fisher_check:
        run_fisher_check(workbook_path)

    # Keep this for scripting integration.
    return 0 if summary["count_exceed_tol_tracking"] >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
