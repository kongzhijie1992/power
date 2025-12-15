#!/usr/bin/env python3
"""Unified Streamlit dashboard for demand and price forecasts."""
from pathlib import Path
from typing import Optional, Tuple, List
import sys

import pandas as pd
import plotly.graph_objs as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.io import load_demand_series, load_tso_forecast_series, load_price_series
from src.power_model.plants import PlantStack

DATA_DIR = Path("data")


@st.cache_data(show_spinner=False)
def _list_areas_with_file(filename: str) -> List[str]:
    areas: List[str] = []
    for area_dir in DATA_DIR.iterdir():
        if not area_dir.is_dir():
            continue
        if (area_dir / filename).exists():
            areas.append(area_dir.name)
    return sorted(areas)


@st.cache_data(show_spinner=False)
def _read_csv_indexed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def _apply_horizon(df: pd.DataFrame, horizon: str) -> pd.DataFrame:
    if df.empty or horizon == "all":
        return df
    try:
        days = int(str(horizon).rstrip("d"))
        cutoff = df.index.max() - pd.Timedelta(days=days)
        return df[df.index >= cutoff]
    except Exception:
        return df


def load_demand_data(area: str) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    fc_path = DATA_DIR / area / "demand_forecast.csv"
    if not fc_path.exists():
        raise FileNotFoundError(f"No demand_forecast.csv for {area}")
    fc = _read_csv_indexed(fc_path)

    try:
        actual = load_demand_series(area)
    except FileNotFoundError:
        actual = pd.Series(dtype=float)
    try:
        tso = load_tso_forecast_series(area)
    except FileNotFoundError:
        tso = pd.Series(dtype=float)

    quantiles = fc[[c for c in fc.columns if c.startswith("corrected_q")]].copy() if any(
        c.startswith("corrected_q") for c in fc.columns
    ) else None

    idx_union = fc.index
    if not actual.empty:
        idx_union = idx_union.union(actual.index)
    if not tso.empty:
        idx_union = idx_union.union(tso.index)
    idx_union = idx_union.sort_values()

    merged = pd.DataFrame(index=idx_union)
    if not actual.empty:
        merged["actual_load"] = actual.reindex(idx_union)
    if "tso_forecast" in fc.columns:
        merged["tso_forecast"] = fc["tso_forecast"].reindex(idx_union)
    elif not tso.empty:
        merged["tso_forecast"] = tso.reindex(idx_union)
    if "corrected_mean" in fc.columns:
        merged["corrected_mean"] = fc["corrected_mean"].reindex(idx_union)
    elif "mean" in fc.columns:
        merged["corrected_mean"] = fc["mean"].reindex(idx_union)
    if quantiles is not None:
        quantiles = quantiles.reindex(idx_union)
    return merged.dropna(how="all"), quantiles


def load_price_data(area: str) -> Tuple[pd.Series, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    actual = load_price_series(area).sort_index()
    if isinstance(actual.index, pd.DatetimeIndex) and actual.index.tz is not None:
        actual.index = actual.index.tz_convert("UTC").tz_localize(None)

    fwd_path = DATA_DIR / area / "price_forecast.csv"
    history_path = DATA_DIR / area / "price_history_predictions.csv"

    forward = _read_csv_indexed(fwd_path) if fwd_path.exists() else None
    history = _read_csv_indexed(history_path) if history_path.exists() else None
    if history is not None and "pred" not in history.columns:
        if "mean" in history.columns:
            history = history.rename(columns={"mean": "pred"})
        elif "corrected_mean" in history.columns:
            history = history.rename(columns={"corrected_mean": "pred"})
    return actual, forward, history


def demand_tab():
    st.subheader("Demand forecasts")
    areas = _list_areas_with_file("demand_forecast.csv")
    area = st.selectbox("Bidding zone", options=areas, index=(areas.index("DE_LU") if "DE_LU" in areas else 0))
    horizon = st.selectbox("Time horizon", options=["7d", "30d", "90d", "180d", "365d", "all"], index=2)

    df, quantiles = load_demand_data(area)
    df = _apply_horizon(df, horizon)
    if quantiles is not None:
        quantiles = _apply_horizon(quantiles, horizon)

    fig = go.Figure()
    if "actual_load" in df:
        fig.add_trace(go.Scatter(x=df.index, y=df["actual_load"], mode="lines", name="Actual load"))
    if "tso_forecast" in df:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["tso_forecast"], mode="lines", name="TSO forecast", line=dict(dash="dot"))
        )
    if "corrected_mean" in df:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["corrected_mean"], mode="lines", name="Model (corrected)", line=dict(color="#d62728"))
        )
    if quantiles is not None and {"corrected_q10", "corrected_q90"}.issubset(quantiles.columns):
        fig.add_trace(
            go.Scatter(
                x=quantiles.index,
                y=quantiles["corrected_q90"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=quantiles.index,
                y=quantiles["corrected_q10"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(214,39,40,0.15)",
                name="Model q10–q90",
            )
        )
    fig.update_layout(yaxis_title="MW", xaxis_title="Time", height=500, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

    st.caption(f"{area} | points: {len(df):,} | span: {df.index.min()} → {df.index.max()}")


def price_tab():
    st.subheader("Price forecasts")
    areas = _list_areas_with_file("day_ahead.csv")
    area = st.selectbox("Price area", options=areas, index=(areas.index("DE_LU") if "DE_LU" in areas else 0))
    horizon = st.selectbox("Price horizon", options=["7d", "30d", "90d", "180d", "365d", "all"], index=2)

    actual, forward, history = load_price_data(area)
    actual = _apply_horizon(actual.to_frame("value"), horizon)["value"] if not actual.empty else actual
    if forward is not None:
        forward = _apply_horizon(forward, horizon)
    if history is not None:
        history = _apply_horizon(history, horizon)

    fig = go.Figure()
    if len(actual) > 0:
        fig.add_trace(go.Scatter(x=actual.index, y=actual.values, mode="lines", name="Actual price"))
    if history is not None and "pred" in history:
        fig.add_trace(go.Scatter(x=history.index, y=history["pred"], mode="lines", name="Historical pred", line=dict(color="#ff7f0e")))
    if forward is not None and "mean" in forward:
        fig.add_trace(go.Scatter(x=forward.index, y=forward["mean"], mode="lines", name="Forward pred", line=dict(color="#d62728")))
    if forward is not None and {"q10", "q90"}.issubset(forward.columns):
        fig.add_trace(
            go.Scatter(
                x=forward.index,
                y=forward["q90"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=forward.index,
                y=forward["q10"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(214,39,40,0.15)",
                name="Forward q10–q90",
            )
        )
    fig.update_layout(yaxis_title="EUR/MWh", xaxis_title="Time", height=500, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

    meta = [f"{area}"]
    if len(actual) > 0:
        meta.append(f"actual: {len(actual):,} pts ({actual.index.min()} → {actual.index.max()})")
    if history is not None:
        meta.append(f"history preds: {len(history):,} pts")
    if forward is not None:
        meta.append(f"forward preds: {len(forward):,} pts")
    st.caption(" | ".join(meta))


@st.cache_data(show_spinner=False)
def load_plants(min_capacity: float, include_chp: bool) -> pd.DataFrame:
    """Load DE/LU plant stack from OPSD and apply quick filters."""
    stack = PlantStack.from_opsd()
    df = stack.plants.copy()
    df = df[df["capacity_mw"] >= min_capacity]
    if not include_chp and "is_chp" in df.columns:
        df = df[~df["is_chp"]]
    return df.reset_index(drop=True)


def plants_tab():
    st.subheader("DE/LU plant stack (OPSD)")
    min_cap = st.slider("Minimum capacity (MW)", min_value=0, max_value=1000, value=50, step=10)
    include_chp = st.checkbox("Include CHP", value=True)
    df = load_plants(min_capacity=min_cap, include_chp=include_chp)
    if df.empty:
        st.info("No plants after filters.")
        return

    total_cap = df["capacity_mw"].sum()
    st.caption(f"{len(df)} plants | {total_cap:,.0f} MW total")

    col1, col2 = st.columns(2)
    with col1:
        if "fuel" in df:
            fuel_summary = df.groupby("fuel")["capacity_mw"].sum().sort_values(ascending=False)
            st.write("Capacity by fuel (MW):")
            st.dataframe(fuel_summary.round(1))
    with col2:
        if "stack_type" in df:
            type_summary = df.groupby("stack_type")["capacity_mw"].sum().sort_values(ascending=False)
            st.write("Capacity by stack type (MW):")
            st.dataframe(type_summary.round(1))

    map_df = df.dropna(subset=["lat", "lon"])
    if not map_df.empty:
        fig = go.Figure(
            go.Scattergeo(
                lon=map_df["lon"],
                lat=map_df["lat"],
                text=map_df["name"],
                mode="markers",
                marker=dict(size=6, color="red", opacity=0.7),
            )
        )
        fig.update_geos(fitbounds="locations", showcountries=True, lataxis_showgrid=True, lonaxis_showgrid=True)
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.write("Plant table")
    display_cols = [
        c
        for c in [
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
        ]
        if c in df.columns
    ]
    st.dataframe(df[display_cols])


def main():
    st.set_page_config(page_title="Power forecasts", layout="wide")
    st.title("Power forecasts dashboard")
    tab1, tab2, tab3 = st.tabs(["Demand forecasts", "Price forecasts", "Plants (DE/LU)"])
    with tab1:
        demand_tab()
    with tab2:
        price_tab()
    with tab3:
        plants_tab()


if __name__ == "__main__":
    main()
