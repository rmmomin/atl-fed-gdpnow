#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

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

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.dynamic_factor import DynamicFactor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK_PATH = PROJECT_ROOT / "data" / "GDPTrackingModelDataAndForecasts.xlsx"
DEFAULT_OUTDIR = PROJECT_ROOT / "outputs"

COMPONENT_TICKERS: list[str] = [
    "CTGZ_USNAqtr",
    "CSZ_USNAqtr",
    "FNEZ_USNAqtr",
    "FNPZ_USNAqtr",
    "FNSZ_USNAqtr",
    "FRZ_USNAqtr",
    "XMZ_USNAqtr",
    "XSZ_USNAqtr",
    "MMZ_USNAqtr",
    "MSZ_USNAqtr",
    "GFZ_USNAqtr",
    "GSZ_USNAqtr",
    "VZ_USNAqtr",
]
IMPORT_TICKERS: set[str] = {"MMZ_USNAqtr", "MSZ_USNAqtr"}
INVENTORY_TICKER = "VZ_USNAqtr"

TRACKING_COMPONENT_COLUMN_MAP: dict[str, str] = {
    "CTGZ_USNAqtr": "PCE Goods",
    "CSZ_USNAqtr": "PCE Services",
    "FNEZ_USNAqtr": "Equipment",
    "FNPZ_USNAqtr": "Intellectual Property Products",
    "FNSZ_USNAqtr": "Structures",
    "FRZ_USNAqtr": "Residential",
    "XMZ_USNAqtr": "Goods exports",
    "XSZ_USNAqtr": "Services exports",
    "MMZ_USNAqtr": "Goods imports",
    "MSZ_USNAqtr": "Services imports",
    "GFZ_USNAqtr": "Federal Govt",
    "GSZ_USNAqtr": "S&L",
}


def _is_date_like(value: Any) -> bool:
    return isinstance(value, (datetime, date, pd.Timestamp, np.datetime64))


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _annualized_growth_from_levels(curr: float, prev: float) -> float:
    if not np.isfinite(curr) or not np.isfinite(prev):
        return float("nan")
    if prev == 0:
        return float("nan")
    if curr > 0 and prev > 0:
        return float(((curr / prev) ** 4 - 1.0) * 100.0)
    return float(((curr - prev) / abs(prev)) * 400.0)


def _annualized_to_qoq_log(growth_annualized: float) -> float:
    if not np.isfinite(growth_annualized):
        return float("nan")
    bounded = float(max(growth_annualized, -99.9))
    return float(0.25 * math.log1p(bounded / 100.0))


def _qoq_log_to_annualized(delta_log: float) -> float:
    if not np.isfinite(delta_log):
        return float("nan")
    return float((math.exp(4.0 * delta_log) - 1.0) * 100.0)


def _project_level_from_annualized_growth(prev_level: float, growth_annualized: float) -> float:
    if not np.isfinite(prev_level) or not np.isfinite(growth_annualized):
        return float("nan")
    if prev_level > 0 and growth_annualized > -99.9:
        return float(prev_level * ((1.0 + growth_annualized / 100.0) ** 0.25))
    scale = abs(prev_level) if prev_level != 0 else 1.0
    return float(prev_level + growth_annualized * scale / 400.0)


def _weighted_ls_fit(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    sqrt_w = np.sqrt(w).reshape(-1, 1)
    xw = x * sqrt_w
    yw = y * sqrt_w.ravel()
    beta, *_ = np.linalg.lstsq(xw, yw, rcond=None)
    return beta


def _quarter_period(ts: pd.Timestamp) -> pd.Period:
    return pd.Period(ts, freq="Q")


def _quarter_end_timestamp(period: pd.Period) -> pd.Timestamp:
    return period.to_timestamp(how="end").normalize()


def _quarter_month_ends(period: pd.Period) -> list[pd.Timestamp]:
    start = period.asfreq("M", how="start").to_timestamp(how="end").normalize()
    return [(start + pd.offsets.MonthEnd(i)).normalize() for i in range(0, 3)]


def _monthly_series_to_quarterly_growth(series: pd.Series) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce")
    q_avg = series.resample("QE").mean()
    growth: list[float] = [float("nan")]
    values = q_avg.to_numpy(dtype=float)
    for i in range(1, len(values)):
        growth.append(_annualized_growth_from_levels(values[i], values[i - 1]))
    return pd.Series(growth, index=q_avg.index)


def _normalize_col_name(value: Any) -> str:
    return re.sub(r"\s+", " ", _safe_str(value)).casefold()


def _find_ticker_column(columns: Sequence[Any]) -> Any:
    for col in columns:
        if _normalize_col_name(col) == "ticker":
            return col
    if len(columns) < 3:
        raise ValueError("Unable to infer ticker column from sheet columns.")
    return columns[2]


def load_wide_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    ticker_col = _find_ticker_column(df.columns)
    date_cols = [col for col in df.columns if _is_date_like(col)]
    if not date_cols:
        raise ValueError(f"Sheet '{sheet_name}' has no date columns.")
    out = df[[ticker_col] + date_cols].copy()
    out = out.loc[out[ticker_col].notna()].copy()
    out[ticker_col] = out[ticker_col].astype(str).str.strip()
    out = out.groupby(ticker_col, as_index=True).first()
    out = out.apply(pd.to_numeric, errors="coerce")
    out = out.T
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out


def load_monthly_panel(path: Path) -> pd.DataFrame:
    monthly_main = load_wide_sheet(path, "TransformedMonthlySeries")
    monthly_cons = load_wide_sheet(path, "ConsTransformedMonthlySeries")
    panel = pd.concat([monthly_main, monthly_cons], axis=1)
    panel = panel.loc[:, ~panel.columns.duplicated(keep="first")]
    panel = panel.sort_index()
    return panel


def load_monthly_levels(path: Path) -> pd.DataFrame:
    levels_main = load_wide_sheet(path, "MonthlyLevels")
    levels_cons = load_wide_sheet(path, "ConsMonthlyLevels")
    levels = pd.concat([levels_main, levels_cons], axis=1)
    levels = levels.loc[:, ~levels.columns.duplicated(keep="first")]
    levels = levels.sort_index()
    return levels


def load_tracking_latest(
    path: Path,
    as_of_date: pd.Timestamp | None,
    target_quarter: pd.Period | None,
) -> pd.Series:
    tracking = pd.read_excel(
        path,
        sheet_name="TrackingArchives",
        engine="openpyxl",
        usecols=[
            "Forecast Date",
            "Quarter being forecasted",
            "GDP Nowcast",
            "PCE Goods",
            "PCE Services",
            "Equipment",
            "Intellectual Property Products",
            "Structures",
            "Residential",
            "Goods exports",
            "Services exports",
            "Goods imports",
            "Services imports",
            "Federal Govt",
            "S&L",
        ],
    )
    tracking["tracking_sheet"] = "TrackingArchives"
    # The active quarter lives in a transposed table, outside TrackingArchives.
    history = pd.read_excel(path, sheet_name="TrackingHistory", header=None, engine="openpyxl")
    title = " ".join(history.iloc[:2, :2].fillna("").astype(str).to_numpy().ravel())
    match = re.search(r"(20\d{2})q([1-4])", title, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Cannot identify the active quarter in TrackingHistory.")
    active_quarter = pd.Period(f"{match[1]}Q{match[2]}", freq="Q")
    history_labels = history.iloc[:, 1].map(
        lambda value: re.sub(r"\s+", " ", str(value).replace("**", "")).strip()
    )
    current_labels = {
        "GDP Nowcast": "GDP Nowcast",
        "2- PCE Goods": "PCE Goods",
        "3- PCE Services": "PCE Services",
        "7- Equipment": "Equipment",
        "8- Intellectual Property Products": "Intellectual Property Products",
        "9- Structures": "Structures",
        "10- Residential": "Residential",
        "12- Federal": "Federal Govt",
        "13- State and Local": "S&L",
        "15- Goods": "Goods imports",
        "16- Services": "Services imports",
        "18- Goods": "Goods exports",
        "19- Services": "Services exports",
    }
    row_indices = {}
    for label, column in current_labels.items():
        matches = history_labels.index[history_labels == label]
        if len(matches) != 1:
            raise ValueError(f"Expected one TrackingHistory row for {label!r}, found {len(matches)}.")
        row_indices[column] = matches[0]
    current_rows = []
    for col in range(2, history.shape[1]):
        forecast_date = history.iloc[0, col]
        if not _is_date_like(forecast_date):
            continue
        row = {name: history.iloc[idx, col] for name, idx in row_indices.items()}
        if pd.isna(row["GDP Nowcast"]):
            continue
        row.update({
            "Forecast Date": forecast_date,
            "Quarter being forecasted": _quarter_end_timestamp(active_quarter),
            "tracking_sheet": "TrackingHistory",
        })
        current_rows.append(row)
    tracking = pd.concat([tracking, pd.DataFrame(current_rows)], ignore_index=True)
    tracking["Forecast Date"] = pd.to_datetime(tracking["Forecast Date"], errors="coerce")
    tracking["Quarter being forecasted"] = pd.to_datetime(
        tracking["Quarter being forecasted"], errors="coerce"
    )
    tracking = tracking.dropna(subset=["Forecast Date", "Quarter being forecasted"])
    if as_of_date is not None:
        tracking = tracking.loc[tracking["Forecast Date"] <= as_of_date]
    if target_quarter is not None:
        q_end = _quarter_end_timestamp(target_quarter)
        tracking = tracking.loc[tracking["Quarter being forecasted"] == q_end]
    if tracking.empty:
        raise ValueError("No TrackingArchives or TrackingHistory rows match requested as-of date / quarter.")
    return tracking.sort_values("Forecast Date", kind="stable").iloc[-1]


def load_rls_bridge_weights(path: Path) -> dict[str, float]:
    df = pd.read_excel(path, sheet_name="RLSweights", engine="openpyxl")
    if "Ticker" not in df.columns or "Weight on Monthly Indicators" not in df.columns:
        return {}
    subset = df[["Ticker", "Weight on Monthly Indicators"]].dropna()
    out: dict[str, float] = {}
    for _, row in subset.iterrows():
        ticker = _safe_str(row["Ticker"])
        weight = row["Weight on Monthly Indicators"]
        if ticker and pd.notna(weight):
            out[ticker] = float(np.clip(float(weight), 0.0, 1.0))
    return out


def select_factor_panel(panel: pd.DataFrame, as_of_date: pd.Timestamp, max_series: int) -> pd.DataFrame:
    truncated = panel.loc[panel.index <= as_of_date].copy()
    if truncated.empty:
        raise ValueError("No transformed monthly panel data available up to as-of date.")
    nonnull_counts = truncated.notna().sum().sort_values(ascending=False)
    keep = nonnull_counts.head(max_series).index
    selected = truncated[keep].copy()
    selected = selected.dropna(axis=1, how="all")
    selected = selected.loc[:, selected.nunique(dropna=True) > 1]
    if selected.shape[1] < 5:
        raise ValueError("Insufficient factor panel columns after filtering.")
    return selected


def estimate_factor_series(
    panel: pd.DataFrame,
    use_kalman: bool = True,
    maxiter: int = 120,
) -> pd.Series:
    standardized = panel.copy()
    standardized = (standardized - standardized.mean()) / standardized.std(ddof=0)
    standardized = standardized.replace([np.inf, -np.inf], np.nan)
    standardized = standardized.dropna(axis=1, how="all")
    standardized = standardized.loc[:, standardized.notna().sum() >= 48]
    if standardized.empty:
        raise ValueError("No usable columns for factor estimation after standardization.")

    # PCA initialization with jagged-edge handling via zero-imputation after standardization.
    filled = standardized.fillna(0.0).to_numpy(dtype=float)
    _, _, vt = np.linalg.svd(filled, full_matrices=False)
    pc = filled @ vt[0, :].T
    pc_series = pd.Series(pc, index=standardized.index)
    pc_series = (pc_series - pc_series.mean()) / pc_series.std(ddof=0)

    if not use_kalman:
        return pc_series.rename("factor")

    try:
        mod = DynamicFactor(standardized, k_factors=1, factor_order=3, error_order=1)
        res = mod.fit(disp=False, maxiter=maxiter)
        factor_vals = np.asarray(res.factors.smoothed[0], dtype=float)
        factor = pd.Series(factor_vals, index=standardized.index, name="factor")
        factor = (factor - factor.mean()) / factor.std(ddof=0)
        return factor
    except Exception as exc:  # pragma: no cover - fallback safety path.
        print(
            f"WARNING: DynamicFactor estimation failed ({exc}); falling back to PCA factor.",
            file=sys.stderr,
        )
        return pc_series.rename("factor")


def extend_factor_with_ar3(factor: pd.Series, end_date: pd.Timestamp) -> pd.Series:
    out = factor.copy()
    out = out.sort_index()
    if out.index[-1] >= end_date:
        return out

    y = out.dropna()
    if len(y) < 24:
        monthly_index = pd.date_range(out.index.min(), end_date, freq="M")
        return out.reindex(monthly_index).ffill()

    y_lag = pd.concat([y.shift(1), y.shift(2), y.shift(3)], axis=1)
    train = pd.concat([y.rename("y"), y_lag], axis=1).dropna()
    x = np.column_stack([np.ones(len(train)), train.iloc[:, 1:].to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(x, train["y"].to_numpy(dtype=float), rcond=None)

    idx = pd.date_range(out.index.min(), end_date, freq="M")
    out = out.reindex(idx)
    out.iloc[: len(y)] = y.reindex(idx[: len(y)])
    out = out.astype(float)

    for ts in idx:
        if pd.notna(out.loc[ts]):
            continue
        l1 = out.shift(1).loc[ts]
        l2 = out.shift(2).loc[ts]
        l3 = out.shift(3).loc[ts]
        if pd.isna(l1) or pd.isna(l2) or pd.isna(l3):
            out.loc[ts] = out.ffill().loc[ts]
            continue
        out.loc[ts] = float(beta[0] + beta[1] * l1 + beta[2] * l2 + beta[3] * l3)
    return out


@dataclass
class IndicatorForecastResult:
    quarterly_growth: float
    mode: str
    used_model: bool


def forecast_indicator_quarterly_growth(
    monthly_series: pd.Series,
    factor: pd.Series,
    target_quarter: pd.Period,
    as_of_date: pd.Timestamp,
    q_lags: int = 6,
    f_lags: int = 4,
) -> IndicatorForecastResult:
    s = pd.to_numeric(monthly_series, errors="coerce").copy()
    s = s.sort_index()
    months = _quarter_month_ends(target_quarter)
    prev_quarter = target_quarter - 1
    prev_months = _quarter_month_ends(prev_quarter)
    needed_end = months[-1]

    if s.index.max() < needed_end:
        s = s.reindex(pd.date_range(s.index.min(), needed_end, freq="M"))

    observed = s.loc[s.index <= needed_end].copy()
    observed.loc[observed.index > as_of_date] = np.nan

    factor_ext = extend_factor_with_ar3(factor, needed_end)
    training = pd.concat([observed.rename("level"), factor_ext.rename("factor")], axis=1)

    positive = bool((training["level"].dropna() > 0).all())
    mode = "log" if positive else "diff"
    if mode == "log":
        target_series = np.log(training["level"]).diff()
    else:
        target_series = training["level"].diff()

    x_parts = []
    for i in range(1, q_lags + 1):
        x_parts.append(target_series.shift(i).rename(f"y_lag{i}"))
    for i in range(0, f_lags + 1):
        x_parts.append(training["factor"].shift(i).rename(f"f_lag{i}"))

    reg = pd.concat([target_series.rename("y"), *x_parts], axis=1).dropna()
    used_model = len(reg) >= max(48, q_lags + f_lags + 6)

    if used_model:
        x = np.column_stack([np.ones(len(reg)), reg.drop(columns=["y"]).to_numpy(dtype=float)])
        y = reg["y"].to_numpy(dtype=float)
        beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    else:
        beta = None

    filled = observed.copy()
    for ts in months:
        if pd.notna(filled.loc[ts]):
            continue
        prev_ts = ts - pd.offsets.MonthEnd(1)
        prev_level = filled.loc[prev_ts] if prev_ts in filled.index else np.nan
        if pd.isna(prev_level):
            filled.loc[ts] = filled.ffill().loc[ts]
            continue

        if not used_model or beta is None:
            filled.loc[ts] = prev_level
            continue

        feat: list[float] = [1.0]
        ok = True
        for i in range(1, q_lags + 1):
            lag_ts = ts - pd.offsets.MonthEnd(i)
            if lag_ts not in filled.index or lag_ts not in factor_ext.index:
                ok = False
                break
            if mode == "log":
                ylag = np.log(filled.loc[lag_ts]) - np.log(filled.shift(1).loc[lag_ts])
            else:
                ylag = filled.loc[lag_ts] - filled.shift(1).loc[lag_ts]
            if not np.isfinite(ylag):
                ok = False
                break
            feat.append(float(ylag))
        for i in range(0, f_lags + 1):
            lag_ts = ts - pd.offsets.MonthEnd(i)
            if lag_ts not in factor_ext.index or pd.isna(factor_ext.loc[lag_ts]):
                ok = False
                break
            feat.append(float(factor_ext.loc[lag_ts]))

        if not ok:
            filled.loc[ts] = prev_level
            continue

        dy_hat = float(np.dot(np.asarray(feat), beta))
        if mode == "log":
            filled.loc[ts] = float(prev_level * math.exp(dy_hat))
        else:
            filled.loc[ts] = float(prev_level + dy_hat)

    q_avg_curr = filled.reindex(months).mean()
    q_avg_prev = filled.reindex(prev_months).mean()
    q_growth = _annualized_growth_from_levels(float(q_avg_curr), float(q_avg_prev))
    return IndicatorForecastResult(quarterly_growth=q_growth, mode=mode, used_model=used_model)


def compute_indicator_quarterly_growth_matrix(monthly_levels: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for ticker in monthly_levels.columns:
        out[ticker] = _monthly_series_to_quarterly_growth(monthly_levels[ticker])
    matrix = pd.DataFrame(out)
    matrix = matrix.sort_index()
    return matrix


def select_component_indicators(
    component_growth: pd.Series,
    indicator_growth_matrix: pd.DataFrame,
    top_n: int,
) -> list[str]:
    y = pd.to_numeric(component_growth, errors="coerce")
    scores: list[tuple[str, float]] = []
    for ticker in indicator_growth_matrix.columns:
        x = pd.to_numeric(indicator_growth_matrix[ticker], errors="coerce")
        aligned = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
        if len(aligned) < 40:
            continue
        corr = aligned["y"].corr(aligned["x"])
        if pd.notna(corr):
            scores.append((ticker, abs(float(corr))))
    scores.sort(key=lambda z: z[1], reverse=True)
    return [ticker for ticker, _ in scores[:top_n]]


@dataclass
class BridgeForecastResult:
    forecast: float
    fitted: pd.Series
    indicators: list[str]
    coefficients: pd.Series


def estimate_bridge_forecast(
    component_growth: pd.Series,
    indicator_growth_matrix: pd.DataFrame,
    indicator_target_values: Mapping[str, float],
    target_quarter_end: pd.Timestamp,
    top_n: int,
    decay: float,
    exclude_pandemic: bool,
    growth_target: bool = True,
) -> BridgeForecastResult:
    y = pd.to_numeric(component_growth, errors="coerce")
    selected = select_component_indicators(y, indicator_growth_matrix, top_n=top_n)
    if not selected:
        fallback = float(y.dropna().iloc[-1])
        return BridgeForecastResult(
            forecast=fallback,
            fitted=pd.Series(dtype=float),
            indicators=[],
            coefficients=pd.Series(dtype=float),
        )

    x = indicator_growth_matrix[selected].copy()
    x = x.reindex(y.index)
    x["AR1"] = y.shift(1)
    x["COVID_2020Q1"] = (x.index == pd.Timestamp("2020-03-31")).astype(float)
    x["COVID_2020Q2"] = (x.index == pd.Timestamp("2020-06-30")).astype(float)
    x["COVID_2020Q3"] = (x.index == pd.Timestamp("2020-09-30")).astype(float)
    x["COVID_2020Q4"] = (x.index == pd.Timestamp("2020-12-31")).astype(float)
    train = pd.concat([y.rename("y"), x], axis=1)
    train = train.loc[train.index < target_quarter_end].dropna()

    if exclude_pandemic:
        pandemic = {
            pd.Timestamp("2020-03-31"),
            pd.Timestamp("2020-06-30"),
            pd.Timestamp("2020-09-30"),
            pd.Timestamp("2020-12-31"),
        }
        train = train.loc[~train.index.isin(pandemic)]

    if len(train) < 40:
        fallback = float(y.dropna().iloc[-1])
        return BridgeForecastResult(
            forecast=fallback,
            fitted=pd.Series(dtype=float),
            indicators=selected,
            coefficients=pd.Series(dtype=float),
        )

    x_train = np.column_stack(
        [np.ones(len(train)), train.drop(columns=["y"]).to_numpy(dtype=float)]
    )
    y_train = train["y"].to_numpy(dtype=float)
    weights = decay ** np.arange(len(train) - 1, -1, -1)
    beta = _weighted_ls_fit(x_train, y_train, weights)
    fitted = pd.Series(x_train @ beta, index=train.index)

    prev_q = pd.Timestamp(target_quarter_end) - pd.offsets.QuarterEnd(1)
    ar1_val = float(y.loc[prev_q]) if prev_q in y.index and pd.notna(y.loc[prev_q]) else float(y.dropna().iloc[-1])

    row_dict: Dict[str, float] = {}
    for ticker in selected:
        row_dict[ticker] = float(indicator_target_values.get(ticker, np.nan))
    row_dict["AR1"] = ar1_val
    row_dict["COVID_2020Q1"] = 1.0 if target_quarter_end == pd.Timestamp("2020-03-31") else 0.0
    row_dict["COVID_2020Q2"] = 1.0 if target_quarter_end == pd.Timestamp("2020-06-30") else 0.0
    row_dict["COVID_2020Q3"] = 1.0 if target_quarter_end == pd.Timestamp("2020-09-30") else 0.0
    row_dict["COVID_2020Q4"] = 1.0 if target_quarter_end == pd.Timestamp("2020-12-31") else 0.0

    feature_order = train.drop(columns=["y"]).columns.tolist()
    row = [row_dict.get(k, np.nan) for k in feature_order]
    if any(pd.isna(v) for v in row):
        forecast = float(y.dropna().iloc[-1])
    else:
        forecast = float(np.dot(np.r_[1.0, row], beta))

    # Robust guardrail against unstable bridge extrapolations.
    y_train = train["y"].to_numpy(dtype=float)
    q05 = float(np.nanpercentile(y_train, 5))
    q95 = float(np.nanpercentile(y_train, 95))
    iqr = q95 - q05
    lower = q05 - 1.5 * iqr
    upper = q95 + 1.5 * iqr
    if growth_target:
        lower = max(lower, -80.0)
        upper = min(upper, 80.0)
    forecast = float(np.clip(forecast, lower, upper))

    coef = pd.Series(beta, index=["const"] + feature_order)
    return BridgeForecastResult(
        forecast=forecast,
        fitted=fitted,
        indicators=selected,
        coefficients=coef,
    )


def growth_to_log_level(growth_series: pd.Series) -> pd.Series:
    """Reconstruct log levels from QtrlyActDLog's 400 * log(q_t/q_{t-1})."""
    growth = pd.to_numeric(growth_series, errors="coerce")
    increments = growth / 400.0
    level = increments.cumsum()
    return level


def prepare_quarterly_inputs(
    native_data: pd.DataFrame, real_levels: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return bridge targets and BVAR states, retaining signed inventories.

    Ordinary targets are compounded annual percent growth; their BVAR states
    are log levels. Inventory's target and state are VZ_t / GDP_{t-1}, the
    representation in working-paper Table A1. Its bridge remains a generic
    approximation, not GDPNow's specialized inventory/contribution equations.
    """
    targets = pd.DataFrame(index=native_data.index)
    states = pd.DataFrame(index=native_data.index)
    for ticker in COMPONENT_TICKERS:
        native = pd.to_numeric(native_data[ticker], errors="coerce")
        if ticker == INVENTORY_TICKER:
            lag_gdp = real_levels["GDPZ_USNA"].shift(1).reindex(native.index)
            if (lag_gdp.dropna() <= 0).any():
                raise ValueError("Inventory normalization requires positive lagged real GDP.")
            targets[ticker] = native / lag_gdp
            states[ticker] = targets[ticker]
        else:
            targets[ticker] = 100.0 * np.expm1(native / 100.0)
            states[ticker] = growth_to_log_level(native)
    return targets, states


def bvar_minnesota_posterior_mean(
    level_df: pd.DataFrame,
    lags: int = 5,
    lam: float = 0.15,
    delta_levels: Mapping[str, float] | None = None,
) -> tuple[np.ndarray, list[str], pd.DataFrame]:
    level_df = level_df.dropna(how="any")
    if len(level_df) <= lags + 10:
        raise ValueError("Insufficient rows for BVAR estimation.")
    tickers = level_df.columns.tolist()
    y_values = level_df.to_numpy(dtype=float)
    t, n = y_values.shape

    x_list: list[np.ndarray] = []
    for lag in range(1, lags + 1):
        x_list.append(y_values[lags - lag : t - lag, :])
    x = np.hstack([np.ones((t - lags, 1)), *x_list])
    y = y_values[lags:, :]
    k = x.shape[1]

    beta_ols, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta_ols
    sigma2 = np.var(resid, axis=0)
    sigma2 = np.where(sigma2 <= 1e-12, 1e-12, sigma2)

    beta_post = np.zeros((k, n), dtype=float)
    xtx = x.T @ x
    xty = x.T @ y
    for i, ticker_i in enumerate(tickers):
        delta_i = 1.0
        if delta_levels is not None and ticker_i in delta_levels:
            delta_i = float(delta_levels[ticker_i])
        beta0 = np.zeros(k, dtype=float)
        beta0[1 + i] = delta_i
        omega_inv = np.zeros((k, k), dtype=float)
        omega_inv[0, 0] = 1e-6
        for lag in range(1, lags + 1):
            for j in range(n):
                idx = 1 + (lag - 1) * n + j
                var_ij = (lam**2 / (lag**2)) * (sigma2[i] / sigma2[j])
                var_ij = max(var_ij, 1e-10)
                omega_inv[idx, idx] = 1.0 / var_ij
        a = xtx + omega_inv
        b = xty[:, i] + omega_inv @ beta0
        beta_post[:, i] = np.linalg.solve(a, b)

    y_index = level_df.index[lags:]
    fitted = pd.DataFrame(x @ beta_post, index=y_index, columns=tickers)
    return beta_post, tickers, fitted


def bvar_one_step_forecast(
    beta_post: np.ndarray,
    tickers: Sequence[str],
    level_history: pd.DataFrame,
    lags: int = 5,
) -> pd.Series:
    hist = level_history.dropna(how="any")
    if len(hist) < lags:
        raise ValueError("Insufficient history to forecast with BVAR.")
    tail = hist.iloc[-lags:]
    x_parts: list[float] = [1.0]
    for lag in range(1, lags + 1):
        x_parts.extend(tail.iloc[-lag].to_numpy(dtype=float))
    x_vec = np.asarray(x_parts, dtype=float)
    forecast_level = x_vec @ beta_post
    return pd.Series(forecast_level, index=tickers)


def constrained_blend_weight(
    actual: pd.Series,
    bridge_hat: pd.Series,
    bvar_hat: pd.Series,
    decay: float,
    exclude_pandemic: bool,
) -> float:
    df = pd.concat(
        [
            actual.rename("actual"),
            bridge_hat.rename("bridge"),
            bvar_hat.rename("bvar"),
        ],
        axis=1,
    ).dropna()
    if exclude_pandemic:
        pandemic = {
            pd.Timestamp("2020-03-31"),
            pd.Timestamp("2020-06-30"),
            pd.Timestamp("2020-09-30"),
            pd.Timestamp("2020-12-31"),
        }
        df = df.loc[~df.index.isin(pandemic)]
    if len(df) < 24:
        return 0.5

    x = (df["bridge"] - df["bvar"]).to_numpy(dtype=float)
    z = (df["actual"] - df["bvar"]).to_numpy(dtype=float)
    w = decay ** np.arange(len(df) - 1, -1, -1)
    denom = float(np.sum(w * x * x))
    if abs(denom) <= 1e-10:
        return 0.5
    delta = float(np.sum(w * x * z) / denom)
    return float(np.clip(delta, 0.0, 1.0))


def fisher_growth_saar(
    q_prev: Mapping[str, float],
    q_curr: Mapping[str, float],
    p_prev: Mapping[str, float],
    p_curr: Mapping[str, float],
) -> float:
    num_l = 0.0
    den_l = 0.0
    num_p = 0.0
    den_p = 0.0
    for ticker in COMPONENT_TICKERS:
        qp = float(q_prev[ticker])
        qc = float(q_curr[ticker])
        pp = float(p_prev[ticker])
        pc = float(p_curr[ticker])
        sign = -1.0 if ticker in IMPORT_TICKERS else 1.0
        qp_adj = sign * qp
        qc_adj = sign * qc
        num_l += pp * qc_adj
        den_l += pp * qp_adj
        num_p += pc * qc_adj
        den_p += pc * qp_adj
    if den_l <= 0 or den_p <= 0 or num_l <= 0 or num_p <= 0:
        raise ValueError("Fisher aggregation denominators/numerators are non-positive.")
    ql = num_l / den_l
    qp = num_p / den_p
    q_fisher = math.sqrt(ql * qp)
    return float(((q_fisher**4) - 1.0) * 100.0)


def parse_quarter(value: str | None) -> pd.Period | None:
    if value is None:
        return None
    text = value.strip().upper()
    if re.fullmatch(r"\d{4}Q[1-4]", text):
        return pd.Period(text, freq="Q")
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Unable to parse quarter argument: {value}")
    return pd.Period(ts, freq="Q")


def component_level_ticker(component_ticker: str) -> str:
    return component_ticker.replace("_USNAqtr", "_USNA")


def run_full_model(
    workbook_path: Path,
    outdir: Path,
    as_of_date: pd.Timestamp | None,
    target_quarter: pd.Period | None,
    top_indicators: int,
    factor_max_series: int,
    use_kalman: bool,
    decay: float,
    exclude_pandemic: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    tracking_row = load_tracking_latest(workbook_path, as_of_date=as_of_date, target_quarter=target_quarter)
    as_of = pd.Timestamp(tracking_row["Forecast Date"]).normalize()
    target_q = _quarter_period(pd.Timestamp(tracking_row["Quarter being forecasted"]))
    target_q_end = _quarter_end_timestamp(target_q)
    prev_q_end = _quarter_end_timestamp(target_q - 1)

    qtr_native = load_wide_sheet(workbook_path, "QtrlyActDLog")[COMPONENT_TICKERS].copy()
    qtr_prices = load_wide_sheet(workbook_path, "QtrlyPriceForecasts")[COMPONENT_TICKERS].copy()
    qtr_real_levels = load_wide_sheet(workbook_path, "QtrlyGDPData")
    qtr_growth, level_matrix = prepare_quarterly_inputs(qtr_native, qtr_real_levels)
    rls_weights = load_rls_bridge_weights(workbook_path)
    monthly_levels = load_monthly_levels(workbook_path)
    monthly_levels.loc[monthly_levels.index > as_of] = np.nan
    factor_panel = load_monthly_panel(workbook_path)
    factor_panel = select_factor_panel(factor_panel, as_of_date=as_of, max_series=factor_max_series)
    factor = estimate_factor_series(factor_panel, use_kalman=use_kalman)

    indicator_q_growth_matrix = compute_indicator_quarterly_growth_matrix(monthly_levels)
    indicator_cache: dict[str, IndicatorForecastResult] = {}

    bridge_forecasts: dict[str, float] = {}
    bvar_forecasts: dict[str, float] = {}
    blend_weights: dict[str, float] = {}
    blended_forecasts: dict[str, float] = {}
    used_indicators: dict[str, list[str]] = {}

    # Log component levels plus signed inventory investment / lagged GDP.
    level_train = level_matrix.loc[level_matrix.index <= prev_q_end].dropna(how="any")
    if level_train.empty or level_train.index[-1] != prev_q_end:
        raise ValueError(f"BVAR requires complete quarterly inputs through {prev_q_end.date()}.")
    delta_levels = {ticker: (0.0 if ticker == INVENTORY_TICKER else 1.0) for ticker in COMPONENT_TICKERS}
    beta_post, beta_tickers, bvar_fitted_levels = bvar_minnesota_posterior_mean(
        level_train,
        lags=5,
        lam=0.15,
        delta_levels=delta_levels,
    )
    bvar_forecast_levels = bvar_one_step_forecast(
        beta_post=beta_post,
        tickers=beta_tickers,
        level_history=level_train,
        lags=5,
    )

    # Convert in-sample fitted levels to growth for blend-weight estimation.
    bvar_fitted_growth = bvar_fitted_levels.copy()
    for ticker in COMPONENT_TICKERS:
        if ticker == INVENTORY_TICKER:
            continue  # Inventory state is already the signed ratio target.
        prev_level = level_train[ticker].shift(1).reindex(bvar_fitted_levels.index)
        bvar_fitted_growth[ticker] = (bvar_fitted_levels[ticker] - prev_level).map(_qoq_log_to_annualized)

    for ticker in COMPONENT_TICKERS:
        y = qtr_growth[ticker].copy()
        y = y.loc[y.index <= prev_q_end]

        indicator_target_values: dict[str, float] = {}
        selected = select_component_indicators(y, indicator_q_growth_matrix, top_n=top_indicators)
        for indicator in selected:
            if indicator not in indicator_cache:
                indicator_cache[indicator] = forecast_indicator_quarterly_growth(
                    monthly_series=monthly_levels[indicator],
                    factor=factor,
                    target_quarter=target_q,
                    as_of_date=as_of,
                )
            indicator_target_values[indicator] = indicator_cache[indicator].quarterly_growth

        bridge = estimate_bridge_forecast(
            component_growth=y,
            indicator_growth_matrix=indicator_q_growth_matrix,
            indicator_target_values=indicator_target_values,
            target_quarter_end=target_q_end,
            top_n=top_indicators,
            decay=decay,
            exclude_pandemic=exclude_pandemic,
            growth_target=ticker != INVENTORY_TICKER,
        )
        bridge_forecasts[ticker] = bridge.forecast
        used_indicators[ticker] = bridge.indicators

        # BVAR forecast growth for this ticker.
        prev_level = float(level_train[ticker].iloc[-1])
        next_level = float(bvar_forecast_levels[ticker])
        bvar_forecasts[ticker] = (
            next_level if ticker == INVENTORY_TICKER
            else _qoq_log_to_annualized(next_level - prev_level)
        )

        bvar_hist_series = bvar_fitted_growth[ticker].dropna()
        delta = constrained_blend_weight(
            actual=y,
            bridge_hat=bridge.fitted,
            bvar_hat=bvar_hist_series,
            decay=decay,
            exclude_pandemic=exclude_pandemic,
        )
        if ticker in rls_weights:
            delta = rls_weights[ticker]
        else:
            delta = float(np.clip(delta, 0.05, 0.95))
        blend_weights[ticker] = delta
        blended_forecasts[ticker] = delta * bridge_forecasts[ticker] + (1.0 - delta) * bvar_forecasts[ticker]

    # Build quantities for Fisher aggregation using real component levels from QtrlyGDPData.
    q_prev: dict[str, float] = {}
    q_curr: dict[str, float] = {}
    for ticker in COMPONENT_TICKERS:
        level_ticker = component_level_ticker(ticker)
        if level_ticker not in qtr_real_levels.columns:
            raise ValueError(f"Missing level ticker '{level_ticker}' in QtrlyGDPData for Fisher aggregation.")
        level_series = pd.to_numeric(qtr_real_levels[level_ticker], errors="coerce")
        if prev_q_end not in level_series.index or pd.isna(level_series.loc[prev_q_end]):
            raise ValueError(
                f"Missing previous-quarter level for '{level_ticker}' at {prev_q_end.date()}."
            )
        prev_level = float(level_series.loc[prev_q_end])
        q_prev[ticker] = prev_level
        if ticker == INVENTORY_TICKER:
            q_curr[ticker] = blended_forecasts[ticker] * float(qtr_real_levels.loc[prev_q_end, "GDPZ_USNA"])
        else:
            q_curr[ticker] = _project_level_from_annualized_growth(prev_level, blended_forecasts[ticker])

    # Price levels for t-1 and t from workbook.
    price_prev = qtr_prices.loc[prev_q_end, COMPONENT_TICKERS]
    if target_q_end in qtr_prices.index:
        price_curr = qtr_prices.loc[target_q_end, COMPONENT_TICKERS]
    else:
        price_curr = price_prev.copy()
    p_prev = {ticker: float(price_prev[ticker]) for ticker in COMPONENT_TICKERS}
    p_curr = {}
    for ticker in COMPONENT_TICKERS:
        val = float(price_curr[ticker]) if pd.notna(price_curr[ticker]) else float(price_prev[ticker])
        p_curr[ticker] = val

    gdp_nowcast_py = fisher_growth_saar(q_prev=q_prev, q_curr=q_curr, p_prev=p_prev, p_curr=p_curr)
    gdp_official = float(tracking_row["GDP Nowcast"])

    rows = []
    for ticker in COMPONENT_TICKERS:
        track_col = TRACKING_COMPONENT_COLUMN_MAP.get(ticker)
        official_component = float(tracking_row[track_col]) if track_col and pd.notna(tracking_row[track_col]) else np.nan
        rows.append(
            {
                "component_ticker": ticker,
                "forecast_unit": "fraction_of_lagged_real_gdp" if ticker == INVENTORY_TICKER else "percent_saar",
                "official_component_tracking": official_component,
                "bridge_forecast": bridge_forecasts[ticker],
                "bvar_forecast": bvar_forecasts[ticker],
                "blend_weight_bridge": blend_weights[ticker],
                "blended_forecast": blended_forecasts[ticker],
                "diff_vs_official_component": blended_forecasts[ticker] - official_component
                if pd.notna(official_component)
                else np.nan,
                "indicators_used": ";".join(used_indicators.get(ticker, [])),
                "previous_real_level_millions": q_prev[ticker],
                "forecast_real_level_millions": q_curr[ticker],
            }
        )
    component_df = pd.DataFrame(rows).sort_values("component_ticker")

    summary = {
        "workbook_path": str(workbook_path),
        "workbook_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
        "model_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_version": "current_quarter_corrected_units_v1",
        "tracking_sheet": tracking_row["tracking_sheet"],
        "model_status": "approximate; not an exact independent GDPNow replication",
        "data_vintage_note": "Uses this workbook's stored data, prices and blend weights; --as-of-date does not reconstruct historical release vintages.",
        "forecast_date": as_of.strftime("%Y-%m-%d"),
        "target_quarter": str(target_q),
        "target_quarter_end": target_q_end.strftime("%Y-%m-%d"),
        "gdp_nowcast_python_fisher": gdp_nowcast_py,
        "gdp_nowcast_official_tracking": gdp_official,
        "diff_python_minus_official": gdp_nowcast_py - gdp_official,
        "factor_series_count": int(factor_panel.shape[1]),
        "top_indicators_per_component": int(top_indicators),
        "use_kalman": bool(use_kalman),
        "decay": float(decay),
        "exclude_pandemic_2020": bool(exclude_pandemic),
        "inventory_forecast_billions_chained_2017_dollars": q_curr[INVENTORY_TICKER] / 1000.0,
        "limitations": [
            "Generic bridges and estimated blends; specialized consumption, inventory and trade modules are not replicated.",
            "Factor panel is selected from available workbook series, not the complete prescribed GDPNow panel.",
            "Official workbook component price forecasts and six bridge weights are reused.",
            "This is a snapshot calculation, not a historical real-time-vintage backtest.",
        ],
    }

    outdir.mkdir(parents=True, exist_ok=True)
    comp_path = outdir / "gdpnow_full_model_components.csv"
    summary_path = outdir / "gdpnow_full_model_summary.json"
    component_df.to_csv(comp_path, index=False)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nGDPNow Approximate Model Report")
    print("==============================")
    print(f"Forecast date used: {summary['forecast_date']}")
    print(f"Quarter being forecasted: {summary['target_quarter_end']}")
    print(f"Python nowcast (Fisher): {summary['gdp_nowcast_python_fisher']:.6f}")
    print(f"Official nowcast: {summary['gdp_nowcast_official_tracking']:.6f}")
    print(f"Diff (Python - official): {summary['diff_python_minus_official']:.6f}")
    print(f"Factor panel series used: {summary['factor_series_count']}")
    print(f"Saved component output: {comp_path}")
    print(f"Saved summary output: {summary_path}")

    mismatch_df = component_df.loc[component_df["official_component_tracking"].notna()].copy()
    if not mismatch_df.empty:
        mismatch_df["abs_diff"] = mismatch_df["diff_vs_official_component"].abs()
        top = mismatch_df.sort_values("abs_diff", ascending=False).head(10)
        print(f"\nTop component mismatches vs {tracking_row['tracking_sheet']}:")
        print(
            top[
                [
                    "component_ticker",
                    "official_component_tracking",
                    "blended_forecast",
                    "diff_vs_official_component",
                    "blend_weight_bridge",
                ]
            ].to_string(index=False)
        )

    return component_df, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Full GDPNow-style model clone: dynamic factor + factor-augmented monthly forecasts + "
            "bridge equations + Minnesota BVAR + constrained blending + Fisher aggregation."
        )
    )
    parser.add_argument(
        "workbook_path",
        nargs="?",
        default=str(DEFAULT_WORKBOOK_PATH),
        help=f"Path to GDPTrackingModelDataAndForecasts.xlsx (default: {DEFAULT_WORKBOOK_PATH})",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="Optional as-of date (YYYY-MM-DD). Uses latest available if omitted.",
    )
    parser.add_argument(
        "--quarter",
        type=str,
        default=None,
        help="Optional target quarter (YYYYQn or quarter-end date). Uses latest available if omitted.",
    )
    parser.add_argument(
        "--top-indicators",
        type=int,
        default=6,
        help="Number of monthly indicators per component bridge equation (default: 6).",
    )
    parser.add_argument(
        "--factor-max-series",
        type=int,
        default=126,
        help="Max transformed monthly series used in dynamic factor model (default: 126).",
    )
    parser.add_argument(
        "--no-kalman",
        action="store_true",
        help="Use PCA factor only (skip DynamicFactor Kalman estimation).",
    )
    parser.add_argument(
        "--decay",
        type=float,
        default=0.98,
        help="Time-decay weight for bridge and blend regressions (default: 0.98).",
    )
    parser.add_argument(
        "--include-pandemic-2020",
        action="store_true",
        help="Include 2020Q1-2020Q4 in weight estimation (default: excluded).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook_path = Path(args.workbook_path).expanduser().resolve()
    if not workbook_path.exists():
        print(f"Workbook not found: {workbook_path}", file=sys.stderr)
        return 2

    as_of = pd.to_datetime(args.as_of_date, errors="coerce") if args.as_of_date else None
    if args.as_of_date and pd.isna(as_of):
        print(f"Invalid --as-of-date: {args.as_of_date}", file=sys.stderr)
        return 2
    quarter = parse_quarter(args.quarter)

    try:
        _, summary = run_full_model(
            workbook_path=workbook_path,
            outdir=args.outdir.expanduser().resolve(),
            as_of_date=pd.Timestamp(as_of) if as_of is not None else None,
            target_quarter=quarter,
            top_indicators=max(args.top_indicators, 1),
            factor_max_series=max(args.factor_max_series, 20),
            use_kalman=not args.no_kalman,
            decay=float(args.decay),
            exclude_pandemic=not args.include_pandemic_2020,
        )
    except Exception as exc:
        print(f"Full model run failed: {exc}", file=sys.stderr)
        return 1

    return 0 if np.isfinite(summary["gdp_nowcast_python_fisher"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
