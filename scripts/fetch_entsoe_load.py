#!/usr/bin/env python3
"""
Fetch ENTSO-E total load / demand using entsoe-py (A65) and save to CSV.

Usage:
  python scripts/fetch_entsoe_load.py --areas DE_LU FR ES --start-date 2023-01-01 --end-date 2025-12-12 --chunk-days 90

Notes:
  - Requires ENTSOE_API_TOKEN in env or .env
  - Saves to data/<AREA>/load_real.csv
  - Uses entsoe-py `query_load_forecast` (day-ahead). Falls back to `query_load` if forecast fails.
"""
import argparse
import os
from pathlib import Path
import datetime as dt
import concurrent.futures
from typing import Iterable, Tuple

import pandas as pd
import requests


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().strip().split("\n"):
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from src.data.io import DATA_DIR, resolve_write_path, write_frame


AREA_MAP = {
    "DE_LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C",
    "IT": "10Y1001A1001A73I",
    "ES": "10YES-REE------0",
    "PT": "10YPT-REN------W",
    "NL": "10YNL----------L",
    "BE": "10YBE----------2",
    "CH": "10YCH-SWISSGRIDZ",
    "AT": "10YAT-APG------L",
    "PL": "10YPL-AREA-----S",
    "CZ": "10YCZ-CEPS-----N",
    "SK": "10YSK-SEPS-----K",
    "HU": "10YHU-MAVIR----U",
    "RO": "10YRO-TEL------P",
    "BG": "10YCA-BULGARIA-R",
    "SI": "10YSI-ELES-----O",
    "HR": "10YHR-HEP------M",
    "GR": "10YGR-HTSO-----Y",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "FI": "10YFI-1--------U",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "LT": "10YLT-1001A0008Q",
    "LV": "10YLV-1001A00074",
    "EE": "10Y1001A1001A39I",
}


def _parse_date(d):
    if isinstance(d, dt.date):
        return d
    return dt.datetime.strptime(str(d), "%Y-%m-%d").date()


def _chunk_ranges(
    start: dt.date, end: dt.date, chunk_days: int
) -> Iterable[Tuple[dt.date, dt.date]]:
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + dt.timedelta(days=1)


ALT_CODES = {
    "DK1": "DK_1",
    "DK2": "DK_2",
    "NO1": "NO_1",
    "NO2": "NO_2",
    "NO3": "NO_3",
    "NO4": "NO_4",
    "NO5": "NO_5",
    "SE1": "SE_1",
    "SE2": "SE_2",
    "SE3": "SE_3",
    "SE4": "SE_4",
}


def fetch_load_entsoe(
    client, area: str, start_date, end_date, forecast: bool = True
) -> pd.Series:
    """Fetch load via entsoe-py. Tries area code, alt code, then EIC."""
    start_ts = pd.Timestamp(_parse_date(start_date)).tz_localize("Europe/Brussels")
    end_ts = (pd.Timestamp(_parse_date(end_date)) + pd.Timedelta(days=1)).tz_localize(
        "Europe/Brussels"
    )

    candidates = [area, ALT_CODES.get(area), AREA_MAP.get(area)]
    last_error = None
    for code in [c for c in candidates if c]:
        try:
            if forecast and hasattr(client, "query_load_forecast"):
                s = client.query_load_forecast(code, start=start_ts, end=end_ts)
            else:
                s = client.query_load(code, start=start_ts, end=end_ts)
            if s is not None and len(s) > 0:
                s.index = pd.to_datetime(s.index).tz_convert("UTC").tz_localize(None)
                return s
        except Exception as e:
            last_error = e
            continue
    if last_error:
        raise last_error
    raise ValueError(f"No load data returned for {area}")


def _fetch_area_load(
    area: str,
    api_token: str,
    ranges: list[Tuple[dt.date, dt.date]],
    output_override: str | None = None,
) -> tuple[str, Path, int]:
    try:
        from entsoe import EntsoePandasClient
    except ImportError:
        raise SystemExit(
            "entsoe-py not installed. Install with `pip install entsoe-py`."
        )

    client = EntsoePandasClient(api_key=api_token)
    combined = []
    for idx, (cs, ce) in enumerate(ranges, start=1):
        print(f"\n[{area}] Chunk {idx}/{len(ranges)}: {cs} → {ce}")
        try:
            s_chunk = fetch_load_entsoe(
                client, AREA_MAP.get(area, area), cs, ce, forecast=True
            )
        except Exception as e:
            print(f"  Forecast load failed for {area}: {e}. Trying actual load...")
            s_chunk = fetch_load_entsoe(
                client, AREA_MAP.get(area, area), cs, ce, forecast=False
            )
        combined.append(s_chunk)

    s = pd.concat(combined).sort_index()
    s = s[~s.index.duplicated(keep="first")]
    # clamp (all naive UTC)
    start_ts = pd.Timestamp(ranges[0][0])
    end_ts = pd.Timestamp(ranges[-1][1] + dt.timedelta(days=1)) - pd.Timedelta(
        hours=1
    )
    s = s[(s.index >= start_ts) & (s.index <= end_ts)]

    area_dir = DATA_DIR / area
    out_csv = output_override if output_override else area_dir / "load_real.csv"
    out_csv = resolve_write_path(out_csv)
    write_frame(s.to_frame("value"), out_csv, index_label="datetime")
    print(f"✅ Saved load to {out_csv} ({len(s):,} rows)")
    return area, out_csv, len(s)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--areas", nargs="+", help="List of areas (overrides --area)")
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--chunk-days", type=int, default=90)
    p.add_argument("--workers", type=int, default=0, help="0 uses a small auto pool")
    p.add_argument(
        "--executor", choices=["thread", "process"], default="thread"
    )
    p.add_argument(
        "--output",
        help="Single-area output CSV (defaults to data/<AREA>/load_real.csv)",
    )
    args = p.parse_args()

    api_token = os.getenv("ENTSOE_API_TOKEN")
    if not api_token:
        raise SystemExit("ENTSOE_API_TOKEN not set (env or .env)")
    areas = args.areas if args.areas else [args.area]
    ranges = list(
        _chunk_ranges(
            _parse_date(args.start_date),
            _parse_date(args.end_date),
            max(args.chunk_days, 1),
        )
    )
    print(f"Planned calls per area: {len(ranges)} chunks")

    if len(areas) == 1 and args.output:
        _fetch_area_load(areas[0], api_token, ranges, output_override=args.output)
        return

    workers = args.workers or min(4, len(areas))
    if workers <= 1 or len(areas) == 1:
        for area in areas:
            _fetch_area_load(area, api_token, ranges)
        return

    executor_cls = (
        concurrent.futures.ThreadPoolExecutor
        if args.executor == "thread"
        else concurrent.futures.ProcessPoolExecutor
    )
    print(f"Fetching {len(areas)} areas using {workers} {args.executor}(s).")
    with executor_cls(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_area_load, area, api_token, ranges): area
            for area in areas
        }
        for fut in concurrent.futures.as_completed(futures):
            area = futures[fut]
            try:
                fut.result()
            except Exception as exc:
                print(f"⚠️  Area {area} failed: {exc}")


if __name__ == "__main__":
    main()
