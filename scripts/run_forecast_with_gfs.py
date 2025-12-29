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
import pandas as pd
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
from src.configuration import load_config_with_overrides
from src.data.validation import validate_price_series
from src.data.versioning import hash_dataframe, record_dataset_version, save_model_artifact

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_or_create_data(area: str, days: int = 90) -> tuple[pd.Series, bool]:
    """Load persisted data or create synthetic."""
    try:
        series = load_price_series(area)
        if len(series) > 0:
            logger.info("Loaded %d points for %s", len(series), area)
            return series, False
    except Exception as e:
        logger.warning("Failed to load persisted price data: %s", e)
    # fallback to older ingest storage
    try:
        series = load_existing(area)
        if len(series) > 0:
            logger.info(
                "Loaded %d points for %s via legacy path", len(series), area
            )
            return series, False
    except Exception:
        pass
    # create synthetic
    logger.info("Generating synthetic data for %s", area)
    series = synthetic_area_series(area, days=days)
    save_combined(series, area)
    return series, True


def _log_retraining_steps():
    steps = [
        "Load or generate price history.",
        "Validate data for missing/ordering issues.",
        "Record dataset hash + metadata.",
        "Retrain mean + quantile models.",
        "Persist model artifacts + metadata.",
    ]
    logger.info("Retraining steps:")
    for step in steps:
        logger.info("  - %s", step)


def main(
    area: str = "DE_LU",
    lat: float = 52.5,
    lon: float = 13.4,
    config_path: str | None = None,
    overrides=None,
):
    """Train and backtest weather-integrated forecasting ensemble."""
    logger.info(
        "Training weather-integrated LightGBM ensemble for %s (lat=%.1f, lon=%.1f)",
        area,
        lat,
        lon,
    )

    cfg = load_config_with_overrides(config_path, overrides or [])
    feature_cfg = cfg.get("features", {})
    model_cfg = cfg.get("model", {})
    data_cfg = cfg.get("data", {})
    artifact_cfg = cfg.get("artifacts", {})
    history_days = int(data_cfg.get("history_days", 90))
    artifact_dir = Path(artifact_cfg.get("dir", "artifacts"))

    _log_retraining_steps()

    # Load/create data
    prices, synthetic = load_or_create_data(area, days=history_days)
    issues = validate_price_series(prices)
    if issues:
        raise ValueError(f"Price series validation failed: {issues}")

    dataset_hash = hash_dataframe(prices)
    record_dataset_version(
        name=f"{area}_prices",
        frame=prices,
        output_dir=artifact_dir / "datasets",
        extra={
            "area": area,
            "synthetic": synthetic,
            "config": {"features": feature_cfg, "model": model_cfg},
        },
    )

    # Train mean model with weather features
    logger.info("Training mean-prediction model...")
    model, stats = cv_train_lgbm(
        prices,
        n_splits=int(model_cfg.get("cv_splits", 3)),
        params=model_cfg.get("lgbm_params"),
        lat=lat,
        lon=lon,
        num_boost_round=int(model_cfg.get("num_boost_round", 200)),
        use_weather=bool(feature_cfg.get("use_weather", True)),
    )
    logger.info("CV stats: %s", stats)

    # Train quantile models for probabilistic forecast
    q_models = None
    if feature_cfg.get("enable_quantile_models", True):
        logger.info("Training quantile models (0.1, 0.5, 0.9)...")
        q_models = quantile_models_train(
            prices,
            quantiles=(0.1, 0.5, 0.9),
            lat=lat,
            lon=lon,
            num_boost_round=int(model_cfg.get("num_boost_round", 200)),
            use_weather=bool(feature_cfg.get("use_weather", True)),
        )
    logger.info(
        "Quantile models trained: %s",
        list(q_models.keys()) if q_models else "None",
    )

    save_model_artifact(
        model,
        output_dir=artifact_dir / "models",
        name=f"{area}_price_forecast",
        extra={
            "area": area,
            "dataset_hash": dataset_hash,
            "config": {"features": feature_cfg, "model": model_cfg},
            "metrics": stats,
        },
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
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--lat", type=float, default=52.5)
    p.add_argument("--lon", type=float, default=13.4)
    p.add_argument("--config", default=None, help="Path to YAML config")
    p.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Override config values (dot.key=value)",
    )
    args = p.parse_args()
    main(
        args.area,
        lat=args.lat,
        lon=args.lon,
        config_path=args.config,
        overrides=args.overrides,
    )
