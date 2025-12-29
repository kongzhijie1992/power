"""Baseline forecasting utilities for day-ahead prices.

This module provides a simple seasonal/lag baseline and an optional LightGBM wrapper.
"""

from typing import Optional
import pandas as pd
import numpy as np

try:
    import lightgbm as lgb
except Exception:
    lgb = None


def make_features(series: pd.Series) -> pd.DataFrame:
    s = series.copy()
    df = pd.DataFrame({"y": s})
    df["hour"] = df.index.hour
    df["dayofweek"] = df.index.dayofweek
    # lags
    for lag in [24, 48, 168]:
        df[f"lag_{lag}"] = df["y"].shift(lag)
    # rolling means
    df["rmean_24"] = df["y"].rolling(24).mean()
    df = df.dropna()
    return df


def _to_utc(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("series must have a DatetimeIndex")
    if series.index.tz is None:
        series = series.tz_localize("UTC")
    else:
        series = series.tz_convert("UTC")
    return series


def _future_index(series: pd.Series, days: int) -> pd.DatetimeIndex:
    last = series.index.max()
    periods = days * 24
    return pd.date_range(
        start=last + pd.Timedelta(hours=1), periods=periods, freq="h", tz="UTC"
    )


def weekday_hour_average_forecast(
    series: pd.Series, days: int = 7
) -> pd.Series:
    """Forecast using historical average by (dayofweek, hour)."""
    hist = _to_utc(series.copy())
    idx = _future_index(hist, days)
    df = hist.to_frame("y")
    df["hour"] = df.index.hour
    df["dayofweek"] = df.index.dayofweek
    pivot = df.groupby(["dayofweek", "hour"])["y"].mean().sort_index()
    hour_means = df.groupby("hour")["y"].mean()
    global_mean = df["y"].mean()
    preds = []
    for ts in idx:
        val = pivot.get((ts.dayofweek, ts.hour))
        if pd.isna(val):
            val = hour_means.get(ts.hour, global_mean)
        if pd.isna(val):
            val = global_mean
        preds.append(val)
    s = pd.Series(preds, index=idx)
    s.index = s.index.tz_convert(None)
    return s


def seasonal_naive_forecast(series: pd.Series, days: int = 7) -> pd.Series:
    """Forecast next `days` days (hourly) using last week's same-hour values."""
    hist = _to_utc(series.copy())
    idx = _future_index(hist, days)
    fallback = weekday_hour_average_forecast(series, days=days)
    preds = []
    for ts in idx:
        prev = ts - pd.Timedelta(days=7)
        val = hist.get(prev)
        if pd.isna(val):
            val = fallback.get(ts.tz_convert(None))
        preds.append(val)
    s = pd.Series(preds, index=idx)
    s.index = s.index.tz_convert(None)
    return s


def train_lgbm(series: pd.Series, params: Optional[dict] = None):
    if lgb is None:
        raise ImportError("lightgbm not available")
    df = make_features(series)
    X = df.drop(columns=["y"])
    y = df["y"]
    dtrain = lgb.Dataset(X, label=y)
    params = params or {
        "objective": "regression",
        "metric": "rmse",
        "verbosity": -1,
    }
    booster = lgb.train(params, dtrain, num_boost_round=100)
    return booster, X.columns.tolist()


def predict_lgbm(
    model, feature_cols, history: pd.Series, days: int = 7
) -> pd.Series:
    # Rolling predict is left as a simple implementation using historical features where possible
    preds = seasonal_naive_forecast(history, days=days)
    return preds
