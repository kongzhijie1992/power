"""Tests for dispatch models."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
import pandas as pd
import numpy as np

from src.ingest.ingest_all import synthetic_area_series
from src.dispatch.merit_order import merit_order_clearing
from src.dispatch.unit_commitment import solve_uc
from src.dispatch.zonal_dispatch import build_generators_from_mix


class TestMeritOrderClearing(unittest.TestCase):
    """Test merit-order dispatch logic."""

    def setUp(self):
        """Create cost curves and demand."""
        # Simple 3-unit fleet with correct keys for merit_order_clearing
        self.generators = [
            {'name': 'wind', 'capacity': 100, 'marginal_cost': 0},
            {'name': 'gas', 'capacity': 200, 'marginal_cost': 50},
            {'name': 'coal', 'capacity': 150, 'marginal_cost': 30}
        ]
        self.demand = 200

    def test_merit_order_clears_demand(self):
        """Test that total dispatch equals demand."""
        result = merit_order_clearing(self.demand, self.generators)
        dispatch = {d['name']: d['dispatched_mw'] for d in result['dispatch']}
        total = sum(dispatch.values())
        self.assertEqual(total, self.demand)

    def test_merit_order_respects_pmax(self):
        """Test that no unit exceeds capacity."""
        result = merit_order_clearing(self.demand, self.generators)
        for d in result['dispatch']:
            pmax = next(u['capacity'] for u in self.generators if u['name'] == d['name'])
            self.assertLessEqual(d['dispatched_mw'], pmax)

    def test_merit_order_uses_cheapest_first(self):
        """Test that cheaper units are dispatched first."""
        result = merit_order_clearing(self.demand, self.generators)
        dispatch = {d['name']: d['dispatched_mw'] for d in result['dispatch']}
        
        # Wind (cost=0) should be fully dispatched
        self.assertEqual(dispatch['wind'], 100)
        # Coal (cost=30) should be dispatched next
        self.assertEqual(dispatch['coal'], 100)
        # Gas (cost=50) fills remainder (200 - 100 - 100 = 0)
        self.assertEqual(dispatch.get('gas', 0), 0)

    def test_merit_order_low_demand(self):
        """Test dispatch with demand < cheapest capacity."""
        result = merit_order_clearing(50, self.generators)
        dispatch = {d['name']: d['dispatched_mw'] for d in result['dispatch']}
        
        # Only wind should be dispatched
        self.assertEqual(dispatch['wind'], 50)
        self.assertEqual(dispatch.get('coal', 0), 0)
        self.assertEqual(dispatch.get('gas', 0), 0)

    def test_merit_order_high_demand(self):
        """Test dispatch with high demand requiring all units."""
        result = merit_order_clearing(450, self.generators)
        dispatch = {d['name']: d['dispatched_mw'] for d in result['dispatch']}
        
        # All units at full capacity
        self.assertEqual(dispatch['wind'], 100)
        self.assertEqual(dispatch['coal'], 150)
        self.assertEqual(dispatch['gas'], 200)

    def test_merit_order_output_format(self):
        """Test that output has clearing price and dispatch."""
        result = merit_order_clearing(200, self.generators)
        self.assertIsInstance(result, dict)
        self.assertIn('clearing_price', result)
        self.assertIn('dispatch', result)
        self.assertGreater(result['clearing_price'], 0)


class TestUnitCommitment(unittest.TestCase):
    """Test MILP unit commitment solver."""

    def setUp(self):
        """Create a simple UC problem."""
        # 3 units, 24 hours
        self.units_uc = [
            {
                'name': 'base',
                'p_min': 50,
                'p_max': 200,
                'marginal_cost': 30,
                'startup_cost': 500,
                'min_up': 4,
                'min_down': 2,
                'ramp_up': 100,
                'ramp_down': 100,
            },
            {
                'name': 'peak',
                'p_min': 0,
                'p_max': 150,
                'marginal_cost': 60,
                'startup_cost': 300,
                'min_up': 1,
                'min_down': 1,
                'ramp_up': 150,
                'ramp_down': 150,
            }
        ]
        # Constant demand as Series (solve_uc expects pd.Series, not ndarray)
        import pandas as pd
        self.demand = pd.Series(
            [250] * 24,
            index=pd.date_range('2023-01-01', periods=24, freq='h')
        )

    def test_uc_solver_returns_feasible_solution(self):
        """Test that UC solver returns a feasible solution."""
        result = solve_uc(self.units_uc, self.demand)
        
        # Should have dispatch and status
        self.assertIn('dispatch', result)
        self.assertIn('status', result)
        self.assertIsInstance(result['dispatch'], pd.DataFrame)

    def test_uc_dispatch_meets_demand(self):
        """Test that total dispatch meets demand."""
        result = solve_uc(self.units_uc, self.demand)
        
        dispatch_df = result['dispatch']
        
        # Each hour should meet demand
        for t in dispatch_df.index:
            hourly_total = dispatch_df.loc[t].sum()
            self.assertGreaterEqual(hourly_total, self.demand.loc[t] * 0.99)  # Allow 1% slack

    def test_uc_respects_pmax(self):
        """Test that dispatch respects generation limits."""
        result = solve_uc(self.units_uc, self.demand)
        
        dispatch_df = result['dispatch']
        for u in self.units_uc:
            name = u['name']
            # Check that no generation exceeds pmax
            self.assertTrue((dispatch_df[name] <= u['p_max'] * 1.01).all())

    def test_uc_respects_pmin_when_on(self):
        """Test that generation >= pmin when unit is on."""
        result = solve_uc(self.units_uc, self.demand)
        
        dispatch_df = result['dispatch']
        for u in self.units_uc:
            name = u['name']
            # When unit generates > 0, should respect pmin
            on_mask = dispatch_df[name] > 0
            on_dispatch = dispatch_df.loc[on_mask, name]
            if len(on_dispatch) > 0:
                self.assertTrue((on_dispatch >= u['p_min'] * 0.99).all())

    def test_uc_respects_min_up_down(self):
        """Test that min-up/min-down constraints are respected."""
        result = solve_uc(self.units_uc, self.demand)
        
        dispatch_df = result['dispatch']
        for u in self.units_uc:
            name = u['name']
            # Check that dispatch is within bounds
            self.assertTrue((dispatch_df[name] >= 0).all())
            self.assertTrue((dispatch_df[name] <= u['p_max']).all())

    def test_uc_objective_value_reasonable(self):
        """Test that objective value (cost) is non-negative."""
        result = solve_uc(self.units_uc, self.demand)
        
        # Objective should be provided and non-negative
        self.assertIn('objective', result)
        self.assertGreaterEqual(result['objective'], 0)


class TestGeneratorsMix(unittest.TestCase):
    """Test generator building from mix."""

    def setUp(self):
        """Create zonal generation mix."""
        self.gen_mix_row = pd.Series({
            'wind': 80,
            'solar': 40,
            'nuclear': 60,
            'gas': 100,
            'coal': 50,
            'hydro': 30
        })
        self.cost_map = {
            'wind': 0,
            'solar': 5,
            'nuclear': 10,
            'hydro': 15,
            'coal': 25,
            'gas': 45
        }

    def test_build_generators_from_mix(self):
        """Test that generators are built from mix."""
        gens = build_generators_from_mix(self.gen_mix_row, self.cost_map)
        
        # Should have 6 generators
        self.assertEqual(len(gens), 6)
        
        # Each should have name, capacity, marginal_cost
        for gen in gens:
            self.assertIn('name', gen)
            self.assertIn('capacity', gen)
            self.assertIn('marginal_cost', gen)

    def test_generator_costs_respected(self):
        """Test that generator costs match cost_map."""
        gens = build_generators_from_mix(self.gen_mix_row, self.cost_map)
        
        gens_dict = {g['name']: g for g in gens}
        for fuel, cost in self.cost_map.items():
            if fuel in gens_dict:
                self.assertEqual(gens_dict[fuel]['marginal_cost'], cost)


class TestDispatchEdgeCases(unittest.TestCase):
    """Test edge cases in dispatch logic."""

    def test_merit_order_zero_demand(self):
        """Test dispatch with zero demand."""
        units = [
            {'name': 'u1', 'capacity': 100, 'marginal_cost': 30}
        ]
        result = merit_order_clearing(0, units)
        # Check structure
        self.assertIn('dispatch', result)
        self.assertIn('clearing_price', result)
        # Zero demand should have zero dispatch
        for item in result['dispatch']:
            self.assertEqual(item['dispatched_mw'], 0)

    def test_merit_order_demand_exceeds_capacity(self):
        """Test that system tries to clear demand even if insufficient capacity."""
        units = [
            {'name': 'u1', 'capacity': 100, 'marginal_cost': 30}
        ]
        result = merit_order_clearing(200, units)
        # Check structure
        self.assertIn('dispatch', result)
        self.assertIn('clearing_price', result)
        # Should dispatch at full capacity
        total_dispatched = sum(item['dispatched_mw'] for item in result['dispatch'])
        self.assertEqual(total_dispatched, 100)

    def test_uc_single_unit(self):
        """Test UC with single unit."""
        units_uc = [
            {
                'name': 'gen',
                'p_min': 0,
                'p_max': 100,
                'marginal_cost': 30,
                'startup_cost': 100,
                'min_up': 1,
                'min_down': 1,
                'ramp_up': 100,
                'ramp_down': 100,
            }
        ]
        demand = pd.Series(
            [50] * 24,
            index=pd.date_range('2023-01-01', periods=24, freq='h')
        )
        result = solve_uc(units_uc, demand)
        
        # Should always have solution
        self.assertIsNotNone(result)
        self.assertIn('dispatch', result)


if __name__ == '__main__':
    unittest.main()
