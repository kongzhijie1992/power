"""Orchestrator to fetch day-ahead prices for all ENTSO-E bidding zones and persist them.

If no ENTSO-E API key is provided, a synthetic dataset can be generated for testing.
"""
import datetime as dt
import logging
from typing import Optional, List

import pandas as pd
import numpy as np

from .entsoe_client import get_client, DEFAULT_ZONES, fetch_day_ahead_prices
from src.data.io import save_series_csv

logger = logging.getLogger(__name__)


def fetch_and_persist_all(api_key: Optional[str] = None, areas: Optional[List[str]] = None, days: int = 90):
    if areas is None:
        areas = DEFAULT_ZONES
    if api_key is None:
        # raise here in real run; caller can use synthetic mode
        raise ValueError("No API key provided — use synthetic mode or provide entsoe.api_key in config")
    client = get_client(api_key=api_key)
    end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    for area in areas:
        try:
            s = fetch_day_ahead_prices(client, area, start, end)
            # normalize to UTC naive
            s.index = pd.to_datetime(s.index).tz_convert('UTC').tz_localize(None)
            path = save_series_csv(s, area)
            logger.info("Saved %s -> %s", area, path)
        except Exception as e:
            logger.warning("Failed to fetch/persist %s: %s", area, e)


def synthetic_area_series(area: str, days: int = 90) -> pd.Series:
    """Create a synthetic hourly price series with daily/weekly seasonality and noise."""
    end = pd.Timestamp.utcnow().replace(minute=0, second=0, microsecond=0).to_pydatetime()
    periods = days * 24
    idx = pd.date_range(end=end, periods=periods, freq='h')
    # components
    hour = idx.hour
    dow = idx.dayofweek
    base = 40 + 10 * (np.sin(2 * np.pi * hour / 24) + 0.5 * (dow >=5))
    noise = np.random.normal(0, 5, size=len(idx))
    s = pd.Series(base + noise, index=idx)
    # Normalize index to UTC-naive (handle both tz-aware and naive indices)
    try:
        if s.index.tz is None:
            s.index = s.index.tz_localize('UTC')
        # convert to UTC and drop timezone info
        if s.index.tz is not None:
            s.index = s.index.tz_convert('UTC').tz_localize(None)
    except Exception:
        # Fallback: leave index as-is
        pass
    return s
