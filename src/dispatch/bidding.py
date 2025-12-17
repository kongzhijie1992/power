from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .costing import Unit, compute_segment_prices, start_cost
from .uc_model import UCResult


@dataclass(frozen=True)
class Block:
    unit_id: str
    hour: pd.Timestamp
    q_mw: float
    price_eur_per_mwh: float
    kind: str  # commit | incremental | renewable
    segment: int = 0


def enforce_monotone(blocks: List[Block]) -> List[Block]:
    out: List[Block] = []
    last = float("-inf")
    for b in blocks:
        price = max(last, float(b.price_eur_per_mwh))
        last = price
        out.append(
            Block(
                unit_id=b.unit_id,
                hour=b.hour,
                q_mw=float(b.q_mw),
                price_eur_per_mwh=price,
                kind=b.kind,
                segment=b.segment,
            )
        )
    return out


def build_blocks_for_unit_hour(
    unit: Unit,
    hour: pd.Timestamp,
    *,
    uc: UCResult,
    fuel_price_eur_per_mwh_fuel: float,
    eua_price_eur_per_tco2: float,
    availability: float = 1.0,
    n_segments: int = 3,
    risk_buffer_eur_per_mwh: float = 0.1,
) -> List[Block]:
    if int(uc.u.loc[hour, unit.unit_id]) != 1:
        return []

    prices = compute_segment_prices(
        unit,
        fuel_price_eur_per_mwh_fuel=float(fuel_price_eur_per_mwh_fuel),
        eua_price_eur_per_tco2=float(eua_price_eur_per_tco2),
        n_segments=n_segments,
    )

    pmin = float(unit.p_min_mw) * float(availability)
    pmax = float(unit.p_max_mw) * float(availability)
    headroom = max(0.0, pmax - pmin)
    seg_q = headroom / max(1, n_segments)

    start = int(uc.v.loc[hour, unit.unit_id]) == 1
    adder = 0.0
    if start and pmin > 0:
        run_h = (
            int(uc.run_length_h.loc[hour, unit.unit_id] or 0)
            or int(unit.min_up_h or 1)
            or 1
        )
        off_h = float(uc.offline_hours.loc[hour, unit.unit_id] or 0.0)
        sc = start_cost(unit, off_h)
        adder = sc / max(1e-6, float(run_h) * pmin)

    blocks: List[Block] = []
    if pmin > 0:
        blocks.append(
            Block(
                unit_id=unit.unit_id,
                hour=hour,
                q_mw=pmin,
                price_eur_per_mwh=float(prices[0])
                + float(adder)
                + float(risk_buffer_eur_per_mwh),
                kind="commit",
                segment=0,
            )
        )
    for k in range(1, n_segments + 1):
        if seg_q <= 0:
            continue
        blocks.append(
            Block(
                unit_id=unit.unit_id,
                hour=hour,
                q_mw=seg_q,
                price_eur_per_mwh=float(prices[k]),
                kind="incremental",
                segment=k,
            )
        )

    return enforce_monotone(blocks)


def build_blocks(
    units: List[Unit],
    uc: UCResult,
    system: pd.DataFrame,
    *,
    horizon_h: int = 24,
    eua_col: str = "eua_price",
    fuel_price_cols: Optional[Dict[str, str]] = None,
    availability: Optional[pd.DataFrame] = None,
    n_segments: int = 3,
) -> List[Block]:
    if fuel_price_cols is None:
        fuel_price_cols = {
            "gas": "gas_price",
            "coal": "coal_price",
            "lignite": "lignite_price",
            "oil": "oil_price",
            "nuclear": "nuclear_price",
            "biomass": "biomass_price",
            "waste": "waste_price",
            "mixed_fossil": "mixed_fossil_price",
        }
    idx = system.index[:horizon_h]
    sys = system.loc[idx]
    eua = pd.to_numeric(sys.get(eua_col, 0.0), errors="coerce").fillna(0.0)

    if availability is None:
        availability = pd.DataFrame(1.0, index=idx, columns=[u.unit_id for u in units])
    else:
        availability = availability.reindex(
            index=idx, columns=[u.unit_id for u in units]
        ).fillna(1.0)

    all_blocks: List[Block] = []
    for t in idx:
        for unit in units:
            fuel_col = unit.fuel_price_col or fuel_price_cols.get(unit.fuel_type)
            fuel_price = 0.0
            if fuel_col and fuel_col in sys.columns:
                fuel_price = float(
                    pd.to_numeric(sys.loc[t, fuel_col], errors="coerce") or 0.0
                )
            all_blocks.extend(
                build_blocks_for_unit_hour(
                    unit,
                    t,
                    uc=uc,
                    fuel_price_eur_per_mwh_fuel=fuel_price,
                    eua_price_eur_per_tco2=float(eua.loc[t]),
                    availability=float(availability.loc[t, unit.unit_id]),
                    n_segments=n_segments,
                )
            )
    return all_blocks
