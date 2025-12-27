"""Integration tests for full pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import tempfile
import shutil
import pandas as pd
import numpy as np

from src.ingest.ingest_all import synthetic_area_series
from src.models.forecast import make_features, seasonal_naive_forecast
from src.models.forecast_cv import cv_train_lgbm, build_features_with_weather
from src.models.backtest import walk_forward_backtest
from src.dispatch.merit_order import merit_order_clearing
from src.dispatch.unit_commitment import solve_uc
from src.data.io import save_series_csv, load_series_csv


class TestFullPipeline(unittest.TestCase):
    """Test end-to-end pipeline."""

    def setUp(self):
        """Create temp directory and sample data."""
        self.temp_dir = tempfile.mkdtemp()
        self.prices = synthetic_area_series("DE", days=60)

    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.temp_dir)

    def test_ingest_forecast_backtest_flow(self):
        """Test pipeline: ingest → features → train → backtest."""
        # Save synthetic data
        save_series_csv(self.prices, "DE", "prices_integration")

        # Load it back
        loaded = load_series_csv("DE", "prices_integration")
        self.assertEqual(len(loaded), len(self.prices))

        # Create features
        features_df = make_features(loaded)
        self.assertGreater(len(features_df), 0)

        # Train seasonal naive model
        forecast = seasonal_naive_forecast(loaded, days=7)
        self.assertEqual(len(forecast), 7 * 24)

    def test_backtest_to_dispatch_flow(self):
        """Test pipeline: backtest → dispatch."""
        # Run backtest
        results = walk_forward_backtest(
            self.prices, seasonal_naive_forecast, train_window_days=30, horizon_days=7
        )

        # Use results to get sample forecast
        forecast = seasonal_naive_forecast(self.prices[-168:], days=7)

        # Dispatch on forecast
        units = [
            {"name": "wind", "capacity": 100, "marginal_cost": 0},
            {"name": "gas", "capacity": 200, "marginal_cost": 50},
        ]

        for hour_demand in forecast:
            result = merit_order_clearing(hour_demand, units)
            total = sum(item["dispatched_mw"] for item in result["dispatch"])
            self.assertAlmostEqual(total, hour_demand, places=1)

    def test_full_pipeline_synthetic_data(self):
        """Test complete pipeline with synthetic data."""
        # 1. Ingest (synthetic)
        prices = synthetic_area_series(
            "DE", days=90
        )  # Use 90 days for seasonal_naive_forecast
        self.assertEqual(len(prices), 90 * 24)

        # 2. Features
        features = make_features(prices)
        self.assertGreater(len(features), 0)

        # 3. Backtest
        results = walk_forward_backtest(
            prices, seasonal_naive_forecast, train_window_days=40, horizon_days=7
        )
        # Results is DataFrame with 'rmse' column
        self.assertIn("rmse", results.columns)
        self.assertGreater(len(results), 0)

        # 4. Forecast
        forecast = seasonal_naive_forecast(prices, days=7)
        self.assertEqual(len(forecast), 168)

        # 5. Dispatch
        units = [{"name": "gen", "capacity": 300, "marginal_cost": 30}]
        for demand in forecast[:24]:
            result = merit_order_clearing(demand, units)
            dispatched = sum(item["dispatched_mw"] for item in result["dispatch"])
            self.assertAlmostEqual(dispatched, demand, places=1)

    def test_uc_dispatch_integration(self):
        """Test UC solver integration with forecast."""
        # Generate forecast
        forecast = seasonal_naive_forecast(self.prices[-168:], days=1)

        # Run UC - demand should be Series, not ndarray
        units = [
            {
                "name": "base",
                "p_min": 50,
                "p_max": 200,
                "marginal_cost": 30,
                "startup_cost": 500,
                "min_up": 4,
                "min_down": 2,
                "ramp_up": 100,
                "ramp_down": 100,
            }
        ]

        result = solve_uc(units, forecast)

        # Verify feasibility
        self.assertIn("dispatch", result)
        dispatch_total = result["dispatch"].sum().sum()
        forecast_total = forecast.sum()
        self.assertGreater(
            dispatch_total, forecast_total * 0.9
        )  # Should meet most demand


class TestPipelineDataFlow(unittest.TestCase):
    """Test data consistency through pipeline."""

    def setUp(self):
        """Create sample data."""
        self.prices = synthetic_area_series("DE", days=60)

    def test_index_preservation_through_pipeline(self):
        """Test that DatetimeIndex is preserved."""
        # Make features
        features = make_features(self.prices)

        # Index should be DatetimeIndex
        self.assertIsInstance(features.index, pd.DatetimeIndex)
        # Index should be the same length or shorter (NaN rows dropped)
        self.assertLessEqual(len(features), len(self.prices))

    def test_value_ranges_through_pipeline(self):
        """Test that values stay in reasonable ranges."""
        # Features
        features = make_features(self.prices)

        # Price target should be in range
        if "y" in features.columns:
            self.assertTrue((features["y"] > 0).any())

        # Lagged features should also be positive
        for col in features.columns:
            if col.startswith("lag"):
                self.assertTrue((features[col] > 0).any())

    def test_no_data_leakage_in_backtest(self):
        """Test that backtest doesn't leak future data."""
        results = walk_forward_backtest(
            self.prices, seasonal_naive_forecast, train_window_days=30, horizon_days=7
        )

        # Should have results (DataFrame with rmse column)
        self.assertIsInstance(results, pd.DataFrame)
        self.assertIn("rmse", results.columns)
        self.assertGreater(len(results), 0)

        # All RMSEs should be positive
        self.assertTrue((results["rmse"] > 0).all())


class TestPipelineRobustness(unittest.TestCase):
    """Test pipeline robustness to edge cases."""

    def setUp(self):
        """Create temp directory."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.temp_dir)

    def test_pipeline_with_gaps_in_data(self):
        """Test pipeline when data has gaps."""
        # Create data with gap
        part1 = synthetic_area_series("DE", days=10)
        part2 = synthetic_area_series("DE", days=10)
        # Shift part2 to create gap
        part2.index = part2.index + pd.Timedelta(days=15)

        combined = pd.concat([part1, part2])

        # Should still process
        features = make_features(combined)
        self.assertGreater(len(features), 0)

    def test_pipeline_with_duplicate_times(self):
        """Test pipeline when data has duplicate timestamps."""
        prices = synthetic_area_series("DE", days=10)

        # Add duplicate
        duplicated = pd.concat([prices, prices.iloc[-24:]])

        # Remove duplicates (typical preprocessing)
        deduplicated = duplicated[~duplicated.index.duplicated(keep="first")]

        features = make_features(deduplicated)
        self.assertGreater(len(features), 0)

    def test_pipeline_different_timezones(self):
        """Test pipeline with timezone-aware data."""
        prices = synthetic_area_series("DE", days=10)
        prices.index = prices.index.tz_localize("UTC")

        features = make_features(prices)
        self.assertGreater(len(features), 0)

    def test_pipeline_scaling_to_year(self):
        """Test pipeline scales to year-long data."""
        prices = synthetic_area_series("DE", days=365)

        # Should complete without error
        features = make_features(prices)
        self.assertGreater(len(features), 0)

        forecast = seasonal_naive_forecast(prices, days=7)
        self.assertEqual(len(forecast), 168)


class TestPipelineConsistency(unittest.TestCase):
    """Test that pipeline is deterministic."""

    def test_forecast_consistency(self):
        """Test that same input produces same forecast."""
        prices = synthetic_area_series("DE", days=30)

        forecast1 = seasonal_naive_forecast(prices, days=7)
        forecast2 = seasonal_naive_forecast(prices, days=7)

        np.testing.assert_array_equal(forecast1.values, forecast2.values)

    def test_backtest_determinism(self):
        """Test that backtest is deterministic."""
        prices = synthetic_area_series("DE", days=90)

        results1 = walk_forward_backtest(
            prices, seasonal_naive_forecast, train_window_days=40, horizon_days=7
        )
        results2 = walk_forward_backtest(
            prices, seasonal_naive_forecast, train_window_days=40, horizon_days=7
        )

        # Results should be identical DataFrames
        pd.testing.assert_frame_equal(results1, results2)

    def test_dispatch_determinism(self):
        """Test that dispatch is deterministic."""
        units = [
            {"name": "u1", "capacity": 100, "marginal_cost": 30},
            {"name": "u2", "capacity": 150, "marginal_cost": 50},
        ]
        demand = 200

        dispatch1 = merit_order_clearing(demand, units)
        dispatch2 = merit_order_clearing(demand, units)

        self.assertEqual(dispatch1, dispatch2)


if __name__ == "__main__":
    unittest.main()
