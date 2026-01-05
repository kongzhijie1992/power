"""Forecast monitoring utilities for error logging, drift, and alerts."""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _tz_naive(series: pd.Series) -> pd.Series:
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series = series.copy()
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series


def build_error_frame(
    actual: pd.Series, forecast: pd.Series
) -> pd.DataFrame:
    """Align actual and forecast and compute error metrics."""
    actual = _tz_naive(actual)
    forecast = _tz_naive(forecast)
    df = pd.concat(
        [actual.rename("actual"), forecast.rename("forecast")], axis=1
    ).dropna()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "actual",
                "forecast",
                "error",
                "abs_error",
                "squared_error",
                "ape",
            ]
        )
    df["error"] = df["actual"] - df["forecast"]
    df["abs_error"] = df["error"].abs()
    df["squared_error"] = df["error"] ** 2
    df["ape"] = df["abs_error"] / df["actual"].replace(0, np.nan)
    return df


def rolling_error_metrics(
    error_frame: pd.DataFrame,
    window: str = "7D",
    min_periods: int = 24,
) -> pd.DataFrame:
    """Compute rolling MAE, RMSE, and MAPE from error frame."""
    if error_frame.empty:
        return pd.DataFrame(columns=["mae", "rmse", "mape"])
    rolling = error_frame.rolling(window=window, min_periods=min_periods)
    mae = rolling["abs_error"].mean()
    rmse = np.sqrt(rolling["squared_error"].mean())
    mape = rolling["ape"].mean()
    return pd.DataFrame({"mae": mae, "rmse": rmse, "mape": mape})


def detect_drift(
    rolling_metrics: pd.DataFrame,
    metric: str = "rmse",
    baseline_window: str = "30D",
    sigma_threshold: float = 3.0,
    min_periods: int = 24,
) -> pd.DataFrame:
    """Flag drift when a rolling metric exceeds a baseline mean + k*std."""
    if rolling_metrics.empty or metric not in rolling_metrics.columns:
        return pd.DataFrame(columns=["metric", "baseline_mean", "baseline_std", "drift"])
    series = rolling_metrics[metric]
    baseline_mean = series.rolling(
        window=baseline_window, min_periods=min_periods
    ).mean()
    baseline_std = series.rolling(
        window=baseline_window, min_periods=min_periods
    ).std()
    threshold = baseline_mean + sigma_threshold * baseline_std
    drift = series > threshold
    return pd.DataFrame(
        {
            "metric": series,
            "baseline_mean": baseline_mean,
            "baseline_std": baseline_std,
            "drift": drift,
        }
    )


def rolling_missing_rate(
    series: pd.Series,
    window: str = "24H",
    expected_freq: str = "H",
    min_periods: int = 1,
) -> pd.Series:
    """Estimate rolling missing data ratio over a time window."""
    series = _tz_naive(series)
    if series.empty:
        return pd.Series(dtype=float)
    full_idx = pd.date_range(
        start=series.index.min(),
        end=series.index.max(),
        freq=expected_freq,
    )
    aligned = series.reindex(full_idx)
    missing = aligned.isna().astype(int)
    return missing.rolling(window=window, min_periods=min_periods).mean()


def apply_alert_thresholds(
    error_frame: pd.DataFrame,
    missing_rate: pd.Series,
    abs_error_threshold: float,
    missing_rate_threshold: float,
) -> pd.DataFrame:
    """Apply alert thresholds for large errors and missing data spikes."""
    if error_frame.empty:
        return pd.DataFrame(columns=["abs_error_alert", "missing_rate_alert"])
    alerts = pd.DataFrame(index=error_frame.index)
    alerts["abs_error_alert"] = error_frame["abs_error"] > abs_error_threshold
    if missing_rate is not None and not missing_rate.empty:
        alerts["missing_rate_alert"] = missing_rate.reindex(alerts.index).fillna(0)
        alerts["missing_rate_alert"] = (
            alerts["missing_rate_alert"] > missing_rate_threshold
        )
    else:
        alerts["missing_rate_alert"] = False
    return alerts


def log_forecast_monitoring(
    actual: pd.Series,
    forecast: pd.Series,
    rolling_window: str = "7D",
    baseline_window: str = "30D",
    abs_error_threshold: float = 50.0,
    missing_rate_threshold: float = 0.1,
    expected_freq: str = "H",
) -> Dict[str, Optional[pd.DataFrame]]:
    """Log monitoring metrics and return computed frames."""
    error_frame = build_error_frame(actual, forecast)
    rolling_metrics = rolling_error_metrics(error_frame, window=rolling_window)
    drift_frame = detect_drift(
        rolling_metrics, baseline_window=baseline_window
    )
    missing_rate = rolling_missing_rate(
        actual, window=rolling_window, expected_freq=expected_freq
    )
    alerts = apply_alert_thresholds(
        error_frame,
        missing_rate,
        abs_error_threshold=abs_error_threshold,
        missing_rate_threshold=missing_rate_threshold,
    )

    if not rolling_metrics.empty:
        latest_metrics = rolling_metrics.dropna().tail(1)
        if not latest_metrics.empty:
            logger.info(
                "Rolling metrics (%s): %s",
                rolling_window,
                latest_metrics.to_dict(orient="records")[0],
            )
    if not drift_frame.empty:
        latest_drift = drift_frame.dropna().tail(1)
        if not latest_drift.empty:
            logger.info(
                "Drift status: %s",
                latest_drift[["metric", "drift"]].to_dict(
                    orient="records"
                )[0],
            )
    if not alerts.empty:
        alert_counts = alerts.tail(1).to_dict(orient="records")[0]
        logger.warning("Alert status: %s", alert_counts)

    return {
        "error_frame": error_frame,
        "rolling_metrics": rolling_metrics,
        "drift": drift_frame,
        "alerts": alerts,
    }
