# European Power Stack Model - End-to-End Example

This notebook demonstrates the complete workflow: ENTSO-E ingestion, weather feature integration, LightGBM forecasting, UC dispatch, and backtesting.

## 1. Setup and Configuration

```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)

# Ensure your ENTSO-E API key is in src/config.yaml
from src.ingest.incremental_ingest import incremental_update, load_existing
from src.ingest.ingest_all import synthetic_area_series
from src.data.io import save_series_csv
```

## 2. Fetch and Prepare Price Data

### Option A: Use Real ENTSO-E Data (requires API key)

```python
area = 'DE'  # Germany bidding zone
try:
    prices = incremental_update(area, api_key='YOUR_KEY_HERE', lookback_hours=6)
except Exception as e:
    print(f"ENTSO-E fetch failed: {e}")
    prices = None
```

### Option B: Use Synthetic Data (no API key needed)

```python
area = 'DE'
prices = synthetic_area_series(area, days=90)
save_series_csv(prices, area)
print(f"Created synthetic data: {len(prices)} hourly points")
```

## 3. Feature Engineering with Weather Integration

```python
from src.features.weather_features import add_gfs_features

# Get weather features for Berlin (Germany)
lat, lon = 52.5, 13.4
weather_df = add_gfs_features(prices.index, lat=lat, lon=lon)
print("Weather features:")
print(weather_df.head())
```

## 4. Train LightGBM Ensemble with Cross-Validation

```python
from src.models.forecast_cv import cv_train_lgbm, quantile_models_train

# Train mean-prediction model
model, stats = cv_train_lgbm(prices, n_splits=3, lat=lat, lon=lon)
print(f"CV training stats: {stats}")

# Train quantile models for probabilistic forecasts
q_models = quantile_models_train(prices, quantiles=(0.1, 0.5, 0.9), lat=lat, lon=lon)
print(f"Quantile models ready: {list(q_models.keys())}")
```

## 5. Backtesting and Performance Evaluation

```python
from src.models.backtest import walk_forward_backtest
from src.models.forecast_cv import predict_with_model

def forecast_fn(s, days=7):
    return predict_with_model(model, s, days=days, lat=lat, lon=lon)

# Walk-forward backtest (last 30 days, 7-day horizon)
bt_results = walk_forward_backtest(prices, forecast_fn, train_window_days=60, horizon_days=7)
print(f"Backtest RMSE (mean): {bt_results['rmse'].mean():.2f}")
print(bt_results.tail(10))
```

## 6. Generate 7-Day Probabilistic Forecast

```python
from src.models.forecast_cv import predict_quantile

forecast_mean = predict_with_model(model, prices, days=7, lat=lat, lon=lon)
forecast_quantiles = predict_quantile(q_models, prices, days=7, lat=lat, lon=lon)

# Combine into a results DataFrame
forecast_df = pd.DataFrame({
    'mean': forecast_mean,
    'q10': forecast_quantiles.get(0.1, forecast_mean * 0.95),
    'q90': forecast_quantiles.get(0.9, forecast_mean * 1.05),
})
print("7-day probabilistic forecast:")
print(forecast_df)
```

## 7. Simple Merit-Order Dispatch

```python
from src.dispatch.merit_order import merit_order_clearing

# Define a sample fleet with fuel costs
units = [
    {'name': 'Nuclear', 'capacity': 3000, 'marginal_cost': 10.0},
    {'name': 'Coal', 'capacity': 4000, 'marginal_cost': 50.0},
    {'name': 'Gas', 'capacity': 5000, 'marginal_cost': 70.0},
    {'name': 'Wind', 'capacity': 2000, 'marginal_cost': 0.0},
]

# Use forecast mean as demand proxy
demand_mw = forecast_mean.iloc[0]
result = merit_order_clearing(demand_mw, units)
print(f"Clearing price @ {demand_mw:.0f} MW demand: ${result['clearing_price']:.2f}/MWh")
print(f"Dispatch: {[(u['name'], u['dispatched_mw']) for u in result['dispatch']]}")
```

## 8. Unit Commitment Optimization

```python
from src.dispatch.unit_commitment import solve_uc

# Small fleet with min-up/down and ramp constraints
units_uc = [
    {
        'name': 'Nuclear',
        'p_min': 1000, 'p_max': 3000,
        'marginal_cost': 10.0,
        'startup_cost': 1000.0,
        'min_up': 24, 'min_down': 4,
        'ramp_up': 500.0, 'ramp_down': 500.0
    },
    {
        'name': 'Coal',
        'p_min': 500, 'p_max': 4000,
        'marginal_cost': 50.0,
        'startup_cost': 500.0,
        'min_up': 8, 'min_down': 4,
        'ramp_up': 200.0, 'ramp_down': 200.0
    },
    {
        'name': 'Gas',
        'p_min': 0, 'p_max': 5000,
        'marginal_cost': 70.0,
        'startup_cost': 300.0,
        'min_up': 1, 'min_down': 1,
        'ramp_up': 1000.0, 'ramp_down': 1000.0
    },
]

# Create synthetic demand profile (use forecast as proxy)
demand_series = forecast_mean.iloc[:24]  # 24-hour horizon
result = solve_uc(units_uc, demand_series, horizon_hours=24)
print(f"UC status: {result['status']}")
print(f"Total cost: ${result['objective']:.2f}")
print("Dispatch (first 5 hours):")
print(result['dispatch'].head(5))
```

## 9. Forward Curve Construction

```python
# Simple daily-average forward curve from 7-day forecast
forward_curve = forecast_mean.resample('D').mean()
print("Simple 7-day forward curve (daily average):")
print(forward_curve)
```

## 10. Next Steps / Production Deployment

- **Data Pipeline**: Set up incremental ingestion schedule using `scripts/schedule_incremental.bat` and Windows Task Scheduler.
- **Model Persistence**: Save trained models (pickle/joblib) for production serving.
- **Real-time Updates**: Run the incremental ingestion nightly to keep prices current.
- **Ensemble Improvement**: Add multiple input areas (FR, BE, NL, etc.), ensemble models across areas, and include reserve/ancillary products.
- **Commercial Solver**: If you have Gurobi/CPLEX licenses, update UC solver to use commercial solvers for larger problems.
- **Monitoring**: Add data quality checks, model drift detection, and performance alerting.
