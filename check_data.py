import pandas as pd

# Check main data file
df = pd.read_csv('data/DE/day_ahead.csv')
df['datetime'] = pd.to_datetime(df['datetime'])

print('=== CURRENT DATA STATUS ===')
print(f'Main data file: data/DE/day_ahead.csv')
print(f'Rows: {len(df):,}')
print(f'Date range: {df["datetime"].min()} to {df["datetime"].max()}')
print(f'Days covered: {(df["datetime"].max() - df["datetime"].min()).days}')
print(f'Missing values: {df["value"].isna().sum()}')

# Check weather
weather = pd.read_csv('data/weather/DE_weather.csv')
print(f'\nWeather data:')
print(f'Rows: {len(weather):,}')

# Show data volume
print(f'\n=== CURRENT DATA INVENTORY ===')
print(f'Price data: ~346 days of hourly data (8,304 rows)')
print(f'Weather data: ~90 days of hourly data (2,160 rows)')
print(f'\n=== FOR PRODUCTION USE ===')
print(f'Recommended: 1-2 years (8,760-17,520 hourly rows)')
print(f'Current: ~95% of 1-year minimum')
print(f'\nOptions:')
print(f'1. Download full year from ENTSO-E GUI or API')
print(f'2. Use sample data for testing (current setup)')
print(f'3. Fetch on-demand via scripts/fetch_entsoe_data.py')
