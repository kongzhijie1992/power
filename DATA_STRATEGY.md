# Data Strategy: What We Have vs. What We Need

## Current Status

### Data Inventory
- **Price Data:** 346 days (8,304 hourly rows) covering Dec 2024 → Dec 2025
- **Weather Data:** 90 days (2,160 hourly rows)
- **Completeness:** ~95% of recommended minimum (1 year = 8,760 rows)

### Date Coverage
```
Price:   2024-12-31 23:00 to 2025-12-12 22:00  (346 days)
Weather: ~90 days recent data
```

## Data Requirements by Use Case

### 1. **Unit Testing** ✅ COVERED
- **Need:** Sample data, any size
- **Have:** 8,304 rows (way more than enough)
- **Status:** All 84 tests passing
- **Action:** None required

### 2. **Backtesting** ✅ ADEQUATE
- **Need:** 30-90 days minimum for model training
- **Have:** 346 days (3.8x the minimum)
- **Status:** Sufficient for validation
- **Action:** Can backtest immediately

### 3. **Production Forecasting** ⚠️ BORDERLINE
- **Need:** 1-2 years historical for robust training
- **Have:** 346 days (~40% of recommended)
- **Status:** Works but limited generalization
- **Action:** Recommended to expand to 1+ year

### 4. **Seasonal Analysis** ❌ INSUFFICIENT
- **Need:** 2+ years to capture seasonal patterns
- **Have:** 346 days (only 1.3 seasons)
- **Status:** Cannot detect year-on-year patterns
- **Action:** Download additional historical data

## How to Get More Data

### Option 1: ENTSO-E GUI Download (Easiest)
**Use when:** You need quick access to large date ranges

```bash
# Visit: https://www.entsoe.eu/data/energy-prices-data/
# Download CSV export (GUI_ENERGY_PRICES_*.csv)
# Then run converter:

python scripts/convert_entsoe.py \
  --input "GUI_ENERGY_PRICES_20240101000-20251212000 (1).csv" \
  --output data/DE/day_ahead.csv \
  --sequence 1 \
  --resample H \
  --tz UTC
```

**Pros:**
- Fast (bulk download)
- No authentication initially required
- Full date range control
- Easy to verify data quality visually

**Cons:**
- GUI sometimes slow for large ranges
- May need to split across multiple downloads
- File expires after session

### Option 2: ENTSO-E API (Best for Automation)
**Use when:** You want automated data pipeline

```bash
# Once token is activated (contact ENTSO-E support)

python scripts/fetch_entsoe_data.py
```

**Status:** Token stored in `.env` (17ad76be-f381...), but returns 400 errors (not yet activated)

**Pros:**
- Automated (no manual download)
- Programmatic date range control
- Live data integration
- Can be scheduled in CI/CD

**Cons:**
- Requires token activation (1-2 business days)
- API limits (data request scheduling)
- Rate limiting for large requests

**Next Steps:**
1. Contact ENTSO-E support: support@entsoe.eu
2. Request activation for:
   - Area codes: DE_LU, FR, IT, ES, NL, BE
   - Document type: A44 (Day-ahead prices)
3. Verify with: `python scripts/diagnose_entsoe.py`

### Option 3: Open-Meteo Weather (Free, No Auth)
**Current:** Already integrated, no action needed

```python
# Automatic fallback in fetch_entsoe_data.py
import requests
r = requests.get("https://archive-api.open-meteo.com/v1/archive?...")
```

## Recommended Data Plan

### Phase 1: Immediate (Today)
✅ **Use current 346 days for:**
- Unit test validation
- Basic backtesting
- Model development
- Testing the entire pipeline

**Command:**
```bash
pytest -q  # All tests pass with current data
```

### Phase 2: Short-term (This Week)
⚠️ **Expand to 1 year via GUI download:**
1. Visit https://www.entsoe.eu/data/energy-prices-data/
2. Download Jan 2024 → Dec 2024 (12 months)
3. Run converter:
   ```bash
   python scripts/convert_entsoe.py \
     --input "GUI_ENERGY_PRICES_20240101000-20241231000.csv" \
     --output data/DE/day_ahead.csv \
     --sequence 1 --resample H --tz UTC
   ```
4. Re-run backtests with full year

**Expected benefit:** Better seasonal patterns, more robust models

### Phase 3: Medium-term (API Integration)
✅ **Once token activated:**
```bash
# Automatic daily fetch via cron or GitHub Actions
python scripts/fetch_entsoe_data.py
```

### Phase 4: Long-term (2+ Years)
📈 **For production:**
- Maintain rolling window of 2+ years
- Archive older data in parquet format
- Use `incremental_ingest.py` for daily updates

## Quick Commands

### Check current data
```bash
python check_data.py
```

### View price statistics
```bash
python -c "
import pandas as pd
df = pd.read_csv('data/DE/day_ahead.csv')
print(df['value'].describe())
"
```

### Download latest year from GUI
```bash
# 1. Visit https://www.entsoe.eu/data/energy-prices-data/
# 2. Filter: Area=DE, Start=2024-01-01, End=2024-12-31
# 3. Export CSV
# 4. Run:
python scripts/convert_entsoe.py \
  --input "PATH/TO/GUI_DOWNLOAD.csv" \
  --output data/DE/day_ahead.csv \
  --sequence 1 --resample H --tz UTC
```

### Fetch via API (when activated)
```bash
python scripts/fetch_entsoe_data.py
```

### Run backtests with current data
```bash
pytest tests/test_backtesting.py -v
```

## Data Quality Checks

All ingestion runs automatic validation:
- ✅ No NaN values (current: 0 missing)
- ✅ Monotonic timestamps (no duplicates, no gaps)
- ✅ Realistic prices (range 20-200 EUR/MWh typically)
- ✅ DST transitions handled correctly

**Verify after new download:**
```bash
python check_data.py
```

## Summary Table

| Use Case | Min. Required | Currently Have | Status | Next Step |
|----------|:---:|:---:|:---:|---|
| Unit Testing | 1 day | 346 days | ✅ Ready | Run tests |
| Backtesting | 30 days | 346 days | ✅ Ready | Backtest now |
| Development | 90 days | 346 days | ✅ Ready | Develop models |
| Production | 1-2 years | 346 days | ⚠️ Borderline | Download 1 more year |
| Seasonal | 2+ years | 346 days | ❌ Insufficient | Download 2022-2024 |

**Conclusion:** You have enough data to **test and backtest now**. For production, download 1 more year of historical prices (quick ENTSO-E GUI download, ~15 min).

