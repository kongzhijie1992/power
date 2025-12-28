"""Tests for forecasting models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import pandas as pd
import numpy as np
import datetime as dt

from src.ingest.ingest_all import synthetic_area_series
from src.models.forecast import make_features, seasonal_naive_forecast
from src.models.forecast_cv import (
    build_features_with_weather,
    cv_train_lgbm,
    quantile_models_train,
)
from src.features.weather_features import add_gfs_features


class TestFeatureEngineering(unittest.TestCase):
    """Test feature construction."""

    def setUp(self):
        """Create synthetic price series."""
        self.prices = synthetic_area_series("DE", days=10)

    def test_make_features_creates_required_columns(self):
        """Test that make_features includes temporal and lag features."""
        df = make_features(self.prices)

        # Check for required columns
        self.assertIn("y", df.columns)
        self.assertIn("hour", df.columns)
        self.assertIn("dayofweek", df.columns)

    def test_make_features_lag_columns(self):
        """Test that lag features are created."""
        df = make_features(self.prices)
        expected_lags = ["lag_24", "lag_48", "lag_168"]
        for lag in expected_lags:
            self.assertIn(lag, df.columns)

    def test_make_features_rolling_mean(self):
        """Test that rolling mean features are created."""
        df = make_features(self.prices)
        self.assertIn("rmean_24", df.columns)

    def test_make_features_removes_nans(self):
        """Test that features are created after dropping NaNs."""
        df = make_features(self.prices)
        # After dropna(), should have fewer rows (due to lags)
        self.assertLess(len(df), len(self.prices))
        self.assertEqual(df.isnull().sum().sum(), 0)

    def test_weather_features_returns_dataframe(self):
        """Test that weather feature function returns DataFrame."""
        df = add_gfs_features(self.prices.index, lat=52.5, lon=13.4)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), len(self.prices.index))

    def test_weather_features_has_proxy_columns(self):
        """Test that weather features include wind and solar proxies."""
        df = add_gfs_features(self.prices.index, lat=52.5, lon=13.4)
        # Should have at least wind_proxy and solar_proxy
        self.assertTrue(len(df.columns) >= 2)

    def test_build_features_with_weather(self):
        """Test combined feature builder."""
        df, cols = build_features_with_weather(self.prices, lat=52.5, lon=13.4)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertIsInstance(cols, list)
        self.assertGreater(
            len(cols), 3
        )  # Should include weather + price features


class TestSeasonalNaiveForecasting(unittest.TestCase):
    """Test baseline seasonal-naive forecaster."""

    def setUp(self):
        """Create synthetic price series."""
        self.prices = synthetic_area_series("DE", days=30)

    def test_seasonal_naive_output_length(self):
        """Test that forecast has correct length."""
        forecast = seasonal_naive_forecast(self.prices, days=7)
        expected_hours = 7 * 24
        self.assertEqual(len(forecast), expected_hours)

    def test_seasonal_naive_output_type(self):
        """Test that output is a pandas Series."""
        forecast = seasonal_naive_forecast(self.prices, days=7)
        self.assertIsInstance(forecast, pd.Series)

    def test_seasonal_naive_output_index(self):
        """Test that forecast has DatetimeIndex."""
        forecast = seasonal_naive_forecast(self.prices, days=7)
        self.assertIsInstance(forecast.index, pd.DatetimeIndex)

    def test_seasonal_naive_values_positive(self):
        """Test that forecasted values are positive."""
        forecast = seasonal_naive_forecast(self.prices, days=7)
        self.assertTrue((forecast > 0).all())

    def test_seasonal_naive_has_daily_pattern(self):
        """Test that forecast captures daily seasonality."""
        forecast = seasonal_naive_forecast(self.prices, days=7)
        # Compare hours 0-6 and 12-18 (night vs day)
        night_avg = forecast.iloc[::24][:3].mean()
        day_avg = forecast.iloc[12::24][:3].mean()
        # Prices typically higher during day (trend visible)
        self.assertNotEqual(night_avg, day_avg)


class TestLightGBMTraining(unittest.TestCase):
    """Test LightGBM model training."""

    def setUp(self):
        """Create synthetic data."""
        self.prices = synthetic_area_series("DE", days=30)

    def test_cv_train_lgbm_returns_model_and_stats(self):
        """Test that CV training returns model and statistics."""
        model, stats = cv_train_lgbm(self.prices, n_splits=2)

        # Should return tuple of (model, dict)
        self.assertIsNotNone(stats)
        self.assertIn("rmse", stats)
        self.assertIn("mae", stats)
        self.assertIn("rmse_splits", stats)

    def test_cv_train_lgbm_stats_reasonable(self):
        """Test that RMSE metrics are reasonable."""
        model, stats = cv_train_lgbm(self.prices, n_splits=2)

        # RMSE should be positive and non-zero
        self.assertGreater(stats["rmse"], 0)
        self.assertGreater(stats["mae"], 0)
        # CV splits should be a list
        self.assertIsInstance(stats["rmse_splits"], list)
        self.assertGreater(len(stats["rmse_splits"]), 0)

    def test_quantile_models_train_returns_models(self):
        """Test that quantile model training works."""
        q_models = quantile_models_train(
            self.prices, quantiles=(0.1, 0.5, 0.9), lat=52.5, lon=13.4
        )

        if q_models is not None:  # LightGBM may not be installed
            self.assertIsInstance(q_models, dict)
            self.assertEqual(len(q_models), 3)

    def test_quantile_models_have_expected_keys(self):
        """Test that quantile models are keyed by quantile."""
        q_models = quantile_models_train(
            self.prices, quantiles=(0.1, 0.5, 0.9), lat=52.5, lon=13.4
        )

        if q_models is not None:
            for q in [0.1, 0.5, 0.9]:
                self.assertIn(q, q_models)


class TestForecastAccuracy(unittest.TestCase):
    """Test forecast accuracy and reasonableness."""

    def setUp(self):
        """Create synthetic data."""
        self.prices = synthetic_area_series("DE", days=30)

    def test_forecast_mean_within_historical_range(self):
        """Test that forecast mean is within historical price range."""
        forecast = seasonal_naive_forecast(self.prices, days=7)

        hist_min = self.prices.min()
        hist_max = self.prices.max()

        # Forecast mean should be within historical range (with some tolerance)
        self.assertGreater(forecast.mean(), hist_min * 0.5)
        self.assertLess(forecast.mean(), hist_max * 1.5)

    def test_forecast_std_similar_to_historical(self):
        """Test that forecast variability is similar to historical."""
        forecast = seasonal_naive_forecast(self.prices, days=7)

        hist_std = self.prices.std()
        forecast_std = forecast.std()

        # Forecast std should be similar to historical (within 50%)
        self.assertGreater(forecast_std, hist_std * 0.5)
        self.assertLess(forecast_std, hist_std * 2.0)


if __name__ == "__main__":
    unittest.main()
