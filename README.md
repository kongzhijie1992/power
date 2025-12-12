Power Stack Model — Europe (ENTSO-E + GFS + UC)
================================================

Overview
--------
A production-oriented prototype for European power-stack analysis with:

**Forecasting**
- Day-ahead price forecasts (up to 7 days, hourly resolution)
- Weather-integrated LightGBM ensemble (GFS wind/solar features)
- Probabilistic outputs (mean + 0.1/0.9 quantiles)
- Walk-forward backtesting framework

**Dispatch & Optimization**
- Merit-order clearing (zonal dispatch)
- Unit Commitment (UC) with MILP solver (PuLP/CBC)
  - Startup/shutdown costs, min up/down, ramp constraints
  - Extensible to commercial solvers (Gurobi, CPLEX)

**Data**
- ENTSO-E day-ahead prices (incremental ingestion, Parquet persistence)
- GFS weather data (wind, solar radiation)
- Forward-curve constructor
- Configurable multi-zone ingestion

**Backtesting & Validation**
- Time-series cross-validation for model training
- Walk-forward backtest harness
- Performance metrics (RMSE, MAE)

Quickstart (poetry)
-------------------
1. Install dependencies:

```bash
poetry install
poetry add pulp lightgbm scikit-learn pyarrow
```

2. Set up your ENTSO-E API key:

```bash
copy src\config.yaml.example src\config.yaml
# Edit src\config.yaml and add your entsoe.api_key
```

3. Run end-to-end demo with synthetic data (no API key required):

```bash
poetry run python scripts\run_forecast_with_gfs.py --area DE_LU
```

4. Or use real ENTSO-E data (default area DE_LU):

```bash
poetry run python scripts\run_full_pipeline.py --area DE_LU
```

5. Try the unit-commitment solver:

```bash
poetry run python scripts\run_uc_demo.py
```

See `notebooks/example_workflow.md` for a full walkthrough.

Sample data and quick local setup
---------------------------------
If you don't have an ENTSO‑E API key yet, use the included helper to generate synthetic prices
and download Open‑Meteo weather (no API key required). This creates files the code expects
under the `data/` folder.

1. Generate sample data for the `DE` zone (90 days):

```powershell
# Windows (cmd/powershell)
C:\Users\zkong\Desktop\power\.venv\Scripts\python.exe scripts\fetch_sample_data.py --area DE_LU --days 90
```

2. Files created:
- `data/DE/day_ahead.csv` — hourly price series with a `value` column and ISO datetime index (UTC)
- `data/weather/DE_weather.csv` — hourly `windspeed_10m` and `shortwave_radiation` from Open‑Meteo

3. Run the full pipeline using the local files (no ENTSO‑E key required):

```powershell
C:\Users\zkong\Desktop\power\.venv\Scripts\python.exe scripts\run_full_pipeline.py --area DE_LU
```

If you prefer to provide your own price CSV, ensure it is saved to `data/<AREA>/day_ahead.csv` with
an ISO datetime index and a column named `value`.

Want to use a different weather provider or file? See `scripts/fetch_sample_data.py` for how the
Open‑Meteo CSV is formatted; the pipeline will use local weather CSVs where available.

What you get
------------

### Forecasting
- `src/models/forecast_cv.py` — LightGBM ensemble with weather features
- `src/features/weather_features.py` — GFS wind/solar feature extraction (fallback proxies if GRIB parsing unavailable)
- Time-series CV and walk-forward backtesting

### Ingestion
- `src/ingest/entsoe_client.py` — ENTSO-E API client (entsoe-py wrapper)
- `src/ingest/incremental_ingest.py` — Detect last persisted timestamp, fetch only new data, append to Parquet
- `src/ingest/parallel_ingest.py` — Multi-threaded parallel fetching across bidding zones
- `src/weather/gfs.py` — GFS GRIB2 download and nearest-gridpoint extraction (requires optional cfgrib)

### Dispatch & Optimization
- `src/dispatch/merit_order.py` — Simple merit-order clearing
- `src/dispatch/unit_commitment.py` — MILP unit-commitment with:
  - Binary on/off, startup/shutdown variables
  - Min-up/min-down constraints
  - Ramp-up/ramp-down limits
  - Startup costs
  - Extensible to Gurobi/CPLEX
- `src/dispatch/zonal_dispatch.py` — Zone-level dispatch using generation-mix data

### Backtesting & Analytics
- `src/models/backtest.py` — Walk-forward backtest harness with RMSE/MAE
- `src/data/io.py` — Parquet/CSV persistence helpers

### Runners & Scheduling
- `scripts/run_forecast_with_gfs.py` — End-to-end: train + backtest + forecast with weather features
- `scripts/run_uc_demo.py` — Unit-commitment solver example
- `scripts/run_full_pipeline.py` — Full pipeline (ingestion + forecast + dispatch)
- `scripts/run_incremental_all.py` — Incremental update runner
- `scripts/schedule_incremental.bat` — Windows Task Scheduler integration (run nightly updates)

Configuration
--------------

Create `src/config.yaml` from the example:

```yaml
# ENTSO-E API token
entsoe:
  api_key: "YOUR_TOKEN_HERE"
  default_area: DE
  # Optional list of areas for bulk ingestion
  areas: ["DE", "FR", "GB", "IT", "ES"]

# Data parameters
data:
  history_days: 90
  forecast_horizon_days: 7

# Optional: weather feature extraction lat/lon (defaults to Berlin)
weather:
  latitude: 52.5
  longitude: 13.4
```

Dependencies
------------

**Required:**
- `pandas`, `numpy`, `requests`, `yaml`
- `entsoe-py` — ENTSO-E API client
- `pulp` — MILP solver wrapper (uses CBC by default; Gurobi/CPLEX optional)
- `lightgbm`, `scikit-learn` — forecasting models
- `pyarrow` — Parquet support

**Optional (for weather feature parsing):**
- `xarray` + `cfgrib` + system `ecCodes` library — GFS GRIB2 parsing
  - Without these, weather features fall back to synthetic proxies (model still works)

Install all via:

```bash
poetry install
poetry add pulp lightgbm scikit-learn pyarrow xarray cfgrib
```

Architecture & Solver Options
------------------------------

**Data Flow:**
1. ENTSO-E or synthetic prices → incremental ingest (Parquet)
2. GFS weather (optional) → feature extraction
3. Price + weather features → LightGBM CV training
4. Trained model + backtest → forecast + error metrics
5. Forecast + generation mix → dispatch optimization
6. UC solver → minimum-cost commitment schedule

**Solver Options:**
- Default: PuLP + CBC (free, open-source)
- Upgrade: Gurobi or CPLEX (commercial; PuLP auto-detects)

Next Steps
----------
- Obtain ENTSO-E API key and test with real data
- Add generation mix / outage data connectors
- Tune LightGBM hyperparameters and add ensemble across multiple areas
- Upgrade UC solver with transmission constraints and reserve markets
- Deploy via Docker and set up scheduled ingestion
# Power Stack model 
