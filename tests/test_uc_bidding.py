"""Tests for daily UC + bid block generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

import pandas as pd

from src.dispatch.bidding import build_blocks
from src.dispatch.costing import Unit, compute_segment_prices, net_demand
from src.dispatch.uc_model import solve_uc_day


class TestDailyUCAndBids(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2025-01-01", periods=24, freq="H")
        self.system = pd.DataFrame(
            {
                "demand_mw": 120.0,
                "gas_price": 30.0,
                "coal_price": 12.0,
                "eua_price": 10.0,
            },
            index=idx,
        )

        self.coal = Unit(
            unit_id="coal_1",
            fuel_type="coal",
            p_max_mw=100.0,
            p_min_mw=50.0,
            ramp_up_mw_per_h=100.0,
            ramp_down_mw_per_h=100.0,
            min_up_h=4,
            min_down_h=2,
            startup_cost_eur=2400.0,
            vom_eur_per_mwh=2.0,
            co2_intensity_t_per_mwh_el=0.9,
            efficiency=0.40,
        )

        self.gas = Unit(
            unit_id="gas_1",
            fuel_type="gas",
            p_max_mw=200.0,
            p_min_mw=0.0,
            ramp_up_mw_per_h=200.0,
            ramp_down_mw_per_h=200.0,
            min_up_h=1,
            min_down_h=1,
            startup_cost_eur=0.0,
            vom_eur_per_mwh=2.0,
            co2_intensity_t_per_mwh_el=0.36,
            efficiency=0.50,
        )

        self.units = [self.coal, self.gas]

    def test_uc_feasible_and_meets_demand(self):
        uc = solve_uc_day(self.units, self.system, horizon_h=24)
        self.assertIn(uc.status, {"Optimal", "Feasible"})

        demand = net_demand(self.system)
        hourly_total = uc.p.sum(axis=1)
        for t in demand.index:
            self.assertAlmostEqual(
                float(hourly_total.loc[t]), float(demand.loc[t]), places=3
            )

        for unit in self.units:
            for t in self.system.index:
                p = float(uc.p.loc[t, unit.unit_id])
                on = int(uc.u.loc[t, unit.unit_id])
                self.assertGreaterEqual(p + 1e-6, unit.p_min_mw * on)
                self.assertLessEqual(p, unit.p_max_mw * on + 1e-6)

        for unit in self.units:
            for t_prev, t in zip(
                self.system.index[:-1], self.system.index[1:]
            ):
                p_prev = float(uc.p.loc[t_prev, unit.unit_id])
                p_now = float(uc.p.loc[t, unit.unit_id])
                self.assertLessEqual(
                    p_now - p_prev,
                    unit.ramp_up_mw_per_h + unit.p_max_mw + 1e-6,
                )
                self.assertLessEqual(
                    p_prev - p_now,
                    unit.ramp_down_mw_per_h + unit.p_max_mw + 1e-6,
                )

    def test_bids_include_commit_block_and_monotone_prices(self):
        uc = solve_uc_day(self.units, self.system, horizon_h=24)
        blocks = build_blocks(
            self.units, uc, self.system, horizon_h=24, n_segments=3
        )

        first_hour = self.system.index[0]
        coal_blocks = [
            b for b in blocks if b.hour == first_hour and b.unit_id == "coal_1"
        ]
        self.assertTrue(any(b.kind == "commit" for b in coal_blocks))

        coal_blocks_sorted = sorted(coal_blocks, key=lambda b: b.segment)
        for b_prev, b_now in zip(
            coal_blocks_sorted[:-1], coal_blocks_sorted[1:]
        ):
            self.assertLessEqual(
                b_prev.price_eur_per_mwh, b_now.price_eur_per_mwh + 1e-9
            )

        prices = compute_segment_prices(
            self.coal,
            fuel_price_eur_per_mwh_fuel=12.0,
            eua_price_eur_per_tco2=10.0,
            n_segments=3,
        )
        run_h = int(uc.run_length_h.loc[first_hour, "coal_1"] or 0) or 1
        expected_adder = 2400.0 / (run_h * 50.0)
        commit = next(b for b in coal_blocks if b.kind == "commit")
        self.assertGreaterEqual(
            commit.price_eur_per_mwh, prices[0] + expected_adder
        )


if __name__ == "__main__":
    unittest.main()
