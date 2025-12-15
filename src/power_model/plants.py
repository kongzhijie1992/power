from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

OPSD_URL = "https://data.open-power-system-data.org/conventional_power_plants/latest/conventional_power_plants_EU.csv"

THERMAL_FUELS = {"lignite", "coal", "gas", "oil"}

EFFICIENCY = {
    "lignite": 0.36,
    "coal": 0.40,
    "ccgt": 0.57,
    "ocgt": 0.34,
    "gas": 0.50,
    "oil": 0.38,
}

CO2_INTENSITY = {
    "lignite": 1.05,
    "coal": 0.90,
    "ccgt": 0.36,
    "ocgt": 0.36,
    "gas": 0.36,
    "oil": 0.78,
}

VOM = {
    "lignite": 1.0,
    "coal": 2.0,
    "ccgt": 2.0,
    "ocgt": 4.0,
    "gas": 2.5,
    "oil": 3.0,
}


def fetch_opsd_conventional(cache_path: Path | None = None, force: bool = False) -> pd.DataFrame:
    """Download OPSD conventional power plants CSV (or load from cache)."""
    if cache_path is None:
        cache_path = Path("data/external/opsd_conventional_power_plants.csv")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        return pd.read_csv(cache_path)
    df = pd.read_csv(OPSD_URL)
    df.to_csv(cache_path, index=False)
    return df


def _map_fuel(row: pd.Series) -> Optional[str]:
    es = str(row.get("energy_source", "")).lower()
    lvl2 = str(row.get("energy_source_level_2", "")).lower()
    if "lignite" in es or "lignite" in lvl2:
        return "lignite"
    if "coal" in es or "hard coal" in lvl2:
        return "coal"
    if "gas" in es:
        return "gas"
    if "oil" in es:
        return "oil"
    return None


def _map_stack_type(row: pd.Series) -> str:
    fuel = row["fuel"]
    tech = str(row.get("technology", "")).lower()
    if fuel == "gas":
        if "combined" in tech or "ccgt" in tech or "cycle" in tech:
            return "ccgt"
        if "turbine" in tech or "ocgt" in tech or "open" in tech:
            return "ocgt"
    return fuel


def enrich_thermal_plants(
    raw: pd.DataFrame, countries: Iterable[str] | None = ("DE", "LU"), min_capacity_mw: float = 20.0
) -> pd.DataFrame:
    """Filter OPSD plants to thermal units (optionally by country) and attach heat-rate/CO2 defaults."""
    df = raw.copy()
    if countries:
        try:
            if isinstance(countries, str):
                countries_list = [countries]
            else:
                countries_list = list(countries)
        except TypeError:
            countries_list = [countries]
        df = df[df["country"].isin(countries_list)]
    df["fuel"] = df.apply(_map_fuel, axis=1)
    df = df[df["fuel"].isin(THERMAL_FUELS)]
    df["stack_type"] = df.apply(_map_stack_type, axis=1)
    df["capacity_mw"] = pd.to_numeric(df["capacity"], errors="coerce")
    df = df[df["capacity_mw"] >= min_capacity_mw]
    df["efficiency"] = df["stack_type"].map(EFFICIENCY).fillna(df["fuel"].map(EFFICIENCY))
    df["co2_intensity"] = df["stack_type"].map(CO2_INTENSITY).fillna(df["fuel"].map(CO2_INTENSITY))
    df["vom"] = df["stack_type"].map(VOM).fillna(df["fuel"].map(VOM)).fillna(2.0)
    df["is_chp"] = df["chp"].fillna("").astype(str).str.lower().isin({"yes", "y", "true", "1"})
    df["commissioned_year"] = pd.to_numeric(df["commissioned"], errors="coerce")
    keep_cols = [
        "name",
        "country",
        "fuel",
        "stack_type",
        "capacity_mw",
        "efficiency",
        "co2_intensity",
        "vom",
        "is_chp",
        "commissioned_year",
        "eic_code",
        "technology",
        "lat",
        "lon",
    ]
    for col in keep_cols:
        if col not in df.columns:
            df[col] = pd.NA
    return df[keep_cols].reset_index(drop=True)


@dataclass
class PlantStack:
    plants: pd.DataFrame

    @classmethod
    def from_opsd(
        cls, force: bool = False, countries: Iterable[str] | None = ("DE", "LU"), min_capacity_mw: float = 20.0
    ) -> "PlantStack":
        raw = fetch_opsd_conventional(force=force)
        enriched = enrich_thermal_plants(raw, countries=countries, min_capacity_mw=min_capacity_mw)
        return cls(plants=enriched)

    def to_blocks(self, availability_factor: float = 1.0) -> List[dict]:
        blocks = []
        for _, row in self.plants.iterrows():
            blocks.append(
                {
                    "name": row["name"],
                    "fuel": row["fuel"],
                    "capacity": float(row["capacity_mw"]) * availability_factor,
                    "marginal_cost": None,  # filled later in model
                    "efficiency": float(row["efficiency"]),
                    "co2_intensity": float(row["co2_intensity"]),
                    "vom": float(row["vom"]),
                }
            )
        return blocks
