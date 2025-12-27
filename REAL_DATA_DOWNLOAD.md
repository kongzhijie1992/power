# Real Data Download / Refresh

## Overview
You already have real ENTSO-E prices through 2025-12-16 (25,944 rows in `data/DE_LU/day_ahead.csv`) with matching weather and load. Use this guide to refresh via API or rebuild via GUI.

**Time Required:** 2–5 minutes (API) or ~15–20 minutes (GUI fallback)  
**Difficulty:** Easy

## Recommended: API Refresh (chunked)

```bash
python scripts/fetch_entsoe_data.py ^
  --areas DE_LU FR IT ES NL BE ^
  --start-date 2023-01-01 --end-date 2025-12-31 ^
  --chunk-days 60 --merge-existing
```

What happens:
- Downloads price data per area into `data/<AREA>/day_ahead_real.csv`
- Downloads weather into `data/weather/<AREA>_weather.csv`
- Dedupes timestamps and merges with existing files
- Keeps everything UTC and DST-safe

Afterwards:
```bash
python check_data.py
.venv\Scripts\pytest -q   # 87 tests
```

## GUI Fallback (if token unavailable)

1️⃣ **Download** from https://www.entsoe.eu/data/energy-prices-data/  
   - Area: Germany (DE)  
   - Data type: Day-ahead prices  
   - Periods: 2024 full year → `GUI_2024.csv`, 2023 full year → `GUI_2023.csv`

2️⃣ **Merge**  
```powershell
python scripts/merge_years.py ^
  --input1 GUI_2024.csv ^
  --input2 GUI_2023.csv ^
  --output data\DE_LU\day_ahead.csv ^
  --sequence 1
```

3️⃣ **Verify**  
```powershell
python check_data.py
.venv\Scripts\pytest -q
```

Expected after merge: ~17,520 rows, UTC, 0 missing values.

## Multi-Area Snapshot (current API pulls)
- DE_LU: 25,944 rows (2022-12-31 → 2025-12-16)
- FR: 25,509 rows (2022-12-31 → 2025-12-12)
- IT: 25,052 rows (2022-12-31 → 2025-12-12)
- ES: 24,104 rows (2022-12-31 → 2025-12-12)
- NL: 25,724 rows (2022-12-31 → 2025-12-12)
- BE: 25,789 rows (2022-12-31 → 2025-12-12)
(Full list: `python scripts/summarize_datasets.py`)

## Troubleshooting
- **HTTP 400 on API:** Use `--chunk-days 60` and confirm token in `.env`.
- **Missing GUI files:** Ensure CSVs are in the repo root; rerun `dir GUI_*.csv`.
- **Parse errors:** Re-download; keep one year per file.
- **Tests failing:** `python check_data.py` then `pytest tests/test_dst_handling.py -v`.

## Quick Commands
```bash
python scripts/fetch_entsoe_data.py --area DE_LU --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing
python check_data.py
python scripts/summarize_datasets.py
.venv\Scripts\pytest -q
```

## Support
- API help: `python scripts/diagnose_entsoe.py`
- GUI merge help: `python scripts/merge_years.py --instructions`
- Full context: `HISTORICAL_DATA_STATUS.md`

**Result:** Production-ready, real ENTSO-E dataset kept current with one command. ✅
