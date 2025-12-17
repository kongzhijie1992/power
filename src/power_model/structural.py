from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .plants import PlantStack
DEFAULT_BLOCKS = [
    {"name": "lignite", "fuel": "lignite", "capacity_mw": 8000, "efficiency": 0.38, "co2_intensity": 1.05, "vom": 1.0},
    {"name": "coal", "fuel": "coal", "capacity_mw": 12000, "efficiency": 0.40, "co2_intensity": 0.9, "vom": 2.0},
    {"name": "ccgt_efficient", "fuel": "gas", "capacity_mw": 15000, "efficiency": 0.58, "co2_intensity": 0.36, "vom": 2.0},
    {"name": "ccgt_marginal", "fuel": "gas", "capacity_mw": 8000, "efficiency": 0.50, "co2_intensity": 0.36, "vom": 2.5},
    {"name": "ocgt", "fuel": "gas", "capacity_mw": 2000, "efficiency": 0.34, "co2_intensity": 0.36, "vom": 4.0},
]


@dataclass
class StructuralConfig:
    blocks: List[Dict] = None
    negative_price_floor: float = -200.0
    uplift_scale: float = 50.0
    uplift_power: float = 2.0
    reserve_margin_floor: float = 0.1  # 10% margin before scarcity kicks in
    default_fuel_prices: Dict[str, float] = None

    def __post_init__(self):
        if self.blocks is None:
            self.blocks = DEFAULT_BLOCKS
        if self.default_fuel_prices is None:
            self.default_fuel_prices = {
                "lignite": 3.0,
                "coal": 12.0,
                "gas": 30.0,
                "oil": 60.0,
                "nuclear": 8.0,
                "biomass": 20.0,
                "waste": 0.0,
                "mixed_fossil": 20.0,
            }
        else:
            fallback = {
                "lignite": 3.0,
                "coal": 12.0,
                "gas": 30.0,
                "oil": 60.0,
                "nuclear": 8.0,
                "biomass": 20.0,
                "waste": 0.0,
                "mixed_fossil": 20.0,
            }
            for fuel, price in fallback.items():
                self.default_fuel_prices.setdefault(fuel, price)


class StructuralStackModel:
    """Merit-order structural price model for DE-LU power."""

    def __init__(self, config: Optional[StructuralConfig] = None):
        self.config = config or StructuralConfig()

    def _fuel_price(self, row: pd.Series, fuel: str) -> float:
        col = f"{fuel}_price"
        if col in row and pd.notna(row[col]):
            return float(row[col])
        if fuel == "gas" and "gas_price" in row and pd.notna(row["gas_price"]):
            return float(row["gas_price"])
        return self.config.default_fuel_prices.get(fuel, 0.0)

    def _available_blocks(self, row: pd.Series) -> List[Dict]:
        avail = float(row.get("availability_factor", 1.0))
        blocks = []
        for block in self.config.blocks:
            fuel_price = self._fuel_price(row, block["fuel"])
            co2_price = float(row.get("eua_price", 0.0))
            srmc = fuel_price / block["efficiency"] + co2_price * block["co2_intensity"] + block["vom"]
            blocks.append(
                {
                    "name": block["name"],
                    "fuel": block["fuel"],
                    "capacity": block["capacity_mw"] * avail,
                    "marginal_cost": srmc,
                }
            )
        return blocks

    def _scarcity_uplift(self, reserve_margin: float) -> float:
        shortfall = max(0.0, self.config.reserve_margin_floor - reserve_margin)
        return self.config.uplift_scale * (shortfall ** self.config.uplift_power)

    def _clear_price(
        self,
        demand_mw: float,
        renewable_mw: float,
        blocks: List[Dict],
    ) -> Tuple[float, Dict]:
        if renewable_mw >= demand_mw:
            return self.config.negative_price_floor, {"reason": "renewable_oversupply"}

        remaining = demand_mw - renewable_mw
        sorted_blocks = sorted(blocks, key=lambda b: b["marginal_cost"])
        dispatched = []
        total_cap = sum(b["capacity"] for b in sorted_blocks)

        if remaining <= 0:
            return self.config.negative_price_floor, {"reason": "no_thermal_needed"}

        for block in sorted_blocks:
            take = min(block["capacity"], remaining)
            dispatched.append({"name": block["name"], "dispatched_mw": take, "marginal_cost": block["marginal_cost"]})
            remaining -= take
            if remaining <= 0:
                price = block["marginal_cost"]
                break
        else:
            price = sorted_blocks[-1]["marginal_cost"]

        reserve_margin = (total_cap - (demand_mw - renewable_mw)) / max(demand_mw, 1.0)
        uplift = self._scarcity_uplift(reserve_margin)
        price_with_uplift = price + uplift
        return price_with_uplift, {"dispatched": dispatched, "reserve_margin": reserve_margin, "uplift": uplift}

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute structural price time series."""
        required = ["load_forecast", "wind_forecast", "solar_forecast", "gas_price", "eua_price"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"missing structural inputs: {missing}")
        out_rows = []
        for ts, row in df.iterrows():
            demand = float(row.get("load_forecast", 0.0))
            wind = float(row.get("wind_actual", row.get("wind_forecast", 0.0)))
            solar = float(row.get("solar_actual", row.get("solar_forecast", 0.0)))
            renewable = max(0.0, wind + solar)
            blocks = self._available_blocks(row)
            price, detail = self._clear_price(demand, renewable, blocks)
            out_rows.append({"datetime": ts, "structural_price": price, "reserve_margin": detail.get("reserve_margin", 0.0), "scarcity_uplift": detail.get("uplift", 0.0)})
        out = pd.DataFrame(out_rows).set_index("datetime")
        return out


class PlantStackModel(StructuralStackModel):
    """Structural model using plant-level stack instead of aggregated blocks."""

    def __init__(self, plant_stack: PlantStack, config: Optional[StructuralConfig] = None):
        super().__init__(config)
        self.plant_stack = plant_stack

    def _available_blocks(self, row: pd.Series) -> List[Dict]:
        sys_avail_raw = row.get("availability_factor", 1.0)
        system_avail = float(sys_avail_raw) if pd.notna(sys_avail_raw) else 1.0
        blocks = []
        co2_price = float(row.get("eua_price", 0.0))
        for _, plant in self.plant_stack.plants.iterrows():
            if plant.get("is_dispatchable", True) is False:
                continue
            fuel_price = self._fuel_price(row, plant["fuel"])
            eff = float(plant["efficiency"]) if pd.notna(plant["efficiency"]) else 1.0
            eff = eff if eff > 0 else 1.0
            plant_avail_raw = plant.get("availability_factor", 1.0)
            plant_avail = float(plant_avail_raw) if pd.notna(plant_avail_raw) else 1.0
            srmc = fuel_price / eff + co2_price * float(plant["co2_intensity"]) + float(plant["vom"])
            blocks.append(
                {
                    "name": plant["name"],
                    "fuel": plant["fuel"],
                    "capacity": plant["capacity_mw"] * system_avail * plant_avail,
                    "marginal_cost": srmc,
                }
            )
        return blocks
