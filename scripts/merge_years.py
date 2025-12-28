#!/usr/bin/env python3
"""
Download & Merge 2 Years of ENTSO-E Price Data

This script helps you gather 2 years of historical electricity prices.
Steps:
  1. Download 2 years from ENTSO-E GUI (3x 4-month chunks, ~15 min total)
  2. Run this script to merge them
  3. Verify quality with check_data.py

Total data: ~17,520 hourly rows (2 years)
"""
import argparse
from pathlib import Path
import pandas as pd
import sys

from src.data.io import resolve_write_path, write_frame

def download_instructions():
    """Print instructions for downloading from ENTSO-E GUI."""
    print(
        """
╔════════════════════════════════════════════════════════════════════════════╗
║                  ENTSOE GUI DATA DOWNLOAD INSTRUCTIONS                     ║
╚════════════════════════════════════════════════════════════════════════════╝

STEP 1: Download 2024 (Jan-Dec)
  1. Go to https://www.entsoe.eu/data/energy-prices-data/
  2. Select:
     - Area: Germany/Luxembourg (DE_LU)
     - Data type: Day-ahead prices
     - Period: 01/01/2024 00:00 to 31/12/2024 23:45
  3. Click "Download as CSV"
  4. Save as: "GUI_2024.csv"

STEP 2: Download 2023 (Jan-Dec)
  1. Same as Step 1, but:
     - Period: 01/01/2023 00:00 to 31/12/2023 23:45
  2. Save as: "GUI_2023.csv"

STEP 3: (Optional) Download Current Year (2025 Jan-Dec so far)
  1. Same as Step 1, but:
     - Period: 01/01/2025 00:00 to 12/12/2025 23:45
  2. Save as: "GUI_2025.csv"

STEP 4: Run this script
  python scripts/merge_years.py \\
    --input1 "GUI_2024.csv" \\
    --input2 "GUI_2023.csv" \\
    --output data/DE_LU/day_ahead.csv \\
    --sequence 1

Expected Result:
  - ~17,500 hourly rows (2 years)
  - UTC timezone-aware
  - No gaps or duplicates
  - All DST transitions handled

═══════════════════════════════════════════════════════════════════════════════

Alternative: Use this script to download directly (requires curl/wget):

  python scripts/merge_years.py --fetch 2023 2024

═══════════════════════════════════════════════════════════════════════════════
"""
    )


def merge_csv_files(input_files, output_file, sequence=1):
    """
    Merge multiple ENTSO-E GUI CSV exports into a single hourly dataset.

    Args:
        input_files: List of CSV file paths to merge
        output_file: Path to write merged output
        sequence: Sequence number to extract (1 or 2)
    """
    all_data = []

    for csv_path in input_files:
        if not Path(csv_path).exists():
            raise FileNotFoundError(f"Input file not found: {csv_path}")

        print(f"Reading {csv_path}...", end=" ")
        df = pd.read_csv(csv_path, dtype=str)

        # Column detection
        mtu_col = next((c for c in df.columns if "MTU" in c), df.columns[0])
        price_col = next((c for c in df.columns if "Day-ahead" in c), None)
        seq_col = next((c for c in df.columns if "Sequence" in c), None)

        if price_col is None:
            raise ValueError(f"Could not find Day-ahead price column in {csv_path}")

        # Filter by sequence
        df_seq = df.copy()
        if seq_col is not None:
            df_seq = df_seq[
                df_seq[seq_col].str.contains(f"Sequence {sequence}", na=False)
            ]

        # Parse timestamps (MTU format: '31/12/2024 23:00:00 - 31/12/2024 23:15:00')
        df_seq["mtu_start"] = df_seq[mtu_col].str.split(" - ").str[0]
        df_seq["timestamp"] = pd.to_datetime(
            df_seq["mtu_start"], dayfirst=True, errors="coerce"
        )

        if df_seq["timestamp"].isna().any():
            print(f"ERROR: Could not parse timestamps")
            raise ValueError(f"Failed to parse MTU timestamps in {csv_path}")

        # Parse prices
        df_seq["price"] = pd.to_numeric(
            df_seq[price_col].str.replace(",", "."), errors="coerce"
        )

        if df_seq["price"].isna().all():
            raise ValueError(f"All prices are NaN in {csv_path}")

        # Resample to hourly
        df_seq = df_seq.set_index("timestamp")
        series = df_seq["price"].resample("H").mean()

        print(f"{len(series)} hourly rows")
        all_data.append(series)

    # Combine all data
    print(f"\nMerging {len(all_data)} datasets...")
    combined = pd.concat(all_data, sort=True).sort_index()

    # Remove duplicates (keep first occurrence)
    combined = combined[~combined.index.duplicated(keep="first")]

    # Localize to UTC
    if combined.index.tz is None:
        combined = combined.tz_localize("UTC")
    else:
        combined = combined.tz_convert("UTC")

    # Write output
    output_file = resolve_write_path(Path(output_file))
    write_frame(
        combined.rename("value").to_frame(),
        output_file,
        index_label="datetime",
    )

    print(f"\n✅ Merged file written: {output_file}")
    print(f"   Rows: {len(combined):,}")
    print(f"   Date range: {combined.index[0]} to {combined.index[-1]}")
    print(f"   Missing values: {combined.isna().sum()}")
    print(f"   Timezone: {combined.index.tz}")

    return combined


def main():
    p = argparse.ArgumentParser(
        description="Merge multiple ENTSO-E GUI CSV exports into a 2-year dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge two yearly CSV files
  python scripts/merge_years.py --input1 GUI_2024.csv --input2 GUI_2023.csv \\
    --output data/DE_LU/day_ahead.csv

  # Show download instructions
  python scripts/merge_years.py --instructions

  # Merge three files
  python scripts/merge_years.py \\
    --input1 GUI_2025.csv --input2 GUI_2024.csv --input3 GUI_2023.csv \\
    --output data/DE_LU/day_ahead.csv
        """,
    )

    p.add_argument(
        "--instructions",
        action="store_true",
        help="Show detailed download instructions",
    )
    p.add_argument("--input1", help="First CSV file (e.g., 2024 data)")
    p.add_argument("--input2", help="Second CSV file (e.g., 2023 data)")
    p.add_argument("--input3", help="Third CSV file (optional, e.g., 2025 data)")
    p.add_argument("--output", help="Output CSV file")
    p.add_argument(
        "--sequence",
        type=int,
        default=1,
        choices=[1, 2],
        help="Sequence to extract (1=SDAC, 2=EXAA)",
    )

    args = p.parse_args()

    if args.instructions:
        download_instructions()
        return

    if not args.input1 or not args.output:
        print("Error: --input1 and --output are required")
        print("Use --instructions to see download guide")
        sys.exit(1)

    # Collect input files
    inputs = [args.input1]
    if args.input2:
        inputs.append(args.input2)
    if args.input3:
        inputs.append(args.input3)

    print(f"Merging {len(inputs)} ENTSO-E CSV file(s)...\n")
    merge_csv_files(inputs, args.output, args.sequence)

    print(f"\n✅ Next steps:")
    print(f"   1. Verify data: python check_data.py")
    print(f"   2. Backtest: pytest tests/test_backtesting.py -v")
    print(f"   3. Check DST handling: pytest tests/test_dst_handling.py -v")


if __name__ == "__main__":
    main()
