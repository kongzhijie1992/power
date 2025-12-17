from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .contracts import TimeSeriesContract, validate_contract
from .timeutils import add_local_time_features, ensure_utc_index

# Define strict contracts for each input stream
PRICE_CONTRACT = TimeSeriesContract("price_da", ["price_da"], freq="1h")
LOAD_FC_CONTRACT = TimeSeriesContract(
    "load_forecast", ["load_forecast"], freq="1h", allow_missing=True
)
LOAD_ACT_CONTRACT = TimeSeriesContract(
    "load_actual", ["load_actual"], freq="1h", allow_missing=True
)
WIND_FC_CONTRACT = TimeSeriesContract(
    "wind_forecast", ["wind_forecast"], freq="1h", allow_missing=True
)
WIND_ACT_CONTRACT = TimeSeriesContract(
    "wind_actual", ["wind_actual"], freq="1h", allow_missing=True
)
SOLAR_FC_CONTRACT = TimeSeriesContract(
    "solar_forecast", ["solar_forecast"], freq="1h", allow_missing=True
)
SOLAR_ACT_CONTRACT = TimeSeriesContract(
    "solar_actual", ["solar_actual"], freq="1h", allow_missing=True
)
GAS_CONTRACT = TimeSeriesContract(
    "gas_price", ["gas_price"], freq="1h", allow_missing=True
)
EUA_CONTRACT = TimeSeriesContract(
    "eua_price", ["eua_price"], freq="1h", allow_missing=True
)
OUTAGE_CONTRACT = TimeSeriesContract(
    "availability_proxy", ["availability_factor"], freq="1h", allow_missing=True
)


def load_parquet_contract(path: Path, contract: TimeSeriesContract) -> pd.DataFrame:
    """Load parquet (or CSV) and enforce contract."""
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, parse_dates=["datetime"]).set_index("datetime")
    else:
        df = pd.read_parquet(path)
        if "datetime" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index("datetime")
    df = ensure_utc_index(df)
    return validate_contract(df, contract)


def _merge_pair(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    return left.join(right, how="outer")


def merge_inputs(
    price: pd.DataFrame,
    load_forecast: pd.DataFrame,
    load_actual: pd.DataFrame,
    wind_forecast: pd.DataFrame,
    wind_actual: pd.DataFrame,
    solar_forecast: pd.DataFrame,
    solar_actual: pd.DataFrame,
    gas: pd.DataFrame,
    eua: pd.DataFrame,
    outage_proxy: pd.DataFrame,
    add_local_features: bool = True,
) -> pd.DataFrame:
    """Align and merge all input series on UTC hourly index."""
    frames = [
        validate_contract(price, PRICE_CONTRACT),
        validate_contract(load_forecast, LOAD_FC_CONTRACT),
        validate_contract(load_actual, LOAD_ACT_CONTRACT),
        validate_contract(wind_forecast, WIND_FC_CONTRACT),
        validate_contract(wind_actual, WIND_ACT_CONTRACT),
        validate_contract(solar_forecast, SOLAR_FC_CONTRACT),
        validate_contract(solar_actual, SOLAR_ACT_CONTRACT),
        validate_contract(gas, GAS_CONTRACT),
        validate_contract(eua, EUA_CONTRACT),
        validate_contract(outage_proxy, OUTAGE_CONTRACT),
    ]

    merged = frames[0]
    for f in frames[1:]:
        merged = _merge_pair(merged, f)

    merged = merged.sort_index()
    merged = merged.ffill()

    if add_local_features:
        merged = add_local_time_features(merged)

    return merged


def cache_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
