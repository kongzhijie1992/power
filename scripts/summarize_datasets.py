#!/usr/bin/env python3
"""
Summarize available price and weather datasets across areas.

Usage:
  python scripts/summarize_datasets.py
"""
import pandas as pd

from src.data.io import DATA_DIR, path_exists, read_frame
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


def summarize_area(area: str):
    price_path = DATA_DIR / area / "day_ahead_real.csv"
    weather_path = DATA_DIR / "weather" / f"{area}_weather.csv"
    load_path = DATA_DIR / area / "load_real.csv"

    price_info = ("MISSING", "-", "-", "-")
    if path_exists(price_path):
        df = read_frame(price_path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        price_info = (
            f"{len(df):,}",
            str(df["datetime"].min()),
            str(df["datetime"].max()),
            df["value"].isna().sum(),
        )

    weather_info = ("MISSING", "-", "-", "-")
    if path_exists(weather_path):
        wf = read_frame(weather_path)
        wf["time"] = pd.to_datetime(wf["time"])
        weather_info = (
            f"{len(wf):,}",
            str(wf["time"].min()),
            str(wf["time"].max()),
            wf.isna().sum().sum(),
        )

    load_info = ("MISSING", "-", "-", "-")
    if path_exists(load_path):
        lf = read_frame(load_path)
        lf["datetime"] = pd.to_datetime(lf["datetime"])
        load_info = (
            f"{len(lf):,}",
            str(lf["datetime"].min()),
            str(lf["datetime"].max()),
            lf.isna().sum().sum(),
        )

    return (
        area,
        price_info,
        weather_info,
        load_info,
        price_path,
        weather_path,
        load_path,
    )


def main():
    rows = []
    for area in AREAS:
        rows.append(summarize_area(area))

    header = (
        "AREA",
        "PRICE_ROWS",
        "PRICE_START",
        "PRICE_END",
        "PRICE_NA",
        "PRICE_PATH",
        "LOAD_ROWS",
        "LOAD_START",
        "LOAD_END",
        "LOAD_NA",
        "LOAD_PATH",
        "WEATHER_ROWS",
        "WEATHER_START",
        "WEATHER_END",
        "WEATHER_NA",
        "WEATHER_PATH",
    )
    print(" | ".join(header))
    print("-" * 140)
    for area, pinfo, winfo, linfo, ppath, wpath, lpath in rows:
        p_rows, p_start, p_end, p_na = pinfo
        w_rows, w_start, w_end, w_na = winfo
        l_rows, l_start, l_end, l_na = linfo
        print(
            f"{area:4} | {p_rows:>8} | {p_start} | {p_end} | {p_na} | {ppath} | "
            f"{l_rows:>8} | {l_start} | {l_end} | {l_na} | {lpath} | "
            f"{w_rows:>8} | {w_start} | {w_end} | {w_na} | {wpath}"
        )


if __name__ == "__main__":
    main()
