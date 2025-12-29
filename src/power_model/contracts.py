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
    allow_gaps: bool = False


def is_utc_timezone(tz) -> bool:
    if tz is None:
        return False
    zone = getattr(tz, "zone", None)
    if zone == "UTC":
        return True
    key = getattr(tz, "key", None)
    if key == "UTC":
        return True
    if str(tz) in {"UTC", "UTC+00:00", "Etc/UTC"}:
        return True
    try:
        if tz.tzname(None) == "UTC":
            return True
    except Exception:
        return False
    return False


def _is_monotonic_utc(idx: pd.DatetimeIndex) -> bool:
    return (
        idx.tz is not None
        and is_utc_timezone(idx.tz)
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
    if df.index.has_duplicates:
        dupes = df.index[df.index.duplicated()].unique().astype(str).tolist()
        raise ValueError(
            f"{contract.name}: duplicate timestamps found "
            f"(count={df.index.duplicated().sum()}, examples={dupes[:5]})"
        )
    missing_cols = [c for c in contract.columns if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{contract.name}: missing columns {missing_cols}")
    if not contract.allow_missing and df[contract.columns].isna().any().any():
        raise ValueError(
            f"{contract.name}: contains NaNs; set allow_missing=True to permit"
        )
    if contract.freq and not contract.allow_gaps:
        expected = pd.date_range(
            df.index.min(), df.index.max(), freq=contract.freq, tz="UTC"
        )
        if len(expected) != len(df.index) or not df.index.equals(expected):
            missing = expected.difference(df.index)
            extra = df.index.difference(expected)
            raise ValueError(
                f"{contract.name}: index not regular at {contract.freq}; "
                f"missing={len(missing)}, extra={len(extra)}"
            )
    return df.sort_index()


def expect_columns(df: pd.DataFrame, cols: Iterable[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
