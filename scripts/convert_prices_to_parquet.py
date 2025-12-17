#!/usr/bin/env python3
"""
Convert all downloaded price CSVs to Parquet for faster loading.

Usage:
  python scripts/convert_prices_to_parquet.py
"""
from pathlib import Path
import pandas as pd

AREAS = [
    "DE_LU",
    "FR",
    "IT",
    "ES",
    "NL",
    "BE",
    "PT",
    "CH",
    "AT",
    "PL",
    "CZ",
    "SK",
    "HU",
    "RO",
    "BG",
    "SI",
    "HR",
    "GR",
    "DK1",
    "DK2",
    "FI",
    "SE1",
    "SE2",
    "SE3",
    "SE4",
    "NO1",
    "NO2",
    "NO3",
    "NO4",
    "NO5",
    "LT",
    "LV",
    "EE",
]


def convert_area(area: str):
    csv_path = Path(f"data/{area}/day_ahead_real.csv")
    parquet_path = Path(f"data/{area}/day_ahead_real.parquet")
    if not csv_path.exists():
        print(f"{area}: CSV missing, skipping ({csv_path})")
        return
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    print(f"{area}: wrote {len(df):,} rows to {parquet_path}")


def main():
    for area in AREAS:
        convert_area(area)


if __name__ == "__main__":
    main()
