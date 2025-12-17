from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit


@dataclass
class ResidualModel:
    feature_cols: Sequence[str]
    quantiles: Sequence[float] = (0.1, 0.5, 0.9)
    point_params: Dict = field(
        default_factory=lambda: {
            "loss_function": "RMSE",
            "depth": 6,
            "learning_rate": 0.05,
            "iterations": 200,
        }
    )
    quantile_params: Dict = field(
        default_factory=lambda: {"iterations": 200, "depth": 6, "learning_rate": 0.05}
    )

    def __post_init__(self):
        self.point_model: CatBoostRegressor | None = None
        self.quantile_models: Dict[float, CatBoostRegressor] = {}

    @staticmethod
    def _residuals(
        df: pd.DataFrame, target_col: str, structural_col: str
    ) -> np.ndarray:
        return (df[target_col] - df[structural_col]).to_numpy()

    def fit(
        self,
        df: pd.DataFrame,
        target_col: str = "price_da",
        structural_col: str = "structural_price",
    ) -> "ResidualModel":
        X = df[self.feature_cols]
        y = self._residuals(df, target_col, structural_col)
        self.point_model = CatBoostRegressor(**self.point_params, verbose=False)
        self.point_model.fit(X, y)
        self.quantile_models = {}
        for q in self.quantiles:
            model = CatBoostRegressor(
                loss_function=f"Quantile:alpha={q}",
                **self.quantile_params,
                verbose=False,
            )
            model.fit(X, y)
            self.quantile_models[q] = model
        return self

    def rolling_cv_mae(
        self,
        df: pd.DataFrame,
        n_splits: int = 3,
        target_col: str = "price_da",
        structural_col: str = "structural_price",
    ) -> float:
        """Walk-forward validation to guard against leakage."""
        tscv = TimeSeriesSplit(n_splits=n_splits)
        maes = []
        y = self._residuals(df, target_col, structural_col)
        X = df[self.feature_cols].to_numpy()
        for train_idx, test_idx in tscv.split(X):
            train_x, test_x = X[train_idx], X[test_idx]
            train_y, test_y = y[train_idx], y[test_idx]
            model = CatBoostRegressor(**self.point_params, verbose=False)
            model.fit(train_x, train_y)
            preds = model.predict(test_x)
            maes.append(mean_absolute_error(test_y, preds))
        return float(np.mean(maes)) if maes else float("nan")

    def predict(
        self, df: pd.DataFrame, structural_col: str = "structural_price"
    ) -> pd.DataFrame:
        if self.point_model is None:
            raise RuntimeError("Model not fitted")
        X = df[self.feature_cols]
        residual_pred = self.point_model.predict(X)
        out = pd.DataFrame(index=df.index)
        structural = df[structural_col]
        out["price_pred"] = structural + residual_pred
        for q, model in self.quantile_models.items():
            res_q = model.predict(X)
            out[f"price_p{int(q*100)}"] = structural + res_q
        return out
