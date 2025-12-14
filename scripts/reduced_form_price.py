#!/usr/bin/env python3
"""Reduced-form Euphemia + hybrid residual model for day-ahead prices.

Pipeline per area:
1) Build a simple supply stack price from residual/net load:
   price_stack = intercept + slope * net_load + scarcity_adder(reserve_margin).
   Stack is calibrated from historical price vs residual_demand.
2) Fit a LightGBM residual model on (price - stack_price) using calendar +
   net-load dynamics, then forecast residuals on the net-load forecast.
3) Save price_forecast.csv with mean/q10/q90 for dashboards.

Inputs expected in data/<AREA>/:
  - day_ahead_real.parquet/csv (or day_ahead.*) with price series (column `value`)
  - residual_demand.csv with columns [datetime, residual_demand]
  - demand_forecast.csv with columns including corrected_mean (MW)
  - optional weather is ignored in this reduced-form version
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Iterable

import numpy as np
import pandas as pd

try:
    from lightgbm import LGBMRegressor
except Exception:  # pragma: no cover
    LGBMRegressor = None

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("reduced_form_price")


def _read_csv_indexed(path: Path, value_col: Optional[str] = None) -> pd.Series:
    df = pd.read_csv(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    if value_col and value_col in df.columns:
        return df[value_col]
    # pick the first numeric column
    num_cols = df.select_dtypes(include="number").columns
    if len(num_cols) == 0:
        raise ValueError(f"No numeric columns in {path}")
    return df[num_cols[0]]


def _load_price(area: str) -> pd.Series:
    candidates = [
        DATA_DIR / area / "day_ahead_real.parquet",
        DATA_DIR / area / "day_ahead_real.csv",
        DATA_DIR / area / "day_ahead.parquet",
        DATA_DIR / area / "day_ahead.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
            series = df["value"]
            series.index = pd.to_datetime(df.index if df.index.name else df["datetime"])
        else:
            series = _read_csv_indexed(path, value_col="value")
        return series.sort_index()
    raise FileNotFoundError(f"No price file found for {area}")


def _load_residual_demand(area: str) -> pd.Series:
    path = DATA_DIR / area / "residual_demand.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return _read_csv_indexed(path, value_col="residual_demand").sort_index()


def _load_demand_forecast(area: str) -> pd.Series:
    path = DATA_DIR / area / "demand_forecast.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    # prefer corrected_mean, fallback to tso_forecast
    for col in ("corrected_mean", "tso_forecast", "mean"):
        if col in df.columns:
            return df[col].sort_index()
    num_cols = df.select_dtypes(include="number").columns
    return df[num_cols[0]].sort_index()


def _to_hourly(series: pd.Series) -> pd.Series:
    series = series.sort_index()
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series.resample("h").mean()


@dataclass
class StackParams:
    intercept: float
    slope: float
    capacity: float
    scarcity_threshold: float = 0.9
    scarcity_scale: float = 80.0  # EUR/MWh when fully scarce


def calibrate_stack(price: pd.Series, net_load: pd.Series) -> StackParams:
    df = pd.concat([price, net_load], axis=1, join="inner").dropna()
    df.columns = ["price", "net_load"]
    if len(df) < 48:
        raise ValueError("Not enough overlap to calibrate stack (need >=48 hours)")
    x = df["net_load"].values
    y = df["price"].values
    slope = float(np.maximum(np.cov(x, y)[0, 1] / (np.var(x) + 1e-9), 0.01))
    intercept = float(y.mean() - slope * x.mean())
    capacity = float(df["net_load"].quantile(0.995) * 1.05)
    return StackParams(intercept=intercept, slope=slope, capacity=capacity)


def scarcity_adder(net_load: pd.Series, params: StackParams) -> pd.Series:
    margin = net_load / params.capacity
    scarcity = np.clip((margin - params.scarcity_threshold) / (1 - params.scarcity_threshold), 0, None)
    return pd.Series(params.scarcity_scale * scarcity ** 2, index=net_load.index)


def build_stack_price(net_load: pd.Series, params: StackParams) -> pd.Series:
    base = params.intercept + params.slope * net_load
    return base + scarcity_adder(net_load, params)


def compute_ratio(residual: pd.Series, demand_fc: pd.Series, window_days: int = 60) -> float:
    df = pd.concat([residual, demand_fc], axis=1, join="inner").dropna()
    if len(df) == 0:
        return 1.0
    recent = df[df.index >= df.index.max() - pd.Timedelta(days=window_days)]
    ratio = (recent.iloc[:, 0] / (recent.iloc[:, 1] + 1e-6)).clip(0.7, 1.1)
    return float(ratio.median())


def build_features(net_load: pd.Series, stack_price: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "net_load": net_load,
            "stack_price": stack_price,
            "net_load_lag24": net_load.shift(24),
            "net_load_diff": net_load.diff(),
            "stack_diff": stack_price.diff(),
            "hour": net_load.index.hour,
            "dow": net_load.index.dayofweek,
            "month": net_load.index.month,
        }
    )
    return df.bfill().fillna(0)


def fit_residual_model(price: pd.Series, stack_price: pd.Series, net_load: pd.Series) -> Tuple[Optional[object], float]:
    base = pd.concat([price, stack_price, net_load], axis=1, join="inner").dropna()
    base.columns = ["price", "stack", "net_load"]
    residual = base["price"] - base["stack"]
    feat = build_features(base["net_load"], base["stack"])
    if LGBMRegressor is None or len(feat) < 200:
        return None, float(residual.std())
    model = LGBMRegressor(
        objective="regression",
        n_estimators=300,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
    )
    model.fit(feat, residual)
    return model, float(residual.std())


def forecast_area(area: str, horizon_days: int = 7) -> Optional[pd.DataFrame]:
    try:
        price = _to_hourly(_load_price(area))
        residual = _to_hourly(_load_residual_demand(area))
        demand_fc = _to_hourly(_load_demand_forecast(area))
    except FileNotFoundError as e:
        logger.warning("%s: missing data (%s)", area, e)
        return None

    ratio = compute_ratio(residual, demand_fc)
    net_load_hist = residual
    try:
        stack_params = calibrate_stack(price, net_load_hist)
    except ValueError as e:
        logger.warning("%s: %s", area, e)
        return None

    stack_train = build_stack_price(net_load_hist, stack_params)
    model, resid_std = fit_residual_model(price, stack_train, net_load_hist)

    last_price_ts = price.index.max()
    horizon = last_price_ts + pd.Timedelta(days=horizon_days)
    fc_net_load = demand_fc[demand_fc.index > last_price_ts]
    if fc_net_load.empty:
        fc_net_load = demand_fc.iloc[-24 * horizon_days :]
    fc_net_load = fc_net_load[fc_net_load.index <= horizon] * ratio

    stack_forecast = build_stack_price(fc_net_load, stack_params)
    feat_fc = build_features(fc_net_load, stack_forecast)

    if model:
        residual_pred = pd.Series(model.predict(feat_fc), index=feat_fc.index)
    else:
        residual_pred = pd.Series(0.0, index=feat_fc.index)

    mean_price = stack_forecast + residual_pred
    q10 = (mean_price - 1.28 * resid_std).clip(lower=0)
    cap_high = float(price.quantile(0.995) + 50) if not price.empty else None
    q90_raw = mean_price + 1.28 * resid_std
    q90 = q90_raw.clip(upper=cap_high) if cap_high else q90_raw
    out = pd.DataFrame({"mean": mean_price, "q10": q10, "q90": q90})
    out.index.name = "datetime"
    out_path = DATA_DIR / area / "price_forecast.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=True)

    # quick backtest metric on overlap
    aligned = pd.concat([price, stack_train], axis=1, join="inner").dropna()
    aligned.columns = ["price", "stack"]
    backtest_rmse = float(np.sqrt(((aligned["price"] - aligned["stack"]) ** 2).mean()))
    logger.info(
        "%s: saved forecast -> %s | ratio=%.3f slope=%.3f rmse(stack)=%.2f n_hist=%d n_fc=%d",
        area,
        out_path,
        ratio,
        stack_params.slope,
        backtest_rmse,
        len(aligned),
        len(out),
    )
    return out


def main(areas: Iterable[str], horizon_days: int = 7):
    for area in areas:
        forecast_area(area, horizon_days=horizon_days)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--areas", nargs="+", help="Areas to forecast (default: autodetect from data folders)")
    ap.add_argument("--horizon", type=int, default=7, help="Forecast horizon in days")
    args = ap.parse_args()

    if args.areas:
        areas = args.areas
    else:
        areas = [p.name for p in DATA_DIR.iterdir() if p.is_dir() and (p / "demand_forecast.csv").exists()]
    main(areas, horizon_days=args.horizon)
