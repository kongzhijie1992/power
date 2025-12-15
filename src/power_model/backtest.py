from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .residual import ResidualModel
from .structural import StructuralStackModel
from .trading import TradingEngine


@dataclass
class BacktestResult:
    pnl: pd.DataFrame
    predictions: pd.DataFrame
    daily_summary: pd.DataFrame


class BacktestRunner:
    """Daily walk-forward backtest."""

    def __init__(
        self,
        structural_model: StructuralStackModel,
        residual_model: ResidualModel,
        trading_engine: TradingEngine,
    ):
        self.structural_model = structural_model
        self.residual_model = residual_model
        self.trading_engine = trading_engine

    def run(
        self,
        data: pd.DataFrame,
        backtest_start: datetime,
        backtest_end: Optional[datetime] = None,
        target_col: str = "price_da",
    ) -> BacktestResult:
        structural = self.structural_model.predict(data)
        df = data.join(structural, how="inner")

        if backtest_end is None:
            backtest_end = df.index.max()

        days = pd.date_range(backtest_start, backtest_end, freq="D", tz="UTC")
        pnl_rows = []
        pred_rows = []

        for day in days:
            day_slice = df.loc[day : day + pd.Timedelta(hours=23)]
            train_slice = df[df.index < day]
            if day_slice.empty or len(train_slice) < 48:
                continue

            model = ResidualModel(
                feature_cols=self.residual_model.feature_cols,
                quantiles=self.residual_model.quantiles,
                point_params=self.residual_model.point_params,
                quantile_params=self.residual_model.quantile_params,
            )
            model.fit(train_slice, target_col=target_col)

            preds = model.predict(day_slice, structural_col="structural_price")
            preds["structural_price"] = day_slice["structural_price"]
            preds["price_da"] = day_slice[target_col]

            positions = self.trading_engine.make_positions(
                preds, structural=day_slice["structural_price"], history_prices=train_slice[target_col]
            )
            pnl = self.trading_engine.compute_pnl(positions, actual_price=day_slice[target_col])
            pnl_rows.append(pnl.assign(day=day))
            pred_rows.append(preds.assign(day=day))

        pnl_df = pd.concat(pnl_rows) if pnl_rows else pd.DataFrame()
        preds_df = pd.concat(pred_rows) if pred_rows else pd.DataFrame()

        daily = pnl_df.groupby("day")["pnl"].sum().to_frame("daily_pnl")
        daily["cum_pnl"] = daily["daily_pnl"].cumsum()
        daily["sharpe_like"] = daily["daily_pnl"].mean() / (daily["daily_pnl"].std() + 1e-6) if not daily.empty else np.nan

        return BacktestResult(pnl=pnl_df, predictions=preds_df, daily_summary=daily)
