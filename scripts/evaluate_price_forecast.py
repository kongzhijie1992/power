#!/usr/bin/env python3
"""
Backtest price forecasts and persist forecasts for dashboarding using LightGBM with lags/seasonality.

Usage examples:
  python scripts/evaluate_price_forecast.py --area DE_LU
  python scripts/evaluate_price_forecast.py --areas DE_LU FR --days 365 --horizon 7 --train-window 120

The script:
  - Loads day-ahead prices from data/<AREA>/day_ahead.csv (or .parquet).
  - Runs a walk-forward backtest using a seasonal-naive forecast baseline.
  - Generates forward-only historical predictions (no look-ahead) for all timestamps.
  - Saves a forward forecast to data/<AREA>/price_forecast.csv for dashboards.
"""
import argparse
import logging
from pathlib import Path
from typing import Iterable, Tuple, Optional
import sys

import pandas as pd

# Ensure local src is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.io import (
    DATA_DIR,
    load_price_series,
    path_exists,
    read_frame,
    resolve_data_path,
    resolve_write_path,
    write_frame,
)
from src.models.backtest import walk_forward_predict_series, simple_rmse
from src.models.price_model import forecast_price

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_price_series(area: str, days: int | None = None) -> pd.Series:
    """Load price series and optionally limit to trailing N days."""
    series = load_price_series(area).sort_index()
    if (
        isinstance(series.index, pd.DatetimeIndex)
        and series.index.tz is not None
    ):
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    if days:
        cutoff = series.index.max() - pd.Timedelta(days=days)
        series = series[series.index >= cutoff]
    return series


def _forecast_func(
    history: pd.Series,
    days: int,
    weather: Optional[pd.DataFrame],
    country: Optional[str],
    params: dict,
) -> pd.Series:
    """Train + forecast using LightGBM with lags/seasonality (no look-ahead)."""
    return forecast_price(
        history,
        weather=weather,
        country=country,
        horizon_days=days,
        params=params,
    )


def evaluate_area(
    area: str,
    days: int | None,
    horizon: int,
    train_window: int,
    weather_path: Optional[str],
    save_forecast: bool = True,
    params: Optional[dict] = None,
    history_step_hours: int = 24,
    enable_history: bool = True,
    backtest_windows: int = 10,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    prices = _load_price_series(area, days=days)
    logger.info(
        "%s: loaded %d points (%s -> %s)",
        area,
        len(prices),
        prices.index.min(),
        prices.index.max(),
    )
    weather_df = None
    if weather_path:
        formatted = weather_path.format(area=area)
        resolved = None
        try:
            if formatted.startswith("s3://"):
                resolved = formatted
            else:
                resolved = resolve_data_path(Path(formatted))
        except FileNotFoundError:
            resolved = None
        if resolved and path_exists(resolved):
            weather_df = read_frame(resolved)

    # lightweight backtest (limit windows for speed)
    bt_rows = []
    idx = prices.index
    for i in range(backtest_windows, 0, -1):
        ref = idx.max() - pd.Timedelta(days=i)
        train_start = ref - pd.Timedelta(days=train_window)
        train = prices[(prices.index > train_start) & (prices.index <= ref)]
        truth = prices[
            (prices.index > ref)
            & (prices.index <= ref + pd.Timedelta(days=horizon))
        ]
        if len(train) < 24 or truth.empty:
            continue
        preds = _forecast_func(
            train,
            horizon,
            weather_df,
            area.split("_")[0][:2] if area else None,
            params or {},
        )
        rmse = simple_rmse(truth, preds)
        bt_rows.append({"ref": ref, "rmse": rmse})
    bt = pd.DataFrame(bt_rows)
    if bt.empty:
        logger.warning("%s: backtest produced no windows", area)
    else:
        logger.info(
            "%s: backtest windows=%d mean RMSE=%.2f",
            area,
            len(bt),
            bt["rmse"].mean(),
        )

    # full-history forward-only predictions (no look-ahead)
    hist_preds = pd.DataFrame()
    if enable_history:
        hist_preds = walk_forward_predict_series(
            prices,
            lambda s, days=horizon: _forecast_func(
                s,
                days,
                weather_df,
                area.split("_")[0][:2] if area else None,
                params or {},
            ),
            train_window_days=train_window,
            horizon_days=horizon,
            step_hours=history_step_hours,
        )
        if hist_preds.empty:
            logger.warning(
                "%s: history predictions empty (not enough data)", area
            )
        else:
            hist_rmse = (hist_preds["pred"] - hist_preds["actual"]).pow(
                2
            ).mean() ** 0.5
            logger.info(
                "%s: history predictions points=%d RMSE=%.2f",
                area,
                len(hist_preds),
                hist_rmse,
            )
            if save_forecast:
                hist_out = resolve_write_path(
                    DATA_DIR / area / "price_history_predictions.csv"
                )
                write_frame(hist_preds, hist_out, index_label="datetime")
                logger.info(
                    "%s: saved history predictions -> %s", area, hist_out
                )

    # forward forecast for dashboarding
    fc = _forecast_func(
        prices,
        days=horizon,
        weather=weather_df,
        country=area.split("_")[0][:2] if area else None,
        params=params or {},
    )
    fc_df = pd.DataFrame({"mean": fc})
    fc_df["q10"] = fc_df["mean"] * 0.9
    fc_df["q90"] = fc_df["mean"] * 1.1
    if save_forecast:
        out_path = resolve_write_path(DATA_DIR / area / "price_forecast.csv")
        write_frame(fc_df, out_path, index_label="datetime")
        logger.info("%s: saved forecast -> %s", area, out_path)

    return bt, fc_df


def main(
    areas: Iterable[str],
    days: int | None,
    horizon: int,
    train_window: int,
    save_forecast: bool = True,
    weather_template: Optional[str] = None,
    params: Optional[dict] = None,
    history_step_hours: int = 24,
    enable_history: bool = True,
    backtest_windows: int = 10,
):
    summary = []
    for area in areas:
        try:
            bt, _ = evaluate_area(
                area,
                days=days,
                horizon=horizon,
                train_window=train_window,
                weather_path=weather_template,
                save_forecast=save_forecast,
                params=params,
                history_step_hours=history_step_hours,
                enable_history=enable_history,
                backtest_windows=backtest_windows,
            )
            rmse_mean = (
                float(bt["rmse"].mean()) if not bt.empty else float("nan")
            )
            summary.append((area, len(bt), rmse_mean))
        except Exception as e:
            logger.exception("Failed evaluation for %s: %s", area, e)
            summary.append((area, 0, float("nan")))

    if summary:
        print("\n=== Backtest summary ===")
        for area, windows, rmse in summary:
            print(f"{area:8s} windows={windows:3d} mean_rmse={rmse:.2f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--area", help="Single area code (e.g., DE_LU)")
    p.add_argument(
        "--areas",
        nargs="+",
        help="List of areas to evaluate (overrides --area)",
    )
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Limit to trailing N days of history",
    )
    p.add_argument(
        "--horizon", type=int, default=7, help="Forecast horizon in days"
    )
    p.add_argument(
        "--train-window",
        type=int,
        default=120,
        help="Training window in days for walk-forward",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist price_forecast.csv",
    )
    p.add_argument(
        "--weather-template",
        default="data/weather/{area}_weather.csv",
        help="Template for weather CSV path",
    )
    p.add_argument(
        "--history-step-hours",
        type=int,
        default=24,
        help="Stride in hours for history predictions to speed up",
    )
    p.add_argument(
        "--skip-history",
        action="store_true",
        help="Skip full history predictions (faster)",
    )
    p.add_argument(
        "--backtest-windows",
        type=int,
        default=10,
        help="Number of walk-forward windows for quick backtest",
    )
    args = p.parse_args()
    areas = args.areas if args.areas else ([args.area] if args.area else [])
    if not areas:
        raise SystemExit("Provide --area DE_LU or --areas DE_LU FR ...")
    main(
        areas,
        days=args.days,
        horizon=args.horizon,
        train_window=args.train_window,
        save_forecast=not args.no_save,
        weather_template=args.weather_template,
        params=None,
        history_step_hours=args.history_step_hours,
        enable_history=not args.skip_history,
        backtest_windows=args.backtest_windows,
    )
