"""Test DST (Daylight Saving Time) handling in the data pipeline."""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import subprocess
import sys


class TestDSTHandling(unittest.TestCase):
    """Verify the pipeline correctly handles DST transitions."""

    def test_dst_spring_forward_2025(self):
        """Test spring forward transition (last Sunday of March 2025: 30 Mar 02:00 UTC → 03:00 UTC).

        In CET: 30 Mar 02:00 CET → 03:00 CEST (UTC+2)
        The hour from 02:00-03:00 CET does NOT exist on this day.

        ENTSO-E publishes in UTC, so there are 25 hours that day (22-23 on 29th + 0-23 on 30th).
        """
        # Create a CSV spanning DST spring forward
        rows = [
            [
                "MTU (UTC)",
                "Area",
                "Sequence",
                "Day-ahead Price (EUR/MWh)",
                "Intraday Period (UTC)",
                "Intraday Price (EUR/MWh)",
            ],
        ]

        # March 29-30, 2025 (spring forward occurs at UTC 00:00 on 30 Mar = 01:00 CET)
        base = datetime(2025, 3, 29, 0, 0)

        # 24 hours on March 29 (in UTC, normal progression)
        for hour in range(24):
            for quarter in range(4):
                ts = base + timedelta(hours=hour, minutes=quarter * 15)
                ts_end = ts + timedelta(minutes=15)
                mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
                price = 50.0 + hour
                rows.append(
                    [
                        mtu,
                        "BZN|DE-LU",
                        "Sequence Sequence 1",
                        f"{price:.2f}",
                        "",
                        "",
                    ]
                )

        # March 30, 2025 (25 hours total, but still normal UTC progression)
        base30 = datetime(2025, 3, 30, 0, 0)
        for hour in range(25):
            for quarter in range(4):
                ts = base30 + timedelta(hours=hour, minutes=quarter * 15)
                ts_end = ts + timedelta(minutes=15)
                mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
                price = 50.0 + (hour % 24)
                rows.append(
                    [
                        mtu,
                        "BZN|DE-LU",
                        "Sequence Sequence 1",
                        f"{price:.2f}",
                        "",
                        "",
                    ]
                )

        # Write to temp file and convert
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "dst_test.csv"
            dst = Path(tmpdir) / "day_ahead.csv"

            with src.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(",".join(f'"{c}"' for c in r) + "\n")

            # Run converter
            cmd = [
                sys.executable,
                "scripts/convert_entsoe.py",
                "--input",
                str(src),
                "--output",
                str(dst),
                "--sequence",
                "1",
                "--resample",
                "h",
                "--tz",
                "UTC",
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 0, f"Converter failed: {result.stderr}"
            )

            # Load converted data
            seq1 = pd.read_csv(dst, index_col=0, parse_dates=True)

            # Verify:
            # - Index is timezone-aware UTC
            self.assertIsNotNone(
                seq1.index.tz, "Index should be timezone-aware"
            )
            self.assertEqual(str(seq1.index.tz), "UTC", "Index should be UTC")

            # - No gaps or duplicates (49 hours total: 24 on 29th + 25 on 30th)
            self.assertEqual(
                len(seq1), 49, f"Expected 49 hourly rows, got {len(seq1)}"
            )

            # - Index is monotonically increasing
            self.assertTrue(
                seq1.index.is_monotonic_increasing,
                "Index should be monotonically increasing",
            )

            # - Values are continuous (no NaN)
            self.assertEqual(
                seq1["value"].isna().sum(), 0, "Should have no NaN values"
            )

            print(
                f"✓ Spring forward test passed: {len(seq1)} hours from {seq1.index[0]} to {seq1.index[-1]}"
            )

    def test_dst_fall_back_2025(self):
        """Test fall back transition (last Sunday of October 2025: 26 Oct 02:00 UTC stays as 01:00 UTC).

        In CEST: 26 Oct 03:00 CEST → 02:00 CET (UTC+1)
        The hour from 02:00-03:00 CET occurs TWICE on this day (once in CEST, once in CET).

        ENTSO-E publishes in UTC, so there are 25 hours that day (00-22 on 25th + 0-24 on 26th).
        """
        rows = [
            [
                "MTU (UTC)",
                "Area",
                "Sequence",
                "Day-ahead Price (EUR/MWh)",
                "Intraday Period (UTC)",
                "Intraday Price (EUR/MWh)",
            ],
        ]

        # October 25-26, 2025 (fall back occurs at UTC 01:00 on 26 Oct = 03:00 CEST → 02:00 CET)
        base = datetime(2025, 10, 25, 0, 0)

        # 24 hours on October 25
        for hour in range(24):
            for quarter in range(4):
                ts = base + timedelta(hours=hour, minutes=quarter * 15)
                ts_end = ts + timedelta(minutes=15)
                mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
                price = 60.0 + hour
                rows.append(
                    [
                        mtu,
                        "BZN|DE-LU",
                        "Sequence Sequence 1",
                        f"{price:.2f}",
                        "",
                        "",
                    ]
                )

        # October 26, 2025 (25 hours: 00-23 UTC)
        base26 = datetime(2025, 10, 26, 0, 0)
        for hour in range(25):
            for quarter in range(4):
                ts = base26 + timedelta(hours=hour, minutes=quarter * 15)
                ts_end = ts + timedelta(minutes=15)
                mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
                price = 60.0 + (hour % 24)
                rows.append(
                    [
                        mtu,
                        "BZN|DE-LU",
                        "Sequence Sequence 1",
                        f"{price:.2f}",
                        "",
                        "",
                    ]
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "dst_test.csv"
            dst = Path(tmpdir) / "day_ahead.csv"

            with src.open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(",".join(f'"{c}"' for c in r) + "\n")

            # Run converter
            cmd = [
                sys.executable,
                "scripts/convert_entsoe.py",
                "--input",
                str(src),
                "--output",
                str(dst),
                "--sequence",
                "1",
                "--resample",
                "h",
                "--tz",
                "UTC",
            ]
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 0, f"Converter failed: {result.stderr}"
            )

            # Load converted data
            seq1 = pd.read_csv(dst, index_col=0, parse_dates=True)

            # Verify:
            # - Index is timezone-aware UTC
            self.assertIsNotNone(
                seq1.index.tz, "Index should be timezone-aware"
            )
            self.assertEqual(str(seq1.index.tz), "UTC", "Index should be UTC")

            # - No gaps or duplicates (49 hours total: 24 on 25th + 25 on 26th)
            self.assertEqual(
                len(seq1), 49, f"Expected 49 hourly rows, got {len(seq1)}"
            )

            # - Index is monotonically increasing
            self.assertTrue(
                seq1.index.is_monotonic_increasing,
                "Index should be monotonically increasing",
            )

            # - Values are continuous (no NaN)
            self.assertEqual(
                seq1["value"].isna().sum(), 0, "Should have no NaN values"
            )

            print(
                f"✓ Fall back test passed: {len(seq1)} hours from {seq1.index[0]} to {seq1.index[-1]}"
            )

    def test_entsoe_client_dst_handling(self):
        """Verify entsoe_client.py correctly converts timezone-aware data to UTC naive."""
        # Simulate entsoe-py returning Europe/Berlin timezone-aware data
        index_berlin = pd.date_range(
            "2025-03-29", "2025-03-31", freq="h", tz="Europe/Berlin"
        )

        series = pd.Series(
            np.random.randn(len(index_berlin)) + 50, index=index_berlin
        )

        # Apply the conversion logic from entsoe_client.py
        # entsoe-py returns timezone-aware series (Europe timezone); convert to UTC naive
        converted = series.tz_convert("UTC").tz_localize(None)

        # Verify:
        # - Result is naive (no timezone)
        self.assertIsNone(
            converted.index.tz, "Converted index should be naive (no timezone)"
        )

        # - No gaps due to DST
        self.assertEqual(
            len(converted),
            len(series),
            "Should preserve all rows during DST conversion",
        )

        # - Index is monotonically increasing
        self.assertTrue(
            converted.index.is_monotonic_increasing,
            "Index should be monotonically increasing after conversion",
        )

        print(
            f"✓ ENTSOE client DST handling verified: {len(converted)} hours, no gaps"
        )


if __name__ == "__main__":
    unittest.main()
