#!/usr/bin/env python3
"""
Train a simple demand forecast with weather features and produce residual demand.

Usage:
  python scripts/run_demand_forecast.py --area DE_LU --days 90
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import yaml
import pandas as pd

from src.data.io import (
    DATA_DIR,
    load_demand_series,
    load_tso_forecast_publication,
    load_tso_forecast_series,
    resolve_write_path,
    write_frame,
)
from src.features.weather_features import add_gfs_features
from src.models.demand_forecast import (
    prepare_demand_features,
    prepare_error_features,
    build_future_error_features,
    train_demand_models,
    train_per_hod_models,
    predict_demand,
    compute_residual_demand,
)
from src.models import demand_forecast as df_mod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config():
    cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml.example"
    return yaml.safe_load(open(cfg_path, "r", encoding="utf-8")) or {}


def _limit_by_days(series: pd.Series, days: int) -> pd.Series:
    """Slice a series to the last N days by timestamp."""
    if series.empty:
        return series
    cutoff = series.index.max() - pd.Timedelta(days=days)
    return series[series.index >= cutoff]


def _train_direct_model(area: str, days: int, weather_path: str):
    """Fallback: direct demand model without TSO forecast baseline."""
    load_series = load_demand_series(area).sort_index()
    load_series = _limit_by_days(load_series, days)
    logger.info(
        "Loaded demand (direct): %d rows, %s → %s",
        len(load_series),
        load_series.index.min(),
        load_series.index.max(),
    )
    weather_df = add_gfs_features(
        load_series.index, lat=0, lon=0, weather_csv=weather_path
    )
    X, y = prepare_demand_features(load_series, weather_df)
    mean_model, q_models, stats = train_demand_models(X, y)
    logger.info("[direct] Demand model stats: %s", stats)

    future_index = pd.date_range(
        load_series.index.max() + pd.Timedelta(hours=1), periods=24 * 2, freq="h"
    )
    combined_index = load_series.index.append(future_index)
    # Avoid backfilling with future values; fill missing with 0 as a neutral fallback.
    combined_weather = weather_df.reindex(combined_index).ffill().fillna(0)

    def build_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
        feats = df_mod._calendar_features(idx)
        feats = pd.concat([feats, combined_weather.loc[idx]], axis=1)
        for lag in (24, 168):
            shifted = load_series.reindex(combined_index).shift(lag)
            feats[f"lag_{lag}h"] = shifted.loc[idx]
        return feats

    X_future = build_features(future_index).ffill().fillna(0)
    forecasts = predict_demand(mean_model, X_future, q_models)
    out = pd.DataFrame(index=future_index)
    out["corrected_mean"] = forecasts["mean"]
    for col in forecasts.columns:
        if col != "mean":
            out[f"corrected_{col}"] = forecasts[col]
    return out, stats, weather_df, load_series


def main(area: str, days: int = 180):
    cfg = load_config()
    paths = cfg.get("paths", {})
    weather_path = paths.get(
        "weather_template", "data/weather/{area}_weather.csv"
    ).format(area=area)

    # Attempt bias-correction with TSO baseline
    try:
        tso_forecast = load_tso_forecast_series(area).sort_index()
        tso_publication = load_tso_forecast_publication(area).sort_index()
    except FileNotFoundError:
        logger.warning(
            "No TSO forecast found for %s; falling back to direct model", area
        )
        tso_forecast = None
        tso_publication = None

    if tso_forecast is None or tso_forecast.empty:
        forecasts, stats, weather_df, load_series = _train_direct_model(
            area, days, weather_path
        )
    else:
        actual_load = load_demand_series(area).sort_index()
        aligned = pd.concat(
            [actual_load.rename("actual"), tso_forecast.rename("forecast")],
            axis=1,
            join="inner",
        ).dropna()
        aligned = _limit_by_days(aligned, days)
        if aligned.empty:
            logger.warning(
                "Aligned load+forecast empty for %s; falling back to direct model", area
            )
            forecasts, stats, weather_df, load_series = _train_direct_model(
                area, days, weather_path
            )
        else:
            # train on historical errors
            weather_df = add_gfs_features(
                tso_forecast.index, lat=0, lon=0, weather_csv=weather_path
            )
            # crude country code from area (first 2 letters)
            country_code = area.split("_")[0][:2] if area else None
            X, y, error_series = prepare_error_features(
                aligned["actual"],
                aligned["forecast"],
                weather_df.reindex(aligned.index),
                country=country_code,
            )
            # per-hour models with xgboost/lightgbm
            models_by_hod, q_by_hod, stats = train_per_hod_models(X, y, use_xgb=True)
            logger.info("[bias-correction per-HoD] Error model stats: %s", stats)
            if not models_by_hod:
                # fallback to pooled model if too few samples per hour
                logger.warning("Per-HoD model fallback to pooled for %s", area)
                pooled_mean, pooled_q, stats = train_demand_models(X, y, use_xgb=True)
                models_by_hod = pooled_mean
                q_by_hod = pooled_q
                logger.info("[bias-correction pooled] Error model stats: %s", stats)

            # predict errors for the full TSO forecast history (so we get more than 1 day)
            X_all = build_future_error_features(
                tso_forecast,
                weather=weather_df.reindex(tso_forecast.index),
                error_history=error_series,
                country=country_code,
            )
            error_preds_all = predict_demand(models_by_hod, X_all, q_by_hod)

            forecasts = pd.DataFrame(index=tso_forecast.index)
            forecasts["tso_forecast"] = tso_forecast
            if tso_publication is not None and not tso_publication.empty:
                forecasts["tso_publication_time_utc"] = tso_publication.reindex(
                    tso_forecast.index
                )
            forecasts["corrected_mean"] = tso_forecast + error_preds_all["mean"]
            for col in error_preds_all.columns:
                if col == "mean":
                    continue
                forecasts[f"corrected_{col}"] = tso_forecast + error_preds_all[col]
            load_series = aligned["actual"]

    # Residual demand for the historical window (uses actual load if available)
    residual = compute_residual_demand(load_series, weather_df)

    # Persist outputs
    out_dir = DATA_DIR / area
    forecast_path = resolve_write_path(out_dir / "demand_forecast.csv")
    residual_path = resolve_write_path(out_dir / "residual_demand.csv")
    write_frame(forecasts, forecast_path, index_label="datetime")
    write_frame(residual.to_frame(), residual_path, index_label="datetime")
    logger.info("Saved forecast -> %s", forecast_path)
    logger.info("Saved residual -> %s", residual_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--areas", nargs="+", help="List of areas to run (overrides --area)")
    p.add_argument("--days", type=int, default=180)
    args = p.parse_args()
    areas = args.areas if args.areas else [args.area]
    for a in areas:
        logger.info("=== Running demand forecast for %s ===", a)
        try:
            main(a, days=args.days)
        except Exception as e:
            logger.exception("Failed demand forecast for %s: %s", a, e)
