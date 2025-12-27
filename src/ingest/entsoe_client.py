import datetime as _dt
import logging
from pathlib import Path
import yaml
import pandas as _pd

logger = logging.getLogger(__name__)

try:
    from entsoe import EntsoePandasClient
except Exception:
    EntsoePandasClient = None


def _load_config():
    cfg_path = Path(__file__).parents[1] / "config.yaml"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parents[1] / "config.yaml.example"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_client(api_key: str = None):
    cfg = _load_config()
    token = api_key or (cfg.get("entsoe") or {}).get("api_key")
    if token is None:
        raise ValueError("ENTSO-E API key not found. Put it in src/config.yaml")
    if EntsoePandasClient is None:
        raise ImportError(
            "entsoe-py library not available. Install `entsoe-py` in your environment."
        )
    return EntsoePandasClient(api_key=token)


DEFAULT_ZONES = [
    "AL",
    "AT",
    "BA",
    "BE",
    "BG",
    "CH",
    "CY",
    "CZ",
    "DE",
    "DK1",
    "DK2",
    "EE",
    "ES",
    "FI",
    "FR",
    "GB",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "ME",
    "MK",
    "MT",
    "NL",
    "NO1",
    "NO2",
    "NO3",
    "NO4",
    "NO5",
    "PL",
    "PT",
    "RO",
    "RS",
    "SE1",
    "SE2",
    "SE3",
    "SE4",
    "SI",
    "SK",
]


def fetch_day_ahead_prices(
    client, area: str, start: _dt.datetime, end: _dt.datetime
) -> _pd.Series:
    """Fetch day-ahead prices for a single bidding zone using entsoe-py client.

    Returns a pandas Series indexed by UTC timestamps.
    """
    logger.info("Fetching day-ahead prices for %s from %s to %s", area, start, end)
    series = client.query_day_ahead_prices(area, start=start, end=end)
    # entsoe-py returns timezone-aware series (Europe timezone); convert to UTC naive
    if isinstance(series.index, _pd.DatetimeIndex):
        series = series.tz_convert("UTC").tz_localize(None)
    return series


def fetch_multi_area_day_ahead(client, areas=None, days=90):
    """Fetch the last `days` of day-ahead prices for multiple areas.

    Returns a dict area->Series
    """
    if areas is None:
        areas = DEFAULT_ZONES
    end = (
        pd.Timestamp.utcnow().replace(minute=0, second=0, microsecond=0).to_pydatetime()
    )
    start = end - _dt.timedelta(days=days)
    results = {}
    for area in areas:
        try:
            s = fetch_day_ahead_prices(client, area, start, end)
            results[area] = s
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", area, e)
    return results
