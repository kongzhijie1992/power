"""CI smoke check: validate synthetic data and run a quick training pass."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging

from src.configuration import load_config_with_overrides
from src.data.validation import validate_price_series
from src.ingest.ingest_all import synthetic_area_series
from src.models.forecast_cv import cv_train_lgbm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(config_path: str | None = None, overrides=None) -> None:
    cfg = load_config_with_overrides(config_path, overrides or [])
    feature_cfg = cfg.get("features", {})
    model_cfg = cfg.get("model", {})

    series = synthetic_area_series("DE_LU", days=30)
    issues = validate_price_series(series)
    if issues:
        raise SystemExit(f"Data validation failed: {issues}")

    model, stats = cv_train_lgbm(
        series,
        n_splits=2,
        params=model_cfg.get("lgbm_params"),
        num_boost_round=10,
        use_weather=bool(feature_cfg.get("use_weather", False)),
    )
    if model is None:
        raise SystemExit("Smoke training failed: model was not created.")
    logger.info("Smoke training completed: %s", stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="Path to YAML config")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Override config values (dot.key=value)",
    )
    args = parser.parse_args()
    main(args.config, overrides=args.overrides)
