import pandas as pd
from pathlib import Path

def load_prices():
    """Load the main price file, preferring DE_LU and falling back to DE."""
    candidates = [Path('data/DE_LU/day_ahead.csv'), Path('data/DE/day_ahead.csv')]
    for path in candidates:
        if path.exists():
            df = pd.read_csv(path)
            df['datetime'] = pd.to_datetime(df['datetime'])
            return path, df
    raise SystemExit("No price file found in data/DE_LU/ or data/DE/.")

price_path, df = load_prices()

print('=== CURRENT DATA STATUS ===')
print(f'Main data file: {price_path}')
print(f'Rows: {len(df):,}')
print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
print(f"Days covered: {(df['datetime'].max() - df['datetime'].min()).days}")
print(f"Missing values: {df['value'].isna().sum()}")

# Check weather (prefer matching area)
weather_candidates = [
    Path('data/weather/DE_LU_weather.csv'),
    Path('data/weather/DE_weather.csv'),
]
weather = None
for w_path in weather_candidates:
    if w_path.exists():
        weather = pd.read_csv(w_path)
        print(f'\nWeather data:')
        print(f'File: {w_path}')
        print(f'Rows: {len(weather):,}')
        break
if weather is None:
    print('\nWeather data: data/weather/DE_LU_weather.csv not found (nor DE)')

# Show data volume based on actual rows
print(f'\n=== CURRENT DATA INVENTORY ===')
print(f'Price data rows: {len(df):,}')
print(f'Weather data rows: {len(weather) if weather is not None else 0:,}')

print(f'\n=== FOR PRODUCTION USE ===')
print(f'Recommended: 1-2 years (8,760-17,520 hourly rows)')
print(f"Current days: {(df['datetime'].max() - df['datetime'].min()).days}")
print(f'\nOptions:')
print(f'1. Download full year from ENTSO-E GUI or API')
print(f'2. Use sample data for testing (current setup)')
print(f'3. Fetch on-demand via scripts/fetch_entsoe_data.py')
