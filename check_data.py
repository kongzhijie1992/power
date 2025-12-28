import pandas as pd
from pathlib import Path

from src.data.io import path_exists, read_frame


def load_prices():
    """Load the main price file for DE_LU."""
    path = Path("data/DE_LU/day_ahead.csv")
    if path_exists(path):
        df = read_frame(path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        return path, df
    raise SystemExit("No price file found in data/DE_LU/.")


price_path, df = load_prices()

print("=== CURRENT DATA STATUS ===")
print(f"Main data file: {price_path}")
print(f"Rows: {len(df):,}")
print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
print(f"Days covered: {(df['datetime'].max() - df['datetime'].min()).days}")
print(f"Missing values: {df['value'].isna().sum()}")

# Check weather (prefer matching area)
weather_path = Path("data/weather/DE_LU_weather.csv")
weather = None
if path_exists(weather_path):
    weather = read_frame(weather_path)
    print(f"\nWeather data:")
    print(f"File: {weather_path}")
    print(f"Rows: {len(weather):,}")
else:
    print("\nWeather data: data/weather/DE_LU_weather.csv not found")

# Show data volume based on actual rows
print(f"\n=== CURRENT DATA INVENTORY ===")
print(f"Price data rows: {len(df):,}")
print(f"Weather data rows: {len(weather) if weather is not None else 0:,}")

print(f"\n=== FOR PRODUCTION USE ===")
print(f"Recommended: 1-2 years (8,760-17,520 hourly rows)")
print(f"Current days: {(df['datetime'].max() - df['datetime'].min()).days}")
print(f"\nOptions:")
print(f"1. Download full year from ENTSO-E GUI or API")
print(f"2. Use sample data for testing (current setup)")
print(f"3. Fetch on-demand via scripts/fetch_entsoe_data.py")
