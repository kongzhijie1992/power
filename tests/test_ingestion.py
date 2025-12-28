"""Tests for ingestion modules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import pandas as pd
import numpy as np
import datetime as dt
import os
import tempfile
import shutil

from src.ingest.ingest_all import synthetic_area_series
from src.ingest.incremental_ingest import (
    save_combined,
    load_existing,
    incremental_update,
)
from src.ingest.entsoe_client import fetch_multi_area_day_ahead, DEFAULT_ZONES


class TestSyntheticDataGeneration(unittest.TestCase):
    """Test synthetic price data generation."""

    def test_synthetic_area_series_length(self):
        """Test that synthetic data has correct length."""
        days = 10
        series = synthetic_area_series("DE", days=days)
        expected_hours = days * 24
        self.assertEqual(len(series), expected_hours)

    def test_synthetic_area_series_index_type(self):
        """Test that index is DatetimeIndex."""
        series = synthetic_area_series("DE", days=5)
        self.assertIsInstance(series.index, pd.DatetimeIndex)

    def test_synthetic_area_series_values_positive(self):
        """Test that synthetic prices are positive (realistic)."""
        series = synthetic_area_series("DE", days=5)
        self.assertTrue((series > 0).all())

    def test_synthetic_area_series_freq(self):
        """Test that synthetic data has hourly frequency."""
        series = synthetic_area_series("DE", days=5)
        self.assertEqual(series.index.inferred_freq, "h")

    def test_synthetic_has_seasonality(self):
        """Test that synthetic data has daily seasonality."""
        series = synthetic_area_series("DE", days=7)
        # Resample to daily mean and check variance across days
        daily_mean = series.resample("D").mean()
        self.assertGreater(daily_mean.std(), 0)


class TestDataPersistence(unittest.TestCase):
    """Test data I/O (save/load)."""

    def setUp(self):
        """Create temporary directory for test data."""
        self.test_dir = tempfile.mkdtemp()
        self.original_s3_disable = os.getenv("S3_DISABLE")
        os.environ["S3_DISABLE"] = "1"
        # Override DATA_DIR for tests
        import src.data.io

        self.original_data_dir = src.data.io.DATA_DIR
        src.data.io.DATA_DIR = Path(self.test_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if self.original_s3_disable is None:
            os.environ.pop("S3_DISABLE", None)
        else:
            os.environ["S3_DISABLE"] = self.original_s3_disable
        import src.data.io

        src.data.io.DATA_DIR = self.original_data_dir

    def test_save_and_load_series(self):
        """Test saving and loading a series."""
        area = "DE"
        series = synthetic_area_series(area, days=5)

        # Save
        from src.data.io import save_series_csv

        save_series_csv(series, area)

        # Load
        from src.data.io import load_series_csv

        loaded = load_series_csv(area)

        # Compare (check_names=False because CSV serialization changes Series name to 'value')
        pd.testing.assert_series_equal(series, loaded, check_names=False)

    def test_load_nonexistent_raises_error(self):
        """Test that loading nonexistent data raises FileNotFoundError."""
        from src.data.io import load_series_csv

        with self.assertRaises(FileNotFoundError):
            load_series_csv("XX_NONEXISTENT")

    def test_save_combined_appends(self):
        """Test that save_combined properly combines old and new data."""
        area = "DE"
        # Create initial data
        s1 = synthetic_area_series(area, days=5)
        save_combined(s1, area)

        # Create new data with 2-day overlap
        end = s1.index.max()
        idx_new = pd.date_range(
            end - pd.Timedelta(days=2), periods=72, freq="h"
        )
        s2 = pd.Series(np.random.uniform(30, 80, len(idx_new)), index=idx_new)

        # Load and combine
        loaded = load_existing(area)
        combined = pd.concat([loaded, s2[~s2.index.isin(loaded.index)]])
        combined = combined[
            ~combined.index.duplicated(keep="last")
        ].sort_index()
        save_combined(combined, area)

        # Verify
        final = load_existing(area)
        self.assertGreaterEqual(len(final), len(s1))


class TestIncrementalUpdate(unittest.TestCase):
    """Test incremental ingestion logic."""

    def test_incremental_creates_new_data(self):
        """Test that incremental update creates data when none exists."""
        # This test would require mocking ENTSO-E API
        # For now, we test that load_existing returns empty when no data
        original_s3_disable = os.getenv("S3_DISABLE")
        os.environ["S3_DISABLE"] = "1"
        area = "TEST_AREA"
        try:
            existing = load_existing(area)
        finally:
            if original_s3_disable is None:
                os.environ.pop("S3_DISABLE", None)
            else:
                os.environ["S3_DISABLE"] = original_s3_disable
        self.assertEqual(len(existing), 0)


class TestDefaultZones(unittest.TestCase):
    """Test ENTSO-E default bidding zones."""

    def test_default_zones_not_empty(self):
        """Test that default zones list is defined."""
        self.assertGreater(len(DEFAULT_ZONES), 0)

    def test_default_zones_contains_de(self):
        """Test that Germany is in default zones."""
        self.assertIn("DE", DEFAULT_ZONES)

    def test_default_zones_contains_major_eu_areas(self):
        """Test that major European areas are included."""
        major_areas = ["DE", "FR", "GB", "IT", "ES", "NL"]
        for area in major_areas:
            self.assertIn(area, DEFAULT_ZONES)


if __name__ == "__main__":
    unittest.main()
