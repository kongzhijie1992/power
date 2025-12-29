import datetime as _dt
import logging
from pathlib import Path
import yaml
import pandas as _pd
import requests
import xml.etree.ElementTree as _ET

logger = logging.getLogger(__name__)


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
        raise ValueError(
            "ENTSO-E API key not found. Put it in src/config.yaml"
        )
    return token


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


API_URL = "https://web-api.tp.entsoe.eu/api"

AREA_EIC = {
    "AL": "10YAL-KESH-----5",
    "AT": "10YAT-APG------L",
    "BA": "10YBA-JPCC-----D",
    "BE": "10YBE----------2",
    "BG": "10YCA-BULGARIA-R",
    "CH": "10YCH-SWISSGRIDZ",
    "CY": "10YCY-1001A0003J",
    "CZ": "10YCZ-CEPS-----N",
    "DE": "10Y1001A1001A83F",
    "DE_LU": "10Y1001A1001A82H",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "EE": "10Y1001A1001A39I",
    "ES": "10YES-REE------0",
    "FI": "10YFI-1--------U",
    "FR": "10YFR-RTE------C",
    "GB": "10YGB----------A",
    "GR": "10YGR-HTSO-----Y",
    "HR": "10YHR-HEP------M",
    "HU": "10YHU-MAVIR----U",
    "IE": "10YIE-1001A00010",
    "IT": "10YIT-GRTN-----B",
    "LT": "10YLT-1001A0008Q",
    "LU": "10YLU-CEGEDEL-NQ",
    "LV": "10YLV-1001A00074",
    "ME": "10YCS-CG-TSO---S",
    "MK": "10YMK-MEPSO----8",
    "MT": "10Y1001A1001A93C",
    "NL": "10YNL----------L",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "PL": "10YPL-AREA-----S",
    "PT": "10YPT-REN------W",
    "RO": "10YRO-TEL------P",
    "RS": "10YCS-SERBIATSOV",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
    "SI": "10YSI-ELES-----O",
    "SK": "10YSK-SEPS-----K",
}

AREA_ALIASES = {
    "DK_1": "DK1",
    "DK_2": "DK2",
    "NO_1": "NO1",
    "NO_2": "NO2",
    "NO_3": "NO3",
    "NO_4": "NO4",
    "NO_5": "NO5",
    "SE_1": "SE1",
    "SE_2": "SE2",
    "SE_3": "SE3",
    "SE_4": "SE4",
}


def _normalize_area(area: str) -> str:
    return AREA_ALIASES.get(area, area)


def fetch_day_ahead_prices(
    api_token: str, area: str, start: _dt.datetime, end: _dt.datetime
) -> _pd.Series:
    """Fetch day-ahead prices for a single bidding zone via ENTSO-E API.

    Returns a pandas Series indexed by UTC timestamps (naive).
    """
    area = _normalize_area(area)
    eic_code = AREA_EIC.get(area, area)
    start_date = _pd.Timestamp(start).date()
    end_date = _pd.Timestamp(end).date()

    start_ts = f"{start_date.strftime('%Y%m%d')}0000"
    end_ts = (end_date + _dt.timedelta(days=1)).strftime("%Y%m%d") + "0000"
    params = {
        "securityToken": api_token,
        "documentType": "A44",
        "In_Domain": eic_code,
        "Out_Domain": eic_code,
        "periodStart": start_ts,
        "periodEnd": end_ts,
    }
    logger.info(
        "Fetching day-ahead prices for %s (%s) from %s to %s",
        area,
        eic_code,
        start_date,
        end_date,
    )
    response = requests.get(API_URL, params=params, timeout=30)
    response.raise_for_status()

    root = _ET.fromstring(response.content)
    prices = []
    timestamps = []

    def _iter_by_suffix(tag_suffix: str):
        return [elem for elem in root.iter() if elem.tag.endswith(tag_suffix)]

    for ts in _iter_by_suffix("TimeSeries"):
        periods = [elem for elem in ts.iter() if elem.tag.endswith("Period")]
        if not periods:
            continue
        period = periods[0]
        time_interval = None
        for elem in period.iter():
            if elem.tag.endswith("timeInterval"):
                time_interval = elem
                break
        start_elem = None
        if time_interval is not None:
            for child in time_interval.iter():
                if child.tag.endswith("start"):
                    start_elem = child
                    break
        if start_elem is None or not start_elem.text:
            continue
        start_time = _pd.to_datetime(start_elem.text, utc=True)
        points = [elem for elem in period.iter() if elem.tag.endswith("Point")]
        for i, point in enumerate(points):
            price_elem = None
            for child in point:
                if child.tag.endswith("price.amount"):
                    price_elem = child
                    break
            if price_elem is not None and price_elem.text:
                prices.append(float(price_elem.text))
                timestamps.append(start_time + _dt.timedelta(hours=i))

    if not prices:
        raise ValueError(f"No price data returned for {area}")

    series = _pd.Series(prices, index=_pd.to_datetime(timestamps, utc=True))
    if isinstance(series.index, _pd.DatetimeIndex):
        series.index = series.index.tz_convert("UTC").tz_localize(None)
    return series


def fetch_multi_area_day_ahead(client, areas=None, days=90):
    """Fetch the last `days` of day-ahead prices for multiple areas.

    Returns a dict area->Series
    """
    if areas is None:
        areas = DEFAULT_ZONES
    end = (
        _pd.Timestamp.utcnow()
        .replace(minute=0, second=0, microsecond=0)
        .to_pydatetime()
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
