from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .bidding import Block, build_blocks
from .costing import Unit, net_demand
from .clearing import clear_day
from .uc_model import UCResult, solve_uc_day


@dataclass(frozen=True)
class DailyResult:
    uc: UCResult
    blocks: List[Block]
    clearing_price: pd.Series


def units_from_plants(
    plants: pd.DataFrame,
    *,
    zone: Optional[str] = None,
    stack_types: Optional[Sequence[str]] = None,
    cluster_size_mw: float = 500.0,
) -> List[Unit]:
    """
    Build a manageable UC unit list from a plant stack by clustering aggregated fleets.

    The input `plants` is expected to include columns produced by `PlantStack.from_opsd()`:
      - bidding_zone, stack_type, fuel
      - p_min_mw, p_max_mw, ramp_up_mw_per_min, ramp_down_mw_per_min
      - min_up_hours, min_down_hours, startup_cost_eur
      - efficiency, co2_intensity, variable_om_eur_per_mwh, fuel_price_eur_per_mwhth
    """
    df = plants.copy()
    if zone is not None and "bidding_zone" in df.columns:
        df = df[df["bidding_zone"] == zone]
    if stack_types is not None and "stack_type" in df.columns:
        df = df[df["stack_type"].isin(stack_types)]
    if df.empty:
        return []

    group_cols = [
        c for c in ["bidding_zone", "stack_type", "fuel"] if c in df.columns
    ]
    grouped = df.groupby(group_cols, dropna=False)

    units: List[Unit] = []
    for key, g in grouped:
        cap = float(
            pd.to_numeric(g["p_max_mw"], errors="coerce").fillna(0.0).sum()
        )
        if cap <= 0:
            continue

        pmin_total = float(
            pd.to_numeric(g.get("p_min_mw"), errors="coerce").fillna(0.0).sum()
        )
        pmin_ratio = pmin_total / cap if cap > 0 else 0.0

        ru = (
            float(
                pd.to_numeric(g.get("ramp_up_mw_per_min"), errors="coerce")
                .fillna(0.0)
                .sum()
            )
            * 60.0
        )
        rd = (
            float(
                pd.to_numeric(g.get("ramp_down_mw_per_min"), errors="coerce")
                .fillna(0.0)
                .sum()
            )
            * 60.0
        )

        min_up = int(
            np.nanmax(
                pd.to_numeric(g.get("min_up_hours"), errors="coerce")
                .fillna(0.0)
                .values
            )
        )
        min_down = int(
            np.nanmax(
                pd.to_numeric(g.get("min_down_hours"), errors="coerce")
                .fillna(0.0)
                .values
            )
        )
        startup = float(
            pd.to_numeric(g.get("startup_cost_eur"), errors="coerce")
            .fillna(0.0)
            .mean()
        )

        eff = float(
            pd.to_numeric(g.get("efficiency"), errors="coerce")
            .fillna(np.nan)
            .mean()
        )
        if np.isnan(eff):
            eff = 1.0
        co2_int = float(
            pd.to_numeric(g.get("co2_intensity"), errors="coerce")
            .fillna(0.0)
            .mean()
        )
        vom = float(
            pd.to_numeric(
                g.get("variable_om_eur_per_mwh", g.get("vom")), errors="coerce"
            )
            .fillna(0.0)
            .mean()
        )

        fuel = str(g["fuel"].iloc[0]) if "fuel" in g.columns else "unknown"
        stack = (
            str(g["stack_type"].iloc[0])
            if "stack_type" in g.columns
            else "fleet"
        )
        zone_name = (
            str(g["bidding_zone"].iloc[0])
            if "bidding_zone" in g.columns
            else "Z"
        )
        base_id = f"{zone_name}:{stack}"

        n = int(np.ceil(cap / float(cluster_size_mw)))
        sizes = [float(cluster_size_mw)] * n
        sizes[-1] = cap - float(cluster_size_mw) * (n - 1)

        for j, pmax in enumerate(sizes, start=1):
            pmin = pmax * pmin_ratio
            units.append(
                Unit(
                    unit_id=f"{base_id}#{j}",
                    fuel_type=fuel,
                    p_max_mw=float(pmax),
                    p_min_mw=float(pmin),
                    ramp_up_mw_per_h=float(ru) if ru > 0 else float(pmax),
                    ramp_down_mw_per_h=float(rd) if rd > 0 else float(pmax),
                    min_up_h=int(min_up),
                    min_down_h=int(min_down),
                    startup_cost_eur=float(startup),
                    vom_eur_per_mwh=float(vom),
                    co2_intensity_t_per_mwh_el=float(co2_int),
                    efficiency=float(eff),
                )
            )
    return units


def run_daily_uc(
    units: List[Unit],
    system: pd.DataFrame,
    *,
    horizon_h: int = 24,
    demand_col: str = "demand_mw",
    renewable_cols: Iterable[str] = (
        "wind_mw",
        "solar_mw",
        "ror_mw",
        "must_run_mw",
    ),
    eua_col: str = "eua_price",
    fuel_price_cols: Optional[Dict[str, str]] = None,
    availability: Optional[pd.DataFrame] = None,
    n_segments: int = 3,
) -> DailyResult:
    uc = solve_uc_day(
        units,
        system,
        horizon_h=horizon_h,
        demand_col=demand_col,
        renewable_cols=renewable_cols,
        eua_col=eua_col,
        fuel_price_cols=fuel_price_cols,
        availability=availability,
        n_segments=n_segments,
    )
    blocks = build_blocks(
        units,
        uc,
        system,
        horizon_h=horizon_h,
        eua_col=eua_col,
        fuel_price_cols=fuel_price_cols,
        availability=availability,
        n_segments=n_segments,
    )
    net = net_demand(
        system.loc[system.index[:horizon_h]],
        demand_col=demand_col,
        renewable_cols=renewable_cols,
    )
    prices = clear_day(blocks, net)
    return DailyResult(uc=uc, blocks=blocks, clearing_price=prices)
