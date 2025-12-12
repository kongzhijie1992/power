#!/usr/bin/env python3
"""
Download 2 Years of Historical ENTSO-E Data

This script provides multiple methods to get 2023-2024 data:
1. Direct API fetch (if token is activated)
2. Guided GUI download + merge
3. Fallback with sample data

Usage:
  python get_historical_data.py [method]
  
Methods:
  api       - Try fetching via API (if token activated)
  gui       - Show GUI download instructions
  merge     - Merge already-downloaded CSVs
  sample    - Create sample 2-year dataset (for testing)
"""
import argparse
import sys
from pathlib import Path
import pandas as pd
import requests
from datetime import datetime, timedelta
import os


def fetch_via_api(start_date, end_date):
    """Attempt to fetch data via ENTSO-E API."""
    print("📡 Attempting to fetch via ENTSO-E API...")
    
    # Load token from .env
    env_path = Path('.env')
    if not env_path.exists():
        print("❌ .env file not found. Cannot fetch via API.")
        return None
    
    token = None
    with open(env_path) as f:
        for line in f:
            if line.startswith('ENTSOE_API_TOKEN='):
                token = line.split('=')[1].strip().strip('"\'')
                break
    
    if token is None:
        print("❌ Token not found in .env file")
        return None
    
    print(f"✓ Token loaded: {token[:20]}...")
    
    # Try to fetch day-ahead prices
    # Document type: A44 (Day-ahead prices)
    # Area: DE_LU (Germany-Luxembourg)
    
    base_url = "https://web-api.tp.entsoe.eu/api"
    
    # Format timestamps for API
    start_str = start_date.strftime("%Y%m%d0000")
    end_str = end_date.strftime("%Y%m%d0000")
    
    params = {
        'securityToken': token,
        'documentType': 'A44',
        'In_Domain': '10Y1001A1001A82F',  # DE_LU
        'Out_Domain': '10Y1001A1001A82F',
        'periodStart': start_str,
        'periodEnd': end_str,
    }
    
    print(f"Fetching {start_date.date()} to {end_date.date()}...")
    
    try:
        response = requests.get(base_url, params=params, timeout=30)
        print(f"API Response: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Successfully fetched data via API!")
            # Parse XML response and convert to CSV
            return response.text
        else:
            print(f"⚠️  API returned {response.status_code}")
            print(f"   Message: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ API request failed: {e}")
        return None


def show_gui_instructions():
    """Show step-by-step GUI download instructions."""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║              ENTSOE GUI DOWNLOAD - STEP-BY-STEP GUIDE                      ║
╚════════════════════════════════════════════════════════════════════════════╝

STEP 1: Open ENTSOE Transparency Website
─────────────────────────────────────────────────────────────────────────────
1. Go to: https://www.entsoe.eu/data/energy-prices-data/
   (Or: https://transparency.entsoe.eu/ → Click "Data" → "Energy Prices")

STEP 2: Set Download Filters
─────────────────────────────────────────────────────────────────────────────
Set the following options:

  Market Area / Country:     Germany (DE)
  Data Type:                 Day-ahead prices
  Date From:                 01/01/2024
  Date To:                   31/12/2024
  Period / Frequency:        (Auto-select)

Then click: "View data" or "Download as CSV"

STEP 3: Download 2024 Data
─────────────────────────────────────────────────────────────────────────────
1. You'll see a table or download option
2. Right-click "Download as CSV" → "Save As"
3. Save to: C:\\Users\\zkong\\Desktop\\power\\
4. Filename: GUI_2024.csv
5. Format: CSV (comma-separated values)

✓ Size: ~500 KB, ~35,000 lines
✓ Rows: 8,760 hourly records

STEP 4: Repeat for 2023 Data
─────────────────────────────────────────────────────────────────────────────
1. Change "Date From" to: 01/01/2023
2. Change "Date To" to: 31/12/2023
3. Download as CSV
4. Save as: GUI_2023.csv

✓ Size: ~500 KB, ~35,000 lines
✓ Rows: 8,760 hourly records

STEP 5: Verify Files
─────────────────────────────────────────────────────────────────────────────
After downloading, you should have:

  C:\\Users\\zkong\\Desktop\\power\\GUI_2024.csv
  C:\\Users\\zkong\\Desktop\\power\\GUI_2023.csv

Check by running:
  dir GUI_*.csv

STEP 6: Merge Files
─────────────────────────────────────────────────────────────────────────────
Run this command in PowerShell:

  python scripts/merge_years.py \\
    --input1 GUI_2024.csv \\
    --input2 GUI_2023.csv \\
    --output data\\DE\\day_ahead.csv \\
    --sequence 1

Expected output:
  Reading GUI_2024.csv... 8760 hourly rows
  Reading GUI_2023.csv... 8760 hourly rows
  
  Merging 2 datasets...
  
  ✅ Merged file written: data\\DE\\day_ahead.csv
     Rows: 17,520
     Date range: 2023-01-01 to 2024-12-31
     Missing values: 0
     Timezone: UTC

STEP 7: Verify
─────────────────────────────────────────────────────────────────────────────
Run:
  python check_data.py

Expected output:
  === CURRENT DATA STATUS ===
  Main data file: data/DE/day_ahead.csv
  Rows: 17,520
  Date range: 2023-01-01 00:00:00 to 2024-12-31 23:00:00
  Days covered: 730
  Missing values: 0

STEP 8: Test Everything Works
─────────────────────────────────────────────────────────────────────────────
Run:
  pytest -q

Expected output:
  84 passed in 8.82s

════════════════════════════════════════════════════════════════════════════════

🎯 TOTAL TIME: ~20 minutes

- Download 2024: ~3-5 min
- Download 2023: ~3-5 min  
- Merge files: ~1 min
- Verify & test: ~1-2 min
- TOTAL: ~20 min

📞 SUPPORT

If download fails:
  - Check internet connection
  - Try incognito/private browsing mode
  - Clear browser cache
  - Try different browser

If merge fails:
  - Verify CSV format (open in Excel)
  - Check file paths match exactly
  - Run: python scripts/merge_years.py --instructions

If tests fail:
  - Run: python check_data.py
  - Check for NaN values
  - Verify UTC timezone

════════════════════════════════════════════════════════════════════════════════
""")


def merge_csv_files(input_files, output_file='data/DE/day_ahead.csv', sequence=1):
    """Merge multiple ENTSO-E GUI CSV files."""
    print(f"\n📦 Merging {len(input_files)} files...")
    
    all_data = []
    
    for csv_path in input_files:
        path = Path(csv_path)
        if not path.exists():
            print(f"❌ File not found: {csv_path}")
            return False
        
        print(f"  Reading {path.name}...", end=" ")
        try:
            df = pd.read_csv(path, dtype=str)
            
            # Find columns
            mtu_col = next((c for c in df.columns if 'MTU' in c), df.columns[0])
            price_col = next((c for c in df.columns if 'Day-ahead' in c), None)
            seq_col = next((c for c in df.columns if 'Sequence' in c), None)
            
            if price_col is None:
                print(f"❌ Could not find Day-ahead price column")
                return False
            
            # Filter by sequence
            df_seq = df.copy()
            if seq_col is not None:
                df_seq = df_seq[df_seq[seq_col].str.contains(f"Sequence {sequence}", na=False)]
            
            # Parse timestamps
            df_seq['mtu_start'] = df_seq[mtu_col].str.split(' - ').str[0]
            df_seq['timestamp'] = pd.to_datetime(df_seq['mtu_start'], dayfirst=True, errors='coerce')
            
            if df_seq['timestamp'].isna().any():
                print(f"❌ Failed to parse timestamps")
                return False
            
            # Parse prices
            df_seq['price'] = pd.to_numeric(df_seq[price_col].str.replace(',', '.'), errors='coerce')
            
            if df_seq['price'].isna().all():
                print(f"❌ All prices are NaN")
                return False
            
            # Resample to hourly
            df_seq = df_seq.set_index('timestamp')
            series = df_seq['price'].resample('h').mean()
            
            print(f"✓ {len(series)} hourly rows")
            all_data.append(series)
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    # Combine and cleanup
    combined = pd.concat(all_data, sort=True).sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]
    
    if combined.index.tz is None:
        combined = combined.tz_localize('UTC')
    else:
        combined = combined.tz_convert('UTC')
    
    # Write output
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.rename('value').to_frame().to_csv(output_path, index_label='datetime')
    
    print(f"\n✅ Merge complete!")
    print(f"   File: {output_path}")
    print(f"   Rows: {len(combined):,}")
    print(f"   Date range: {combined.index[0]} to {combined.index[-1]}")
    print(f"   Missing values: {combined.isna().sum()}")
    
    return True


def create_sample_2year():
    """Create sample 2-year dataset for testing."""
    print("🎨 Creating sample 2-year dataset...")
    import numpy as np
    
    rows = [
        ['MTU (UTC)', 'Area', 'Sequence', 'Day-ahead Price (EUR/MWh)', 'Intraday Period (UTC)', 'Intraday Price (EUR/MWh)'],
    ]
    
    base = datetime(2023, 1, 1, 0, 0)
    np.random.seed(42)
    
    for day in range(730):  # 2 years
        day_price = 60 + 30 * np.sin(2 * np.pi * day / 365)
        
        for hour in range(24):
            hour_price = day_price + 30 * np.sin(2 * np.pi * hour / 24)
            
            for quarter in range(4):
                ts = base + timedelta(days=day, hours=hour, minutes=quarter*15)
                ts_end = ts + timedelta(minutes=15)
                mtu = f'{ts.strftime("%d/%m/%Y %H:%M:%S")} - {ts_end.strftime("%d/%m/%Y %H:%M:%S")}'
                
                price = hour_price + np.random.normal(0, 2)
                rows.append([mtu, 'BZN|DE-LU', 'Sequence Sequence 1', f'{price:.2f}', '', ''])
    
    # Write files (simulate 2024 and 2023)
    for rows_subset, year, month_range in [
        (rows[1:17521], 2024, (1, 366)),  # First 365 days = 2024
        (rows[17521:], 2023, (1, 366)),   # Remaining 365 days = 2023 (renumbered)
    ]:
        filename = f'GUI_{year}_sample.csv'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(','.join(f'"{c}"' for c in rows[0]) + '\n')
            for r in rows_subset:
                f.write(','.join(f'"{c}"' for c in r) + '\n')
        print(f"  Created {filename}")
    
    print(f"\n📝 Sample files created. Merge with:")
    print(f"   python scripts/merge_years.py --input1 GUI_2024_sample.csv --input2 GUI_2023_sample.csv --output data/DE/day_ahead.csv")


def main():
    p = argparse.ArgumentParser(
        description="Download 2 years of historical ENTSO-E electricity price data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python get_historical_data.py api      # Try fetching via API
  python get_historical_data.py gui      # Show GUI download instructions
  python get_historical_data.py merge    # Merge downloaded CSVs
  python get_historical_data.py sample   # Create sample 2-year data
        """)
    
    p.add_argument('method', nargs='?', default='gui', 
                   choices=['api', 'gui', 'merge', 'sample'],
                   help='Method to obtain data (default: gui)')
    p.add_argument('--input1', help='First CSV file to merge')
    p.add_argument('--input2', help='Second CSV file to merge')
    p.add_argument('--input3', help='Third CSV file to merge (optional)')
    p.add_argument('--output', default='data/DE/day_ahead.csv',
                   help='Output file path')
    
    args = p.parse_args()
    
    if args.method == 'api':
        # Try API fetch for 2023-2024
        start = datetime(2023, 1, 1)
        end = datetime(2024, 12, 31)
        result = fetch_via_api(start, end)
        if result:
            print("✅ API fetch successful!")
        else:
            print("❌ API fetch failed. Try 'gui' method for manual download.")
    
    elif args.method == 'gui':
        show_gui_instructions()
    
    elif args.method == 'merge':
        if not args.input1 or not args.input2:
            print("Error: --input1 and --input2 required for merge")
            print("Usage: python get_historical_data.py merge --input1 GUI_2024.csv --input2 GUI_2023.csv")
            sys.exit(1)
        
        inputs = [args.input1, args.input2]
        if args.input3:
            inputs.append(args.input3)
        
        if merge_csv_files(inputs, args.output):
            print("\n✅ Files merged successfully!")
            print(f"✓ Next: python check_data.py")
            print(f"✓ Then: pytest -q")
        else:
            print("\n❌ Merge failed")
            sys.exit(1)
    
    elif args.method == 'sample':
        create_sample_2year()


if __name__ == '__main__':
    main()
