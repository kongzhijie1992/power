# Power Stack Workflow (Detailed)

This document describes the end-to-end flow of the power stack model: where data comes from, how features are built, how models are trained/evaluated, and how forecasts feed dispatch/unit-commitment.

## 1) Inputs & Storage
All runtime data is stored in S3. Paths like `data/<AREA>/...` are logical and
resolve to `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/...` when the S3 env vars are set.
Local `data/` is no longer used for runtime storage.

- **Prices:** `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/day_ahead.csv` (primary) and `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/day_ahead_real.csv` (raw API). Current primary: `s3://$S3_BUCKET/$S3_PREFIX/DE_LU/day_ahead.csv` (25,944 rows, 2022-12-31 → 2025-12-16, UTC).
- **Weather:** `s3://$S3_BUCKET/$S3_PREFIX/weather/<AREA>_weather.csv` (hourly wind/solar proxies). Current: `s3://$S3_BUCKET/$S3_PREFIX/weather/DE_LU_weather.csv` (25,872 rows).
- **Load:** `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/load_real.csv` (quarter-hour actuals) and `s3://$S3_BUCKET/$S3_PREFIX/<AREA>/load_forecast.csv` (TSO forecast if available). Current DE_LU load: 103,380 rows.
- **Config:** `src/config.yaml` (ENTSO-E token, default areas, optional weather lat/lon).
- **Helpers:** `src/data/io.py` handles CSV/Parquet read/write, column normalization, and fallback column detection.

## 2) Ingestion Layer
- **API (preferred):** `scripts/fetch_entsoe_data.py` performs chunked ENTSO-E calls (A44 Day-ahead prices) with `--chunk-days` to avoid 400s. It also downloads Open-Meteo weather for matching windows. Outputs one CSV per area + weather file; `--merge-existing` dedupes timestamps.
- **GUI fallback:** `scripts/convert_entsoe.py` (15-min → hourly, UTC) and `scripts/merge_years.py` (multi-year merge with sequence selection).
- **Incremental append:** `src/ingest/incremental_ingest.py` fetches only missing hours with overlap, writes `day_ahead_real.csv/parquet`, and dedupes.
- **Parallel pulls:** `src/ingest/parallel_ingest.py` threads multi-area fetches; `src/ingest/ingest_all.py` orchestrates across `DEFAULT_ZONES` and can generate synthetic series for tests.
- **DST handling:** All ingest paths convert to UTC and strip tz info (`tz_convert('UTC').tz_localize(None)`), eliminating duplicates/gaps at transitions.

## 3) Feature Engineering
- **Price features:** Calendar (hour/day/week/month + cyclic encodings), lagged values (1/24/48/168h), rolling means (24/168h), holiday flags (if `holidays` installed). Implemented in `src/models/price_model.py` and `src/models/forecast.py`.
- **Weather features:** `src/features/weather_features.py` adds wind/solar from Open-Meteo CSV or GFS GRIBs (if `cfgrib` available). Falls back to synthetic diurnal proxies when data is missing.
- **Demand features:** `src/models/demand_forecast.py` builds calendar + weather + ramp/lag features for load, including heating/cooling degree days and DST-transition flags.
- **Error modeling:** `prepare_error_features` / `build_future_error_features` in `src/models/demand_forecast.py` learn TSO forecast errors using lagged errors + weather.

## 4) Modeling
- **Price forecast (regression + quantiles):**
  - `src/models/price_model.py` trains a LightGBM regressor with recursive one-hour roll-out for `horizon_days` (default 7). Supports holiday flags and weather columns (`windspeed_10m`, `shortwave_radiation`).
  - `src/models/forecast_cv.py` builds feature matrices with optional weather, performs time-series CV, and trains quantile LightGBM models (0.1/0.5/0.9). Falls back to seasonal-naive if LightGBM unavailable.
- **Baseline:** `src/models/forecast.py` provides seasonal-naive forecasts using hour/day-of-week means; used as robust fallback.
- **Demand forecast:** `src/models/demand_forecast.py` trains mean and quantile models (LightGBM if available, else GradientBoosting). Supports per-hour-of-day models and residual demand computation (`compute_residual_demand`).

## 5) Backtesting & Evaluation
- **Walk-forward backtest:** `src/models/backtest.py::walk_forward_backtest` trains on rolling windows (default 60d train, 7d horizon) and reports RMSE per window.
- **Leakage-safe prediction:** `walk_forward_predict_series` generates forward-only predictions, retaining the first-available forecast per timestamp to avoid look-ahead. Tested in `tests/test_walk_forward_predict_no_leakage.py`.
- **CV stats:** Returned from `cv_train_lgbm` (RMSE/MAE + per-split RMSE) and logged in runners.
- **Evaluation script:** `scripts/evaluate_price_forecast.py` compares a forecast CSV to truth, computing RMSE/MAE and optional quantile coverage.

## 6) Forecast Generation
- **Price:** `src/models/price_model.py::forecast_price` rolls forward recursively for N days (default 7) using trained LightGBM + weather alignment. Quantile predictions available via `src/models/forecast_cv.py::predict_quantile` for probabilistic outputs.
- **Demand:** `src/models/demand_forecast.py::predict_demand` supports single model or per-hour models, emitting mean + quantile series aligned to provided future features.
- **Persistence:** Use `src/data/io.py::save_series_csv` or Parquet utilities in `scripts/convert_prices_to_parquet.py` to store outputs.

## 7) Dispatch & Unit Commitment
- **Merit order:** `src/dispatch/merit_order.py::merit_order_clearing` clears hourly demand against a sorted supply stack, returning clearing price and dispatch vector.
- **Zonal dispatch:** `src/dispatch/zonal_dispatch.py` converts a generation-mix row into generator blocks (with configurable marginal costs) and applies merit order across a demand series.
- **Unit commitment:** `src/dispatch/unit_commitment.py::solve_uc` builds a MILP with on/off, startup/shutdown, min up/down, and ramp constraints; solves with PuLP/CBC by default. Returns dispatch schedule and objective.
- **Integration point:** Forecasted prices/demand can be fed into dispatch/UC to simulate revenues or commitment feasibility.

## 8) Runners & Entry Points
- `scripts/run_forecast_with_gfs.py` — Load/create prices → train LightGBM (mean + quantiles) with weather → walk-forward backtest → 7-day forecast.
- `scripts/run_demand_forecast.py` — Build demand features (actual + TSO forecast + weather) → train per-hour models → forecast horizon.
- `scripts/run_full_pipeline.py` — Ingest (real or synthetic) → CV → forecast → synthetic generation mix dispatch demo.
- `scripts/run_uc_demo.py` — Small UC example with ramps/min up/down/startup costs.
- `scripts/streamlit_dashboard.py` — Quick local visualization of prices/forecasts.
- `scripts/run_incremental_all.py` — Batch incremental updates across areas.

## 9) Observability & Testing
- **Test suite:** 87 tests covering DST, ingestion, data I/O, backtesting, walk-forward leakage, dispatch/UC, forecasting, integration. Run with `.venv\Scripts\pytest -q`.
- **DST:** `tests/test_dst_handling.py` validates spring/fall transitions and ENTSO-E timezone conversion.
- **Data validation:** `check_data.py` prints row counts, date ranges, and NaN checks; `scripts/summarize_datasets.py` reports coverage across all areas.

## 10) Operating the Pipeline
- **Refresh data:** `python scripts/fetch_entsoe_data.py --areas DE_LU FR IT ES NL BE --start-date 2023-01-01 --end-date 2025-12-31 --chunk-days 60 --merge-existing`
- **Train + backtest price model:** `python scripts/run_forecast_with_gfs.py --area DE_LU`
- **Train + backtest demand model:** `python scripts/run_demand_forecast.py --area DE_LU`
- **Dispatch demo with synthetic mix:** `python scripts/run_full_pipeline.py --area DE_LU --synthetic`
- **UC demo:** `python scripts/run_uc_demo.py`

## 11) Outputs & Artifacts
- Forecasts and backtest metrics are printed/logged in runners; persist outputs via `src/data/io.py` or by editing runners to write CSV/Parquet.
- Dispatch/UC results return DataFrames with hourly prices/dispatch; capture them in runners as needed.
- Weather/price/load artifacts live in `s3://$S3_BUCKET/$S3_PREFIX/` with area-specific folders; summarize with `scripts/summarize_datasets.py`.

Use this map to trace any result back to its input and module. Every stage is UTC/DST-safe, merge-safe, and covered by tests in the `tests/` folder.
