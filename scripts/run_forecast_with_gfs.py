"""Demo: Train LightGBM ensemble with weather features (GFS) and generate probabilistic forecasts.

This script:
1. Loads or generates synthetic price data for a pilot area.
2. Trains a LightGBM mean-prediction model with integrated weather features (wind, solar).
3. Trains quantile models (0.1, 0.5, 0.9) for probabilistic forecasts.
4. Backtests walk-forward to estimate out-of-sample performance.
5. Generates a 7-day probabilistic forecast.
"""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import datetime as dt

import pandas as pd
import yaml

from src.ingest.ingest_all import synthetic_area_series
from src.ingest.incremental_ingest import load_existing, save_combined
from src.models.forecast_cv import (
    cv_train_lgbm,
    quantile_models_train,
    predict_with_model,
    predict_quantile,
)
from src.models.backtest import walk_forward_backtest
from src.data.io import load_price_series

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_or_create_data(area: str, days: int = 90) -> pd.Series:
    """Load persisted data or create synthetic."""
    try:
        series = load_price_series(area)
        if len(series) > 0:
            logger.info("Loaded %d points for %s", len(series), area)
            return series
    except Exception as e:
        logger.warning("Failed to load persisted price data: %s", e)
    # fallback to older ingest storage
    try:
        series = load_existing(area)
        if len(series) > 0:
            logger.info("Loaded %d points for %s via legacy path", len(series), area)
            return series
    except Exception:
        pass
    # create synthetic
    logger.info("Generating synthetic data for %s", area)
    series = synthetic_area_series(area, days=days)
    save_combined(series, area)
    return series


def load_config():
    cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml.example"
    return yaml.safe_load(open(cfg_path)) or {}


def main(area: str = "DE", lat: float = 52.5, lon: float = 13.4):
    """Train and backtest weather-integrated forecasting ensemble."""
    logger.info(
        "Training weather-integrated LightGBM ensemble for %s (lat=%.1f, lon=%.1f)",
        area,
        lat,
        lon,
    )

    # Load/create data
    prices = load_or_create_data(area, days=90)

    # Train mean model with weather features
    logger.info("Training mean-prediction model...")
    model, stats = cv_train_lgbm(prices, n_splits=3, lat=lat, lon=lon)
    logger.info("CV stats: %s", stats)

    # Train quantile models for probabilistic forecast
    logger.info("Training quantile models (0.1, 0.5, 0.9)...")
    q_models = quantile_models_train(
        prices, quantiles=(0.1, 0.5, 0.9), lat=lat, lon=lon
    )
    logger.info(
        "Quantile models trained: %s", list(q_models.keys()) if q_models else "None"
    )

    # Walk-forward backtest
    logger.info("Running walk-forward backtest...")

    def fc_fn(s, days=7):
        return predict_with_model(model, s, days=days, lat=lat, lon=lon)

    bt_results = walk_forward_backtest(
        prices, fc_fn, train_window_days=60, horizon_days=7
    )
    logger.info("Backtest results (last 10 windows):")
    logger.info(bt_results.tail(10))
    if len(bt_results) > 0:
        logger.info("Mean RMSE: %.2f", bt_results["rmse"].mean())

    # Generate 7-day forecast with quantiles
    logger.info("Generating 7-day probabilistic forecast...")
    fcst_mean = predict_with_model(model, prices, days=7, lat=lat, lon=lon)
    fcst_q = predict_quantile(q_models, prices, days=7, lat=lat, lon=lon)

    logger.info("Mean forecast:")
    logger.info(fcst_mean.head())

    logger.info("Quantile forecasts:")
    for q, s in fcst_q.items():
        logger.info("  q=%.1f: %s", q, s.head().to_dict())

    # Simple summary
    fcst_df = pd.DataFrame(
        {
            "mean": fcst_mean,
            "q10": fcst_q.get(0.1, fcst_mean * 0.95),
            "q90": fcst_q.get(0.9, fcst_mean * 1.05),
        }
    )
    logger.info("Summary forecast DF:")
    logger.info(fcst_df)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE")
    p.add_argument("--lat", type=float, default=52.5)
    p.add_argument("--lon", type=float, default=13.4)
    args = p.parse_args()
    main(args.area, lat=args.lat, lon=args.lon)
