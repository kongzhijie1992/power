from __future__ import annotations

from datetime import timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

berlin_zone = ZoneInfo("Europe/Berlin")


def ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure dataframe has UTC tz-aware DatetimeIndex, preserving timestamps."""
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("expected DatetimeIndex")
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df = df.copy()
    df.index = idx
    return df


def add_local_time_features(
    df: pd.DataFrame,
    tz: ZoneInfo = berlin_zone,
    prefix: str = "berlin",
    drop_index: bool = False,
    extra_holidays: Iterable[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """
    Attach Europe/Berlin local-time features that handle 23/25h DST days.

    Features:
        {prefix}_hour_local, {prefix}_dow, {prefix}_is_dst, {prefix}_dst_offset_hours
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("expected DatetimeIndex for local feature creation")
    utc = df.index
    if utc.tz is None:
        raise ValueError(
            "index must be tz-aware UTC before adding local features"
        )
    local = utc.tz_convert(tz)
    dst_offset = local.map(
        lambda ts: (ts.utcoffset() or timedelta(0)).total_seconds() / 3600
    )
    out = df.copy()
    out[f"{prefix}_hour_local"] = local.hour
    out[f"{prefix}_dow"] = local.dayofweek
    out[f"{prefix}_is_dst"] = local.map(
        lambda ts: int(ts.dst() != timedelta(0))
    )
    out[f"{prefix}_dst_offset_hours"] = dst_offset
    if extra_holidays:
        hol_set = {h.date() for h in extra_holidays}
        out[f"{prefix}_is_holiday"] = local.date.isin(hol_set).astype(int)
    if drop_index:
        out = out.reset_index().rename(columns={"index": "datetime"})
    return out
