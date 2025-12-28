"""LightGBM-based price forecasting with calendar/lag features and optional weather."""

from typing import Optional, Dict
from pathlib import Path
import pandas as pd
import numpy as np

try:
    from lightgbm import LGBMRegressor
except Exception:  # pragma: no cover
    LGBMRegressor = None

try:
    import holidays
except Exception:  # pragma: no cover
    holidays = None


def _tz_naive(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if idx.tz is not None:
        return idx.tz_convert("UTC").tz_localize(None)
    return idx


def _add_calendar_features(
    df: pd.DataFrame, idx: pd.DatetimeIndex, country: Optional[str]
) -> pd.DataFrame:
    df["hour"] = idx.hour
    df["dayofweek"] = idx.dayofweek
    df["month"] = idx.month
    df["is_weekend"] = df["dayofweek"].isin([5, 6]).astype(int)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["dayofweek"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dayofweek"] / 7)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    if holidays and country:
        try:
            hol = holidays.country_holidays(country, years=list(set(idx.year)))
        except Exception:
            hol = {}
        df["is_holiday"] = [1 if ts.date() in hol else 0 for ts in idx]
    else:
        df["is_holiday"] = 0
    return df


def build_price_features(
    series: pd.Series,
    weather: Optional[pd.DataFrame] = None,
    country: Optional[str] = None,
) -> pd.DataFrame:
    """Construct feature matrix with lags/rolling stats and optional weather."""
    series = series.sort_index()
    idx = series.index
    df = pd.DataFrame({"y": series})
    df = _add_calendar_features(df, idx, country)
    for lag in (1, 24, 48, 168):
        df[f"lag_{lag}"] = series.shift(lag)
    df["rmean_24"] = series.rolling(24).mean()
    df["rmean_168"] = series.rolling(168).mean()
    if weather is not None:
        w = weather.copy()
        if not isinstance(w.index, pd.DatetimeIndex):
            if "datetime" in w.columns:
                w = w.set_index(pd.to_datetime(w["datetime"]))
            elif "time" in w.columns:
                w = w.set_index(pd.to_datetime(w["time"]))
        w.index = _tz_naive(pd.to_datetime(w.index))
        w = w.reindex(idx).ffill().fillna(0)
        if "windspeed_10m" in w.columns:
            df["windspeed_10m"] = w["windspeed_10m"]
        if "shortwave_radiation" in w.columns:
            df["shortwave_radiation"] = w["shortwave_radiation"]
    return df.dropna()


def train_price_model(
    series: pd.Series,
    weather: Optional[pd.DataFrame] = None,
    country: Optional[str] = None,
    params: Optional[Dict] = None,
):
    if LGBMRegressor is None:
        raise ImportError("lightgbm is required for price model")
    feat_df = build_price_features(series, weather=weather, country=country)
    y = feat_df.pop("y")
    default = dict(
        objective="regression",
        learning_rate=0.05,
        n_estimators=200,
        max_depth=-1,
        num_leaves=64,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    if params:
        default.update(params)
    model = LGBMRegressor(**default)
    model.fit(feat_df, y)
    model.feature_list_ = list(feat_df.columns)
    return model


def _build_recursive_features(
    history: pd.Series,
    model,
    weather: Optional[pd.DataFrame],
    horizon_hours: int,
    country: Optional[str],
):
    preds = []
    series_aug = history.copy()
    for i in range(horizon_hours):
        ts = series_aug.index.max() + pd.Timedelta(hours=1)
        candidate = pd.concat([series_aug, pd.Series(index=[ts], dtype=float)])
        feat_df = build_price_features(
            candidate, weather=weather, country=country
        )
        row = feat_df.iloc[[-1]].drop(columns=["y"])
        if hasattr(model, "feature_list_"):
            row = row.reindex(columns=model.feature_list_, fill_value=0)
        pred = float(model.predict(row)[0])
        preds.append((ts, pred))
        series_aug.loc[ts] = pred
    return pd.Series({ts: val for ts, val in preds})


def forecast_price(
    history: pd.Series,
    weather: Optional[pd.DataFrame] = None,
    country: Optional[str] = None,
    horizon_days: int = 7,
    params: Optional[Dict] = None,
) -> pd.Series:
    """Train a model on history and forecast horizon using recursive one-hour steps."""
    history = history.sort_index()
    history.index = _tz_naive(history.index)
    model = train_price_model(
        history, weather=weather, country=country, params=params
    )
    horizon_hours = horizon_days * 24
    return _build_recursive_features(
        history, model, weather, horizon_hours, country
    )
