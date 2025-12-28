"""Tests for Streamlit dashboard helper functions and data assembly."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "streamlit_dashboard.py"

spec = importlib.util.spec_from_file_location("streamlit_dashboard", SCRIPT_PATH)
dashboard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(dashboard)


def test_downsample_indexed_includes_last():
    idx = pd.date_range("2024-01-01", periods=9, freq="h")
    series = pd.Series(range(9), index=idx)

    out = dashboard._downsample_indexed(series, max_points=4)

    assert len(out) == 4
    assert out.index[0] == series.index[0]
    assert out.index[-1] == series.index[-1]


def test_downsample_rows_reduces_and_preserves_order():
    df = pd.DataFrame({"v": range(10)}, index=pd.date_range("2024-01-01", periods=10, freq="h"))

    out = dashboard._downsample_rows(df, max_rows=4)

    assert len(out) == 4
    assert out.index[0] == df.index[0]
    assert out.index[-1] == df.index[-1]


def test_format_index_as_strings():
    idx = pd.date_range("2024-03-01 00:00", periods=2, freq="h")
    out = dashboard._format_index_as_strings(idx)

    assert out == ["2024-03-01 00:00", "2024-03-01 01:00"]


def test_apply_horizon_slices_last_days():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({"v": range(10)}, index=idx)

    out = dashboard._apply_horizon(df, "3d")

    assert len(out) == 4
    assert out.index.min() == idx[-4]


def test_apply_date_range_inclusive_for_tz_aware():
    idx = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    df = pd.DataFrame({"v": range(48)}, index=idx)

    out = dashboard._apply_date_range(df, "2024-01-01", "2024-01-02")

    assert out.index.min().date() == pd.Timestamp("2024-01-01").date()
    assert out.index.max().date() == pd.Timestamp("2024-01-02").date()


def test_convert_index_timezone_handles_invalid_tz():
    idx = pd.date_range("2024-01-01 00:00", periods=2, freq="h")
    df = pd.DataFrame({"v": [1, 2]}, index=idx)

    out = dashboard._convert_index_timezone(df, "Nope/Nope")

    assert out.index.tz is not None
    assert str(out.index.tz) == "UTC"


def test_convert_index_timezone_from_utc_to_berlin():
    idx = pd.date_range("2024-01-01 00:00", periods=1, freq="h")
    df = pd.DataFrame({"v": [1]}, index=idx)

    out = dashboard._convert_index_timezone(df, "Europe/Berlin")

    assert out.index.tz is not None
    assert out.index[0].hour == 1


def test_format_timestamp_series_adds_tz_label_and_defaults():
    series = pd.Series(
        [pd.Timestamp("2024-01-01 12:00"), pd.NaT],
        index=[0, 1],
    )

    out = dashboard._format_timestamp_series(
        series, "Europe/London", default="n/a", include_tz_label=True
    )

    assert out.iloc[0].endswith("(Europe/London)")
    assert out.iloc[1] == "n/a"


def test_load_demand_data_merges_quantiles(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="h")
    fc = pd.DataFrame(
        {
            "datetime": idx,
            "tso_forecast": [10.0, 11.0, 12.0],
            "corrected_mean": [9.0, 10.0, 11.0],
            "corrected_q10": [8.0, 9.0, 10.0],
            "corrected_q90": [11.0, 12.0, 13.0],
        }
    )
    actual = pd.Series([99.0, 100.0], index=idx[1:])
    tso = pd.Series([10.0, 11.0, 12.0], index=idx)
    pub = pd.Series(
        [pd.Timestamp("2024-01-01 00:30"), pd.Timestamp("2024-01-01 01:30"), pd.Timestamp("2024-01-01 02:30")],
        index=idx,
    )

    monkeypatch.setattr(dashboard, "read_frame", lambda path: fc.copy())
    monkeypatch.setattr(dashboard, "path_exists", lambda path: True)
    monkeypatch.setattr(dashboard, "load_demand_series", lambda area, prefer_parquet=False: actual)
    monkeypatch.setattr(dashboard, "load_tso_forecast_series", lambda area, prefer_parquet=False: tso)
    monkeypatch.setattr(
        dashboard, "load_tso_forecast_publication", lambda area, prefer_parquet=False: pub
    )

    merged, quantiles = dashboard.load_demand_data("DE_LU")

    assert "actual_load" in merged.columns
    assert "tso_forecast" in merged.columns
    assert "tso_publication_time_utc" in merged.columns
    assert "corrected_mean" in merged.columns
    assert merged.index.min() == idx[0]
    assert merged.index.max() == idx[-1]
    assert quantiles is not None
    assert set(quantiles.columns) == {"corrected_q10", "corrected_q90"}


def test_load_price_data_reads_forecast_and_history(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="h")
    actual = pd.Series([1.0, 2.0, 3.0], index=idx)
    forward = pd.DataFrame({"datetime": idx, "mean": [1.1, 2.1, 3.1]})
    history = pd.DataFrame({"datetime": idx, "mean": [0.9, 1.9, 2.9]})

    def fake_read_frame(path):
        path_str = str(path)
        if "price_forecast.csv" in path_str:
            return forward.copy()
        return history.copy()

    def fake_path_exists(path):
        return True

    monkeypatch.setattr(dashboard, "read_frame", fake_read_frame)
    monkeypatch.setattr(dashboard, "path_exists", fake_path_exists)
    monkeypatch.setattr(dashboard, "load_price_series", lambda area: actual)

    actual_out, forward_out, history_out = dashboard.load_price_data("DE_LU")

    pd.testing.assert_series_equal(actual_out, actual)
    assert forward_out is not None
    assert history_out is not None
    assert "pred" in history_out.columns

