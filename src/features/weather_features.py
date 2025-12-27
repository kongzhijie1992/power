"""Feature builder to extract weather-based features (wind, solar) using GFS when available.

The functions here try to use `src.weather.gfs.fetch_and_extract_point` which requires
`xarray`+`cfgrib`+`ecCodes`. If parsing is unavailable, functions return lightweight synthetic
seasonal features so the forecasting pipeline can still run.
"""

from typing import Optional
from pathlib import Path
import datetime as dt
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    from src.weather.gfs import fetch_and_extract_point
except Exception:
    fetch_and_extract_point = None


def add_gfs_features(
    history_index: pd.DatetimeIndex,
    lat: float,
    lon: float,
    varnames=None,
    weather_csv: Optional[str] = None,
) -> pd.DataFrame:
    """Return a DataFrame indexed by `history_index` with weather features.

    Behavior:
    - If `weather_csv` is provided and exists, load hourly weather from that CSV and map
      common columns to expected variables (e.g. `windspeed_10m`, `shortwave_radiation`).
    - Otherwise, if `src.weather.gfs.fetch_and_extract_point` is available, fetch nearest-gridpoint
      series from GFS GRIBs.
    - If neither is available, return simple diurnal/cyclical proxies for wind and solar.

    The function is backwards-compatible: callers that don't pass `weather_csv` or
    the optional GRIB parser will receive the synthetic proxies as before.
    """
    varnames = varnames or ["10u", "10v", "dswrf"]

    # If a local weather CSV is provided, prefer it (no external API key required)
    if weather_csv is not None:
        try:
            wpath = Path(weather_csv)
        except Exception:
            wpath = None
        if wpath and wpath.exists():
            try:
                dfw = pd.read_csv(wpath, parse_dates=True, index_col=0)
                # Normalize index to UTC-naive
                try:
                    if dfw.index.tz is None:
                        dfw.index = dfw.index.tz_localize("UTC")
                    if dfw.index.tz is not None:
                        dfw.index = dfw.index.tz_convert("UTC").tz_localize(None)
                except Exception:
                    pass

                # Map common column names to expected variables
                colmap = {}
                if "windspeed_10m" in dfw.columns:
                    colmap["windspeed_10m"] = "wind_speed"
                if "shortwave_radiation" in dfw.columns:
                    colmap["shortwave_radiation"] = "dswrf"
                # also accept 10u/10v if provided
                if "10u" in dfw.columns:
                    colmap["10u"] = "10u"
                if "10v" in dfw.columns:
                    colmap["10v"] = "10v"

                dfw = dfw.rename(columns=colmap)
                # Reindex to history_index and forward-fill only (avoid future leakage); fill remaining with 0.
                df = dfw.reindex(history_index).ffill().fillna(0)
                # If wind components present, compute wind_speed
                if (
                    "10u" in df.columns
                    and "10v" in df.columns
                    and "wind_speed" not in df.columns
                ):
                    df["wind_speed"] = (df["10u"] ** 2 + df["10v"] ** 2) ** 0.5
                # If dswrf present, keep it; otherwise create solar proxy from hour
                if "dswrf" not in df.columns:
                    hour = history_index.hour
                    df["solar_proxy"] = (
                        np.clip(np.cos(2 * np.pi * (hour - 6) / 24), 0, 1) * 800
                    )
                return df
            except Exception as e:
                logger.warning("Failed to load weather_csv %s: %s", weather_csv, e)

    # If no local CSV provided or it failed, fall back to GRIB extraction if available
    if fetch_and_extract_point is None:
        logger.info("GFS parser not available; returning synthetic weather proxies")
        idx = history_index
        hour = idx.hour
        wind_proxy = 8 + 3 * (np.sin(2 * np.pi * hour / 24) + 0.5)
        solar_proxy = np.clip(np.cos(2 * np.pi * (hour - 6) / 24), 0, 1) * 800
        df = pd.DataFrame(
            {"wind_proxy": wind_proxy, "solar_proxy": solar_proxy}, index=idx
        )
        return df

    # Attempt to fetch from most recent GFS run(s)
    try:
        now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        # fetch analysis (fh=0) for nearest run
        extracted = fetch_and_extract_point(
            lat, lon, run_dt=now, fh=0, varnames=varnames
        )
        # extracted is dict var -> pandas Series (indexed by time)
        # convert to DataFrame and reindex to history_index
        df_list = []
        for v, s in (extracted or {}).items():
            s.index = pd.to_datetime(s.index).tz_convert("UTC").tz_localize(None)
            df_list.append(s.rename(v))
        if not df_list:
            raise RuntimeError("No vars extracted from GFS")
        df = pd.concat(df_list, axis=1).reindex(history_index, fill_value=None)
        # Forward-fill only (avoid future leakage); fill remaining with 0.
        df = df.ffill().fillna(0)
        # compute wind speed if u/v provided
        if "10u" in df.columns and "10v" in df.columns:
            df["wind_speed"] = (df["10u"] ** 2 + df["10v"] ** 2) ** 0.5
        return df
    except Exception as e:
        logger.warning(
            "Failed to extract features from GFS: %s; falling back to proxies", e
        )
        return add_gfs_features(history_index, lat, lon, varnames=None)
