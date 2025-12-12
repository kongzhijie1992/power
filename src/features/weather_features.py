"""Feature builder to extract weather-based features (wind, solar) using GFS when available.

The functions here try to use `src.weather.gfs.fetch_and_extract_point` which requires
`xarray`+`cfgrib`+`ecCodes`. If parsing is unavailable, functions return lightweight synthetic
seasonal features so the forecasting pipeline can still run.
"""
from typing import Optional
import datetime as dt
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    from src.weather.gfs import fetch_and_extract_point
except Exception:
    fetch_and_extract_point = None


def add_gfs_features(history_index: pd.DatetimeIndex, lat: float, lon: float, varnames=None) -> pd.DataFrame:
    """Return a DataFrame indexed by `history_index` with weather features.

    - If GFS parsing is available, fetch nearest-gridpoint series for requested variables.
    - Otherwise return simple diurnal/cyclical proxies for wind and solar.
    """
    varnames = varnames or ['10u', '10v', 'dswrf']
    if fetch_and_extract_point is None:
        logger.info('GFS parser not available; returning synthetic weather proxies')
        idx = history_index
        hour = idx.hour
        wind_proxy = 8 + 3 * (np.sin(2 * np.pi * hour / 24) + 0.5)
        solar_proxy = np.clip(np.cos(2 * np.pi * (hour - 6) / 24), 0, 1) * 800
        df = pd.DataFrame({'wind_proxy': wind_proxy, 'solar_proxy': solar_proxy}, index=idx)
        return df

    # Attempt to fetch from most recent GFS run(s)
    try:
        now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        # fetch analysis (fh=0) for nearest run
        extracted = fetch_and_extract_point(lat, lon, run_dt=now, fh=0, varnames=varnames)
        # extracted is dict var -> pandas Series (indexed by time)
        # convert to DataFrame and reindex to history_index
        df_list = []
        for v, s in (extracted or {}).items():
            s.index = pd.to_datetime(s.index).tz_convert('UTC').tz_localize(None)
            df_list.append(s.rename(v))
        if not df_list:
            raise RuntimeError('No vars extracted from GFS')
        df = pd.concat(df_list, axis=1).reindex(history_index, fill_value=None)
        df = df.ffill().bfill()
        # compute wind speed if u/v provided
        if '10u' in df.columns and '10v' in df.columns:
            df['wind_speed'] = (df['10u']**2 + df['10v']**2)**0.5
        return df
    except Exception as e:
        logger.warning('Failed to extract features from GFS: %s; falling back to proxies', e)
        return add_gfs_features(history_index, lat, lon, varnames=None)
