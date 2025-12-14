import pandas as pd

from src.models.backtest import walk_forward_predict_series


def test_walk_forward_predict_no_leakage_and_alignment():
    # Synthetic hourly series with unique ascending values
    idx = pd.date_range("2025-01-01", periods=24 * 5, freq="h")
    series = pd.Series(range(len(idx)), index=idx, dtype=float)

    # Forecast function that repeats the last observed value for the horizon
    def fc(train: pd.Series, days: int):
        last_val = train.iloc[-1]
        start = train.index.max() + pd.Timedelta(hours=1)
        out_idx = pd.date_range(start, periods=24 * days, freq="h")
        return pd.Series(last_val, index=out_idx)

    df = walk_forward_predict_series(series, fc, train_window_days=1, horizon_days=1)
    # We should have predictions for every point after the first training window
    assert not df.empty
    assert df.index.min() > series.index.min()
    # No leakage: each prediction targets timestamps strictly after the training end
    assert (df.index > df["train_end"]).all()
    # For this fc, prediction should equal previous actual value
    expected = series.shift(1).reindex(df.index)
    pd.testing.assert_series_equal(df["pred"], expected, check_names=False)
