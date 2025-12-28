#!/usr/bin/env python3
"""
Fetch ENTSO-E Actual Total Load (A65) and Day-ahead Total Load Forecast (A65) and
store them separately.

Usage:
  python scripts/fetch_entsoe_load_and_forecast.py --areas DE_LU FR --start-date 2023-01-01 --end-date 2025-12-13 --chunk-days 90

Outputs per area:
  - data/<AREA>/load_actual.csv
  - data/<AREA>/load_forecast.csv
    (includes `tso_day_ahead_forecast` and `tso_publication_time_utc` when available)

Notes:
  - Requires ENTSOE_API_TOKEN in environment or .env
  - Uses entsoe-py query_load_and_forecast; falls back to separate calls if needed.
"""
import argparse
import datetime as dt
import os
from pathlib import Path
import re
import concurrent.futures
from typing import Iterable, Tuple
import xml.etree.ElementTree as ET

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

from src.data.io import (
    DATA_DIR,
    path_exists,
    read_csv_indexed,
    resolve_write_path,
    write_frame,
)


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


def _chunk_ranges(
    start: dt.date, end: dt.date, chunk_days: int
) -> Iterable[Tuple[dt.date, dt.date]]:
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


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_first_text(elem: ET.Element, name: str) -> str | None:
    for child in elem.iter():
        if _strip_ns(child.tag) == name and child.text:
            return child.text.strip()
    return None


_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def _parse_duration(text: str) -> pd.Timedelta | None:
    if not text:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        return None
    parts = {
        key: int(val) if val else 0 for key, val in match.groupdict().items()
    }
    return pd.Timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["minutes"],
        seconds=parts["seconds"],
    )


def _parse_timestamp(text: str) -> pd.Timestamp | None:
    if not text:
        return None
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _extract_publication_times(xml_text: str) -> pd.Series:
    root = ET.fromstring(xml_text)
    root_created_text = _find_first_text(root, "createdDateTime")
    root_created = _parse_timestamp(root_created_text) if root_created_text else pd.NaT

    timestamps = []
    publications = []

    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        ts_created_text = _find_first_text(ts, "createdDateTime")
        ts_created = (
            _parse_timestamp(ts_created_text) if ts_created_text else root_created
        )
        if pd.isna(ts_created):
            continue
        for period in ts.iter():
            if _strip_ns(period.tag) != "Period":
                continue
            start_text = _find_first_text(period, "start")
            resolution_text = _find_first_text(period, "resolution")
            if not start_text or not resolution_text:
                continue
            step = _parse_duration(resolution_text)
            if step is None or step <= pd.Timedelta(0):
                continue
            start_ts = _parse_timestamp(start_text)
            if pd.isna(start_ts):
                continue
            for point in period.iter():
                if _strip_ns(point.tag) != "Point":
                    continue
                pos_text = _find_first_text(point, "position")
                if not pos_text:
                    continue
                try:
                    position = int(pos_text)
                except ValueError:
                    continue
                ts_point = start_ts + step * (position - 1)
                timestamps.append(ts_point)
                publications.append(ts_created)

    if not timestamps:
        return pd.Series(dtype="datetime64[ns]")

    df = pd.DataFrame({"timestamp": timestamps, "publication_time": publications})
    df = df.dropna(subset=["timestamp", "publication_time"])
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    return df.groupby("timestamp")["publication_time"].max().sort_index()


def _read_ts_csv(path: Path) -> pd.DataFrame:
    df = read_csv_indexed(path)
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()]
    return df


def _merge_timeseries(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([existing, new], axis=0)
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def fetch_load_and_forecast(
    client, area: str, start_date, end_date
) -> Tuple[pd.Series, pd.Series]:
    """Return actual load + day-ahead forecast as two Series (UTC-naive)."""
    start_ts = pd.Timestamp(_parse_date(start_date)).tz_localize("Europe/Brussels")
    end_ts = (pd.Timestamp(_parse_date(end_date)) + pd.Timedelta(days=1)).tz_localize(
        "Europe/Brussels"
    )

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
        actual_col = (
            col_lower.get("load") or col_lower.get("actual load") or list(df.columns)[0]
        )
        forecast_col = col_lower.get("day-ahead total load forecast") or col_lower.get(
            "forecasted load"
        )
        actual = df[actual_col] if actual_col in df.columns else df.iloc[:, 0]
        forecast = (
            df[forecast_col] if forecast_col and forecast_col in df.columns else None
        )

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


def fetch_load_forecast_publication_times(
    raw_client, area: str, start_date, end_date
) -> pd.Series:
    """Return per-timestamp publication times for day-ahead load forecasts (UTC-naive)."""
    start_ts = pd.Timestamp(_parse_date(start_date)).tz_localize("Europe/Brussels")
    end_ts = (pd.Timestamp(_parse_date(end_date)) + pd.Timedelta(days=1)).tz_localize(
        "Europe/Brussels"
    )

    candidates = [area, ALT_CODES.get(area), AREA_MAP.get(area)]
    last_error = None
    for code in [c for c in candidates if c]:
        try:
            xml_text = raw_client.query_load_forecast(code, start=start_ts, end=end_ts)
            if isinstance(xml_text, bytes):
                xml_text = xml_text.decode("utf-8", errors="ignore")
            if not xml_text:
                continue
            series = _extract_publication_times(str(xml_text))
            if not series.empty:
                return series
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    return pd.Series(dtype="datetime64[ns]")


def _fetch_area_load_and_forecast(
    area: str,
    api_token: str,
    ranges: list[Tuple[dt.date, dt.date]],
    merge_existing: bool,
    parquet: bool,
) -> tuple[str, Path, Path]:
    try:
        from entsoe import EntsoePandasClient, EntsoeRawClient
    except ImportError:
        raise SystemExit(
            "entsoe-py not installed. Install with `pip install entsoe-py`."
        )

    client = EntsoePandasClient(api_key=api_token)
    raw_client = EntsoeRawClient(api_key=api_token)

    actual_chunks = []
    forecast_chunks = []
    for idx, (cs, ce) in enumerate(ranges, start=1):
        print(f"\n[{area}] Chunk {idx}/{len(ranges)}: {cs} → {ce}")
        try:
            act, fc = fetch_load_and_forecast(client, area, cs, ce)
            actual_chunks.append(act)
            forecast_chunk = fc.to_frame(name="tso_day_ahead_forecast")
            try:
                pub = fetch_load_forecast_publication_times(raw_client, area, cs, ce)
                if pub is not None and not pub.empty:
                    pub = pub.reindex(forecast_chunk.index)
                    forecast_chunk["tso_publication_time_utc"] = pub
            except Exception as e:
                print(f"  publication timestamps not available: {e}")
            forecast_chunks.append(forecast_chunk)
            print(f"  got actual {len(act)} pts, forecast {len(fc)} pts")
        except Exception as e:
            print(f"  failed chunk {cs}->{ce} for {area}: {e}")
            continue

    if not actual_chunks or not forecast_chunks:
        print(f"⚠️ No data for {area}, skipping")
        return area, Path(), Path()

    actual = pd.concat(actual_chunks).sort_index()
    forecast = pd.concat(forecast_chunks).sort_index()
    # drop duplicates
    actual = actual[~actual.index.duplicated(keep="first")]
    forecast = forecast[~forecast.index.duplicated(keep="first")]

    # clamp to requested window (UTC naive)
    start_ts = pd.Timestamp(ranges[0][0])
    end_ts = pd.Timestamp(ranges[-1][1] + dt.timedelta(days=1)) - pd.Timedelta(
        hours=1
    )
    actual = actual[(actual.index >= start_ts) & (actual.index <= end_ts)]
    forecast = forecast[
        (forecast.index >= start_ts) & (forecast.index <= end_ts + pd.Timedelta(days=1))
    ]

    area_dir = DATA_DIR / area

    actual_df = actual.to_frame(name="actual_load")
    forecast_df = forecast.copy()

    actual_csv = resolve_write_path(area_dir / "load_actual.csv")
    forecast_csv = resolve_write_path(area_dir / "load_forecast.csv")
    to_write_actual = actual_df
    to_write_forecast = forecast_df
    if merge_existing:
        if path_exists(actual_csv):
            try:
                old = _read_ts_csv(actual_csv)
                to_write_actual = _merge_timeseries(old, actual_df)
            except Exception as e:
                print(
                    f"⚠️  Failed to merge existing actual load for {area}: {e}; overwriting."
                )
        if path_exists(forecast_csv):
            try:
                old = _read_ts_csv(forecast_csv)
                to_write_forecast = _merge_timeseries(old, forecast_df)
            except Exception as e:
                print(
                    f"⚠️  Failed to merge existing forecast load for {area}: {e}; overwriting."
                )

    write_frame(to_write_actual, actual_csv, index_label="datetime")
    write_frame(to_write_forecast, forecast_csv, index_label="datetime")
    print(f"✅ Saved actual -> {actual_csv} ({len(to_write_actual):,} rows)")
    print(f"✅ Saved forecast -> {forecast_csv} ({len(to_write_forecast):,} rows)")

    if parquet:
        write_frame(
            to_write_actual, resolve_write_path(area_dir / "load_actual.parquet")
        )
        write_frame(
            to_write_forecast, resolve_write_path(area_dir / "load_forecast.parquet")
        )

    return area, actual_csv, forecast_csv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--area", default="DE_LU")
    p.add_argument("--areas", nargs="+", help="List of areas (overrides --area)")
    p.add_argument("--start-date", default="2023-01-01")
    p.add_argument("--end-date", default=dt.date.today().isoformat())
    p.add_argument("--chunk-days", type=int, default=90)
    p.add_argument("--workers", type=int, default=0, help="0 uses a small auto pool")
    p.add_argument(
        "--executor", choices=["thread", "process"], default="thread"
    )
    p.add_argument("--parquet", action="store_true", help="Also write Parquet")
    p.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge fetched window into existing CSVs instead of overwriting",
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
    print(f"Planned calls per area: {len(ranges)} chunks (actual + forecast)")

    workers = args.workers or min(4, len(areas))
    if workers <= 1 or len(areas) == 1:
        for area in areas:
            _fetch_area_load_and_forecast(
                area, api_token, ranges, args.merge_existing, args.parquet
            )
        return

    executor_cls = (
        concurrent.futures.ThreadPoolExecutor
        if args.executor == "thread"
        else concurrent.futures.ProcessPoolExecutor
    )
    print(f"Fetching {len(areas)} areas using {workers} {args.executor}(s).")
    with executor_cls(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _fetch_area_load_and_forecast,
                area,
                api_token,
                ranges,
                args.merge_existing,
                args.parquet,
            ): area
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
