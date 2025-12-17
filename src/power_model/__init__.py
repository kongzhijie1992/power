"""
Power model package for DE-LU day-ahead price forecasting and P&L backtesting.

Modules:
    contracts: strict time-series schemas and validation helpers.
    timeutils: timezone and DST-safe feature engineering.
    loaders: data loaders and merge helpers with Parquet caching.
    structural: merit-order stack model for DE-LU.
    residual: residual ML forecaster (CatBoost) on top of structural price.
    trading: position sizing and P&L utilities.
    backtest: daily walk-forward simulation and reporting.
"""

from .contracts import TimeSeriesContract, validate_contract
from .timeutils import (
    ensure_utc_index,
    add_local_time_features,
    berlin_zone,
)
from .loaders import (
    load_parquet_contract,
    merge_inputs,
)
from .structural import StructuralStackModel, PlantStackModel
from .plants import PlantStack

try:
    from .residual import ResidualModel  # type: ignore
except ModuleNotFoundError as _residual_exc:  # pragma: no cover
    class ResidualModel:  # type: ignore
        def __init__(self, *_, **__):
            raise ModuleNotFoundError(
                "ResidualModel requires the optional 'catboost' dependency. "
                "Install it (e.g. `pip install catboost`) to enable residual forecasts."
            ) from _residual_exc

from .trading import TradingEngine, PositionSizer
from .backtest import BacktestRunner, BacktestResult

__all__ = [
    "TimeSeriesContract",
    "validate_contract",
    "ensure_utc_index",
    "add_local_time_features",
    "berlin_zone",
    "load_parquet_contract",
    "merge_inputs",
    "StructuralStackModel",
    "PlantStack",
    "PlantStackModel",
    "ResidualModel",
    "TradingEngine",
    "PositionSizer",
    "BacktestRunner",
    "BacktestResult",
]
