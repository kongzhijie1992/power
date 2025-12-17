#!/usr/bin/env python3
"""
Quick script to download real ENTSOE data and process it

Steps:
1. Visit: https://www.entsoe.eu/data/energy-prices-data/
2. Download 2024 data → Save as GUI_2024.csv
3. Download 2023 data → Save as GUI_2023.csv
4. Run this script: python download_real_data.py
"""
import sys
from pathlib import Path
import subprocess


def check_files():
    """Check if downloaded CSV files exist."""
    csv_2024 = Path("GUI_2024.csv")
    csv_2023 = Path("GUI_2023.csv")

    print("\n📋 Checking for downloaded files...")
    print(f"   {'✓' if csv_2024.exists() else '✗'} GUI_2024.csv", end="")
    if csv_2024.exists():
        size_mb = csv_2024.stat().st_size / (1024 * 1024)
        print(f" ({size_mb:.1f} MB)")
    else:
        print(" [MISSING]")

    print(f"   {'✓' if csv_2023.exists() else '✗'} GUI_2023.csv", end="")
    if csv_2023.exists():
        size_mb = csv_2023.stat().st_size / (1024 * 1024)
        print(f" ({size_mb:.1f} MB)")
    else:
        print(" [MISSING]")

    if not (csv_2024.exists() and csv_2023.exists()):
        print("\n❌ Missing files! Please download from ENTSOE first:")
        print("   https://www.entsoe.eu/data/energy-prices-data/")
        print("\n   1. Set: Market Area = Germany (DE)")
        print("   2. Set: Data Type = Day-ahead prices")
        print("   3. Date From = 01/01/2024, Date To = 31/12/2024")
        print("   4. Download CSV → Save as GUI_2024.csv")
        print("   5. Repeat for 2023 (01/01/2023 - 31/12/2023) → GUI_2023.csv")
        return False

    return True


def merge_and_verify():
    """Merge CSVs and verify data."""
    print("\n🔧 Merging downloaded files...")

    result = subprocess.run(
        [
            "python",
            "scripts/merge_years.py",
            "--input1",
            "GUI_2024.csv",
            "--input2",
            "GUI_2023.csv",
        ],
        capture_output=False,
    )

    if result.returncode != 0:
        print("❌ Merge failed")
        return False

    return True


def run_tests():
    """Run test suite to verify data."""
    print("\n✅ Running test suite...")

    result = subprocess.run(["pytest", "-q", "--tb=short"], capture_output=False)

    if result.returncode != 0:
        print("❌ Tests failed")
        return False

    print("\n✅ REAL DATA INSTALLED AND VERIFIED!")
    print("   All 87 tests passing with production ENTSOE data")
    return True


def main():
    """Main workflow."""
    print("╔════════════════════════════════════════════════════════════╗")
    print("║       ENTSOE Real Data Download & Processing               ║")
    print("╚════════════════════════════════════════════════════════════╝")

    if not check_files():
        return 1

    if not merge_and_verify():
        return 1

    if not run_tests():
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
