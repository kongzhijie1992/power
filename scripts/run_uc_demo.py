"""Run a small unit-commitment demo using synthetic demand and a tiny unit fleet."""

import sys
from pathlib import Path

# Add parent directory to path so 'src' can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.dispatch.unit_commitment import solve_uc


def main():
    # synthetic 24h demand
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    idx = pd.date_range(now, periods=24, freq="H")
    demand = pd.Series(8000 + 2000 * np.sin(2 * np.pi * idx.hour / 24), index=idx)

    units = [
        {
            "name": "Nuclear",
            "p_min": 1000,
            "p_max": 3000,
            "marginal_cost": 10.0,
            "startup_cost": 1000.0,
        },
        {
            "name": "Coal",
            "p_min": 500,
            "p_max": 4000,
            "marginal_cost": 50.0,
            "startup_cost": 500.0,
        },
        {
            "name": "Gas",
            "p_min": 0,
            "p_max": 5000,
            "marginal_cost": 70.0,
            "startup_cost": 300.0,
        },
        {
            "name": "Wind",
            "p_min": 0,
            "p_max": 2000,
            "marginal_cost": 0.0,
            "startup_cost": 0.0,
        },
    ]

    res = solve_uc(units, demand, horizon_hours=24)
    print("UC status:", res["status"])
    print("Objective:", res["objective"])
    print(res["dispatch"].head())


if __name__ == "__main__":
    main()
