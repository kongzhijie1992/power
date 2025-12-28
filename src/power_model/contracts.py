from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd


@dataclass(frozen=True)
class TimeSeriesContract:
    """Schema for time-series inputs with UTC datetime index."""

    name: str
    columns: List[str]
    tz: str = "UTC"
    allow_missing: bool = False
    freq: Optional[str] = None  # e.g. "1h"


def _is_monotonic_utc(idx: pd.DatetimeIndex) -> bool:
    return (
        idx.tz is not None
        and idx.tz.zone == "UTC"
        and idx.is_monotonic_increasing
    )


def validate_contract(
    df: pd.DataFrame, contract: TimeSeriesContract
) -> pd.DataFrame:
    """Validate that dataframe meets the expected time-series contract."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"{contract.name}: index must be DatetimeIndex")
    if not _is_monotonic_utc(df.index):
        raise ValueError(
            f"{contract.name}: index must be timezone-aware UTC and increasing"
        )
    missing_cols = [c for c in contract.columns if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{contract.name}: missing columns {missing_cols}")
    if not contract.allow_missing and df[contract.columns].isna().any().any():
        raise ValueError(
            f"{contract.name}: contains NaNs; set allow_missing=True to permit"
        )
    if contract.freq:
        expected = pd.date_range(
            df.index.min(), df.index.max(), freq=contract.freq, tz="UTC"
        )
        if len(expected) != len(df.index) or not df.index.equals(expected):
            raise ValueError(
                f"{contract.name}: index not regular at {contract.freq}"
            )
    return df.sort_index()


def expect_columns(df: pd.DataFrame, cols: Iterable[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
