"""Incremental ingestion helper for ENTSO-E day-ahead prices.

This helper detects the latest persisted timestamp for an area and fetches only
the missing hours (with a small lookback window to handle corrections), then
appends and persists the combined series as Parquet/CSV.
"""

import datetime as dt
import logging
import pandas as pd

from .entsoe_client import get_client, fetch_day_ahead_prices
from src.data.io import (
    DATA_DIR,
    path_exists,
    read_frame,
    resolve_data_path,
    resolve_write_path,
    write_frame,
)

logger = logging.getLogger(__name__)


def _area_data_path(area: str):
    area_dir = DATA_DIR / area
    parquet_path = area_dir / "day_ahead.parquet"
    csv_path = area_dir / "day_ahead.csv"
    # real-data variants (preferred if present)
    parquet_real = area_dir / "day_ahead_real.parquet"
    csv_real = area_dir / "day_ahead_real.csv"
    return parquet_path, csv_path, parquet_real, csv_real


def load_existing(area: str) -> pd.Series:
    pq, csv, pq_real, csv_real = _area_data_path(area)
    candidates = [pq_real, csv_real, pq, csv]
    for path in candidates:
        try:
            resolved = resolve_data_path(path)
        except FileNotFoundError:
            continue
        if not path_exists(resolved):
            continue
        try:
            df = read_frame(resolved)
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
            df.index = pd.to_datetime(df.index)
            s = df["value"] if "value" in df.columns else df.iloc[:, 0]
            return s
        except Exception as e:
            logger.warning("Failed to read %s for %s: %s", path.name, area, e)
            continue
    return pd.Series(dtype="float64")


def save_combined(series: pd.Series, area: str):
    pq, csv, pq_real, csv_real = _area_data_path(area)
    df = series.to_frame("value")
    try:
        path = resolve_write_path(pq_real)
        write_frame(df, path)
    except Exception as e:
        logger.warning(
            "Parquet write failed for %s: %s; falling back to CSV", area, e
        )
        path = resolve_write_path(csv_real)
        write_frame(df, path, index_label="datetime")


def incremental_update(
    area: str,
    api_key: str = None,
    lookback_hours: int = 6,
    days_max: int = 365,
):
    """Fetch missing hours for `area` and append to existing data.

    - `lookback_hours` pulls a small overlap to catch corrections
    - `days_max` limits the maximum history we allow fetching when no data exists
    """
    existing = load_existing(area)
    now = pd.Timestamp.now(tz="UTC").floor("h")
    if not existing.empty:
        last = pd.to_datetime(existing.index.max())
        if last.tz is None:
            last = last.tz_localize("UTC")
        else:
            last = last.tz_convert("UTC")
        start = last - pd.Timedelta(hours=lookback_hours)
    else:
        # fresh ingest: fetch up to days_max days
        start = now - pd.Timedelta(days=days_max)
    end = now

    client = get_client(api_key=api_key) if api_key else get_client()
    try:
        fetched = fetch_day_ahead_prices(client, area, start, end)
        # normalize
        fetched.index = (
            pd.to_datetime(fetched.index).tz_convert("UTC").tz_localize(None)
        )
    except Exception as e:
        logger.error("ENTSO-E fetch failed for %s: %s", area, e)
        raise

    if existing.empty:
        combined = fetched
    else:
        # align tz
        existing.index = pd.to_datetime(existing.index)
        combined = pd.concat(
            [existing, fetched[~fetched.index.isin(existing.index)]]
        )
        combined = combined[
            ~combined.index.duplicated(keep="last")
        ].sort_index()

    save_combined(combined, area)
    logger.info(
        "Incremental update completed for %s: %d rows", area, len(combined)
    )
    return combined
