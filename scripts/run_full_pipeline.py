"""Run full pipeline: ingestion (real or synthetic), forecasting CV, forward curve, and zonal dispatch.

This script is useful when you want to run everything locally. When no ENTSO-E key is present,
it runs in `--synthetic` mode so you can test functionality.
"""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging

import pandas as pd
import numpy as np

from src.ingest.ingest_all import synthetic_area_series, fetch_and_persist_all
from src.models.forecast_cv import cv_train_lgbm, predict_with_model
from src.dispatch.zonal_dispatch import dispatch_series_with_mix
from src.data.io import save_series_csv, load_price_series
from src.configuration import load_config_with_overrides
from src.data.validation import validate_price_series
from src.data.versioning import hash_dataframe, record_dataset_version, save_model_artifact


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _log_retraining_steps():
    steps = [
        "Load price history (real or synthetic).",
        "Validate price data quality.",
        "Record dataset hash + metadata for versioning.",
        "Retrain the forecasting model with configured parameters.",
        "Persist model artifact + metadata for reproducibility.",
    ]
    logger.info("Retraining steps:")
    for step in steps:
        logger.info("  - %s", step)


def main(area: str, synthetic: bool = True, config_path: str | None = None, overrides=None):
    cfg = load_config_with_overrides(config_path, overrides or [])
    feature_cfg = cfg.get("features", {})
    model_cfg = cfg.get("model", {})
    data_cfg = cfg.get("data", {})
    artifact_cfg = cfg.get("artifacts", {})
    history_days = int(data_cfg.get("history_days", 90))
    forecast_days = int(data_cfg.get("forecast_horizon_days", 7))
    artifact_dir = Path(artifact_cfg.get("dir", "artifacts"))

    _log_retraining_steps()
    if synthetic:
        prices = synthetic_area_series(area, days=history_days)
    else:
        # attempt to read entsoe.api_key from config
        from pathlib import Path
        import yaml

        cfg_path = Path(__file__).parents[1] / "src" / "config.yaml"
        if not cfg_path.exists():
            cfg_path = (
                Path(__file__).parents[1] / "src" / "config.yaml.example"
            )
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        api_key = (cfg.get("entsoe") or {}).get("api_key")
        if not api_key:
            raise ValueError(
                "No ENTSO-E key available in config — run with --synthetic"
            )
        # prefer existing real data on disk; fall back to fetching if missing
        try:
            prices = load_price_series(area)
        except FileNotFoundError:
            fetch_and_persist_all(api_key=api_key, areas=[area], days=history_days)
            prices = load_price_series(area)

    # Persist fetched/generated prices
    if synthetic:
        save_series_csv(prices, area)

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

    # Train CV model (if available)
    model, stats = cv_train_lgbm(
        prices,
        n_splits=int(model_cfg.get("cv_splits", 3)),
        params=model_cfg.get("lgbm_params"),
        num_boost_round=int(model_cfg.get("num_boost_round", 200)),
        use_weather=bool(feature_cfg.get("use_weather", True)),
    )
    print("CV stats:", stats)

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

    # Predict 7 days
    forecast = predict_with_model(model, prices, days=forecast_days)
    print("Forecast head:")
    print(forecast.head())

    # Create a synthetic generation mix for dispatch demo
    # columns: wind, solar, coal, gas, nuclear
    gen_mix = pd.DataFrame(index=prices.index)
    gen_mix["wind"] = 3000 * (
        0.5 + 0.5 * np.sin(2 * np.pi * prices.index.hour / 24)
    )
    gen_mix["solar"] = 2000 * (
        np.clip(np.cos(2 * np.pi * (prices.index.hour - 6) / 24), 0, 1)
    )
    gen_mix["coal"] = 5000
    gen_mix["gas"] = 4000
    gen_mix["nuclear"] = 2000

    # run dispatch on a downsampled demand series (use prices as proxy demand here)
    demand = prices.resample("H").mean().fillna(method="ffill")
    dispatch_df = dispatch_series_with_mix(demand, gen_mix)
    print("Dispatch sample:")
    print(dispatch_df.head())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--config", default=None, help="Path to YAML config")
    p.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Override config values (dot.key=value)",
    )
    args = p.parse_args()
    main(args.area, synthetic=args.synthetic, config_path=args.config, overrides=args.overrides)
