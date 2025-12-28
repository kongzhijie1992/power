import pandas as pd

from src.data.io import read_frame

df = read_frame("data/DE_LU/day_ahead_2year.csv")

print("=== 2-YEAR MERGED DATA ===")
print(f"File: data/DE_LU/day_ahead_2year.csv")
print(f"Rows: {len(df):,}")
print(f"Date range: {df.index[0]} to {df.index[-1]}")
print(f"Days covered: {(df.index[-1] - df.index[0]).days}")
print(f'Missing values: {df["value"].isna().sum()}')
print(f'Price range: {df["value"].min():.2f} - {df["value"].max():.2f} EUR/MWh')
print(f'Mean price: {df["value"].mean():.2f} EUR/MWh')
print(f"Timezone: {df.index.tz}")
print(f"\nMonthly breakdown:")
print(df.groupby(df.index.month)["value"].agg(["count", "mean", "min", "max"]).round(2))
