"""Simple demand forecasting utilities using scikit-learn gradient boosting.

This module prepares calendar + weather features from a load series and trains
one mean model plus optional quantile models.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Iterable, Tuple, Union

from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.base import RegressorMixin

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None

try:
    import holidays
except ImportError:  # pragma: no cover
    holidays = None

logger = logging.getLogger(__name__)


def _calendar_features(index: pd.DatetimeIndex, country: str = None) -> pd.DataFrame:
    df = pd.DataFrame(index=index)
    df["hour"] = index.hour
    df["dow"] = index.dayofweek
    df["month"] = index.month
    df["is_weekend"] = df["dow"].isin([5, 6]).astype(int)
    # simple DST proxy: last Sunday of March/October for EU CET/CEST zones
    df["is_dst_transition"] = (
        (df.index.month.isin([3, 10])) & (df.index.dayofweek == 6)
    ).astype(int)

    if holidays and country:
        try:
            hol = holidays.country_holidays(country, years=list(set(index.year)))
        except Exception:
            hol = {}
        df["is_holiday"] = [1 if ts.date() in hol else 0 for ts in index]
    else:
        df["is_holiday"] = 0

    # cyclical encodings
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    return df


def _augment_temperature_features(
    weather: pd.DataFrame, base_c: float = 18.0
) -> pd.DataFrame:
    """
    Add temperature, HDD, and CDD features if a temperature-like column exists.

    - Detect temp column from common names.
    - If values look like Kelvin (> 200), convert to C.
    - HDD = max(base - temp, 0)
    - CDD = max(temp - base, 0)
    """
    w = weather.copy()
    temp_col = None
    for cand in ["temperature", "temp", "t2m", "2t", "temp_c", "temperature_2m"]:
        if cand in w.columns:
            temp_col = cand
            break
    if temp_col is None:
        return w
    temp = w[temp_col].astype(float)
    # rough Kelvin to Celsius detection
    if temp.max() > 200:
        temp = temp - 273.15
    w["temp_c"] = temp
    w["hdd_base18"] = np.clip(base_c - temp, 0, None)
    w["cdd_base18"] = np.clip(temp - base_c, 0, None)
    # piecewise heating/cooling slopes
    w["heating_15c"] = np.clip(15 - temp, 0, None)
    w["cooling_22c"] = np.clip(temp - 22, 0, None)
    return w


def prepare_demand_features(
    load: pd.Series,
    weather: pd.DataFrame = None,
    add_lags: Iterable[int] = (24, 168),
    country: str = None,
) -> Tuple[pd.DataFrame, pd.Series]:
    """Build a feature matrix for demand forecasting."""
    load = load.sort_index()
    feats = _calendar_features(load.index, country=country)
    if weather is not None:
        w = _augment_temperature_features(weather)
        if isinstance(w.index, pd.DatetimeIndex):
            # Avoid backfilling with future values; fill missing with 0 as a neutral fallback.
            w = w.reindex(load.index).ffill().fillna(0)
        feats = pd.concat([feats, w], axis=1)
    if add_lags:
        for lag in add_lags:
            feats[f"lag_{lag}h"] = load.shift(lag)
    # short ramp
    feats["lag_1h"] = load.shift(1)
    feats["ramp_1h"] = load.diff(1)
    feats["ramp_24h"] = load.diff(24)
    df = pd.concat([feats, load.rename("target")], axis=1).dropna()
    y = df.pop("target")
    X = df
    return X, y


def _make_model(use_xgb: bool = False, **kwargs) -> RegressorMixin:
    if lgb:
        params = dict(
            num_leaves=31,
            learning_rate=0.05,
            n_estimators=300,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            min_split_gain=0.0,
            min_child_samples=20,
        )
        params.update(kwargs)
        return lgb.LGBMRegressor(**params)
    return GradientBoostingRegressor(random_state=42)


def train_demand_models(
    X: pd.DataFrame,
    y: pd.Series,
    quantiles=(0.1, 0.5, 0.9),
    use_xgb: bool = False,
) -> Tuple[object, Dict[float, object], Dict[str, float]]:
    """Train a mean model and optional quantile models."""
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.1, shuffle=False
    )
    feature_list = list(X.columns)

    mean_model = _make_model(use_xgb=use_xgb)
    mean_model.fit(X_train, y_train)
    y_pred = mean_model.predict(X_val)
    if not hasattr(mean_model, "feature_list_"):
        mean_model.feature_list_ = feature_list

    quantile_models: Dict[float, object] = {}
    for q in quantiles:
        if lgb:
            m = lgb.LGBMRegressor(
                objective="quantile",
                alpha=q,
                num_leaves=31,
                learning_rate=0.05,
                n_estimators=300,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
            )
        else:
            m = GradientBoostingRegressor(loss="quantile", alpha=q, random_state=42)
        m.fit(X_train, y_train)
        quantile_models[q] = m
        if not hasattr(m, "feature_list_"):
            m.feature_list_ = feature_list

    stats = {
        "mae": float(mean_absolute_error(y_val, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
    }

    return mean_model, quantile_models, stats


def train_per_hod_models(
    X: pd.DataFrame, y: pd.Series, quantiles=(0.1, 0.5, 0.9), use_xgb: bool = False
) -> Tuple[Dict[int, object], Dict[int, Dict[float, object]], Dict[str, float]]:
    """Train separate models per hour-of-day to capture horizon-specific patterns."""
    models = {}
    q_models: Dict[int, Dict[float, object]] = {}
    y_true_all = []
    y_pred_all = []
    for hod in sorted(X["hour"].unique()):
        mask = X["hour"] == hod
        X_h = X[mask]
        y_h = y[mask]
        if len(X_h) < 150:
            continue
        m, qs, _ = train_demand_models(X_h, y_h, quantiles=quantiles, use_xgb=use_xgb)
        models[hod] = m
        q_models[hod] = qs
        # quick validation for stats aggregation
        X_train, X_val, y_train, y_val = train_test_split(
            X_h, y_h, test_size=0.1, shuffle=False
        )
        m_val = _make_model(use_xgb=use_xgb)
        m_val.fit(X_train, y_train)
        y_pred_all.append(m_val.predict(X_val))
        y_true_all.append(y_val.values)
    if y_true_all:
        y_true_cat = np.concatenate(y_true_all)
        y_pred_cat = np.concatenate(y_pred_all)
        stats = {
            "mae": float(mean_absolute_error(y_true_cat, y_pred_cat)),
            "rmse": float(np.sqrt(mean_squared_error(y_true_cat, y_pred_cat))),
        }
    else:
        stats = {"mae": float("nan"), "rmse": float("nan")}
    return models, q_models, stats


def predict_demand(
    models: Dict[str, GradientBoostingRegressor],
    X_future: pd.DataFrame,
    quantile_models: Dict[float, GradientBoostingRegressor] = None,
):
    # per-hour models dict
    if isinstance(models, dict) and not hasattr(models, "predict"):
        preds_dict = {}
        for hod, model in models.items():
            mask = X_future["hour"] == hod
            if mask.sum() == 0:
                continue
            X_sub = X_future.loc[mask]
            if hasattr(model, "feature_list_"):
                X_sub = X_sub.reindex(model.feature_list_, axis=1, fill_value=0)
            preds_dict.setdefault("mean", pd.Series(index=X_future.index, dtype=float))
            preds_dict["mean"].loc[mask] = model.predict(X_sub)
            if quantile_models and hod in quantile_models:
                for q, m in quantile_models[hod].items():
                    X_aligned = X_sub
                    if hasattr(m, "feature_list_"):
                        X_aligned = X_sub.reindex(m.feature_list_, axis=1, fill_value=0)
                    key = f"q{int(q*100)}"
                    preds_dict.setdefault(
                        key, pd.Series(index=X_future.index, dtype=float)
                    )
                    preds_dict[key].loc[mask] = m.predict(X_aligned)
        return pd.DataFrame(preds_dict, index=X_future.index)

    # single model
    if hasattr(models, "feature_list_"):
        X_future = X_future.reindex(models.feature_list_, axis=1, fill_value=0)
    preds = {"mean": models.predict(X_future)}
    if quantile_models:
        for q, m in quantile_models.items():
            X_aligned = X_future
            if hasattr(m, "feature_list_"):
                X_aligned = X_future.reindex(m.feature_list_, axis=1, fill_value=0)
            preds[f"q{int(q*100)}"] = m.predict(X_aligned)
    return pd.DataFrame(preds, index=X_future.index)


def compute_residual_demand(load: pd.Series, weather: pd.DataFrame) -> pd.Series:
    """Compute residual demand = load minus simple renewable proxies from weather.

    Uses rough heuristics:
      - wind_gen = wind_speed (m/s) * 300 (MW proxy)
      - solar_gen = shortwave_radiation (W/m2) * 0.5 (MW proxy)
    """
    # Avoid backfilling with future values; fill missing with 0 as a neutral fallback.
    w = weather.reindex(load.index).ffill().fillna(0)
    wind_col = None
    for cand in ["wind_speed", "windspeed_10m"]:
        if cand in w.columns:
            wind_col = cand
            break
    solar_col = None
    for cand in ["shortwave_radiation", "dswrf", "solar_proxy"]:
        if cand in w.columns:
            solar_col = cand
            break
    wind_gen = w[wind_col] * 300 if wind_col else 0
    solar_gen = w[solar_col] * 0.5 if solar_col else 0
    residual = load - (wind_gen + solar_gen)
    residual.name = "residual_demand"
    return residual


def prepare_error_features(
    actual: pd.Series,
    forecast: pd.Series,
    weather: pd.DataFrame = None,
    add_lags: Iterable[int] = (1, 24, 168),
    country: str = None,
) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """
    Build features to learn TSO forecast error = actual - forecast.

    Returns (X, y, error_series) where y is the error aligned to X.
    """
    df = pd.DataFrame({"actual": actual, "forecast": forecast}).dropna().sort_index()
    error = df["actual"] - df["forecast"]

    feats = _calendar_features(df.index, country=country)
    if weather is not None:
        w = _augment_temperature_features(weather).reindex(df.index).ffill().fillna(0)
        feats = pd.concat([feats, w], axis=1)
    feats["forecast"] = df["forecast"]
    # forecast lags/ramps
    feats["forecast_lag_1h"] = df["forecast"].shift(freq=pd.Timedelta(hours=1))
    feats["forecast_lag_24h"] = df["forecast"].shift(freq=pd.Timedelta(hours=24))
    # Use backward-looking ramps (t - t-1) to avoid leakage from future values.
    feats["forecast_ramp_1h"] = df["forecast"].diff()
    feats["forecast_ramp_24h"] = df["forecast"] - df["forecast"].shift(
        freq=pd.Timedelta(hours=24)
    )
    # actual load lags/ramps
    feats["actual_lag_1h"] = df["actual"].shift(freq=pd.Timedelta(hours=1))
    feats["actual_lag_24h"] = df["actual"].shift(freq=pd.Timedelta(hours=24))
    feats["actual_ramp_1h"] = df["actual"].diff()
    feats["actual_ramp_24h"] = df["actual"] - df["actual"].shift(
        freq=pd.Timedelta(hours=24)
    )

    if add_lags:
        for lag in add_lags:
            lag_delta = pd.Timedelta(hours=lag)
            feats[f"error_lag_{lag}h"] = error.shift(freq=lag_delta)

    full = pd.concat([feats, error.rename("target")], axis=1).dropna()
    y = full.pop("target")
    X = full
    return X, y, error


def build_future_error_features(
    forecast: pd.Series,
    weather: pd.DataFrame = None,
    error_history: pd.Series = None,
    add_lags: Iterable[int] = (24, 168),
    country: str = None,
) -> pd.DataFrame:
    """
    Build feature matrix for future timestamps using known TSO forecast and lagged errors.
    """
    forecast = forecast.sort_index()
    feats = _calendar_features(forecast.index, country=country)
    if weather is not None:
        feats = pd.concat(
            [
                feats,
                _augment_temperature_features(weather)
                .reindex(forecast.index)
                .ffill()
                .fillna(0),
            ],
            axis=1,
        )
    feats["forecast"] = forecast

    if add_lags and error_history is not None:
        hist = error_history.sort_index()
        # extend error history with future index to allow freq-based shifting
        combined_idx = hist.index.union(forecast.index)
        hist_full = hist.reindex(combined_idx).ffill()
        for lag in add_lags:
            lag_delta = pd.Timedelta(hours=lag)
            feats[f"error_lag_{lag}h"] = hist_full.shift(freq=lag_delta).reindex(
                forecast.index
            )
    # Forward-fill only; never backfill time-series features with future values.
    return feats.ffill().fillna(0)
