Power Stack Model — Europe (ENTSO-E + GFS + UC)
================================================

Overview
--------
A production-oriented prototype for European power-stack analysis with:

- Day-ahead price and demand forecasting (hourly, up to 7 days) using LightGBM ensembles with weather/load features
- Walk-forward backtesting, leakage-safe evaluation, and probabilistic quantiles
- Simplified dispatch and unit commitment (PuLP/CBC; upgradeable to commercial solvers)
- ENTSO-E + Open-Meteo ingestion (chunked API, multi-area) with DST-safe UTC handling

S3-Only Storage
---------------
All data lives in S3. Paths like `data/<AREA>/...` are logical and resolve to
`s3://$S3_BUCKET/$S3_PREFIX/<AREA>/...` when the S3 env vars are set. The local
`data/` folder is no longer used for runtime storage.

Current Data & Tests
--------------------
- Prices: 25,944 rows (UTC) in `s3://$S3_BUCKET/$S3_PREFIX/DE_LU/day_ahead.csv` covering 2022-12-31 → 2025-12-16
- Weather: 25,872 rows in `s3://$S3_BUCKET/$S3_PREFIX/weather/DE_LU_weather.csv` (aligned)
- Loads: 103,380 quarter-hour rows in `s3://$S3_BUCKET/$S3_PREFIX/DE_LU/load_real.csv`
- Multi-area: 30+ bidding zones populated (prices + weather; many with load)
- Tests: 87/87 passing (`.venv\Scripts\pytest -q`)
- Quick checks: `python check_data.py`, `python scripts/summarize_datasets.py`

Power Stack Workflow
--------------------
1. **Data ingest**  
   - Prices via ENTSO-E API (chunked) → `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/day_ahead_real.csv` (`scripts/fetch_entsoe_data.py`)  
   - GUI fallback → `scripts/convert_entsoe.py` + `scripts/merge_years.py`  
   - Persisted primary series → `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/day_ahead.csv`
2. **Weather ingest**  
   - Open-Meteo archive via fetch script (hourly wind/solar) → `s3://$S3_BUCKET/$S3_PREFIX/weather/<AREA>_weather.csv`
3. **Feature engineering**  
   - Price lags/rolling/calendar: `src/models/forecast.py`, `src/models/price_model.py`  
   - Weather features / proxies: `src/features/weather_features.py`  
   - Demand features (calendar, weather, ramps, lags): `src/models/demand_forecast.py`
4. **Modeling**  
   - Price: LightGBM regression + quantiles (`src/models/price_model.py`, `src/models/forecast_cv.py`)  
   - Demand: GradientBoosting/LightGBM per-hour models with quantiles (`src/models/demand_forecast.py`)  
   - Fallback seasonal-naive when ML unavailable
5. **Backtesting & evaluation**  
   - Time-series CV + walk-forward (`src/models/backtest.py`, `src/models/forecast_cv.py`)  
   - Leakage-safe walk-forward predictions (`test_walk_forward_predict_no_leakage`)
6. **Forecast generation**  
   - Hourly recursive forecasts with optional weather (`src/models/price_model.py`)  
   - Probabilistic outputs (0.1/0.5/0.9)
7. **Dispatch & UC**  
   - Merit-order clearing (`src/dispatch/merit_order.py`)  
   - Zonal dispatch from generation mix (`src/dispatch/zonal_dispatch.py`)  
   - Unit commitment with startup/shutdown, ramps, min up/down (`src/dispatch/unit_commitment.py`)
8. **Outputs & reporting**  
   - Parquet/CSV helpers (`src/data/io.py`)  
   - Forecast evaluation (`scripts/evaluate_price_forecast.py`)  
   - Streamlit dashboard (`scripts/streamlit_dashboard.py`)

Quickstart (poetry)
-------------------
1. Install dependencies:

```bash
poetry install
poetry add pulp lightgbm scikit-learn pyarrow
```

2. Verify data and tests (uses existing DE_LU dataset):

```bash
python check_data.py
.venv\Scripts\pytest -q
```

3. Run an end-to-end demo:

```bash
python scripts\run_forecast_with_gfs.py --area DE_LU      # price forecast + backtest + weather features
python scripts\run_full_pipeline.py --area DE_LU --synthetic  # synthetic end-to-end (no API needed)
python scripts\run_uc_demo.py                             # unit commitment example
```

4. Refresh or extend real data (optional):

```bash
python scripts\fetch_entsoe_data.py --areas DE_LU FR IT ES NL BE --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing
```

Sample data (optional)
----------------------
Real data is already present; generate synthetic only if you want a minimal sandbox:

```powershell
python scripts\fetch_sample_data.py --area DE_LU --days 90
python scripts\run_full_pipeline.py --area DE_LU --synthetic
```

What you get
------------

### Forecasting & Demand
- `src/models/forecast_cv.py` — LightGBM ensemble with weather features + CV
- `src/models/price_model.py` — Recursive price forecaster with calendar/weather/holiday features
- `src/models/demand_forecast.py` — Demand + quantile models with load/weather features
- `src/models/forecast.py` — Baseline features + seasonal-naive fallback
- `src/models/backtest.py` — Walk-forward backtests + leakage-safe predict

### Features & Weather
- `src/features/weather_features.py` — GFS/Open-Meteo feature extraction and proxies
- `src/weather/gfs.py` — GFS GRIB download/parsing helpers

### Ingestion
- `src/ingest/entsoe_client.py` — ENTSO-E client wrapper (UTC normalization)
- `src/ingest/incremental_ingest.py` — Append-only updates with overlap for corrections
- `src/ingest/parallel_ingest.py` — Threaded multi-area fetch
- `src/ingest/ingest_all.py` — Orchestration + synthetic generator

### Dispatch & Optimization
- `src/dispatch/merit_order.py` — Simple merit-order clearing
- `src/dispatch/unit_commitment.py` — MILP UC (startup/shutdown, ramps, min up/down)
- `src/dispatch/zonal_dispatch.py` — Generation-mix-based zonal clearing

### Backtesting & Analytics
- `src/models/backtest.py` — RMSE helpers, walk-forward splits
- `scripts/evaluate_price_forecast.py` — Evaluate forecast CSVs vs truth
- `src/data/io.py` — CSV/Parquet helpers, flexible column parsing

### Runners & Dashboard
- `scripts/run_forecast_with_gfs.py` — Train + backtest + forecast with weather
- `scripts/run_demand_forecast.py` — Demand model training/forecast
- `scripts/run_full_pipeline.py` — Ingest → forecast → dispatch demo
- `scripts/run_incremental_all.py` — Bulk incremental updates
- `scripts/streamlit_dashboard.py` — Quick visualization
- `scripts/run_uc_demo.py` — UC example

Configuration
--------------

Create `src/config.yaml` from the example:

```yaml
entsoe:
  api_key: "YOUR_TOKEN_HERE"
  default_area: DE_LU
  areas: ["DE_LU", "FR", "GB", "IT", "ES"]

data:
  history_days: 90
  forecast_horizon_days: 7

weather:
  latitude: 52.5
  longitude: 13.4
```

Dependencies
------------

**Required:**
- `pandas`, `numpy`, `requests`, `yaml`
- ENTSO-E API (direct requests) — day-ahead prices and load data
- `pulp` — MILP solver wrapper (CBC by default; Gurobi/CPLEX optional)
- `lightgbm`, `scikit-learn` — forecasting models
- `pyarrow` — Parquet support

**Optional (for GRIB parsing):**
- `xarray` + `cfgrib` + system `ecCodes` — GFS parsing (falls back to proxies otherwise)

Architecture & Solver Options
------------------------------

**Data Flow:**
1. ENTSO-E/API or GUI prices → ingest (`scripts/fetch_entsoe_data.py` / `scripts/merge_years.py`)
2. Weather (Open-Meteo/GFS) → `data/weather/<AREA>_weather.csv`
3. Feature build (lags, calendar, weather, load) → `src/models/price_model.py`, `src/models/demand_forecast.py`
4. CV + backtests → `src/models/forecast_cv.py`, `src/models/backtest.py`
5. Forecasts (mean + quantiles) → CSV/Parquet via `src/data/io.py`
6. Dispatch/UC → `src/dispatch/merit_order.py`, `src/dispatch/unit_commitment.py`, `src/dispatch/zonal_dispatch.py`

**Solver Options:**
- Default: PuLP + CBC (open-source)
- Upgrade: Gurobi/CPLEX (auto-detected by PuLP if installed)

Next Steps
----------
- Keep data fresh: `python scripts/fetch_entsoe_data.py --merge-existing ...`
- Run dashboards/backtests on the live 3-year dataset
- Convert large CSVs to Parquet for faster training/evaluation
- Explore multi-area training or residual-demand modeling with weather/load
