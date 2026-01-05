"""Data validation helpers for pipeline checks."""

from __future__ import annotations

from typing import List

import pandas as pd


def validate_price_series(series: pd.Series) -> List[str]:
    issues: List[str] = []
    if series.empty:
        issues.append("price series is empty")
        return issues
    if not isinstance(series.index, pd.DatetimeIndex):
        issues.append("price series index is not a DatetimeIndex")
    if series.isna().any():
        issues.append("price series contains missing values")
    if isinstance(series.index, pd.DatetimeIndex) and not series.index.is_monotonic_increasing:
        issues.append("price series index is not monotonic increasing")
    return issues
