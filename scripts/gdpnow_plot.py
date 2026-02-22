#!/usr/bin/env python3
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

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


OFFICIAL_COL = "GDP Nowcast (TrackingArchives AB)"
MODEL_COL = "GDP Nowcast (Python from ContribArchives components)"
DATE_COL = "Forecast Date"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = PROJECT_ROOT / "outputs" / "gdpnow_validation_results.csv"
DEFAULT_PLOT_PATH = PROJECT_ROOT / "outputs" / "gdpnow_model_vs_official.png"


def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=[DATE_COL])
    required = [DATE_COL, OFFICIAL_COL, MODEL_COL]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")

    df = df[required].copy()
    df[OFFICIAL_COL] = pd.to_numeric(df[OFFICIAL_COL], errors="coerce")
    df[MODEL_COL] = pd.to_numeric(df[MODEL_COL], errors="coerce")
    df = df.dropna(subset=[DATE_COL]).sort_values(DATE_COL, kind="stable")
    return df


def make_plot(df: pd.DataFrame, output_path: Path) -> None:
    fig, (ax_top, ax_bottom) = plt.subplots(
        nrows=2,
        ncols=1,
        figsize=(14, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    ax_top.plot(df[DATE_COL], df[MODEL_COL], label="Model Output (Python)", linewidth=2.0, color="#1f77b4")
    ax_top.plot(df[DATE_COL], df[OFFICIAL_COL], label="Official Atlanta Fed GDPNow", linewidth=1.8, color="#d62728")
    ax_top.set_ylabel("GDP Growth (SAAR, %)")
    ax_top.set_title("GDPNow Model Output vs Official Atlanta Fed GDPNow Forecasts")
    ax_top.grid(alpha=0.25)
    ax_top.legend(loc="best")

    diff = df[MODEL_COL] - df[OFFICIAL_COL]
    ax_bottom.plot(df[DATE_COL], diff, color="#2ca02c", linewidth=1.5, label="Model - Official")
    ax_bottom.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
    ax_bottom.set_ylabel("Difference")
    ax_bottom.set_xlabel("Forecast Date")
    ax_bottom.grid(alpha=0.25)
    ax_bottom.legend(loc="best")

    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax_bottom.xaxis.set_major_locator(locator)
    ax_bottom.xaxis.set_major_formatter(formatter)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot Python GDPNow model output against official Atlanta Fed GDPNow forecasts."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Path to validation CSV (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_PLOT_PATH,
        help=f"Output plot file path (default: {DEFAULT_PLOT_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    csv_path = args.csv.expanduser().resolve()
    out_path = args.out.expanduser().resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = load_data(csv_path)
    if df.empty:
        raise ValueError("No valid rows found to plot.")

    make_plot(df, out_path)
    print(f"Saved plot: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
