from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import pulp

from .costing import (
    Unit,
    compute_segment_prices,
    coerce_hours_index,
    net_demand,
)


@dataclass(frozen=True)
class UCResult:
    status: str
    objective: float
    u: pd.DataFrame
    v: pd.DataFrame
    w: pd.DataFrame
    p: pd.DataFrame
    run_length_h: pd.DataFrame
    offline_hours: pd.DataFrame


def _bool_allowed(avail: float) -> int:
    return 1 if float(avail or 0.0) > 0.0 else 0


def solve_uc_day(
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
    initial_on: Optional[Dict[str, int]] = None,
    initial_offline_h: Optional[Dict[str, float]] = None,
    solver: Optional[pulp.LpSolver] = None,
) -> UCResult:
    """
    Solve a 24h unit commitment MILP and return the UC schedule plus derived run-lengths and offline hours.

    This is intended for aggregated fleets / clusters (not thousands of individual plants).
    """
    idx = coerce_hours_index(system, horizon_h=horizon_h)
    sys = system.loc[idx]
    demand = net_demand(
        sys, demand_col=demand_col, renewable_cols=renewable_cols
    )

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

    if eua_col not in sys.columns:
        sys = sys.copy()
        sys[eua_col] = 0.0
    eua = pd.to_numeric(sys[eua_col], errors="coerce").fillna(0.0)

    if availability is None:
        availability = pd.DataFrame(
            1.0, index=idx, columns=[u.unit_id for u in units]
        )
    else:
        availability = availability.reindex(
            index=idx, columns=[u.unit_id for u in units]
        ).fillna(1.0)

    initial_on = initial_on or {}
    initial_offline_h = initial_offline_h or {}

    prob = pulp.LpProblem("UC_Day", pulp.LpMinimize)

    u_var: Dict[Tuple[str, pd.Timestamp], pulp.LpVariable] = {}
    v_var: Dict[Tuple[str, pd.Timestamp], pulp.LpVariable] = {}
    w_var: Dict[Tuple[str, pd.Timestamp], pulp.LpVariable] = {}
    p_var: Dict[Tuple[str, pd.Timestamp], pulp.LpVariable] = {}
    p_seg: Dict[Tuple[str, pd.Timestamp, int], pulp.LpVariable] = {}

    for unit in units:
        for t in idx:
            u_var[(unit.unit_id, t)] = pulp.LpVariable(
                f"u_{unit.unit_id}_{t}", cat="Binary"
            )
            v_var[(unit.unit_id, t)] = pulp.LpVariable(
                f"v_{unit.unit_id}_{t}", cat="Binary"
            )
            w_var[(unit.unit_id, t)] = pulp.LpVariable(
                f"w_{unit.unit_id}_{t}", cat="Binary"
            )
            p_var[(unit.unit_id, t)] = pulp.LpVariable(
                f"p_{unit.unit_id}_{t}", lowBound=0, cat="Continuous"
            )
            for k in range(1, n_segments + 1):
                p_seg[(unit.unit_id, t, k)] = pulp.LpVariable(
                    f"pseg_{unit.unit_id}_{t}_{k}",
                    lowBound=0,
                    cat="Continuous",
                )

    obj_terms: List[pulp.LpAffineExpression] = []
    for unit in units:
        fuel_col = unit.fuel_price_col or fuel_price_cols.get(unit.fuel_type)
        fuel_price_series = (
            pd.to_numeric(sys[fuel_col], errors="coerce").fillna(0.0)
            if fuel_col and fuel_col in sys.columns
            else pd.Series(0.0, index=idx)
        )
        for t in idx:
            prices = compute_segment_prices(
                unit,
                fuel_price_eur_per_mwh_fuel=float(fuel_price_series.loc[t]),
                eua_price_eur_per_tco2=float(eua.loc[t]),
                n_segments=n_segments,
            )
            avail = float(availability.loc[t, unit.unit_id])
            pmin_t = float(unit.p_min_mw) * avail
            pmax_t = float(unit.p_max_mw) * avail

            obj_terms.append(
                float(prices[0]) * pmin_t * u_var[(unit.unit_id, t)]
            )
            for k in range(1, n_segments + 1):
                obj_terms.append(
                    float(prices[k]) * p_seg[(unit.unit_id, t, k)]
                )
            if unit.startup_cost_eur:
                obj_terms.append(
                    float(unit.startup_cost_eur) * v_var[(unit.unit_id, t)]
                )

            prob += p_var[(unit.unit_id, t)] == pmin_t * u_var[
                (unit.unit_id, t)
            ] + pulp.lpSum(
                p_seg[(unit.unit_id, t, k)] for k in range(1, n_segments + 1)
            )
            prob += (
                p_var[(unit.unit_id, t)] <= pmax_t * u_var[(unit.unit_id, t)]
            )

            headroom = max(0.0, pmax_t - pmin_t)
            seg_cap = headroom / max(1, n_segments)
            for k in range(1, n_segments + 1):
                prob += (
                    p_seg[(unit.unit_id, t, k)]
                    <= seg_cap * u_var[(unit.unit_id, t)]
                )

            if unit.is_must_run and pmin_t > 0:
                prob += u_var[(unit.unit_id, t)] == 1

            prob += u_var[(unit.unit_id, t)] <= _bool_allowed(avail)

    prob += pulp.lpSum(obj_terms)

    for t in idx:
        prob += pulp.lpSum(
            p_var[(unit.unit_id, t)] for unit in units
        ) == float(demand.loc[t])

    for unit in units:
        for j, t in enumerate(idx):
            if j == 0:
                u0 = int(initial_on.get(unit.unit_id, 0))
                prob += (
                    u_var[(unit.unit_id, t)] - u0
                    == v_var[(unit.unit_id, t)] - w_var[(unit.unit_id, t)]
                )
            else:
                t_prev = idx[j - 1]
                prob += (
                    u_var[(unit.unit_id, t)] - u_var[(unit.unit_id, t_prev)]
                    == v_var[(unit.unit_id, t)] - w_var[(unit.unit_id, t)]
                )

    for unit in units:
        up = int(max(0, unit.min_up_h))
        down = int(max(0, unit.min_down_h))
        if up > 0:
            for j, t in enumerate(idx):
                end = min(j + up, len(idx))
                prob += (
                    pulp.lpSum(
                        u_var[(unit.unit_id, idx[k])] for k in range(j, end)
                    )
                    >= up * v_var[(unit.unit_id, t)]
                )
        if down > 0:
            for j, t in enumerate(idx):
                end = min(j + down, len(idx))
                prob += (
                    pulp.lpSum(
                        1 - u_var[(unit.unit_id, idx[k])]
                        for k in range(j, end)
                    )
                    >= down * w_var[(unit.unit_id, t)]
                )

    for unit in units:
        for j, t in enumerate(idx):
            if j == 0:
                continue
            t_prev = idx[j - 1]
            avail_t = float(availability.loc[t, unit.unit_id])
            avail_prev = float(availability.loc[t_prev, unit.unit_id])
            pmax_t = float(unit.p_max_mw) * avail_t
            pmax_prev = float(unit.p_max_mw) * avail_prev

            ru = float(
                unit.ramp_up_mw_per_h if unit.ramp_up_mw_per_h > 0 else pmax_t
            )
            rd = float(
                unit.ramp_down_mw_per_h
                if unit.ramp_down_mw_per_h > 0
                else pmax_prev
            )

            prob += p_var[(unit.unit_id, t)] - p_var[
                (unit.unit_id, t_prev)
            ] <= ru + pmax_t * (1 - u_var[(unit.unit_id, t_prev)])
            prob += p_var[(unit.unit_id, t_prev)] - p_var[
                (unit.unit_id, t)
            ] <= rd + pmax_prev * (1 - u_var[(unit.unit_id, t)])

    if solver is None:
        solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    unit_ids = [u.unit_id for u in units]

    u_df = pd.DataFrame(index=idx, columns=unit_ids, dtype=int)
    v_df = pd.DataFrame(index=idx, columns=unit_ids, dtype=int)
    w_df = pd.DataFrame(index=idx, columns=unit_ids, dtype=int)
    p_df = pd.DataFrame(index=idx, columns=unit_ids, dtype=float)
    for unit in units:
        for t in idx:
            u_df.loc[t, unit.unit_id] = int(
                round(u_var[(unit.unit_id, t)].value() or 0)
            )
            v_df.loc[t, unit.unit_id] = int(
                round(v_var[(unit.unit_id, t)].value() or 0)
            )
            w_df.loc[t, unit.unit_id] = int(
                round(w_var[(unit.unit_id, t)].value() or 0)
            )
            p_df.loc[t, unit.unit_id] = float(
                p_var[(unit.unit_id, t)].value() or 0.0
            )

    run_len = pd.DataFrame(0, index=idx, columns=unit_ids, dtype=int)
    for unit in units:
        on = u_df[unit.unit_id].astype(int).tolist()
        for j, t in enumerate(idx):
            if v_df.loc[t, unit.unit_id] != 1:
                continue
            length = 0
            for k in range(j, len(idx)):
                if on[k] != 1:
                    break
                length += 1
            run_len.loc[t, unit.unit_id] = length

    offline = pd.DataFrame(0.0, index=idx, columns=unit_ids, dtype=float)
    for unit in units:
        off_h = float(initial_offline_h.get(unit.unit_id, 9999.0))
        prev_on = int(initial_on.get(unit.unit_id, 0))
        for t in idx:
            if prev_on == 0:
                offline.loc[t, unit.unit_id] = off_h
            if u_df.loc[t, unit.unit_id] == 1:
                off_h = 0.0
                prev_on = 1
            else:
                off_h += 1.0
                prev_on = 0

    return UCResult(
        status=status,
        objective=float(pulp.value(prob.objective) or 0.0),
        u=u_df,
        v=v_df,
        w=w_df,
        p=p_df,
        run_length_h=run_len,
        offline_hours=offline,
    )
