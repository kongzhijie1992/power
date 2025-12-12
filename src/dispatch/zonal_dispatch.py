"""Zonal dispatch using generation mix (per fuel) to build a simplified merit order.

This module expects a generation-mix DataFrame with columns for fuel types containing available MW.
"""
from typing import Dict, List
import pandas as pd


DEFAULT_MARGINAL_COST = {
    'nuclear': 10.0,
    'hydro': 5.0,
    'wind': 0.0,
    'solar': 0.0,
    'coal': 50.0,
    'gas': 70.0,
    'oil': 100.0,
    'other': 80.0,
}


def build_generators_from_mix(gen_mix_row: pd.Series, cost_map: Dict = None) -> List[Dict]:
    cost_map = cost_map or DEFAULT_MARGINAL_COST
    gens = []
    for fuel, cap in gen_mix_row.items():
        cap_mw = float(cap)
        if cap_mw <= 0:
            continue
        cost = float(cost_map.get(fuel.lower(), cost_map.get('other', 100.0)))
        gens.append({'name': fuel, 'capacity': cap_mw, 'marginal_cost': cost})
    return gens


def dispatch_series_with_mix(demand_series: pd.Series, gen_mix: pd.DataFrame, cost_map: Dict = None) -> pd.DataFrame:
    rows = []
    # align indices
    gen_mix = gen_mix.reindex(demand_series.index, method='ffill').fillna(0)
    for ts, demand in demand_series.items():
        row = gen_mix.loc[ts]
        gens = build_generators_from_mix(row, cost_map=cost_map)
        # use the simple merit order function from merit_order module to compute price
        from src.dispatch.merit_order import merit_order_clearing
        res = merit_order_clearing(float(demand), gens)
        rows.append({'ts': ts, 'price': res['clearing_price']})
    return pd.DataFrame(rows).set_index('ts')
