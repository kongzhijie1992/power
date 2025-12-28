# Quick Start: Refresh or Rebuild Multi-Year Data

## Overview
The project already has ~3 years of prices (2022-12-31 → 2025-12-16) plus matching weather. Use this guide only if you need to rebuild from GUI downloads or add new years.

## What You'll Get (if you rebuild)
- 2023 + 2024 (+ optional 2025) electricity prices
- UTC timezone-aware, DST-safe
- ~17,520 rows for 2 years; ~25,900 rows for 2023–2025
- Zero missing values after merge

## Fast Path: Use the API (recommended)
```bash
python scripts/fetch_entsoe_data.py ^
  --area DE_LU ^
  --start-date 2023-01-01 --end-date 2025-12-31 ^
  --chunk-days 60 --merge-existing
```
Result: Updates `data/DE_LU/day_ahead_real.csv` (raw) and `data/DE_LU/day_ahead.csv` (primary) with deduped timestamps; also fetches weather.

## GUI Steps (fallback)

### Step 1: Download 2024 (5 minutes)
1. Visit **https://www.entsoe.eu/data/energy-prices-data/**
2. Area **Germany/Luxembourg (DE_LU)**, Data type **Day-ahead prices**
3. Period: `01/01/2024 00:00` → `31/12/2024 23:45`
4. Save as `GUI_2024.csv`

### Step 2: Download 2023 (5 minutes)
1. Same page, Period: `01/01/2023 00:00` → `31/12/2023 23:45`
2. Save as `GUI_2023.csv`

### Step 3: Merge (1 minute)
```bash
python scripts/merge_years.py ^
  --input1 GUI_2024.csv ^
  --input2 GUI_2023.csv ^
  --output data\DE_LU\day_ahead.csv ^
  --sequence 1
```

Expected:
```
Rows: 17,520
Range: 2023-01-01 00:00 → 2024-12-31 23:00 (UTC)
Missing values: 0
```

### Step 4: Verify
```bash
python check_data.py
.venv\Scripts\pytest -q   # 87 tests
```

## Optional: Add 2025 YTD
```bash
python scripts/merge_years.py ^
  --input1 GUI_2025.csv --input2 GUI_2024.csv --input3 GUI_2023.csv ^
  --output data\DE_LU\day_ahead.csv --sequence 1
```
Result: ~25,900 rows (2022-12-31/2023-01-01 → 2025-12-12/16).

## Troubleshooting

- **Input file not found:** Ensure CSVs are in the repo root and names match.
- **No price column:** Confirm you downloaded Day-ahead prices, not load.
- **Parse errors:** Re-download; keep period within a single year per file.
- **Tests fail after merge:** Run `python check_data.py` then `pytest tests/test_dst_handling.py -v`.

## Quick Checks

```bash
python check_data.py                  # row counts, ranges
python scripts/summarize_datasets.py  # multi-area coverage
.venv\Scripts\pytest -q               # 87/87 passing
```

## Support
- Download guide: https://www.entsoe.eu/data/energy-prices-data/
- API docs: https://web-api.tp.entsoe.eu/api
- Script help: `python scripts/merge_years.py --instructions`

**Total time (GUI path):** ~20 minutes  
**Result:** Production-ready multi-year dataset ✅
