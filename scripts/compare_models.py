import pandas as pd
from src.models.demand_forecast import (
    prepare_demand_features,
    train_demand_models,
    prepare_timeseries_dataset,
    train_deep_learning_model,
)
from src.power_model.loaders import Mwh, Price, Load
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error
import numpy as np
import torch

def main():
    """
    This script compares the performance of the Gradient Boosting model and a deep learning model.
    """
    print("Loading data...")
    country = "DE"
    year = 2023
    load = Load(country=country, year=year).load()

    print("Preparing features for Gradient Boosting model...")
    X, y = prepare_demand_features(load, country=country)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.1, shuffle=False
    )

    print("Training Gradient Boosting model...")
    mean_model, _, _ = train_demand_models(X, y)
    y_pred_gb = mean_model.predict(X_val)

    gb_mae = mean_absolute_error(y_val, y_pred_gb)
    gb_rmse = np.sqrt(mean_squared_error(y_val, y_pred_gb))

    print("Preparing TimeSeriesDataSet for deep learning model...")
    dataset = prepare_timeseries_dataset(X, y, country=country)

    print("Training deep learning model...")
    model, trainer = train_deep_learning_model(dataset, max_epochs=1, gpus=0)

    print("Evaluating deep learning model...")
    val_dataloader = dataset.to_dataloader(train=False, batch_size=128, num_workers=0)
    
    # Get predictions
    predictions = model.predict(val_dataloader)
    
    # Get actuals
    actuals, _ = zip(*[(batch.y, batch.x) for batch in iter(val_dataloader)])
    
    dl_mae = mean_absolute_error(torch.cat(actuals).numpy(), predictions.numpy())
    dl_rmse = np.sqrt(mean_squared_error(torch.cat(actuals).numpy(), predictions.numpy()))


    print("\nModel Comparison:")
    print(f"Gradient Boosting MAE: {gb_mae:.2f}")
    print(f"Gradient Boosting RMSE: {gb_rmse:.2f}")
    print(f"Deep Learning MAE: {dl_mae:.2f}")
    print(f"Deep Learning RMSE: {dl_rmse:.2f}")


if __name__ == "__main__":
    main()
