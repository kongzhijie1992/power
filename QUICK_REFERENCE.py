#!/usr/bin/env python3
"""
POWER PROJECT QUICK REFERENCE CARD

Status: ✅ PRODUCTION-READY (87/87 tests passing)
"""

print(
    """
╔════════════════════════════════════════════════════════════════════════════╗
║                     POWER PROJECT - QUICK REFERENCE                       ║
╚════════════════════════════════════════════════════════════════════════════╝

📊 DATA STATUS
──────────────────────────────────────────────────────────────────────────────
Current:      ~3 years (25,944 hourly rows) in data/DE_LU/day_ahead.csv
Weather:      25,872 hourly rows in data/weather/DE_LU_weather.csv
Loads:        103,380 quarter-hour rows in data/DE_LU/load_real.csv
Areas:        30+ bidding zones populated via API (prices + weather; many loads)
Quality:      Zero missing values, UTC, DST-safe ✅

🧪 TESTING STATUS
──────────────────────────────────────────────────────────────────────────────
Total Tests:  87/87 passing ✅
Modules:      Backtesting, walk-forward leakage guards, dispatch/UC, price & demand forecasting, data I/O, DST, integration
DST Tests:    3/3 passing (Spring forward ✅, Fall back ✅, Conversion ✅)

🔄 QUICK COMMANDS
──────────────────────────────────────────────────────────────────────────────
Check data:           python check_data.py
Inventory (all areas): python scripts/summarize_datasets.py
Run all tests:        .venv\\Scripts\\pytest -q
Run DST tests:        .venv\\Scripts\\pytest tests/test_dst_handling.py -v
Refresh data (API):   python scripts/fetch_entsoe_data.py --areas DE_LU FR IT ES NL BE --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing
Backtest:             python -m src.models.backtest

📥 REFRESH DATA (API)
──────────────────────────────────────────────────────────────────────────────
python scripts/fetch_entsoe_data.py ^
  --areas DE_LU FR IT ES NL BE ^
  --start-date 2023-01-01 --end-date 2025-12-31 ^
  --chunk-days 60 --merge-existing

✅ Result: deduped price + weather files per area, UTC/DST-safe

📂 KEY FILES
──────────────────────────────────────────────────────────────────────────────
Documentation:
  DATA_STRATEGY.md            ← Requirements and plan
  DST_HANDLING.md             ← DST deep dive
  PROJECT_STATUS.md           ← Status snapshot
  REAL_DATA_DOWNLOAD.md       ← Refresh guide
  POWER_STACK_WORKFLOW.md     ← Pipeline overview

Scripts:
  scripts/fetch_entsoe_data.py ← Chunked API + weather (preferred)
  scripts/merge_years.py       ← Merge GUI CSVs (fallback)
  scripts/convert_entsoe.py    ← GUI CSV → hourly
  scripts/summarize_datasets.py← Multi-area inventory
  check_data.py                ← Data inventory check

Data:
  data/DE_LU/day_ahead.csv     ← Main price data (~3 years)
  data/weather/DE_LU_weather.csv← Weather (aligned)
  data/DE_LU/load_real.csv     ← Quarter-hour load

🔑 API TOKEN STATUS
──────────────────────────────────────────────────────────────────────────────
Token:       Stored in .env as ENTSOE_API_TOKEN (not committed)
Status:      Working with chunked calls
Next:        Schedule periodic refresh with --merge-existing

🎯 ROADMAP
──────────────────────────────────────────────────────────────────────────────
✅ Immediate:  Use existing 3y dataset for backtests/forecasts/UC
⚙️  Routine:   Run fetch_entsoe_data.py weekly to append new days
📦  Storage:   Convert large CSVs to Parquet for speed

💡 EXAMPLES
──────────────────────────────────────────────────────────────────────────────
# View current data
import pandas as pd
df = pd.read_csv('data/DE_LU/day_ahead.csv')
df['datetime'] = pd.to_datetime(df['datetime'])
print(len(df), df['value'].mean())

# Quick monthly averages
print(df.groupby(df['datetime'].dt.to_period('M'))['value'].mean().tail())

# Verify DST handling
.venv\\Scripts\\pytest tests/test_dst_handling.py -v

✨ PRODUCTION READINESS CHECKLIST
──────────────────────────────────────────────────────────────────────────────
✅ Unit tests: 87/87 passing
✅ Data quality: Zero missing values, UTC/DST-safe
✅ API integration: Chunked, merge-safe fetch working
✅ Documentation: Updated guides + workflow
✅ Scalability: 30+ areas populated; merge/convert scripts ready

════════════════════════════════════════════════════════════════════════════════
Last Updated: 2025-12-13
Python Version: 3.13.5
Test Framework: pytest 9.0.2
════════════════════════════════════════════════════════════════════════════════
"""
)
