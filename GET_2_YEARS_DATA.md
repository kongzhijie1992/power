# Quick Start: Get 2 Years of Data (20 Minutes)

## Overview
Expand from 1 year (~346 days) to **2 full years (~17,500 hourly rows)** for production-grade analysis.

## What You'll Get
- 2023 + 2024 complete electricity prices
- UTC timezone-aware, DST-safe
- ~17,520 hourly rows = 730 days
- Zero missing values
- Ready for seasonal analysis & robust modeling

## Steps

### Step 1: Download 2024 Data (5 minutes)
1. Go to: **https://www.entsoe.eu/data/energy-prices-data/**
2. Select:
   - **Area:** Germany (DE)
   - **Data type:** Day-ahead prices  
   - **Period:** `01/01/2024 00:00` to `31/12/2024 23:45`
3. Click **Download as CSV**
4. Save as: `GUI_2024.csv`

### Step 2: Download 2023 Data (5 minutes)
1. Same page, change **Period** to: `01/01/2023 00:00` to `31/12/2023 23:45`
2. Click **Download as CSV**
3. Save as: `GUI_2023.csv`

### Step 3: Merge Files (1 minute)
```bash
cd C:\Users\zkong\Desktop\power

python scripts/merge_years.py \
  --input1 GUI_2024.csv \
  --input2 GUI_2023.csv \
  --output data\DE\day_ahead.csv \
  --sequence 1
```

**Expected output:**
```
Reading GUI_2024.csv... 8760 hourly rows
Reading GUI_2023.csv... 8760 hourly rows

Merging 2 datasets...

✅ Merged file written: data\DE\day_ahead.csv
   Rows: 17,520
   Date range: 2023-01-01 00:00:00+00:00 to 2024-12-31 23:00:00+00:00
   Missing values: 0
   Timezone: UTC
```

### Step 4: Verify (1 minute)
```bash
python check_data.py
```

You should see:
```
=== CURRENT DATA STATUS ===
Main data file: data/DE/day_ahead.csv
Rows: 17,520
Date range: 2023-01-01 00:00:00 to 2024-12-31 23:00:00
Days covered: 730
Missing values: 0
```

### Step 5: Test Everything Still Works (2 minutes)
```bash
pytest -q
```

All 84 tests should pass with the new 2-year dataset.

## Optional: Add 2025 Year-to-Date (3 minutes)

If you want to include 2025 data (Jan 1 - Dec 12, 2025):

```bash
# Download 2025 from ENTSO-E GUI (same URL, period: 01/01/2025 to 12/12/2025)
# Save as: GUI_2025.csv

python scripts/merge_years.py \
  --input1 GUI_2025.csv \
  --input2 GUI_2024.csv \
  --input3 GUI_2023.csv \
  --output data\DE\day_ahead.csv \
  --sequence 1
```

Result: **2.95 years** (~25,800 rows) for comprehensive seasonal analysis.

## What Each Download Includes

| Year | Rows | Coverage | File Size |
|------|:---:|:---:|:---:|
| 2024 | 8,760 | Full year | ~500 KB |
| 2023 | 8,760 | Full year | ~500 KB |
| 2025 YTD | 8,100 | Jan-Dec 12 | ~450 KB |

## Advanced: Automate with Script

Once you have the CSV files downloaded:

```python
# Python script example
from pathlib import Path
import subprocess
import sys

files = {
    'GUI_2024.csv': 'https://www.entsoe.eu/...',  # (manual download)
    'GUI_2023.csv': 'https://www.entsoe.eu/...',  # (manual download)
}

# After manual downloads, merge:
subprocess.run([
    sys.executable, 'scripts/merge_years.py',
    '--input1', 'GUI_2024.csv',
    '--input2', 'GUI_2023.csv',
    '--output', 'data/DE/day_ahead.csv',
    '--sequence', '1'
])
```

## Troubleshooting

### "Input file not found"
- Make sure CSV files are in your current directory
- Check file names match exactly (case-sensitive on Linux)

### "Could not find Day-ahead price column"
- Verify you downloaded the correct data type (Day-ahead prices, not Load)
- Check the CSV file opens in Excel correctly

### "Failed to parse MTU timestamps"
- Ensure CSV is not corrupted
- Re-download from ENTSO-E if needed

### After merge, tests fail
- Run `python check_data.py` to verify
- Check for NaN values: `pandas` should show 0
- Run `pytest tests/test_dst_handling.py -v` to verify DST handling

## FAQ

**Q: Can I download just one year?**
A: Yes, use `--input1` only, or use the original `scripts/convert_entsoe.py`

**Q: What if I want different areas (FR, IT, ES)?**
A: Download for each area, then merge separately or modify script to handle multiple areas

**Q: Can I update this monthly?**
A: Yes, once ENTSO-E API token is activated, use `scripts/fetch_entsoe_data.py` for automatic updates

**Q: How long does download take?**
A: ~2 minutes per year file (depends on internet speed)

**Q: Can I use other sequences (Sequence 2)?**
A: Yes, use `--sequence 2` flag in merge script

## Next Steps

After merging 2 years of data:

1. **Run backtests with more data:**
   ```bash
   pytest tests/test_backtesting.py -v
   ```

2. **Analyze seasonal patterns:**
   ```python
   import pandas as pd
   df = pd.read_csv('data/DE/day_ahead.csv')
   df.groupby(df['datetime'].dt.month)['value'].mean()
   ```

3. **Train models on 2 years:**
   ```bash
   python -m src.backtest.run_backtest
   ```

4. **Set up automation (future):**
   - Once API token is activated, configure `scripts/fetch_entsoe_data.py` to run daily
   - Store in GitHub Actions or local cron job

## Support

- Download guide: https://www.entsoe.eu/data/energy-prices-data/
- API docs: https://transparency.entsoe.eu/
- Script help: `python scripts/merge_years.py --instructions`

---

**Total time commitment:** ~20 minutes hands-on
**Result:** Production-ready 2-year dataset ✅
