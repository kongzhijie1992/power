from typing import List, Dict
import pandas as pd


def merit_order_clearing(demand_mw: float, generators: List[Dict]) -> Dict:
    """Simple merit-order clearing.

    generators: list of dicts with keys: 'name', 'capacity', 'marginal_cost'
    Returns clearing price and dispatch per unit.
    """
    # Build supply curve
    gens = sorted(generators, key=lambda g: g["marginal_cost"])
    remaining = demand_mw
    dispatch = []
    price = None
    for g in gens:
        take = min(g["capacity"], remaining)
        dispatch.append(
            {
                "name": g["name"],
                "dispatched_mw": take,
                "marginal_cost": g["marginal_cost"],
            }
        )
        remaining -= take
        if remaining <= 0:
            price = g["marginal_cost"]
            break
    if remaining > 0:
        # unmet demand -> set price to very high
        price = max([g["marginal_cost"] for g in gens]) * 2
    return {"clearing_price": price, "dispatch": dispatch}


def dispatch_time_series(
    demand_series: pd.Series, generators: List[Dict]
) -> pd.DataFrame:
    rows = []
    for ts, demand in demand_series.items():
        res = merit_order_clearing(float(demand), generators)
        rows.append({"ts": ts, "price": res["clearing_price"]})
    df = pd.DataFrame(rows).set_index("ts")
    return df
