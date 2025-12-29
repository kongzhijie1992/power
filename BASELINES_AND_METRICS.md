# Baselines, Training, and Evaluation References

This repo’s baseline forecasting and evaluation logic lives primarily in:

## Core training & evaluation modules (`src/`)

- **`src/models/forecast.py`**
  - Baselines:
    - `seasonal_naive_forecast`: last-week same-hour seasonal naive.
    - `weekday_hour_average_forecast`: weekday/hour historical averages.
  - Feature engineering: `make_features` builds hour, day-of-week, lag, and rolling
    features for ML models.
- **`src/models/forecast_cv.py`**
  - ML training: `cv_train_lgbm` (LightGBM) with time-series CV.
  - Metrics: RMSE + MAE reported per split and averaged.
  - Optional quantile models: `quantile_models_train`.
- **`src/models/backtest.py`**
  - Walk-forward backtesting: `walk_forward_backtest` (RMSE per window).
  - Leakage-safe rolling predictions: `walk_forward_predict_series`.
  - Error analysis: `error_breakdown` for horizon + seasonal buckets.
- **`src/power_model/residual.py`**
  - CatBoost residual model training + rolling CV evaluation.
  - Metric: MAE via `rolling_cv_mae`.

## Tests that exercise baselines and metrics (`tests/`)

- **`tests/test_forecasting.py`**
  - Baselines: `seasonal_naive_forecast`, `weekday_hour_average_forecast`.
  - ML evaluation: `cv_train_lgbm`, `quantile_models_train`.
  - Metrics checked: RMSE/MAE (presence + basic sanity checks).
- **`tests/test_backtesting.py`**
  - Walk-forward backtests (RMSE).
  - Error breakdown summary outputs (horizon/seasonality buckets).
- **`tests/test_leakage_guard.py`**
  - Ensures time-series splits are leakage-free for residual CV.
- **`tests/test_integration.py`**
  - End-to-end flow: ingest → features → train → backtest, and leakage checks.

These references are the main places to update when adding new baselines,
metrics, or evaluation splits.
