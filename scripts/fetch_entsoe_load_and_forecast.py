#!/usr/bin/env python3
"""
Fetch ENTSO-E Actual Total Load (A65) and Day-ahead Total Load Forecast (A65) and
store them separately.

Usage:
  python scripts/fetch_entsoe_load_and_forecast.py --areas DE_LU FR --start-date 2023-01-01 --end-date 2025-12-13 --chunk-days 90

Outputs per area:
  - data/<AREA>/load_actual.csv
  - data/<AREA>/load_forecast.csv

Notes:
  - Requires ENTSOE_API_TOKEN in environment or .env
  - Uses entsoe-py query_load_and_forecast; falls back to separate calls if needed.
"""
import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

# Best-effort dotenv load so CLI can stay simple
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    env_path = Path(__file__).parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().strip().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()


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


def _parse_date(d):
    if isinstance(d, dt.date):
        return d
    return dt.datetime.strptime(str(d), "%Y-%m-%d").date()


def _chunk_ranges(start: dt.date, end: dt.date, chunk_days: int) -> Iterable[Tuple[dt.date, dt.date]]:
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + dt.timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + dt.timedelta(days=1)


def _normalize_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.to_datetime(idx)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx


def fetch_load_and_forecast(client, area: str, start_date, end_date) -> Tuple[pd.Series, pd.Series]:
    """Return actual load + day-ahead forecast as two Series (UTC-naive)."""
    start_ts = pd.Timestamp(_parse_date(start_date)).tz_localize("Europe/Brussels")
    end_ts = (pd.Timestamp(_parse_date(end_date)) + pd.Timedelta(days=1)).tz_localize("Europe/Brussels")

    candidates = [area, ALT_CODES.get(area), AREA_MAP.get(area)]
    last_error = None
    for code in [c for c in candidates if c]:
        try:
            df = client.query_load_and_forecast(code, start=start_ts, end=end_ts)
            if df is not None and len(df) > 0:
                df.index = _normalize_index(df.index)
                break
        except Exception as e:
            last_error = e
            df = None
            continue
    else:
        if last_error:
            raise last_error
        raise ValueError(f"No data returned for {area}")

    # Some control areas (Nordics) label columns differently; be defensive
    if isinstance(df, pd.Series):
        # entsoe-py may return a Series when only one column exists
        actual = df
        forecast = pd.Series(dtype=float)
    else:
        col_lower = {c.lower(): c for c in df.columns}
        actual_col = col_lower.get("load") or col_lower.get("actual load") or list(df.columns)[0]
        forecast_col = col_lower.get("day-ahead total load forecast") or col_lower.get("forecasted load")
        actual = df[actual_col] if actual_col in df.columns else df.iloc[:, 0]
        forecast = df[forecast_col] if forecast_col and forecast_col in df.columns else None

    if forecast is None or forecast.empty:
        # fallback to separate calls
        actual = None
        forecast = None
        for code in [c for c in candidates if c]:
            try:
                actual = client.query_load(code, start=start_ts, end=end_ts)
                if actual is not None and len(actual) > 0:
                    actual.index = _normalize_index(actual.index)
                    break
            except Exception:
                continue
        for code in [c for c in candidates if c]:
            try:
                forecast = client.query_load_forecast(code, start=start_ts, end=end_ts)
                if forecast is not None and len(forecast) > 0:
                    forecast.index = _normalize_index(forecast.index)
                    break
            except Exception:
                continue

    if actual is None or len(actual) == 0:
        raise ValueError(f"No actual load returned for {area}")
    if forecast is None or len(forecast) == 0:
        raise ValueError(f"No forecast load returned for {area}")

    return actual, forecast


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--areas", nargs="+", help="List of areas (overrides --area)")
    p.add_argument("--start-date", default="2023-01-01")
    p.add_argument("--end-date", default=dt.date.today().isoformat())
    p.add_argument("--chunk-days", type=int, default=90)
    p.add_argument("--parquet", action="store_true", help="Also write Parquet")
    args = p.parse_args()

    api_token = os.getenv("ENTSOE_API_TOKEN")
    if not api_token:
        raise SystemExit("ENTSOE_API_TOKEN not set (env or .env)")
    try:
        from entsoe import EntsoePandasClient
    except ImportError:
        raise SystemExit("entsoe-py not installed. Install with `pip install entsoe-py`.")

    areas = args.areas if args.areas else [args.area]
    ranges = list(_chunk_ranges(_parse_date(args.start_date), _parse_date(args.end_date), max(args.chunk_days, 1)))
    print(f"Planned calls per area: {len(ranges)} chunks (actual + forecast)")

    client = EntsoePandasClient(api_key=api_token)

    for area in areas:
        actual_chunks = []
        forecast_chunks = []
        for idx, (cs, ce) in enumerate(ranges, start=1):
            print(f"\n[{area}] Chunk {idx}/{len(ranges)}: {cs} → {ce}")
            try:
                act, fc = fetch_load_and_forecast(client, area, cs, ce)
                actual_chunks.append(act)
                forecast_chunks.append(fc)
                print(f"  got actual {len(act)} pts, forecast {len(fc)} pts")
            except Exception as e:
                print(f"  failed chunk {cs}->{ce} for {area}: {e}")
                continue

        if not actual_chunks or not forecast_chunks:
            print(f"⚠️ No data for {area}, skipping")
            continue

        actual = pd.concat(actual_chunks).sort_index()
        forecast = pd.concat(forecast_chunks).sort_index()
        # drop duplicates
        actual = actual[~actual.index.duplicated(keep="first")]
        forecast = forecast[~forecast.index.duplicated(keep="first")]

        # clamp to requested window (UTC naive)
        start_ts = pd.Timestamp(_parse_date(args.start_date))
        end_ts = pd.Timestamp(_parse_date(args.end_date) + dt.timedelta(days=1)) - pd.Timedelta(hours=1)
        actual = actual[(actual.index >= start_ts) & (actual.index <= end_ts)]
        forecast = forecast[(forecast.index >= start_ts) & (forecast.index <= end_ts + pd.Timedelta(days=1))]

        area_dir = Path("data") / area
        area_dir.mkdir(parents=True, exist_ok=True)

        actual_df = actual.to_frame(name="actual_load")
        forecast_df = forecast.to_frame(name="tso_day_ahead_forecast")

        actual_csv = area_dir / "load_actual.csv"
        forecast_csv = area_dir / "load_forecast.csv"
        actual_df.to_csv(actual_csv, index_label="datetime")
        forecast_df.to_csv(forecast_csv, index_label="datetime")
        print(f"✅ Saved actual -> {actual_csv} ({len(actual):,} rows)")
        print(f"✅ Saved forecast -> {forecast_csv} ({len(forecast):,} rows)")

        if args.parquet:
            actual_df.to_parquet(area_dir / "load_actual.parquet")
            forecast_df.to_parquet(area_dir / "load_forecast.parquet")


if __name__ == "__main__":
    main()
