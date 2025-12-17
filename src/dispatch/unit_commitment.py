"""A small mixed-integer unit commitment solver using PuLP.

This is a prototype: it models on/off states and production limits per hour and minimizes fuel cost.
PuLP with CBC solver is recommended (install via `pip install pulp`).
"""

from typing import Dict, List
import pandas as pd
import pulp


def solve_uc(
    units: List[Dict], demand: pd.Series, horizon_hours: int = 24, solver=None
):
    """Solve a UC over `horizon_hours` with on/off, startup/shutdown, min up/down and ramp constraints.

    units: list of dicts with keys:
      - 'name'
      - 'p_min', 'p_max'
      - 'marginal_cost'
      - optional: 'startup_cost', 'min_up', 'min_down', 'ramp_up', 'ramp_down'

    demand: pd.Series indexed by timestamps (length should be >= horizon_hours)
    Returns dict with status, dispatch DataFrame, and objective value.
    """
    # prepare time index
    idx = list(demand.index[:horizon_hours])
    prob = pulp.LpProblem("UC", pulp.LpMinimize)

    # variables
    p = {}
    on = {}
    startup = {}
    shutdown = {}
    for u in units:
        name = u["name"]
        for t in idx:
            p[(name, t)] = pulp.LpVariable(
                f"p_{name}_{t}", lowBound=0, upBound=u["p_max"], cat="Continuous"
            )
            on[(name, t)] = pulp.LpVariable(f"on_{name}_{t}", cat="Binary")
            startup[(name, t)] = pulp.LpVariable(f"start_{name}_{t}", cat="Binary")
            shutdown[(name, t)] = pulp.LpVariable(f"shutdown_{name}_{t}", cat="Binary")

    # objective: fuel cost + startup costs
    obj_terms = []
    for u in units:
        name = u["name"]
        mc = u.get("marginal_cost", 100.0)
        sc = u.get("startup_cost", 0.0)
        for t in idx:
            obj_terms.append(mc * p[(name, t)])
            if sc:
                obj_terms.append(sc * startup[(name, t)])
    prob += pulp.lpSum(obj_terms)

    # demand balance per hour
    for t in idx:
        prob += pulp.lpSum([p[(u["name"], t)] for u in units]) == float(demand.loc[t])

    # production bounds linked to on
    for u in units:
        name = u["name"]
        pmin = u.get("p_min", 0.0)
        pmax = u["p_max"]
        for t in idx:
            prob += p[(name, t)] <= pmax * on[(name, t)]
            prob += p[(name, t)] >= pmin * on[(name, t)]

    # startup/shutdown relationship: on_t - on_{t-1} = start_t - shut_t
    for u in units:
        name = u["name"]
        for i, t in enumerate(idx):
            if i == 0:
                # assume off before horizon
                prob += on[(name, t)] - 0 == startup[(name, t)] - shutdown[(name, t)]
            else:
                t_prev = idx[i - 1]
                prob += (
                    on[(name, t)] - on[(name, t_prev)]
                    == startup[(name, t)] - shutdown[(name, t)]
                )

    # min up / min down constraints (big-M style linking)
    for u in units:
        name = u["name"]
        min_up = int(u.get("min_up", 0))
        min_down = int(u.get("min_down", 0))
        if min_up > 0:
            for i, t in enumerate(idx):
                # sum_{tau=t}^{t+min_up-1} on_tau >= min_up * start_t
                end_i = min(i + min_up, len(idx))
                prob += (
                    pulp.lpSum([on[(name, idx[j])] for j in range(i, end_i)])
                    >= min_up * startup[(name, t)]
                )
        if min_down > 0:
            for i, t in enumerate(idx):
                end_i = min(i + min_down, len(idx))
                prob += (
                    pulp.lpSum([1 - on[(name, idx[j])] for j in range(i, end_i)])
                    >= min_down * shutdown[(name, t)]
                )

    # ramp constraints
    for u in units:
        name = u["name"]
        ramp_up = float(u.get("ramp_up", u.get("p_max", 1e6)))
        ramp_down = float(u.get("ramp_down", u.get("p_max", 1e6)))
        for i, t in enumerate(idx):
            if i == 0:
                # no ramp constraint for first period vs outside horizon
                continue
            t_prev = idx[i - 1]
            prob += p[(name, t)] - p[(name, t_prev)] <= ramp_up
            prob += p[(name, t_prev)] - p[(name, t)] <= ramp_down

    # solve
    if solver is None:
        solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    dispatch = pd.DataFrame(index=idx)
    for u in units:
        name = u["name"]
        vals = [p[(name, t)].varValue for t in idx]
        dispatch[name] = vals
    return {
        "status": status,
        "dispatch": dispatch,
        "objective": pulp.value(prob.objective),
    }
