import numpy as np
import pandas as pd


from src.models.demand_forecast import (
    prepare_error_features,
    build_future_error_features,
)


def test_prepare_error_features_uses_past_ramps_only():
    idx = pd.date_range("2024-01-01", periods=200, freq="h")
    # Nonlinear sequence so forward/backward diffs differ.
    forecast = pd.Series(np.cumsum(np.arange(len(idx)) ** 2), index=idx).astype(float)
    actual = forecast + 10.0

    X, y, _error = prepare_error_features(actual, forecast, add_lags=(1, 24))
    t = idx[30]
    assert t in X.index
    assert t in y.index

    expected_forecast_ramp = forecast.loc[t] - forecast.loc[t - pd.Timedelta(hours=1)]
    expected_actual_ramp = actual.loc[t] - actual.loc[t - pd.Timedelta(hours=1)]
    assert X.loc[t, "forecast_ramp_1h"] == expected_forecast_ramp
    assert X.loc[t, "actual_ramp_1h"] == expected_actual_ramp


def test_build_future_error_features_does_not_backfill_future_errors():
    idx = pd.date_range("2024-01-01", periods=48, freq="h")
    forecast = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    # If future backfill happened, early rows would inherit ~100+ values.
    error_history = pd.Series(np.arange(30, dtype=float) + 100.0, index=idx[:30])

    feats = build_future_error_features(
        forecast, error_history=error_history, add_lags=(24,)
    )

    # For the first 24 hours there's no lag-24 available; should be 0 (not backfilled).
    assert feats.loc[idx[0], "error_lag_24h"] == 0
    assert feats.loc[idx[10], "error_lag_24h"] == 0

    # Once lag becomes available, it should match the historical value.
    assert feats.loc[idx[24], "error_lag_24h"] == error_history.loc[idx[0]]
