"""Parallel, rate-limited ingestion helper for ENTSO-E day-ahead prices.

This module fetches multiple bidding zones in parallel (thread or process pool),
respects a simple per-worker delay to avoid hitting rate limits, and persists
results to Parquet/CSV.
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from typing import List, Optional

import pandas as pd

from .entsoe_client import get_client, DEFAULT_ZONES, fetch_day_ahead_prices
from src.data.io import DATA_DIR, resolve_write_path, write_frame, save_series_csv

logger = logging.getLogger(__name__)


def _fetch_one(
    area: str, api_key: Optional[str], start, end, save_parquet: bool = True
):
    client = get_client(api_key=api_key) if api_key else get_client()
    s = fetch_day_ahead_prices(client, area, start, end)
    # normalize index
    s.index = pd.to_datetime(s.index).tz_convert("UTC").tz_localize(None)
    # attempt parquet
    area_dir = DATA_DIR / area
    try:
        if save_parquet:
            path = resolve_write_path(area_dir / "day_ahead.parquet")
            write_frame(s.to_frame("value"), path)
        else:
            path = resolve_write_path(area_dir / "day_ahead.csv")
            write_frame(s.to_frame("value"), path, index_label="datetime")
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
    save_parquet: bool = True,
    executor: str = "thread",
):
    if areas is None:
        areas = DEFAULT_ZONES
    end = pd.Timestamp.utcnow().to_pydatetime()
    start = end - pd.Timedelta(days=days)
    results = []
    executor = executor.lower().strip()
    if executor not in {"thread", "process"}:
        raise ValueError("executor must be 'thread' or 'process'")
    executor_cls = ThreadPoolExecutor if executor == "thread" else ProcessPoolExecutor
    with executor_cls(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_fetch_one, a, api_key, start, end, save_parquet): a
            for a in areas
        }
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
