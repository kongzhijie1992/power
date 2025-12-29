from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeSeriesAudit:
    missing_columns: list[str]
    tz: Optional[str]
    tz_is_utc: bool
    is_monotonic: bool
    duplicate_count: int
    duplicate_examples: list[str]
    gap_count: int
    gap_examples: list[str]
    outlier_count: int
    outlier_examples: list[str]


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


def detect_outliers(
    series: pd.Series, z_threshold: float = 6.0
) -> pd.Index:
    s = series.astype(float).dropna()
    if s.empty:
        return pd.Index([])
    median = s.median()
    mad = np.median(np.abs(s - median))
    if mad == 0:
        return pd.Index([])
    robust_z = 0.6745 * (s - median) / mad
    return s.index[np.abs(robust_z) > z_threshold]


def audit_timeseries(
    df: pd.DataFrame,
    columns: Iterable[str] | None = None,
    freq: str | None = None,
    outlier_z: float = 6.0,
    sample_size: int = 5,
) -> TimeSeriesAudit:
    cols = list(columns) if columns is not None else list(df.columns)
    missing = [c for c in cols if c not in df.columns]
    tz = None
    tz_is_utc = False
    is_monotonic = False
    duplicate_count = 0
    duplicate_examples: list[str] = []
    gap_count = 0
    gap_examples: list[str] = []
    outlier_count = 0
    outlier_examples: list[str] = []

    if isinstance(df.index, pd.DatetimeIndex):
        tz = str(df.index.tz) if df.index.tz is not None else None
        tz_is_utc = is_utc_timezone(df.index.tz)
        is_monotonic = df.index.is_monotonic_increasing
        duplicate_mask = df.index.duplicated()
        if duplicate_mask.any():
            duplicate_count = int(duplicate_mask.sum())
            duplicates = (
                df.index[duplicate_mask].unique().astype(str).tolist()
            )
            duplicate_examples = duplicates[:sample_size]
        if freq:
            expected = pd.date_range(
                df.index.min(),
                df.index.max(),
                freq=freq,
                tz=df.index.tz,
            )
            missing_ts = expected.difference(df.index)
            gap_count = int(len(missing_ts))
            if gap_count:
                gap_examples = (
                    missing_ts.astype(str).to_list()[:sample_size]
                )
    if cols:
        numeric_cols = [
            c for c in cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])
        ]
        for col in numeric_cols:
            outliers = detect_outliers(df[col], z_threshold=outlier_z)
            if len(outliers):
                outlier_count += int(len(outliers))
                outlier_examples.extend(outliers.astype(str).tolist())
        if outlier_examples:
            outlier_examples = outlier_examples[:sample_size]

    return TimeSeriesAudit(
        missing_columns=missing,
        tz=tz,
        tz_is_utc=tz_is_utc,
        is_monotonic=is_monotonic,
        duplicate_count=duplicate_count,
        duplicate_examples=duplicate_examples,
        gap_count=gap_count,
        gap_examples=gap_examples,
        outlier_count=outlier_count,
        outlier_examples=outlier_examples,
    )


def format_audit(audit: TimeSeriesAudit) -> list[str]:
    lines = []
    if audit.missing_columns:
        lines.append(f"missing columns: {audit.missing_columns}")
    if audit.tz is None:
        lines.append("timezone: naive (expected UTC)")
    elif not audit.tz_is_utc:
        lines.append(f"timezone: {audit.tz} (expected UTC)")
    if not audit.is_monotonic:
        lines.append("timestamps: non-monotonic index")
    if audit.duplicate_count:
        lines.append(
            f"timestamps: {audit.duplicate_count} duplicates "
            f"(examples: {audit.duplicate_examples})"
        )
    if audit.gap_count:
        lines.append(
            f"timestamps: {audit.gap_count} gaps "
            f"(examples: {audit.gap_examples})"
        )
    if audit.outlier_count:
        lines.append(
            f"outliers: {audit.outlier_count} "
            f"(examples: {audit.outlier_examples})"
        )
    return lines
