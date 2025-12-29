"""Time-series cross-validation helpers with leakage-safe splits."""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import numpy as np
import pandas as pd


def _to_timedelta(value: pd.Timedelta | int | float) -> pd.Timedelta:
    if isinstance(value, pd.Timedelta):
        return value
    return pd.Timedelta(hours=float(value))


def rolling_time_series_split(
    index: pd.DatetimeIndex,
    train_window: pd.Timedelta | int | float,
    test_window: pd.Timedelta | int | float,
    step: Optional[pd.Timedelta | int | float] = None,
    expanding: bool = False,
    n_splits: Optional[int] = None,
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    """Yield rolling/expanding train/test indices without leakage.

    Windows are defined in time (not row counts). Test windows start immediately
    after the training window end and never overlap the training data.
    """
    idx = pd.DatetimeIndex(index).sort_values()
    train_window = _to_timedelta(train_window)
    test_window = _to_timedelta(test_window)
    step = _to_timedelta(step) if step is not None else test_window

    train_end = idx.min() + train_window
    splits = 0
    while train_end + test_window <= idx.max():
        train_start = idx.min() if expanding else train_end - train_window
        test_start = train_end
        test_end = train_end + test_window

        train_mask = (idx >= train_start) & (idx < train_end)
        test_mask = (idx >= test_start) & (idx < test_end)
        train_idx = np.flatnonzero(train_mask)
        test_idx = np.flatnonzero(test_mask)
        if len(train_idx) and len(test_idx):
            yield train_idx, test_idx
            splits += 1
            if n_splits is not None and splits >= n_splits:
                break
        train_end += step
