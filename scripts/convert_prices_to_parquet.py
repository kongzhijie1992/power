#!/usr/bin/env python3
"""
Convert all downloaded price CSVs to Parquet for faster loading.

Usage:
  python scripts/convert_prices_to_parquet.py
"""
import pandas as pd

from src.data.io import (
    DATA_DIR,
    path_exists,
    read_frame,
    resolve_write_path,
    write_frame,
)

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
    csv_path = DATA_DIR / area / "day_ahead_real.csv"
    parquet_path = DATA_DIR / area / "day_ahead_real.parquet"
    if not path_exists(csv_path):
        print(f"{area}: CSV missing, skipping ({csv_path})")
        return
    df = read_frame(csv_path)
    out_path = resolve_write_path(parquet_path)
    write_frame(df, out_path, index=False)
    print(f"{area}: wrote {len(df):,} rows to {out_path}")


def main():
    for area in AREAS:
        convert_area(area)


if __name__ == "__main__":
    main()
