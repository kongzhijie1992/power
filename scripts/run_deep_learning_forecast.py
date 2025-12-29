
import pandas as pd
from src.models.demand_forecast import (
    prepare_demand_features,
    prepare_timeseries_dataset,
    train_deep_learning_model,
)
from src.power_model.loaders import Mwh, Price, Load
from pathlib import Path

def main():
    """
    This script trains and evaluates a deep learning model for demand forecasting.
    """
    print("Loading data...")
    country = "DE"
    year = 2023
    load = Load(country=country, year=year).load()
    
    print("Preparing features...")
    X, y = prepare_demand_features(load, country=country)
    
    print("Preparing TimeSeriesDataSet...")
    dataset = prepare_timeseries_dataset(X, y, country=country)
    
    print("Training deep learning model...")
    model, trainer = train_deep_learning_model(dataset, max_epochs=1, gpus=0)
    
    print("Evaluating model...")
    val_dataloader = dataset.to_dataloader(train=False, batch_size=128, num_workers=0)
    results = trainer.test(model, dataloaders=val_dataloader)
    
    print("Validation results:")
    print(results)

if __name__ == "__main__":
    main()
