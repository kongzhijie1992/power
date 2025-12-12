"""Tests for data I/O utilities."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import pandas as pd
import numpy as np
import shutil

from src.ingest.ingest_all import synthetic_area_series
from src.data.io import save_series_csv, load_series_csv, DATA_DIR


class TestCSVIO(unittest.TestCase):
    """Test CSV save/load."""

    def setUp(self):
        """Create sample data."""
        self.prices = synthetic_area_series('DE', days=10)

    def tearDown(self):
        """Clean up test data."""
        try:
            (DATA_DIR / 'DE').rmdir()
        except Exception:
            pass

    def test_save_and_load_csv(self):
        """Test save/load roundtrip with CSV."""
        save_series_csv(self.prices, 'DE', 'test_csv')
        loaded = load_series_csv('DE', 'test_csv')
        
        # Values and index should match (name may differ due to CSV format)
        pd.testing.assert_series_equal(self.prices, loaded, check_names=False)

    def test_csv_preserves_index(self):
        """Test that DatetimeIndex is preserved in CSV."""
        save_series_csv(self.prices, 'DE', 'test_idx')
        loaded = load_series_csv('DE', 'test_idx')
        
        # Index should be DatetimeIndex
        self.assertIsInstance(loaded.index, pd.DatetimeIndex)
        pd.testing.assert_index_equal(self.prices.index, loaded.index)

    def test_csv_preserves_values(self):
        """Test that values are preserved exactly."""
        save_series_csv(self.prices, 'DE', 'test_val')
        loaded = load_series_csv('DE', 'test_val')
        
        np.testing.assert_array_almost_equal(self.prices.values, loaded.values)

    def test_load_nonexistent_csv_raises_error(self):
        """Test that loading nonexistent CSV raises error."""
        with self.assertRaises(FileNotFoundError):
            load_series_csv('DE', 'nonexistent_xyz_123')


class TestDataIntegrity(unittest.TestCase):
    """Test data integrity and edge cases."""

    def tearDown(self):
        """Clean up test data."""
        try:
            (DATA_DIR / 'DE').rmdir()
        except Exception:
            pass

    def test_save_empty_series_csv(self):
        """Test saving empty series to CSV."""
        empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
        save_series_csv(empty, 'DE', 'empty')
        loaded = load_series_csv('DE', 'empty')
        
        self.assertEqual(len(loaded), 0)

    def test_save_series_with_nans_csv(self):
        """Test saving series with NaN values to CSV."""
        prices = pd.Series(
            [10.0, np.nan, 30.0, np.nan, 50.0],
            index=pd.date_range('2024-01-01', periods=5, freq='h')
        )
        save_series_csv(prices, 'DE', 'nans')
        loaded = load_series_csv('DE', 'nans')
        
        # NaNs should be preserved
        self.assertEqual(loaded.isna().sum(), prices.isna().sum())

    def test_save_series_with_negative_values(self):
        """Test saving series with negative values (realistic in some markets)."""
        prices = pd.Series(
            [-5.0, 10.0, 0.0, -2.5, 15.0],
            index=pd.date_range('2024-01-01', periods=5, freq='h')
        )
        save_series_csv(prices, 'DE', 'negative')
        loaded = load_series_csv('DE', 'negative')
        
        np.testing.assert_array_equal(prices.values, loaded.values)

    def test_large_series_roundtrip(self):
        """Test roundtrip with large series (1 year)."""
        large_prices = synthetic_area_series('DE', days=365)
        save_series_csv(large_prices, 'DE', 'large')
        loaded = load_series_csv('DE', 'large')
        
        self.assertEqual(len(loaded), len(large_prices))
        np.testing.assert_array_almost_equal(large_prices.values, loaded.values)


class TestIOErrorHandling(unittest.TestCase):
    """Test error handling in I/O."""

    def tearDown(self):
        """Clean up test data."""
        try:
            (DATA_DIR / 'DE').rmdir()
        except Exception:
            pass

    def test_load_nonexistent_area(self):
        """Test loading from nonexistent area."""
        with self.assertRaises(FileNotFoundError):
            load_series_csv('NONEXISTENT_AREA_XYZ', 'any')

    def test_directory_creation(self):
        """Test that save creates area directories."""
        prices = synthetic_area_series('TEST_AREA', days=5)
        save_series_csv(prices, 'TEST_AREA', 'test')
        
        path = DATA_DIR / 'TEST_AREA'
        self.assertTrue(path.exists())
        
        # Cleanup
        shutil.rmtree(path, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
