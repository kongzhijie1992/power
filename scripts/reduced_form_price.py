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
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Iterable, List

import numpy as np
import pandas as pd

from src.data.io import (
    DATA_DIR,
    list_areas_with_file,
    path_exists,
    read_frame,
    resolve_data_path,
    resolve_write_path,
    write_frame,
)

try:
    from lightgbm import LGBMRegressor
except Exception:  # pragma: no cover
    LGBMRegressor = None

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("reduced_form_price")


def _load_frame(path: Path) -> pd.DataFrame:
    try:
        resolved = resolve_data_path(path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(path) from exc
    if not path_exists(resolved):
        raise FileNotFoundError(path)
    df = read_frame(resolved)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    return df


def _read_series(path: Path, value_col: Optional[str] = None) -> pd.Series:
    df = _load_frame(path)
    if value_col and value_col in df.columns:
        return df[value_col]
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
        try:
            df = _load_frame(path)
        except FileNotFoundError:
            continue
        series = df["value"] if "value" in df.columns else df.iloc[:, 0]
        return series.sort_index()
    raise FileNotFoundError(f"No price file found for {area}")


def _load_residual_demand(area: str) -> pd.Series:
    path = DATA_DIR / area / "residual_demand.csv"
    return _read_series(path, value_col="residual_demand").sort_index()


def _load_demand_forecast(area: str) -> pd.Series:
    path = DATA_DIR / area / "demand_forecast.csv"
    df = _load_frame(path)
    # prefer corrected_mean, fallback to tso_forecast
    for col in ("corrected_mean", "tso_forecast", "mean"):
        if col in df.columns:
            return df[col].sort_index()
    num_cols = df.select_dtypes(include="number").columns
    return df[num_cols[0]].sort_index()


def _to_hourly(series: pd.Series) -> pd.Series:
    series = series.sort_index()
    if (
        isinstance(series.index, pd.DatetimeIndex)
        and series.index.tz is not None
    ):
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series.resample("h").mean()


def load_commodities(path: Optional[str]) -> Optional[pd.DataFrame]:
    """Load commodity price time series (e.g., gas, coal, co2) from CSV/Parquet."""
    if path is None:
        return None
    try:
        if path.startswith("s3://"):
            resolved = path
        else:
            resolved = resolve_data_path(Path(path))
    except FileNotFoundError:
        return None
    if not path_exists(resolved):
        return None
    df = read_frame(resolved)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().resample("h").ffill()
    return df[["gas", "coal", "co2"]].rename(columns=str.lower)


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
        raise ValueError(
            "Not enough overlap to calibrate stack (need >=48 hours)"
        )
    x = df["net_load"].values
    y = df["price"].values
    slope = float(np.maximum(np.cov(x, y)[0, 1] / (np.var(x) + 1e-9), 0.01))
    intercept = float(y.mean() - slope * x.mean())
    capacity = float(df["net_load"].quantile(0.995) * 1.05)
    return StackParams(intercept=intercept, slope=slope, capacity=capacity)


def scarcity_adder(net_load: pd.Series, params: StackParams) -> pd.Series:
    margin = net_load / params.capacity
    scarcity = np.clip(
        (margin - params.scarcity_threshold) / (1 - params.scarcity_threshold),
        0,
        None,
    )
    return pd.Series(params.scarcity_scale * scarcity**2, index=net_load.index)


def build_stack_price(net_load: pd.Series, params: StackParams) -> pd.Series:
    base = params.intercept + params.slope * net_load
    return base + scarcity_adder(net_load, params)


def compute_ratio(
    residual: pd.Series, demand_fc: pd.Series, window_days: int = 60
) -> float:
    df = pd.concat([residual, demand_fc], axis=1, join="inner").dropna()
    if len(df) == 0:
        return 1.0
    recent = df[df.index >= df.index.max() - pd.Timedelta(days=window_days)]
    ratio = (recent.iloc[:, 0] / (recent.iloc[:, 1] + 1e-6)).clip(0.7, 1.1)
    return float(ratio.median())


def build_features(
    net_load: pd.Series,
    stack_price: pd.Series,
    commodities: Optional[pd.DataFrame] = None,
    eta_gas: float = 0.55,
    eta_coal: float = 0.38,
    ef_gas: float = 0.36,
    ef_coal: float = 0.90,
) -> pd.DataFrame:
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
    if commodities is not None:
        c = commodities.reindex(net_load.index).ffill()
        gas = c["gas"] if "gas" in c else 0
        coal = c["coal"] if "coal" in c else 0
        co2 = c["co2"] if "co2" in c else 0
        df["mc_gas"] = gas / max(eta_gas, 1e-3) + co2 * ef_gas
        df["mc_coal"] = coal / max(eta_coal, 1e-3) + co2 * ef_coal
        df["css"] = df["stack_price"] - df["mc_gas"]
        df["cds"] = df["stack_price"] - df["mc_coal"]
    return df.bfill().fillna(0)


def fit_residual_model(
    price: pd.Series,
    stack_price: pd.Series,
    net_load: pd.Series,
    commodities: Optional[pd.DataFrame] = None,
    eta_gas: float = 0.55,
    eta_coal: float = 0.38,
    ef_gas: float = 0.36,
    ef_coal: float = 0.90,
) -> Tuple[Optional[object], float]:
    base = pd.concat(
        [price, stack_price, net_load], axis=1, join="inner"
    ).dropna()
    base.columns = ["price", "stack", "net_load"]
    residual = base["price"] - base["stack"]
    feat = build_features(
        base["net_load"],
        base["stack"],
        commodities=(
            commodities.reindex(base.index).ffill()
            if commodities is not None
            else None
        ),
        eta_gas=eta_gas,
        eta_coal=eta_coal,
        ef_gas=ef_gas,
        ef_coal=ef_coal,
    )
    if LGBMRegressor is None or len(feat) < 200:
        return None, float(residual.std())
    model = LGBMRegressor(
        objective="regression",
        n_estimators=300,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        verbose=-1,
    )
    model.fit(feat, residual)
    return model, float(residual.std())


def forecast_area(
    area: str,
    horizon_days: int = 7,
    commodities: Optional[pd.DataFrame] = None,
    eta_gas: float = 0.55,
    eta_coal: float = 0.38,
    ef_gas: float = 0.36,
    ef_coal: float = 0.90,
) -> Optional[pd.DataFrame]:
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
    model, resid_std = fit_residual_model(
        price,
        stack_train,
        net_load_hist,
        commodities=commodities,
        eta_gas=eta_gas,
        eta_coal=eta_coal,
        ef_gas=ef_gas,
        ef_coal=ef_coal,
    )

    last_price_ts = price.index.max()
    horizon = last_price_ts + pd.Timedelta(days=horizon_days)
    fc_net_load = demand_fc[demand_fc.index > last_price_ts]
    if fc_net_load.empty:
        fc_net_load = demand_fc.iloc[-24 * horizon_days :]
    fc_net_load = fc_net_load[fc_net_load.index <= horizon] * ratio

    stack_forecast = build_stack_price(fc_net_load, stack_params)
    feat_fc = build_features(
        fc_net_load,
        stack_forecast,
        commodities=commodities,
        eta_gas=eta_gas,
        eta_coal=eta_coal,
        ef_gas=ef_gas,
        ef_coal=ef_coal,
    )

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
    out_path = resolve_write_path(DATA_DIR / area / "price_forecast.csv")
    write_frame(out, out_path, index_label="datetime")

    # quick backtest metric on overlap
    aligned = pd.concat([price, stack_train], axis=1, join="inner").dropna()
    aligned.columns = ["price", "stack"]
    backtest_rmse = float(
        np.sqrt(((aligned["price"] - aligned["stack"]) ** 2).mean())
    )
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


def backtest_area(
    area: str,
    train_window_days: int = 120,
    horizon_days: int = 7,
    eval_days: int = 30,
    commodities: Optional[pd.DataFrame] = None,
    eta_gas: float = 0.55,
    eta_coal: float = 0.38,
    ef_gas: float = 0.36,
    ef_coal: float = 0.90,
) -> Optional[Tuple[int, float, float, float]]:
    """Walk-forward backtest using rolling stack + residual model."""
    try:
        price = _to_hourly(_load_price(area))
        net = _to_hourly(_load_residual_demand(area))
    except FileNotFoundError:
        return None

    end = min(price.index.max(), net.index.max())
    start = end - pd.Timedelta(days=eval_days)
    refs = pd.date_range(start=start, end=end - pd.Timedelta(days=1), freq="D")

    errs: List[float] = []
    for ref in refs:
        train_start = ref - pd.Timedelta(days=train_window_days)
        train_price = price[(price.index > train_start) & (price.index <= ref)]
        train_net = net[(net.index > train_start) & (net.index <= ref)]
        if len(train_price) < 48 or len(train_net) < 48:
            continue
        try:
            params = calibrate_stack(train_price, train_net)
        except Exception:
            continue
        stack_train = build_stack_price(train_net, params)
        model, _ = fit_residual_model(
            train_price,
            stack_train,
            train_net,
            commodities=commodities,
            eta_gas=eta_gas,
            eta_coal=eta_coal,
            ef_gas=ef_gas,
            ef_coal=ef_coal,
        )

        target_net = net[
            (net.index > ref)
            & (net.index <= ref + pd.Timedelta(days=horizon_days))
        ]
        if target_net.empty:
            continue
        stack_fc = build_stack_price(target_net, params)
        feat_fc = build_features(
            target_net,
            stack_fc,
            commodities=commodities,
            eta_gas=eta_gas,
            eta_coal=eta_coal,
            ef_gas=ef_gas,
            ef_coal=ef_coal,
        )
        if model:
            residual_pred = pd.Series(
                model.predict(feat_fc), index=feat_fc.index
            )
        else:
            residual_pred = pd.Series(0.0, index=feat_fc.index)
        preds = (stack_fc + residual_pred).rename("pred")
        truth = price.reindex(preds.index).rename("actual")
        aligned = pd.concat([truth, preds], axis=1).dropna()
        if aligned.empty:
            continue
        errs.extend((aligned["pred"] - aligned["actual"]).tolist())

    if not errs:
        return None
    err_series = pd.Series(errs)
    rmse = math.sqrt((err_series.pow(2).mean()))
    mae = err_series.abs().mean()
    bias = err_series.mean()
    return len(errs), rmse, mae, bias


def main(
    areas: Iterable[str],
    horizon_days: int = 7,
    commodities: Optional[pd.DataFrame] = None,
    eta_gas: float = 0.55,
    eta_coal: float = 0.38,
    ef_gas: float = 0.36,
    ef_coal: float = 0.90,
):
    for area in areas:
        forecast_area(
            area,
            horizon_days=horizon_days,
            commodities=commodities,
            eta_gas=eta_gas,
            eta_coal=eta_coal,
            ef_gas=ef_gas,
            ef_coal=ef_coal,
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--areas",
        nargs="+",
        help="Areas to forecast/backtest (default: autodetect)",
    )
    ap.add_argument(
        "--horizon", type=int, default=7, help="Forecast horizon in days"
    )
    ap.add_argument(
        "--train-window",
        type=int,
        default=120,
        help="Training window in days for backtest",
    )
    ap.add_argument(
        "--eval-days",
        type=int,
        default=30,
        help="How many trailing days to evaluate in backtest",
    )
    ap.add_argument(
        "--commodities-file",
        type=str,
        help="CSV/Parquet with datetime, gas, coal, co2 columns",
    )
    ap.add_argument(
        "--eta-gas",
        type=float,
        default=0.55,
        help="Gas fleet efficiency (electric)",
    )
    ap.add_argument(
        "--eta-coal",
        type=float,
        default=0.38,
        help="Coal fleet efficiency (electric)",
    )
    ap.add_argument(
        "--ef-gas", type=float, default=0.36, help="Gas CO2 intensity t/MWh_e"
    )
    ap.add_argument(
        "--ef-coal",
        type=float,
        default=0.90,
        help="Coal CO2 intensity t/MWh_e",
    )
    ap.add_argument(
        "--backtest-only",
        action="store_true",
        help="Run walk-forward backtest instead of writing forecasts",
    )
    args = ap.parse_args()

    commodities = load_commodities(args.commodities_file)

    if args.areas:
        areas = args.areas
    else:
        if args.backtest_only:
            residual_areas = set(list_areas_with_file("residual_demand.csv"))
            price_areas: set[str] = set()
            for name in (
                "day_ahead_real.parquet",
                "day_ahead_real.csv",
                "day_ahead.parquet",
                "day_ahead.csv",
            ):
                price_areas.update(list_areas_with_file(name))
            areas = sorted(residual_areas & price_areas)
        else:
            areas = list_areas_with_file("demand_forecast.csv")

    if args.backtest_only:
        rows = []
        for area in areas:
            res = backtest_area(
                area,
                train_window_days=args.train_window,
                horizon_days=args.horizon,
                eval_days=args.eval_days,
                commodities=commodities,
                eta_gas=args.eta_gas,
                eta_coal=args.eta_coal,
                ef_gas=args.ef_gas,
                ef_coal=args.ef_coal,
            )
            if res is None:
                continue
            n, rmse, mae, bias = res
            rows.append((area, n, rmse, mae, bias))
        print("area n_points rmse mae bias")
        for area, n, rmse, mae, bias in sorted(rows):
            print(f"{area:5s} {n:7d} {rmse:8.2f} {mae:8.2f} {bias:8.2f}")
    else:
        main(
            areas,
            horizon_days=args.horizon,
            commodities=commodities,
            eta_gas=args.eta_gas,
            eta_coal=args.eta_coal,
            ef_gas=args.ef_gas,
            ef_coal=args.ef_coal,
        )
