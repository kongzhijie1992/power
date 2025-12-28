"""Backtesting utilities for forecasts and simple metrics."""

import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error


def _tz_naive(series: pd.Series) -> pd.Series:
    """Ensure DatetimeIndex is tz-naive (convert to UTC first if needed)."""
    if (
        isinstance(series.index, pd.DatetimeIndex)
        and series.index.tz is not None
    ):
        series = series.copy()
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series


def simple_rmse(true: pd.Series, pred: pd.Series) -> float:
    # align with consistent timezone handling
    true = _tz_naive(true)
    pred = _tz_naive(pred)
    df = pd.concat([true, pred], axis=1).dropna()
    if df.shape[0] == 0:
        return float("nan")
    return float(np.sqrt(mean_squared_error(df.iloc[:, 0], df.iloc[:, 1])))


def walk_forward_backtest(
    series: pd.Series,
    forecast_func,
    train_window_days: int = 60,
    horizon_days: int = 7,
):
    results = []
    freq = "D"
    end = series.index.max()
    # generate rolling windows ending each day in last 30 days
    for i in range(30, 0, -1):
        ref = end - pd.Timedelta(days=i)
        train_start = ref - pd.Timedelta(days=train_window_days)
        train = series[train_start:ref]
        truth = series[
            ref + pd.Timedelta(hours=1) : ref + pd.Timedelta(days=horizon_days)
        ]
        if len(train) < 24:
            continue
        pred = forecast_func(train, days=horizon_days)
        rmse = simple_rmse(truth, pred)
        results.append({"ref": ref, "rmse": rmse})
    return pd.DataFrame(results)


def walk_forward_predict_series(
    series: pd.Series,
    forecast_func,
    train_window_days: int = 60,
    horizon_days: int = 7,
    step_hours: int = 1,
):
    """
    Generate forward-only predictions across history without look-ahead.

    For each reference time (hourly) after the training window, train on the
    trailing `train_window_days` of data and forecast `horizon_days`. Predictions
    are kept only the first time a timestamp becomes available, so no later
    window overwrites an earlier forecast (avoids leakage).

    Returns a DataFrame indexed by forecast target timestamps with columns:
      - pred: model prediction
      - actual: observed value (if available)
      - train_end: last timestamp included in the training window
    """
    series = _tz_naive(series.sort_index())
    if series.empty:
        return pd.DataFrame(columns=["pred", "actual", "train_end"])

    horizon = pd.Timedelta(days=horizon_days)
    window = pd.Timedelta(days=train_window_days)
    end = series.index.max()

    preds: dict = {}
    # iterate over each hour after the initial window
    step = max(int(step_hours), 1)
    for ref in series.index[::step]:
        train_end = ref - pd.Timedelta(hours=1)
        train_start = train_end - window
        train = series[
            (series.index > train_start) & (series.index <= train_end)
        ]
        if len(train) < 24:
            continue
        fc = forecast_func(train, days=horizon_days)
        fc = _tz_naive(fc)
        fc = fc[fc.index <= end]
        for ts, val in fc.items():
            existing = preds.get(ts)
            # keep the prediction with the most recent train_end that is still <= ts
            if existing is None or train_end > existing[1]:
                preds[ts] = (val, train_end)

    if not preds:
        return pd.DataFrame(columns=["pred", "actual", "train_end"])

    df = pd.DataFrame.from_dict(
        preds, orient="index", columns=["pred", "train_end"]
    ).sort_index()
    df["actual"] = series.reindex(df.index)
    return df[["pred", "actual", "train_end"]]
