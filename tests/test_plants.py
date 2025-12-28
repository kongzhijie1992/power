import pandas as pd

from src.power_model.plants import enrich_thermal_plants, PlantStack
from src.power_model.structural import PlantStackModel


def _sample_raw():
    return pd.DataFrame(
        [
            {
                "name": "Gas CCGT A",
                "country": "DE",
                "energy_source": "Natural gas",
                "technology": "Combined cycle",
                "capacity": 400,
                "chp": "No",
                "commissioned": 2015,
                "eic_code": "PLANTA",
            },
            {
                "name": "Coal Plant B",
                "country": "DE",
                "energy_source": "Hard coal",
                "technology": "Steam",
                "capacity": 600,
                "chp": "Yes",
                "commissioned": 2005,
                "eic_code": "PLANTB",
            },
            {
                "name": "Lignite Plant C",
                "country": "LU",
                "energy_source": "Lignite",
                "technology": "Steam",
                "capacity": 300,
                "chp": None,
                "commissioned": 2010,
                "eic_code": "PLANTC",
            },
            {
                "name": "Nuclear X",
                "country": "DE",
                "energy_source": "Nuclear",
                "technology": "PWR",
                "capacity": 1300,
                "chp": None,
                "commissioned": 1990,
                "eic_code": "NUC",
            },
        ]
    )


def test_enrich_thermal_plants_filters_and_enriches():
    raw = _sample_raw()
    enriched = enrich_thermal_plants(
        raw, countries=("DE", "LU"), min_capacity_mw=100
    )
    assert set(enriched["name"]) == {
        "Gas CCGT A",
        "Coal Plant B",
        "Lignite Plant C",
    }
    for col in [
        "capacity_mw",
        "efficiency",
        "co2_intensity",
        "vom",
        "fuel",
        "stack_type",
    ]:
        assert col in enriched.columns
    assert (enriched["capacity_mw"] >= 100).all()


def test_plant_stack_model_outputs_price():
    plants = enrich_thermal_plants(_sample_raw(), min_capacity_mw=0)
    stack = PlantStack(plants=plants)
    model = PlantStackModel(stack)
    df = pd.DataFrame(
        {
            "load_forecast": [2000, 500],
            "wind_forecast": [200, 800],
            "solar_forecast": [100, 600],
            "gas_price": [40.0, 30.0],
            "eua_price": [60.0, 60.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC"),
    )
    out = model.predict(df)
    assert "structural_price" in out.columns
    assert len(out) == 2
