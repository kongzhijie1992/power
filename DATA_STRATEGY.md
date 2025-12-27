# Data Strategy: What We Have vs. What We Need

## Current Status

### Data Inventory (as of 2025-12-13)
- **Price Data (primary):** 25,944 hourly rows in `data/DE_LU/day_ahead.csv`
- **Price Data (raw API):** 25,872 hourly rows in `data/DE_LU/day_ahead_real.csv`
- **Weather:** 25,872 hourly rows in `data/weather/DE_LU_weather.csv`
- **Loads:** 103,380 quarter-hourly rows in `data/DE_LU/load_real.csv`
- **Multi-area coverage:** 30+ bidding zones (DE_LU, FR, IT, ES, NL, BE, PT, CH, Nordics, Baltics, Balkans) all with price + weather; many also include load/TSO forecast
- **Tests:** 87/87 passing on current dataset

### Date Coverage
```
Price (main):   2022-12-31 23:00 → 2025-12-16 22:00  (~1,080 days, 3.0 years)
Price (raw):    2022-12-31 00:00 → 2025-12-12 23:00  (aligned to weather)
Weather:        2022-12-31 00:00 → 2025-12-12 23:00
Loads:          2023-01-01 00:00 → 2025-12-12 22:45 (15-min)
```

## Data Requirements by Use Case

### 1. **Unit Testing** ✅ COVERED
- **Need:** Sample data, any size
- **Have:** 25,944 rows (far above requirement)
- **Status:** All 87 tests passing
- **Action:** None required

### 2. **Backtesting** ✅ ROBUST
- **Need:** 30–90 days minimum
- **Have:** ~1,080 days (12x the minimum)
- **Status:** Strong coverage for CV/backtests
- **Action:** Use current set; optionally trim via rolling window

### 3. **Production Forecasting** ✅ READY
- **Need:** 1–2 years historical
- **Have:** ~3.0 years + weather + load for many areas
- **Status:** Above target; supports seasonal generalization
- **Action:** Keep updated via API; consider parquet snapshots for speed

### 4. **Seasonal Analysis** ✅ READY
- **Need:** 2+ years for YoY patterns
- **Have:** ~3.0 years
- **Status:** Year-on-year effects fully observable
- **Action:** Maintain rolling 3y window; archive older data if needed

## How to Maintain and Extend

### Preferred: ENTSO-E API (Chunked, Automated)
**Use when:** Refreshing or extending any area; avoids GUI throttling.

```bash
# Pull 2023-01-01 → 2025-12-31 for multiple areas, merge into existing files
python scripts/fetch_entsoe_data.py ^
  --areas DE_LU FR IT ES NL BE ^
  --start-date 2023-01-01 --end-date 2025-12-31 ^
  --chunk-days 90 --merge-existing
```

**Pros:** Automated, chunked to avoid 400s, writes `day_ahead_real.csv` + weather per area.

### GUI Download (Fallback)
**Use when:** API token unavailable.
1. Download CSV from https://www.entsoe.eu/data/energy-prices-data/
2. Convert/merge:
   ```bash
   python scripts/convert_entsoe.py --input GUI_2024.csv --output data/DE_LU/day_ahead.csv --sequence 1 --resample H --tz UTC
   python scripts/merge_years.py --input1 GUI_2024.csv --input2 GUI_2023.csv --output data/DE_LU/day_ahead.csv --sequence 1
   ```

### Weather (Open-Meteo, No Auth)
- Auto-downloaded by `scripts/fetch_entsoe_data.py` (hourly wind + solar proxies).
- Stored in `data/weather/<AREA>_weather.csv`.

## Recommended Data Plan

### Phase 1: Operate (Today)
✅ Use current ~3-year dataset for backtests, demand/price models, UC demos.  
Commands: `python check_data.py`, `.venv\Scripts\pytest -q`

### Phase 2: Keep Fresh (Nightly/Weekly)
✅ Run chunked API fetch with merge to append latest days:
```bash
python scripts/fetch_entsoe_data.py --areas DE_LU FR IT ES NL BE --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing
```

### Phase 3: Archive & Optimize
- Write Parquet snapshots for speed (`scripts/convert_prices_to_parquet.py`)
- Keep rolling 3y window; archive older years under `data/archive/`

### Phase 4: Enrich
- Add load forecasts/residual demand features (already supported in `src/models/demand_forecast.py`)
- Expand to more areas using the same fetch command

## Quick Commands

```bash
# Check primary dataset
python check_data.py

# Summarize all areas (price/weather/load coverage)
python scripts/summarize_datasets.py

# Refresh data via API (DE_LU example, weather included)
python scripts/fetch_entsoe_data.py --area DE_LU --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing

# Run tests/backtests
.venv\Scripts\pytest -q
python -m src.models.backtest
```

## Data Quality Checks

Current validations (all ✅):
- No NaNs or duplicate timestamps in price/weather/load
- UTC-normalized, DST-safe across 2023–2025 transitions
- Realistic price ranges; monotonic indices
- Tests: 87/87 passing on live data

Re-run after any update:
```bash
python check_data.py
.venv\Scripts\pytest -q
```

## Summary Table

| Use Case | Min. Required | Currently Have | Status | Next Step |
|----------|:---:|:---:|:---:|---|
| Unit Testing | 1 day | 1,080 days | ✅ Ready | None |
| Backtesting | 30 days | 1,080 days | ✅ Ready | Tune/train |
| Development | 90 days | 1,080 days | ✅ Ready | Feature work |
| Production | 1–2 years | ~3.0 years | ✅ Ready | Keep fresh via API |
| Seasonal | 2+ years | ~3.0 years | ✅ Ready | Maintain rolling window |

**Conclusion:** The project already has ~3 years of price + weather + load data across 30+ areas. Focus on keeping feeds fresh (API merge) and optimizing storage; no additional historical downloads are required right now.
