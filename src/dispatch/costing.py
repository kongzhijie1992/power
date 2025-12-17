from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd


@dataclass(frozen=True)
class Unit:
    unit_id: str
    fuel_type: str
    p_max_mw: float
    p_min_mw: float
    ramp_up_mw_per_h: float
    ramp_down_mw_per_h: float
    min_up_h: int
    min_down_h: int
    startup_cost_eur: float = 0.0
    vom_eur_per_mwh: float = 0.0
    fuel_price_col: Optional[str] = None
    co2_intensity_t_per_mwh_el: Optional[float] = None
    emissions_factor_t_per_mwh_fuel: Optional[float] = None
    efficiency: Optional[float] = None
    heat_rate_mwh_th_per_mwh_el: Optional[float] = None
    is_must_run: bool = False

    def heat_rate(self) -> Optional[float]:
        if self.heat_rate_mwh_th_per_mwh_el is not None:
            return self.heat_rate_mwh_th_per_mwh_el
        if self.efficiency is None:
            return None
        if self.efficiency <= 0:
            return None
        return 1.0 / self.efficiency

    def co2_intensity(self) -> float:
        if self.co2_intensity_t_per_mwh_el is not None:
            return float(self.co2_intensity_t_per_mwh_el)
        hr = self.heat_rate()
        if hr is None:
            return 0.0
        if self.emissions_factor_t_per_mwh_fuel is None:
            return 0.0
        return float(self.emissions_factor_t_per_mwh_fuel) * hr


def start_cost(unit: Unit, offline_hours: float) -> float:
    return float(unit.startup_cost_eur or 0.0)


def _default_segment_efficiencies(base_eff: float, n_segments: int) -> List[float]:
    multipliers = [1.02, 1.0, 0.98, 0.95]
    vals = []
    for i in range(n_segments + 1):
        m = multipliers[i] if i < len(multipliers) else multipliers[-1]
        vals.append(max(0.01, min(0.9, base_eff * m)))
    return vals


def segment_efficiencies(unit: Unit, n_segments: int = 3) -> List[float]:
    hr = unit.heat_rate()
    if hr is not None and hr > 0:
        base_eff = 1.0 / hr
        return _default_segment_efficiencies(base_eff, n_segments)
    if unit.efficiency is None or unit.efficiency <= 0:
        return [1.0] * (n_segments + 1)
    return _default_segment_efficiencies(float(unit.efficiency), n_segments)


def compute_segment_prices(
    unit: Unit,
    fuel_price_eur_per_mwh_fuel: float,
    eua_price_eur_per_tco2: float,
    n_segments: int = 3,
) -> List[float]:
    """
    Returns a list of segment marginal prices in EUR/MWh_el.

    Segment 0 is interpreted as "low load" (min-load) cost; segments 1..K are incremental blocks.
    """
    seg_eff = segment_efficiencies(unit, n_segments=n_segments)
    prices: List[float] = []
    for eff in seg_eff:
        hr = 1.0 / eff if eff and eff > 0 else 1.0
        co2_int = unit.co2_intensity_t_per_mwh_el
        if co2_int is None:
            if unit.emissions_factor_t_per_mwh_fuel is None:
                co2_int = 0.0
            else:
                co2_int = float(unit.emissions_factor_t_per_mwh_fuel) * hr
        prices.append(
            float(fuel_price_eur_per_mwh_fuel) * hr
            + float(eua_price_eur_per_tco2) * float(co2_int)
            + float(unit.vom_eur_per_mwh or 0.0)
        )
    return prices


def coerce_hours_index(df: pd.DataFrame, horizon_h: int = 24) -> pd.DatetimeIndex:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("system inputs must be indexed by datetime")
    idx = df.index[:horizon_h]
    if len(idx) != horizon_h:
        raise ValueError(f"need at least {horizon_h} hours, got {len(idx)}")
    return idx


def net_demand(
    system: pd.DataFrame,
    demand_col: str = "demand_mw",
    renewable_cols: Iterable[str] = ("wind_mw", "solar_mw", "ror_mw", "must_run_mw"),
) -> pd.Series:
    if demand_col not in system.columns:
        raise KeyError(f"missing demand column: {demand_col}")
    demand = pd.to_numeric(system[demand_col], errors="coerce").fillna(0.0)
    renew = 0.0
    for c in renewable_cols:
        if c in system.columns:
            renew = renew + pd.to_numeric(system[c], errors="coerce").fillna(0.0)
    return (demand - renew).clip(lower=0.0)
