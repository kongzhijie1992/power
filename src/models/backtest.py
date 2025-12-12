"""Backtesting utilities for forecasts and simple metrics."""
import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error


def simple_rmse(true: pd.Series, pred: pd.Series) -> float:
    # align
    df = pd.concat([true, pred], axis=1).dropna()
    if df.shape[0] == 0:
        return float('nan')
    return float(np.sqrt(mean_squared_error(df.iloc[:,0], df.iloc[:,1])))


def walk_forward_backtest(series: pd.Series, forecast_func, train_window_days: int = 60, horizon_days: int = 7):
    results = []
    freq = 'D'
    end = series.index.max()
    # generate rolling windows ending each day in last 30 days
    for i in range(30, 0, -1):
        ref = end - pd.Timedelta(days=i)
        train_start = ref - pd.Timedelta(days=train_window_days)
        train = series[train_start:ref]
        truth = series[ref + pd.Timedelta(hours=1): ref + pd.Timedelta(days=horizon_days)]
        if len(train) < 24:
            continue
        pred = forecast_func(train, days=horizon_days)
        rmse = simple_rmse(truth, pred)
        results.append({'ref': ref, 'rmse': rmse})
    return pd.DataFrame(results)
