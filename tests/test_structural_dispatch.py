import pandas as pd

from src.power_model.structural import StructuralStackModel


def make_row(
    load: float,
    wind: float,
    solar: float,
    gas: float = 40.0,
    eua: float = 60.0,
):
    return pd.Series(
        {
            "load_forecast": load,
            "wind_forecast": wind,
            "solar_forecast": solar,
            "gas_price": gas,
            "eua_price": eua,
            "availability_factor": 1.0,
        }
    )


def test_structural_negative_price_on_oversupply():
    model = StructuralStackModel()
    row = make_row(load=5000, wind=6000, solar=2000)
    price, _ = model._clear_price(
        demand_mw=row["load_forecast"],
        renewable_mw=row["wind_forecast"] + row["solar_forecast"],
        blocks=model._available_blocks(row),
    )
    assert price == model.config.negative_price_floor


def test_structural_price_increases_with_scarcity():
    model = StructuralStackModel()
    # Load near total thermal capacity to force scarcity uplift
    row = make_row(load=44000, wind=500, solar=500)
    blocks = model._available_blocks(row)
    price, detail = model._clear_price(
        demand_mw=row["load_forecast"],
        renewable_mw=row["wind_forecast"] + row["solar_forecast"],
        blocks=blocks,
    )
    assert detail["reserve_margin"] < model.config.reserve_margin_floor
    assert detail["uplift"] > 0
    assert price > 0


def test_structural_predict_series():
    model = StructuralStackModel()
    df = pd.DataFrame(
        {
            "load_forecast": [15000, 5000],
            "wind_forecast": [1000, 8000],
            "solar_forecast": [1000, 2000],
            "gas_price": [40.0, 30.0],
            "eua_price": [60.0, 60.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC"),
    )
    out = model.predict(df)
    assert "structural_price" in out.columns
    assert len(out) == 2
