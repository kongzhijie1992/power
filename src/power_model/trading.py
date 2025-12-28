from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class PositionSizer:
    max_basesize_mw: float = 200.0
    max_hourly_mw: float = 50.0
    vol_floor: float = 5.0

    def _risk_scale(
        self, series: pd.Series, history: Optional[pd.Series]
    ) -> float:
        vol = float(series.std()) if not series.empty else self.vol_floor
        if history is not None and len(history) > 10:
            vol = float(history.tail(30).std())
        return max(vol, self.vol_floor)

    def baseload_position(
        self,
        preds: pd.Series,
        structural: pd.Series,
        history: Optional[pd.Series] = None,
    ) -> float:
        signal = preds.mean() - structural.mean()
        risk = self._risk_scale(preds, history)
        raw = signal / risk
        return float(np.clip(raw, -1, 1) * self.max_basesize_mw)

    def hourly_shape(
        self,
        preds: pd.Series,
        structural: pd.Series,
        history: Optional[pd.Series] = None,
    ) -> pd.Series:
        risk = self._risk_scale(preds, history)
        signal = preds - structural
        scaled = np.clip(signal / risk, -1, 1) * self.max_hourly_mw
        return pd.Series(scaled, index=preds.index)


class TradingEngine:
    """Builds baseload and hourly shape positions and computes PnL."""

    def __init__(
        self,
        transaction_cost: float = 0.5,
        position_sizer: Optional[PositionSizer] = None,
    ):
        self.transaction_cost = transaction_cost
        self.position_sizer = position_sizer or PositionSizer()

    def make_positions(
        self,
        preds: pd.DataFrame,
        structural: pd.Series,
        history_prices: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        base = self.position_sizer.baseload_position(
            preds["price_pred"], structural, history_prices
        )
        hourly = self.position_sizer.hourly_shape(
            preds["price_pred"], structural, history_prices
        )
        positions = pd.DataFrame({"baseload_mw": base, "shape_mw": hourly})
        return positions

    def compute_pnl(
        self, positions: pd.DataFrame, actual_price: pd.Series
    ) -> pd.DataFrame:
        if "shape_mw" not in positions or "baseload_mw" not in positions:
            raise ValueError("positions must contain baseload_mw and shape_mw")
        base_qty = positions["baseload_mw"].iloc[0]
        base_leg = base_qty * actual_price
        base_leg.iloc[0] = base_leg.iloc[0] - self.transaction_cost * abs(
            base_qty
        )
        shape_leg = (
            positions["shape_mw"] * actual_price
            - self.transaction_cost * positions["shape_mw"].abs()
        )
        pnl = pd.DataFrame(
            {
                "pnl": base_leg + shape_leg,
                "base_leg": base_leg,
                "shape_leg": shape_leg,
            }
        )
        return pnl
