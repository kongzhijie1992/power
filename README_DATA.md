# Data Download Status & Recommendations

## Quick Answer: ✅ Ready with ~3 Years of Real Data

All runtime data is stored in S3. Paths like `data/<AREA>/...` are logical and
resolve to `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/...` when the S3 env vars are set.
Local `data/` is no longer used for runtime storage.

**Current Inventory (DE_LU primary):**
- Prices: 25,944 hourly rows (`s3://$S3_BUCKET/$S3_PREFIX/DE_LU/day_ahead.csv`, 2022-12-31 → 2025-12-16)
- Weather: 25,872 hourly rows (`s3://$S3_BUCKET/$S3_PREFIX/weather/DE_LU_weather.csv`, aligned to 2025-12-12)
- Loads: 103,380 quarter-hour rows (`s3://$S3_BUCKET/$S3_PREFIX/DE_LU/load_real.csv`)
- Multi-area: 30+ bidding zones with price + weather; many with load forecasts too
- Tests: 87/87 passing on this dataset

## What You Can Do Right Now

- ✅ Test & validate: `.venv\Scripts\pytest -q`
- ✅ Backtest models: `python -m src.models.backtest`
- ✅ Train price + demand models with weather/load: use `scripts/run_demand_forecast.py` or `scripts/run_forecast_with_gfs.py`
- ✅ Run UC/dispatch demos: `python scripts/run_uc_demo.py`, `python scripts/run_full_pipeline.py`

## Do We Need More Data?

| Use Case | Have | Need | Status |
|----------|:---:|:---:|:---:|
| Unit Tests | 1,080 days | 1 day | ✅ |
| Backtesting | 1,080 days | 30–90 days | ✅ |
| Model Dev | 1,080 days | 90+ days | ✅ |
| Production | 1–2 years | 1,080 days | ✅ |
| Seasonal | 2+ years | 1,080 days | ✅ |

No additional historical download is required. Focus on keeping data fresh.

## How to Refresh / Extend

### API (Preferred, Automated)
```bash
python scripts/fetch_entsoe_data.py ^
  --areas DE_LU FR IT ES NL BE ^
  --start-date 2023-01-01 --end-date 2025-12-31 ^
  --chunk-days 60 --merge-existing
```
Writes `day_ahead_real.csv` + `weather/<AREA>_weather.csv` and merges safely.

### GUI (Fallback)
```bash
python scripts/convert_entsoe.py --input GUI_2024.csv --output data/DE_LU/day_ahead.csv --sequence 1 --resample H --tz UTC
python scripts/merge_years.py --input1 GUI_2024.csv --input2 GUI_2023.csv --output data/DE_LU/day_ahead.csv --sequence 1
```

## Data Sources

| Source | Data | Status | Access |
|--------|:---:|:---:|---|
| ENTSO-E API | Day-ahead prices | ✅ Working via chunked fetch | `scripts/fetch_entsoe_data.py` |
| Open-Meteo | Weather | ✅ Working | Auto-called by fetch script |
| CSV Import | Custom data | ✅ | `scripts/convert_entsoe.py`, `scripts/merge_years.py` |

## Storage & Organization (key files)

```
s3://$S3_BUCKET/$S3_PREFIX/
├── DE_LU/day_ahead.csv         # main price series (25,944 rows)
├── DE_LU/day_ahead_real.csv    # raw API pull (25,872 rows)
├── DE_LU/load_real.csv         # quarter-hour load
└── weather/DE_LU_weather.csv   # hourly weather
```
Use `scripts/summarize_datasets.py` to see coverage for all areas.

## Recommended Actions

- Today: Run `.venv\Scripts\pytest -q` and `python check_data.py` (should stay green).
- Weekly: Refresh via API with `--merge-existing` to append the newest week.
- Monthly: Convert to Parquet for speed (`scripts/convert_prices_to_parquet.py`).
- Ongoing: Keep `.env` token valid; monitor ENTSO-E rate limits with `scripts/diagnose_entsoe.py`.

## Data Quality Verification

```bash
python check_data.py                 # row counts, date ranges, NaN check
python scripts/summarize_datasets.py # multi-area inventory
.venv\Scripts\pytest -q              # 87/87 tests
```

## File Reference

| File | Purpose |
|------|---------|
| DATA_STRATEGY.md | Requirements and plan |
| DST_HANDLING.md | DST details and tests |
| scripts/fetch_entsoe_data.py | Chunked API + weather |
| scripts/convert_entsoe.py | GUI CSV converter |
| scripts/merge_years.py | Merge multi-year CSVs |
| scripts/summarize_datasets.py | Multi-area coverage report |
| check_data.py | Quick inventory |

## Summary

You already have a production-quality, DST-safe, 3-year dataset with price, weather, and load across 30+ zones. Keep it fresh with the API fetch script; no further historical downloads are needed unless you want a longer archive.
