"""Generate sample price data and download weather for a given area.

Usage:
  python scripts/fetch_sample_data.py --area DE_LU --days 90

Creates:
 - data/<AREA>/day_ahead.csv  (hourly prices, column 'value')
 - data/weather/<area>_weather.csv (hourly weather columns from Open-Meteo)

This script uses the project's synthetic generator for realistic-looking prices and Open-Meteo
archive API for weather (no API key required).
"""

import argparse
import os
from pathlib import Path
import json
import datetime as dt

import requests
import pandas as pd

# ensure project root is on path to import synthetic helper
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.ingest.ingest_all import synthetic_area_series
from src.data.io import (
    DATA_DIR,
    resolve_write_path,
    save_series_csv,
    write_frame,
)


def download_open_meteo(lat, lon, start_date, end_date, out_csv_path):
    # Open-Meteo archive API
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}"
        "&hourly=windspeed_10m,shortwave_radiation&timezone=UTC"
    )
    print("Requesting", url)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    j = r.json()
    if "hourly" not in j:
        raise RuntimeError("Open-Meteo returned no hourly data")
    hourly = j["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    out_path = resolve_write_path(out_csv_path)
    write_frame(df, out_path)
    print("Saved weather to", out_csv_path)
    return out_csv_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--lat", type=float, default=52.52)
    p.add_argument("--lon", type=float, default=13.405)
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()

    area = args.area
    days = args.days

    # Prices: use synthetic generator
    print("Generating synthetic prices for", area, f"({days} days)")
    s = synthetic_area_series(area, days=days)
    data_dir = DATA_DIR / area
    price_csv = data_dir / "day_ahead.csv"
    # write as CSV with column 'value' via save_series_csv
    save_series_csv(s, area)
    print("Saved synthetic prices to", price_csv)

    # Weather: use Open-Meteo archive for the same period
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    start_str = start.isoformat()
    end_str = (
        end - dt.timedelta(days=1)
    ).isoformat()  # end param is inclusive
    weather_dir = DATA_DIR / "weather"
    weather_csv = weather_dir / f"{area}_weather.csv"
    try:
        download_open_meteo(
            args.lat, args.lon, start_str, end_str, weather_csv
        )
    except Exception as e:
        print("Weather download failed:", e)
        print(
            "You can still run the pipeline using synthetic weather proxies."
        )

    print("\nDone.")


if __name__ == "__main__":
    main()
