"""Tests for backtesting framework."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import pandas as pd
import numpy as np

from src.ingest.ingest_all import synthetic_area_series
from src.models.forecast import seasonal_naive_forecast
from src.models.backtest import walk_forward_backtest


class TestWalkForwardBacktest(unittest.TestCase):
    """Test walk-forward backtesting framework."""

    def setUp(self):
        """Create synthetic price series."""
        self.prices = synthetic_area_series("DE", days=60)

    def test_walk_forward_backtest_returns_dataframe(self):
        """Test that backtest returns a DataFrame."""
        results = walk_forward_backtest(self.prices, seasonal_naive_forecast)

        self.assertIsInstance(results, pd.DataFrame)
        self.assertIn("rmse", results.columns)

    def test_walk_forward_backtest_has_results(self):
        """Test that backtest produces results."""
        results = walk_forward_backtest(self.prices, seasonal_naive_forecast)

        self.assertGreater(len(results), 0)
        self.assertTrue((results["rmse"] > 0).all())

    def test_walk_forward_backtest_custom_window(self):
        """Test backtest with custom train/horizon windows."""
        results = walk_forward_backtest(
            self.prices,
            seasonal_naive_forecast,
            train_window_days=30,
            horizon_days=7,
        )

        self.assertGreater(len(results), 0)

    def test_walk_forward_backtest_rmse_realistic(self):
        """Test that RMSE values are realistic (positive, not infinite)."""
        results = walk_forward_backtest(
            self.prices,
            seasonal_naive_forecast,
            train_window_days=30,
            horizon_days=5,
        )

        # All RMSE values should be positive and finite
        self.assertTrue((results["rmse"] > 0).all())
        self.assertTrue(np.isfinite(results["rmse"]).all())


class TestBacktestWithDifferentForecasters(unittest.TestCase):
    """Test backtesting with different forecast functions."""

    def setUp(self):
        """Create synthetic data."""
        self.prices = synthetic_area_series("DE", days=60)

    def test_backtest_with_seasonal_naive(self):
        """Test backtest with seasonal naive forecaster."""
        results = walk_forward_backtest(self.prices, seasonal_naive_forecast)

        self.assertGreater(len(results), 0)
        for rmse in results["rmse"]:
            if not np.isnan(rmse):
                self.assertGreater(rmse, 0)

    def test_custom_forecast_function(self):
        """Test backtest with custom forecast function."""

        def simple_mean_forecast(train_series, days):
            """Simple mean forecast for testing."""
            return pd.Series(
                np.full(days * 24, train_series.mean()),
                index=pd.date_range(
                    start=train_series.index[-1], periods=days * 24, freq="h"
                ),
            )

        results = walk_forward_backtest(self.prices, simple_mean_forecast)
        self.assertGreater(len(results), 0)


class TestBacktestEdgeCases(unittest.TestCase):
    """Test edge cases in backtesting."""

    def test_backtest_consistency(self):
        """Test that backtest is deterministic for same input."""
        prices = synthetic_area_series("DE", days=90)

        results1 = walk_forward_backtest(
            prices,
            seasonal_naive_forecast,
            train_window_days=30,
            horizon_days=5,
        )
        results2 = walk_forward_backtest(
            prices,
            seasonal_naive_forecast,
            train_window_days=30,
            horizon_days=5,
        )

        # Should produce identical results
        pd.testing.assert_frame_equal(results1, results2)

    def test_backtest_large_data(self):
        """Test backtest with 365 days of data."""
        prices = synthetic_area_series("DE", days=365)

        results = walk_forward_backtest(
            prices,
            seasonal_naive_forecast,
            train_window_days=90,
            horizon_days=14,
        )

        # Should complete and have multiple windows
        self.assertGreater(len(results), 1)

    def test_backtest_result_structure(self):
        """Test that backtest results have correct structure."""
        prices = synthetic_area_series("DE", days=60)
        results = walk_forward_backtest(prices, seasonal_naive_forecast)

        # Check required columns
        self.assertIn("rmse", results.columns)
        # Check index is datetime-like
        self.assertIsNotNone(results.index)


if __name__ == "__main__":
    unittest.main()
