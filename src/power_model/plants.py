from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

OPSD_URL = "https://data.open-power-system-data.org/conventional_power_plants/latest/conventional_power_plants_EU.csv"
RENEWABLE_URL = "https://data.open-power-system-data.org/renewable_power_plants/latest/renewable_power_plants_EU.csv"
RENEWABLE_DISTRIBUTED_THRESHOLD_MW = 5.0

# Keep the historical "thermal" grouping for compatibility with tests/model training.
THERMAL_FUELS = {"lignite", "coal", "gas", "oil"}

DEFAULT_CO2_PRICE = 80.0

ZONE_ALIASES = {
    "east (dk2)": "DK2",
    "west (dk1)": "DK1",
    "se-1": "SE1",
    "se-2": "SE2",
    "se-3": "SE3",
    "se-4": "SE4",
    "nord": "IT_NORD",
    "centro-nord": "IT_CNOR",
    "centro-sud": "IT_CSUD",
    "sud": "IT_SUD",
    "sicilia": "IT_SICI",
    "sardegna": "IT_SARD",
}

# For countries with a single bidding zone we map directly; for DE/LU we expose DE_LU.
COUNTRY_TO_DEFAULT_ZONE = {
    "DE": "DE_LU",
    "LU": "DE_LU",
}

# Technology defaults used to decorate the plant stack for the dashboard and dispatch model.
STACK_DEFAULTS = {
    "nuclear": {
        "efficiency": 0.33,
        "co2_intensity": 0.0,
        "vom": 2.0,
        "p_min_ratio": 0.5,
        "ramp_ratio_per_min": 0.005,
        "min_up_hours": 24,
        "min_down_hours": 48,
        "startup_cost_eur": 50000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 8.0,
        "dispatchable": True,
    },
    "lignite": {
        "efficiency": 0.36,
        "co2_intensity": 1.05,
        "vom": 1.0,
        "p_min_ratio": 0.4,
        "ramp_ratio_per_min": 0.01,
        "min_up_hours": 12,
        "min_down_hours": 12,
        "startup_cost_eur": 15000.0,
        "availability_factor": 0.88,
        "fuel_price_eur_per_mwhth": 3.0,
        "dispatchable": True,
    },
    "coal": {
        "efficiency": 0.40,
        "co2_intensity": 0.90,
        "vom": 2.0,
        "p_min_ratio": 0.35,
        "ramp_ratio_per_min": 0.015,
        "min_up_hours": 8,
        "min_down_hours": 8,
        "startup_cost_eur": 10000.0,
        "availability_factor": 0.85,
        "fuel_price_eur_per_mwhth": 12.0,
        "dispatchable": True,
    },
    "ccgt": {
        "efficiency": 0.57,
        "co2_intensity": 0.36,
        "vom": 2.0,
        "p_min_ratio": 0.2,
        "ramp_ratio_per_min": 0.03,
        "min_up_hours": 4,
        "min_down_hours": 4,
        "startup_cost_eur": 7000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 30.0,
        "dispatchable": True,
    },
    "ocgt": {
        "efficiency": 0.34,
        "co2_intensity": 0.36,
        "vom": 4.0,
        "p_min_ratio": 0.05,
        "ramp_ratio_per_min": 0.1,
        "min_up_hours": 1,
        "min_down_hours": 1,
        "startup_cost_eur": 3000.0,
        "availability_factor": 0.95,
        "fuel_price_eur_per_mwhth": 30.0,
        "dispatchable": True,
    },
    "gas": {
        "efficiency": 0.50,
        "co2_intensity": 0.36,
        "vom": 2.5,
        "p_min_ratio": 0.25,
        "ramp_ratio_per_min": 0.025,
        "min_up_hours": 4,
        "min_down_hours": 4,
        "startup_cost_eur": 6000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 30.0,
        "dispatchable": True,
    },
    "oil": {
        "efficiency": 0.38,
        "co2_intensity": 0.78,
        "vom": 3.0,
        "p_min_ratio": 0.15,
        "ramp_ratio_per_min": 0.04,
        "min_up_hours": 2,
        "min_down_hours": 2,
        "startup_cost_eur": 4000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 60.0,
        "dispatchable": True,
    },
    "biomass": {
        "efficiency": 0.35,
        "co2_intensity": 0.05,
        "vom": 3.0,
        "p_min_ratio": 0.3,
        "ramp_ratio_per_min": 0.02,
        "min_up_hours": 6,
        "min_down_hours": 6,
        "startup_cost_eur": 5000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 20.0,
        "dispatchable": True,
    },
    "waste": {
        "efficiency": 0.30,
        "co2_intensity": 0.45,
        "vom": 3.5,
        "p_min_ratio": 0.25,
        "ramp_ratio_per_min": 0.02,
        "min_up_hours": 4,
        "min_down_hours": 4,
        "startup_cost_eur": 4000.0,
        "availability_factor": 0.85,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": True,
    },
    "mixed_fossil": {
        "efficiency": 0.38,
        "co2_intensity": 0.75,
        "vom": 3.0,
        "p_min_ratio": 0.3,
        "ramp_ratio_per_min": 0.02,
        "min_up_hours": 6,
        "min_down_hours": 6,
        "startup_cost_eur": 6000.0,
        "availability_factor": 0.88,
        "fuel_price_eur_per_mwhth": 20.0,
        "dispatchable": True,
    },
    "hydro_run_of_river": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.0,
        "p_min_ratio": 0.05,
        "ramp_ratio_per_min": 0.25,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.95,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": True,
    },
    "hydro_reservoir": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.5,
        "p_min_ratio": 0.05,
        "ramp_ratio_per_min": 0.3,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.93,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": True,
    },
    "hydro_pumped": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 2.0,
        "p_min_ratio": 0.1,
        "ramp_ratio_per_min": 0.35,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": True,
    },
    "hydro": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.5,
        "p_min_ratio": 0.1,
        "ramp_ratio_per_min": 0.2,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.92,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": True,
    },
    "geothermal": {
        "efficiency": 0.12,
        "co2_intensity": 0.02,
        "vom": 5.0,
        "p_min_ratio": 0.6,
        "ramp_ratio_per_min": 0.01,
        "min_up_hours": 24,
        "min_down_hours": 24,
        "startup_cost_eur": 7000.0,
        "availability_factor": 0.9,
        "fuel_price_eur_per_mwhth": 5.0,
        "dispatchable": True,
    },
    "wind_onshore": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.0,
        "p_min_ratio": 0.0,
        "ramp_ratio_per_min": 1.0,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.30,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": False,
    },
    "wind_offshore": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.0,
        "p_min_ratio": 0.0,
        "ramp_ratio_per_min": 1.0,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.45,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": False,
    },
    "solar_pv_utility": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.0,
        "p_min_ratio": 0.0,
        "ramp_ratio_per_min": 1.0,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.18,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": False,
    },
    "solar_pv_distributed": {
        "efficiency": 1.0,
        "co2_intensity": 0.0,
        "vom": 1.0,
        "p_min_ratio": 0.0,
        "ramp_ratio_per_min": 1.0,
        "min_up_hours": 0,
        "min_down_hours": 0,
        "startup_cost_eur": 0.0,
        "availability_factor": 0.15,
        "fuel_price_eur_per_mwhth": 0.0,
        "dispatchable": False,
    },
}


def fetch_opsd_conventional(
    cache_path: Path | None = None, force: bool = False
) -> pd.DataFrame:
    """Download OPSD conventional power plants CSV (or load from cache)."""
    if cache_path is None:
        cache_path = Path("data/external/opsd_conventional_power_plants.csv")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        return pd.read_csv(cache_path)
    df = pd.read_csv(OPSD_URL)
    df.to_csv(cache_path, index=False)
    return df


def _categorize_renewable_row(row: pd.Series) -> Optional[str]:
    lvl2 = str(row.get("energy_source_level_2", "")).lower()
    tech = str(row.get("technology", "")).lower()
    lvl3 = str(row.get("energy_source_level_3", "")).lower()
    capacity = pd.to_numeric(row.get("electrical_capacity", None), errors="coerce")
    if pd.isna(capacity):
        capacity = 0.0
    if lvl2 == "wind":
        if "offshore" in tech or "offshore" in lvl3:
            return "wind_offshore"
        return "wind_onshore"
    if lvl2 == "solar":
        if "roof" in tech or capacity < RENEWABLE_DISTRIBUTED_THRESHOLD_MW:
            return "solar_pv_distributed"
        return "solar_pv_utility"
    return None


def fetch_opsd_renewable(
    cache_path: Path | None = None, force: bool = False
) -> pd.DataFrame:
    """
    Download OPSD renewable power plants CSV (or load from cache) and aggregate to country-level stacks.
    We keep aggregated onshore/offshore wind and solar (utility/distributed) per country to avoid multi-million rows.
    """
    if cache_path is None:
        cache_path = Path("data/external/opsd_renewable_power_plants_agg.csv")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and not force:
        return pd.read_csv(cache_path)

    usecols = [
        "electrical_capacity",
        "energy_source_level_2",
        "energy_source_level_3",
        "technology",
        "country",
    ]
    df = pd.read_csv(RENEWABLE_URL, usecols=usecols)
    df = df[df["energy_source_level_2"].str.lower().isin({"wind", "solar"})]
    df["stack_hint"] = df.apply(_categorize_renewable_row, axis=1)
    df = df.dropna(subset=["stack_hint", "country"])
    df["capacity"] = pd.to_numeric(df["electrical_capacity"], errors="coerce")
    df = df.dropna(subset=["capacity"])
    grouped = (
        df.groupby(["country", "stack_hint"], as_index=False)["capacity"]
        .sum()
        .rename(columns={"stack_hint": "stack_type"})
    )
    grouped["name"] = grouped.apply(
        lambda r: f"{r['country']} {r['stack_type']}", axis=1
    )
    grouped["energy_source"] = grouped["stack_type"].apply(
        lambda s: "wind" if "wind" in s else "solar"
    )
    grouped["energy_source_level_1"] = "Renewable energy"
    grouped["energy_source_level_2"] = grouped["energy_source"].str.title()
    grouped["energy_source_level_3"] = grouped["stack_type"]
    grouped["technology"] = grouped["stack_type"]
    grouped["commissioned"] = pd.NA
    grouped["chp"] = False
    grouped["eic_code"] = pd.NA
    grouped["additional_info"] = pd.NA
    grouped["lat"] = pd.NA
    grouped["lon"] = pd.NA
    grouped.to_csv(cache_path, index=False)
    return grouped


def _normalize_countries(countries: Iterable[str] | None) -> Optional[List[str]]:
    if countries is None:
        return None
    if isinstance(countries, str):
        return [countries]
    try:
        return list(countries)
    except TypeError:
        return [countries]


def _extract_bidding_zone(row: pd.Series) -> Optional[str]:
    info = " ".join(
        str(val)
        for val in [row.get("additional_info", ""), row.get("comment", "")]
        if pd.notna(val) and str(val) != "nan"
    )
    match = re.search(r"Zone[:\s]+([^;,|]+)", info, flags=re.IGNORECASE)
    if match:
        raw = match.group(1).strip()
        alias_key = raw.lower()
        if alias_key in ZONE_ALIASES:
            return ZONE_ALIASES[alias_key]
        return raw.replace("-", "").upper()

    country = row.get("country")
    if pd.isna(country):
        return None
    if country in COUNTRY_TO_DEFAULT_ZONE:
        return COUNTRY_TO_DEFAULT_ZONE[country]
    return str(country)


def _map_fuel(row: pd.Series) -> Optional[str]:
    es = str(row.get("energy_source", "")).lower()
    lvl1 = str(row.get("energy_source_level_1", "")).lower()
    lvl2 = str(row.get("energy_source_level_2", "")).lower()
    lvl3 = str(row.get("energy_source_level_3", "")).lower()
    tech = str(row.get("technology", "")).lower()
    text = " ".join([es, lvl1, lvl2, lvl3, tech])

    if "nuclear" in text:
        return "nuclear"
    if "lignite" in text:
        return "lignite"
    if "coal" in text:
        return "coal"
    if "gas" in text:
        return "gas"
    if "oil" in text:
        return "oil"
    if "mixed fossil" in text or "other fossil" in text:
        return "mixed_fossil"
    if "waste" in text:
        return "waste"
    if "bio" in text:
        return "biomass"
    if "geothermal" in text:
        return "geothermal"
    if "hydro" in text:
        return "hydro"
    if "wind" in text:
        return "wind"
    if "solar" in text or "photovoltaic" in text:
        return "solar"
    return None


def _map_stack_type(row: pd.Series) -> str:
    fuel = row["fuel"]
    tech = str(row.get("technology", "")).lower()
    lvl2 = str(row.get("energy_source_level_2", "")).lower()
    lvl3 = str(row.get("energy_source_level_3", "")).lower()
    text = " ".join([tech, lvl2, lvl3])

    if fuel == "gas":
        if "combined" in tech or "ccgt" in tech or "cycle" in tech:
            return "ccgt"
        if "turbine" in tech or "ocgt" in tech or "open" in tech:
            return "ocgt"
    if fuel == "hydro":
        if "pumped" in text:
            return "hydro_pumped"
        if "run" in text:
            return "hydro_run_of_river"
        if "reservoir" in text or "storage" in text:
            return "hydro_reservoir"
    if fuel == "wind":
        if "offshore" in text:
            return "wind_offshore"
        return "wind_onshore"
    if fuel == "solar":
        capacity = row.get("capacity_mw")
        if pd.notna(capacity) and capacity < 5:
            return "solar_pv_distributed"
        if "roof" in text:
            return "solar_pv_distributed"
        return "solar_pv_utility"
    return fuel


def _default_for(stack_type: str, field: str):
    return STACK_DEFAULTS.get(stack_type, {}).get(field)


def _load_availability_overrides(
    overrides: pd.DataFrame | Path | None,
) -> Optional[pd.DataFrame]:
    if overrides is None:
        return None
    if isinstance(overrides, (str, Path)):
        overrides = pd.read_csv(overrides)
    else:
        overrides = overrides.copy()

    if "availability_factor" not in overrides.columns:
        raise ValueError("availability overrides require 'availability_factor' column")
    if "eic_code" not in overrides.columns:
        if "unit_id" in overrides.columns:
            overrides = overrides.rename(columns={"unit_id": "eic_code"})
        else:
            raise ValueError("availability overrides require 'eic_code' column")

    overrides["eic_code"] = (
        overrides["eic_code"].astype(str).str.strip().replace({"": pd.NA})
    )
    overrides = overrides.dropna(subset=["eic_code"])
    overrides = overrides.groupby("eic_code", as_index=False)["availability_factor"].mean()
    return overrides


def optimize_availability_factors(
    plants: pd.DataFrame,
    availability_history: pd.DataFrame,
    id_columns: Iterable[str] = ("eic_code", "name"),
    min_factor: float = 0.0,
    max_factor: float = 1.0,
    fallback: str = "stack_type",
) -> pd.DataFrame:
    """
    Calibrate plant availability factors using historical availability data.

    availability_history: wide dataframe with plant identifiers as columns and
    availability factors (0-1) as values. Mean availability is used per plant.
    """
    if availability_history is None or availability_history.empty:
        return plants.copy()

    history = availability_history.apply(pd.to_numeric, errors="coerce")
    availability_means = history.mean(skipna=True)
    availability_means.index = availability_means.index.astype(str)

    updated = plants.copy()
    derived = pd.Series(float("nan"), index=updated.index, dtype="float")
    id_cols = list(id_columns)

    for idx, row in updated.iterrows():
        factor = None
        for col in id_cols:
            if col not in updated.columns:
                continue
            key = row.get(col)
            if pd.isna(key):
                continue
            key = str(key)
            if key in availability_means.index and pd.notna(availability_means[key]):
                factor = float(availability_means[key])
                break
        derived.loc[idx] = factor

    if fallback == "stack_type" and "stack_type" in updated.columns:
        stack_means = (
            updated.assign(_derived=derived)
            .groupby("stack_type")["_derived"]
            .mean()
        )
        for idx, row in updated.iterrows():
            if pd.isna(derived.loc[idx]):
                stack = row.get("stack_type")
                if pd.notna(stack) and stack in stack_means.index:
                    derived.loc[idx] = stack_means.loc[stack]

    if "availability_factor" in updated.columns:
        derived = derived.fillna(
            pd.to_numeric(updated["availability_factor"], errors="coerce")
        )

    derived = derived.clip(lower=min_factor, upper=max_factor)
    updated["availability_factor"] = derived
    return updated


def enrich_thermal_plants(
    raw: pd.DataFrame,
    countries: Iterable[str] | None = ("DE", "LU"),
    min_capacity_mw: float = 20.0,
    include_non_thermal: bool = False,
    co2_price_eur_per_t: float = DEFAULT_CO2_PRICE,
    availability_overrides: pd.DataFrame | Path | None = None,
) -> pd.DataFrame:
    """
    Filter OPSD plants (optionally by country) and attach operational/economic defaults.

    include_non_thermal: if True, retain nuclear/renewables/other fuels. If False, keep the legacy thermal set.
    """
    df = raw.copy()
    countries_list = _normalize_countries(countries)
    if countries_list:
        df = df[df["country"].isin(countries_list)]

    if "capacity_mw" not in df.columns:
        cap_col = "capacity" if "capacity" in df.columns else "electrical_capacity"
        df["capacity_mw"] = pd.to_numeric(df[cap_col], errors="coerce")
    df = df[df["capacity_mw"] >= min_capacity_mw]

    df["fuel"] = df.apply(_map_fuel, axis=1)
    if not include_non_thermal:
        df = df[df["fuel"].isin(THERMAL_FUELS)]
    df = df.dropna(subset=["fuel"])

    df["stack_type"] = df.apply(_map_stack_type, axis=1)
    df["efficiency"] = df["stack_type"].map(lambda t: _default_for(t, "efficiency"))
    df["co2_intensity"] = df["stack_type"].map(
        lambda t: _default_for(t, "co2_intensity")
    )
    df["vom"] = df["stack_type"].map(lambda t: _default_for(t, "vom")).fillna(2.0)

    df["p_max_mw"] = df["capacity_mw"]
    df["p_min_mw"] = df["capacity_mw"] * df["stack_type"].map(
        lambda t: _default_for(t, "p_min_ratio")
    ).fillna(0.0)
    df["ramp_up_mw_per_min"] = df["capacity_mw"] * df["stack_type"].map(
        lambda t: _default_for(t, "ramp_ratio_per_min")
    )
    df["ramp_down_mw_per_min"] = df["ramp_up_mw_per_min"]
    df["min_up_hours"] = df["stack_type"].map(lambda t: _default_for(t, "min_up_hours"))
    df["min_down_hours"] = df["stack_type"].map(
        lambda t: _default_for(t, "min_down_hours")
    )
    df["startup_cost_eur"] = df["stack_type"].map(
        lambda t: _default_for(t, "startup_cost_eur")
    )
    df["availability_factor"] = (
        df["stack_type"]
        .map(lambda t: _default_for(t, "availability_factor"))
        .fillna(1.0)
    )
    df["fuel_price_eur_per_mwhth"] = (
        df["stack_type"]
        .map(lambda t: _default_for(t, "fuel_price_eur_per_mwhth"))
        .fillna(0.0)
    )
    df["co2_price_eur_per_t"] = co2_price_eur_per_t
    df["variable_om_eur_per_mwh"] = df["vom"]
    df["heat_rate_mwh_th_per_mwh_el"] = df["efficiency"].apply(
        lambda eff: 1.0 / eff if pd.notna(eff) and eff > 0 else pd.NA
    )
    df["is_dispatchable"] = (
        df["stack_type"].map(lambda t: _default_for(t, "dispatchable")).fillna(True)
    )

    df["is_chp"] = df.get("chp", pd.NA)
    df["is_chp"] = (
        df["is_chp"].fillna("").astype(str).str.lower().isin({"yes", "y", "true", "1"})
    )
    df["commissioned_year"] = pd.to_numeric(
        df.get("commissioned", pd.NA), errors="coerce"
    )
    df["bidding_zone"] = df.apply(_extract_bidding_zone, axis=1)

    keep_cols = [
        "name",
        "bidding_zone",
        "country",
        "fuel",
        "stack_type",
        "capacity_mw",
        "p_min_mw",
        "p_max_mw",
        "ramp_up_mw_per_min",
        "ramp_down_mw_per_min",
        "min_up_hours",
        "min_down_hours",
        "startup_cost_eur",
        "efficiency",
        "heat_rate_mwh_th_per_mwh_el",
        "co2_intensity",
        "variable_om_eur_per_mwh",
        "vom",
        "fuel_price_eur_per_mwhth",
        "co2_price_eur_per_t",
        "availability_factor",
        "is_dispatchable",
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
    # Fill missing names from municipality/technology to keep the dashboard readable.
    if "municipality" in df.columns:
        df["name"] = df["name"].fillna(df["municipality"])
    df["name"] = df["name"].fillna(df["technology"]).fillna(df["stack_type"])

    overrides = _load_availability_overrides(availability_overrides)
    if overrides is not None:
        df = df.merge(overrides, on="eic_code", how="left", suffixes=("", "_override"))
        df["availability_factor"] = df["availability_factor_override"].fillna(
            df["availability_factor"]
        )
        df = df.drop(columns=["availability_factor_override"])

    return df[keep_cols].reset_index(drop=True)


@dataclass
class PlantStack:
    plants: pd.DataFrame

    @classmethod
    def from_opsd(
        cls,
        force: bool = False,
        countries: Iterable[str] | None = ("DE", "LU"),
        bidding_zones: Iterable[str] | None = None,
        min_capacity_mw: float = 20.0,
        include_renewables: bool = True,
        co2_price_eur_per_t: float = DEFAULT_CO2_PRICE,
        availability_overrides: pd.DataFrame | Path | None = None,
    ) -> "PlantStack":
        frames: List[pd.DataFrame] = [fetch_opsd_conventional(force=force)]
        if include_renewables:
            frames.append(fetch_opsd_renewable(force=force))
        raw = pd.concat(frames, ignore_index=True, sort=False)
        enriched = enrich_thermal_plants(
            raw,
            countries=countries,
            min_capacity_mw=min_capacity_mw,
            include_non_thermal=True,
            co2_price_eur_per_t=co2_price_eur_per_t,
            availability_overrides=availability_overrides,
        )
        if bidding_zones:
            zones = _normalize_countries(bidding_zones)
            enriched = enriched[enriched["bidding_zone"].isin(zones)]
        return cls(plants=enriched.reset_index(drop=True))

    def to_blocks(self, availability_factor: float = 1.0) -> List[dict]:
        blocks = []
        for _, row in self.plants.iterrows():
            if row.get("is_dispatchable", True) is False:
                continue
            plant_avail_raw = row.get("availability_factor", 1.0)
            plant_avail = float(plant_avail_raw) if pd.notna(plant_avail_raw) else 1.0
            eff = float(row["efficiency"]) if pd.notna(row["efficiency"]) else 1.0
            blocks.append(
                {
                    "name": row["name"],
                    "fuel": row["fuel"],
                    "capacity": float(row["capacity_mw"])
                    * availability_factor
                    * plant_avail,
                    "marginal_cost": None,  # filled later in model
                    "efficiency": eff,
                    "co2_intensity": (
                        float(row["co2_intensity"])
                        if pd.notna(row["co2_intensity"])
                        else 0.0
                    ),
                    "vom": float(row["vom"]) if pd.notna(row["vom"]) else 0.0,
                }
            )
        return blocks

    def optimize_availability(
        self,
        availability_history: pd.DataFrame,
        id_columns: Iterable[str] = ("eic_code", "name"),
        min_factor: float = 0.0,
        max_factor: float = 1.0,
        fallback: str = "stack_type",
    ) -> "PlantStack":
        optimized = optimize_availability_factors(
            self.plants,
            availability_history=availability_history,
            id_columns=id_columns,
            min_factor=min_factor,
            max_factor=max_factor,
            fallback=fallback,
        )
        return PlantStack(plants=optimized)
