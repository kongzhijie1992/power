"""Tests for dashboard tooltip formatting and data encoding."""

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "streamlit_dashboard.py"

spec = importlib.util.spec_from_file_location("streamlit_dashboard", SCRIPT_PATH)
dashboard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(dashboard)


class TestDashboardTooltip(unittest.TestCase):
    """Ensure tooltip data is encoded in a way the JS formatter can read."""

    def test_series_helpers(self):
        values = pd.Series([1.234, None, 2.345], index=pd.date_range("2024-01-01", periods=3, freq="h"))
        low = pd.Series([1.0, None, 2.0], index=values.index)
        high = pd.Series([2.0, None, 4.0], index=values.index)

        out = dashboard._series_to_list(values)
        base, diff = dashboard._series_band_base_diff(low, high)

        self.assertEqual(out, [1.234, None, 2.345])
        self.assertEqual(base, [1.0, None, 2.0])
        self.assertEqual(diff, [1.0, None, 2.0])

    def test_tooltip_formatter_includes_ranges_and_updates(self):
        formatter = dashboard._demand_tooltip_formatter(
            actual_updates=["2024-01-01 00:00 (UTC)"],
            tso_updates=["2024-01-01 00:00 (UTC)"],
            q10_vals=[1.0],
            q90_vals=[2.0],
        )
        code = getattr(formatter, "js_code", "")

        self.assertIn("actualUpdates", code)
        self.assertIn("tsoUpdates", code)
        self.assertIn("q10Vals", code)
        self.assertIn("q90Vals", code)
        self.assertIn("toFixed(2)", code)
        self.assertIn("Updated at:", code)
        self.assertIn("Model q10–q90", code)
        self.assertIn("Model q10 base", code)
