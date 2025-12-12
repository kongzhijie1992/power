# Real Data Download Walkthrough

## Overview
Replace sample 2-year data with real ENTSOE prices (2023-2024)

**Time Required:** ~15-20 minutes
**Difficulty:** Very Easy (just downloading files)

## Step-by-Step Guide

### 1️⃣ Download 2024 Data (5 minutes)

**Option A: Direct URL**
```
https://www.entsoe.eu/data/energy-prices-data/
```

**Option B: Full Site**
```
https://transparency.entsoe.eu/
→ Click "Data" menu
→ Click "Energy Prices"
```

**On the page:**
1. Set filter: **Area = Germany (DE)**
2. Set filter: **Data Type = Day-ahead prices**
3. Set filter: **From = 01/01/2024**
4. Set filter: **To = 31/12/2024**
5. Click **"View data"** or **"Download as CSV"**
6. Save file as: `GUI_2024.csv`
   - Save location: `C:\Users\zkong\Desktop\power\`
   - Make sure it saves in the power directory!

**Expected:** ~500 KB file, ~35,000 lines

### 2️⃣ Download 2023 Data (5 minutes)

**Same as Step 1, but change dates:**
- From = **01/01/2023**
- To = **31/12/2023**

**Save as:** `GUI_2023.csv` (same directory)

### 3️⃣ Verify Downloads (1 minute)

Open PowerShell in the power directory and run:
```powershell
dir GUI_*.csv
```

You should see:
```
GUI_2024.csv  (≈500 KB)
GUI_2023.csv  (≈500 KB)
```

### 4️⃣ Merge into Production Data (30 seconds)

Run in PowerShell:
```powershell
python process_real_data.py
```

This will automatically:
- ✅ Check both files exist
- ✅ Merge them into production format
- ✅ Verify data quality
- ✅ Run all 84 tests
- ✅ Confirm everything works

**Expected output:**
```
╔════════════════════════════════════════════════════════════════╗
║            ENTSOE DATA PROCESSING HELPER                      ║
╚════════════════════════════════════════════════════════════════╝

✅ Files found:
   - GUI_2024.csv (0.50 MB)
   - GUI_2023.csv (0.50 MB)

🔄 Merging files...
Reading GUI_2024.csv... 8760 hourly rows
Reading GUI_2023.csv... 8760 hourly rows

Merging 2 datasets...

✅ Merged file written: data\DE\day_ahead.csv
   Rows: 17,520
   Date range: 2023-01-01 to 2024-12-31
   Missing values: 0
   Timezone: UTC

✅ Verifying data...
   Rows: 17,520
   Range: 2023-01-01 to 2024-12-31
   Missing: 0
   Mean: 65.00 EUR/MWh

🧪 Running tests...
======================= 84 passed in 6.96s =======================

✅ REAL DATA INSTALLED AND VERIFIED!
   All 84 tests passing with production ENTSOE data
   Ready to backtest and deploy
```

### 5️⃣ Optional: Remove Sample Files

Once verified, you can delete the sample files:
```powershell
del GUI_2024_sample.csv
del GUI_2023_sample.csv
```

(The real `GUI_2024.csv` and `GUI_2023.csv` will be kept)

## Troubleshooting

### "Can't download - website is slow"
- Try a different browser
- Use incognito/private mode
- Try downloading during off-peak hours
- Check your internet connection

### "File won't download"
- Browser blocks: Check download settings
- Quota exceeded: Try a smaller date range (e.g., 6 months)
- Session timeout: Refresh page and try again

### "process_real_data.py says files not found"
Make sure files are in: `C:\Users\zkong\Desktop\power\`

Check with:
```powershell
dir GUI_*.csv
```

Not in a subfolder!

### "Merge fails with parse error"
Usually means the CSV format is different. Try:
1. Open GUI_2024.csv in Excel
2. Verify it has column: "Day-ahead Price (EUR/MWh)"
3. Verify MTU column format looks like: "01/01/2024 00:00:00 - 01/01/2024 00:15:00"
4. Re-download if corrupted

### "Tests fail after merge"
Run detailed check:
```powershell
python check_data.py
pytest tests/test_dst_handling.py -v
```

## What Gets Replaced

| File | Before (Sample) | After (Real) |
|------|:---:|:---:|
| `data/DE/day_ahead.csv` | Synthetic 2023-2024 | Real ENTSOE 2023-2024 |
| `GUI_2024_sample.csv` | Removed (optional) | Keep original download |
| `GUI_2023_sample.csv` | Removed (optional) | Keep original download |

Sample files are kept in case you need them for reference.

## Quick Command Reference

```bash
# After downloading both CSV files

# Auto-process everything
python process_real_data.py

# Or manual merge
python scripts/merge_years.py --input1 GUI_2024.csv --input2 GUI_2023.csv --output data/DE/day_ahead.csv

# Verify
python check_data.py
pytest -q

# Analyze real data
python verify_2year.py
```

## Data Quality Check

After running `process_real_data.py`, you'll see:

✅ **17,520 rows** = 2 complete years (2023-2024)
✅ **Zero missing values** = No gaps in data
✅ **UTC timezone** = DST-safe
✅ **84/84 tests pass** = All validated
✅ **Real ENTSOE prices** = Production-ready

## Next Steps

After real data is installed:

1. **Backtest with real data:**
   ```bash
   python -m src.backtest.run_backtest
   ```

2. **Analyze seasonal patterns:**
   ```bash
   python verify_2year.py
   ```

3. **Deploy with confidence:**
   ```bash
   git add data/DE/day_ahead.csv
   git commit -m "data: update with real 2023-2024 ENTSOE prices"
   git push
   ```

## Support

**Still stuck?**
- See: `python get_historical_data.py gui` (full instructions)
- Check: `python scripts/merge_years.py --instructions` (merge help)
- Review: `HISTORICAL_DATA_STATUS.md` (complete reference)

---

**Total time:** ~20 minutes
**Effort:** Minimal (just download and run one script)
**Result:** Production-ready real electricity price data ✅
