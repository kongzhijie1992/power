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
import os

import pandas as pd
import numpy as np

from src.ingest.ingest_all import synthetic_area_series, fetch_and_persist_all
from src.models.forecast_cv import cv_train_lgbm, predict_with_model
from src.dispatch.zonal_dispatch import dispatch_series_with_mix
from src.data.io import save_series_csv, load_price_series


logging.basicConfig(level=logging.INFO)


def main(area: str, synthetic: bool = True):
    if synthetic:
        prices = synthetic_area_series(area, days=90)
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
            fetch_and_persist_all(api_key=api_key, areas=[area], days=90)
            prices = load_price_series(area)

    # Persist fetched/generated prices
    if synthetic:
        save_series_csv(prices, area)

    # Train CV model (if available)
    model, stats = cv_train_lgbm(prices)
    print("CV stats:", stats)

    # Predict 7 days
    forecast = predict_with_model(model, prices, days=7)
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
    args = p.parse_args()
    main(args.area, synthetic=args.synthetic)
