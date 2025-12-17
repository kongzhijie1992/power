"""Demo runner: fetch day-ahead prices for a pilot area, baseline forecast, simple forward curve, dispatch example."""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import datetime as dt

import pandas as pd

from src.ingest.entsoe_client import get_client, fetch_day_ahead_prices
from src.models.forecast import seasonal_naive_forecast
from src.dispatch.merit_order import merit_order_clearing


logging.basicConfig(level=logging.INFO)


def main(area: str, history_days: int = 90, horizon: int = 7):
    client = get_client()
    end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=history_days)
    prices = fetch_day_ahead_prices(client, area, start, end)
    print(f"Fetched {len(prices)} price points for {area}")

    # Ensure hourly UTC index
    prices.index = pd.to_datetime(prices.index).tz_convert("UTC").tz_localize(None)

    # Forecast
    forecast = seasonal_naive_forecast(prices, days=horizon)
    print(f"Forecast {len(forecast)} hourly points (next {horizon} days)")

    # Simple forward curve: daily average of forecast
    fc_daily = forecast.resample("D").mean()
    print("Simple forward (daily avg):")
    print(fc_daily.head(10))

    # Simple dispatch example
    generators = [
        {"name": "Coal", "capacity": 10000, "marginal_cost": 60.0},
        {"name": "Gas", "capacity": 8000, "marginal_cost": 80.0},
        {"name": "Wind", "capacity": 5000, "marginal_cost": 0.0},
        {"name": "Solar", "capacity": 3000, "marginal_cost": 0.0},
    ]
    sample_demand = 15000
    res = merit_order_clearing(sample_demand, generators)
    print(
        f"Dispatch for demand {sample_demand} MW -> clearing price {res['clearing_price']}"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE")
    p.add_argument("--history-days", type=int, default=90)
    p.add_argument("--horizon", type=int, default=7)
    args = p.parse_args()
    main(args.area, args.history_days, args.horizon)
