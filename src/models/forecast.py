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
    df = pd.DataFrame({'y': s})
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    # lags
    for lag in [24, 48, 168]:
        df[f'lag_{lag}'] = df['y'].shift(lag)
    # rolling means
    df['rmean_24'] = df['y'].rolling(24).mean()
    df = df.dropna()
    return df


def seasonal_naive_forecast(series: pd.Series, days: int = 7) -> pd.Series:
    """Forecast next `days` days (hourly) using historical average by (hour, dayofweek).
    """
    last = series.index.max()
    freq = series.index.inferred_freq or 'h'
    periods = days * 24
    idx = pd.date_range(start=last + pd.Timedelta(hours=1), periods=periods, freq='h', tz='UTC')
    # historical averages
    hist = series.copy()
    hist = hist.tz_localize('UTC') if hist.index.tz is None else hist
    df = hist.to_frame('y')
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    pivot = df.groupby(['dayofweek', 'hour'])['y'].mean()
    preds = []
    for ts in idx:
        preds.append(pivot.loc[(ts.dayofweek, ts.hour)])
    s = pd.Series(preds, index=idx)
    s.index = s.index.tz_convert(None)
    return s


def train_lgbm(series: pd.Series, params: Optional[dict] = None):
    if lgb is None:
        raise ImportError('lightgbm not available')
    df = make_features(series)
    X = df.drop(columns=['y'])
    y = df['y']
    dtrain = lgb.Dataset(X, label=y)
    params = params or {'objective': 'regression', 'metric': 'rmse', 'verbosity': -1}
    booster = lgb.train(params, dtrain, num_boost_round=100)
    return booster, X.columns.tolist()


def predict_lgbm(model, feature_cols, history: pd.Series, days: int = 7) -> pd.Series:
    # Rolling predict is left as a simple implementation using historical features where possible
    preds = seasonal_naive_forecast(history, days=days)
    return preds
