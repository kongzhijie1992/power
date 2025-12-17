from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd

from .bidding import Block


@dataclass(frozen=True)
class ClearResult:
    clearing_price_eur_per_mwh: float
    dispatched_mw_by_unit: Dict[str, float]
    dispatched_blocks: List[Tuple[Block, float]]


def clear_hour(blocks: List[Block], net_demand_mw: float) -> ClearResult:
    if net_demand_mw <= 0:
        return ClearResult(
            clearing_price_eur_per_mwh=0.0,
            dispatched_mw_by_unit={},
            dispatched_blocks=[],
        )

    sorted_blocks = sorted(
        blocks, key=lambda b: (b.price_eur_per_mwh, b.unit_id, b.segment)
    )
    remaining = float(net_demand_mw)
    dispatched: List[Tuple[Block, float]] = []
    by_unit: Dict[str, float] = {}
    price = 0.0
    for b in sorted_blocks:
        if remaining <= 0:
            break
        take = min(float(b.q_mw), remaining)
        if take <= 0:
            continue
        dispatched.append((b, take))
        by_unit[b.unit_id] = by_unit.get(b.unit_id, 0.0) + take
        remaining -= take
        price = float(b.price_eur_per_mwh)

    return ClearResult(
        clearing_price_eur_per_mwh=price,
        dispatched_mw_by_unit=by_unit,
        dispatched_blocks=dispatched,
    )


def clear_day(
    blocks: List[Block],
    demand: pd.Series,
) -> pd.Series:
    prices: Dict[pd.Timestamp, float] = {}
    for t, d in demand.items():
        hour_blocks = [b for b in blocks if b.hour == t]
        prices[t] = clear_hour(hour_blocks, float(d)).clearing_price_eur_per_mwh
    return pd.Series(prices).sort_index()
