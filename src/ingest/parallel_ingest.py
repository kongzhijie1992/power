"""Parallel, rate-limited ingestion helper for ENTSO-E day-ahead prices.

This module fetches multiple bidding zones in parallel (thread pool), respects a
simple per-thread delay to avoid hitting rate limits, and persists results to Parquet/CSV.
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .entsoe_client import get_client, DEFAULT_ZONES, fetch_day_ahead_prices
from src.data.io import save_series_csv

logger = logging.getLogger(__name__)


def _fetch_one(
    area: str, api_key: Optional[str], start, end, save_parquet: bool = True
):
    client = get_client(api_key=api_key) if api_key else get_client()
    s = fetch_day_ahead_prices(client, area, start, end)
    # normalize index
    s.index = pd.to_datetime(s.index).tz_convert("UTC").tz_localize(None)
    # attempt parquet
    area_dir = Path(__file__).parents[1] / ".." / "data" / area
    area_dir = Path(area_dir).resolve()
    area_dir.mkdir(parents=True, exist_ok=True)
    try:
        if save_parquet:
            path = area_dir / "day_ahead.parquet"
            s.to_frame("value").to_parquet(path)
        else:
            path = save_series_csv(s, area)
    except Exception as e:
        logger.warning("Parquet save failed for %s: %s, falling back to CSV", area, e)
        path = save_series_csv(s, area)
    return area, path, len(s)


def fetch_parallel(
    api_key: Optional[str] = None,
    areas: Optional[List[str]] = None,
    days: int = 90,
    max_workers: int = 6,
    throttle_s: float = 0.5,
):
    if areas is None:
        areas = DEFAULT_ZONES
    end = pd.Timestamp.utcnow().to_pydatetime()
    start = end - pd.Timedelta(days=days)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, a, api_key, start, end): a for a in areas}
        for fut in as_completed(futures):
            area = futures[fut]
            try:
                res = fut.result()
                logger.info("Fetched %s -> %s (%d rows)", res[0], res[1], res[2])
                results.append(res)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", area, e)
            time.sleep(throttle_s)
    return results
