#!/usr/bin/env python3
"""Unified Streamlit dashboard for demand and price forecasts."""
import os
import subprocess
from datetime import timedelta
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
MARKET_DIR = Path("data/market")


def _load_secrets_into_env():
    """Propagate Streamlit secrets to env vars so ingestion code can read tokens locally."""
    needs_entsoe = not os.getenv("ENTSOE_API_TOKEN")
    needs_tv = (not os.getenv("TV_USERNAME")) or (not os.getenv("TV_PASSWORD"))
    if not needs_entsoe and not needs_tv:
        return
    try:
        token = st.secrets.get("ENTSOE_API_TOKEN") or st.secrets.get("ENTSOE_TOKEN")
        tv_user = st.secrets.get("TV_USERNAME")
        tv_pwd = st.secrets.get("TV_PASSWORD")
    except Exception:
        token = None
        tv_user = None
        tv_pwd = None
    if needs_entsoe and token:
        os.environ["ENTSOE_API_TOKEN"] = str(token)
    if needs_tv and tv_user and not os.getenv("TV_USERNAME"):
        os.environ["TV_USERNAME"] = str(tv_user)
    if needs_tv and tv_pwd and not os.getenv("TV_PASSWORD"):
        os.environ["TV_PASSWORD"] = str(tv_pwd)


_load_secrets_into_env()


def _is_git_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(200)
        text = head.decode("utf-8", errors="ignore")
        return "git-lfs.github.com/spec/v1" in text
    except Exception:
        return False


def _try_git_lfs_pull(include_path: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", "lfs", "pull", "--include", include_path],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return False, out.strip() or f"git lfs pull failed (code={proc.returncode})"
        return True, out.strip() or "git lfs pull succeeded"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


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

    quantiles = (
        fc[[c for c in fc.columns if c.startswith("corrected_q")]].copy()
        if any(c.startswith("corrected_q") for c in fc.columns)
        else None
    )

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


def load_price_data(
    area: str,
) -> Tuple[pd.Series, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
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
    area = st.selectbox(
        "Bidding zone",
        options=areas,
        index=(areas.index("DE_LU") if "DE_LU" in areas else 0),
    )
    horizon = st.selectbox(
        "Time horizon", options=["7d", "30d", "90d", "180d", "365d", "all"], index=2
    )

    df, quantiles = load_demand_data(area)
    df = _apply_horizon(df, horizon)
    if quantiles is not None:
        quantiles = _apply_horizon(quantiles, horizon)

    fig = go.Figure()
    if "actual_load" in df:
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["actual_load"], mode="lines", name="Actual load"
            )
        )
    if "tso_forecast" in df:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["tso_forecast"],
                mode="lines",
                name="TSO forecast",
                line=dict(dash="dot"),
            )
        )
    if "corrected_mean" in df:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["corrected_mean"],
                mode="lines",
                name="Model (corrected)",
                line=dict(color="#d62728"),
            )
        )
    if quantiles is not None and {"corrected_q10", "corrected_q90"}.issubset(
        quantiles.columns
    ):
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
    fig.update_layout(
        yaxis_title="MW", xaxis_title="Time", height=500, legend_orientation="h"
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"{area} | points: {len(df):,} | span: {df.index.min()} → {df.index.max()}"
    )


def price_tab():
    st.subheader("Price forecasts")
    areas = _list_areas_with_file("day_ahead.csv")
    area = st.selectbox(
        "Price area",
        options=areas,
        index=(areas.index("DE_LU") if "DE_LU" in areas else 0),
    )
    horizon = st.selectbox(
        "Price horizon", options=["7d", "30d", "90d", "180d", "365d", "all"], index=2
    )

    actual, forward, history = load_price_data(area)
    actual = (
        _apply_horizon(actual.to_frame("value"), horizon)["value"]
        if not actual.empty
        else actual
    )
    if forward is not None:
        forward = _apply_horizon(forward, horizon)
    if history is not None:
        history = _apply_horizon(history, horizon)

    fig = go.Figure()
    if len(actual) > 0:
        fig.add_trace(
            go.Scatter(
                x=actual.index, y=actual.values, mode="lines", name="Actual price"
            )
        )
    if history is not None and "pred" in history:
        fig.add_trace(
            go.Scatter(
                x=history.index,
                y=history["pred"],
                mode="lines",
                name="Historical pred",
                line=dict(color="#ff7f0e"),
            )
        )
    if forward is not None and "mean" in forward:
        fig.add_trace(
            go.Scatter(
                x=forward.index,
                y=forward["mean"],
                mode="lines",
                name="Forward pred",
                line=dict(color="#d62728"),
            )
        )
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
    fig.update_layout(
        yaxis_title="EUR/MWh", xaxis_title="Time", height=500, legend_orientation="h"
    )
    st.plotly_chart(fig, use_container_width=True)

    meta = [f"{area}"]
    if len(actual) > 0:
        meta.append(
            f"actual: {len(actual):,} pts ({actual.index.min()} → {actual.index.max()})"
        )
    if history is not None:
        meta.append(f"history preds: {len(history):,} pts")
    if forward is not None:
        meta.append(f"forward preds: {len(forward):,} pts")
    st.caption(" | ".join(meta))


@st.cache_data(show_spinner=False)
def _load_market_commodities() -> pd.DataFrame:
    candidates = [
        MARKET_DIR / "commodities.parquet",
        MARKET_DIR / "commodities.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if _is_git_lfs_pointer(path):
            continue
        if path.suffix.lower() == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index)
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        df = df.sort_index()
        # Commodities are daily settlement series; normalize to daily timestamps.
        df = df.resample("1D").last().dropna(how="all")

        rename = {"co2": "eua_price", "gas": "gas_price", "coal": "coal_price"}
        for src, dst in rename.items():
            if src in df.columns and dst not in df.columns:
                df[dst] = df[src]
        return df
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _fetch_market_commodities_from_tradingview() -> pd.DataFrame:
    """
    Fetch commodity proxies from TradingView via tvdatafeed (daily settlement).
    Returns a DataFrame indexed by datetime with columns gas, coal, co2 and normalized gas_price/coal_price/eua_price.
    """
    try:
        from tvDatafeed import Interval, TvDatafeed  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "tvdatafeed is not available; install dependencies or upload a CSV."
        ) from e

    user = os.getenv("TV_USERNAME")
    pwd = os.getenv("TV_PASSWORD")
    tv = TvDatafeed(username=user, password=pwd) if user and pwd else TvDatafeed()

    symbols = {
        "gas": ("TFM1!", "ICEEUR"),  # TTF front month, EUR/MWh
        "coal": ("API2!", "ICEEUR"),  # API2 front, EUR/ton (proxy)
        "co2": ("EUA1!", "ICEEUR"),  # EUA front, EUR/t
    }

    rows = []
    for name, (symbol, exchange) in symbols.items():
        df = tv.get_hist(
            symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=900
        )
        if df is None or df.empty or "close" not in df.columns:
            continue
        s = df["close"].copy()
        s.name = name
        rows.append(s)

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, axis=1).sort_index().ffill()
    out.index = pd.to_datetime(out.index)
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)

    rename = {"co2": "eua_price", "gas": "gas_price", "coal": "coal_price"}
    for src, dst in rename.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def commodities_tab():
    st.subheader("Commodity prices")

    lfs_candidate = None
    for p in [MARKET_DIR / "commodities.parquet", MARKET_DIR / "commodities.csv"]:
        if p.exists() and _is_git_lfs_pointer(p):
            lfs_candidate = p
            break
    if lfs_candidate is not None:
        st.error(
            f"`{lfs_candidate.as_posix()}` is a Git LFS pointer file (the real data was not pulled). "
            "Enable Git LFS on the Streamlit server (or run `git lfs pull`)."
        )
        if st.button("Try `git lfs pull` now"):
            ok, msg = _try_git_lfs_pull(str(lfs_candidate.as_posix()))
            if ok:
                st.success(msg)
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(msg)

    df = _load_market_commodities()
    if df.empty:
        st.info("No commodity file found yet.")
        uploaded = st.file_uploader("Upload `commodities.csv`", type=["csv"])
        if uploaded is not None:
            df = pd.read_csv(uploaded)
            if "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = df.set_index("datetime")
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            rename = {"co2": "eua_price", "gas": "gas_price", "coal": "coal_price"}
            for src, dst in rename.items():
                if src in df.columns and dst not in df.columns:
                    df[dst] = df[src]

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Fetch via TradingView"):
                with st.spinner("Fetching commodity proxies..."):
                    try:
                        df = _fetch_market_commodities_from_tradingview()
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
                        df = pd.DataFrame()

        with col_b:
            if not df.empty and st.button("Save to `data/market/commodities.csv`"):
                MARKET_DIR.mkdir(parents=True, exist_ok=True)
                out = df.copy()
                out = out.reset_index().rename(columns={"index": "datetime"})
                out.to_csv(MARKET_DIR / "commodities.csv", index=False)
                st.success("Saved `data/market/commodities.csv`.")

        if df.empty:
            st.caption(
                "Expected columns: `datetime, gas, coal, co2` (optionally `gas_price, coal_price, eua_price`). "
                "To generate locally: `python scripts/fetch_tradingview.py`."
            )
            return

    # Date range selector (inclusive).
    min_date = df.index.min().date() if not df.empty else None
    max_date = df.index.max().date() if not df.empty else None
    default_end = max_date
    default_start = max(min_date, max_date - timedelta(days=90)) if min_date else max_date

    date_range = st.date_input(
        "Date range (inclusive)",
        value=(default_start, default_end),
        min_value=min_date,
        max_value=max_date,
        key="commodities_date_range",
    )
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select a start and end date.")
        return
    start_date, end_date = date_range
    if start_date > end_date:
        st.error("Start date must be <= end date.")
        return

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df[(df.index >= start_ts) & (df.index <= end_ts)]
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        st.warning("Commodity file has no numeric columns to plot.")
        return

    default_cols = [
        c for c in ["gas_price", "coal_price", "eua_price"] if c in numeric_cols
    ] or numeric_cols[: min(3, len(numeric_cols))]
    cols = st.multiselect(
        "Series", options=numeric_cols, default=default_cols, key="commodities_series"
    )
    if not cols:
        st.info("Select at least one series.")
        return

    fig = go.Figure()
    for c in cols:
        fig.add_trace(go.Scatter(x=df.index, y=df[c], mode="lines", name=c))
    fig.update_layout(xaxis_title="Time", height=450, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

    latest = df[cols].dropna(how="all").tail(1)
    if not latest.empty:
        st.caption(f"Latest: {latest.index[0]}")
        st.dataframe(
            latest.T.rename(columns={latest.index[0]: "value"}),
            use_container_width=True,
        )


@st.cache_data(show_spinner=False)
def load_all_plants() -> pd.DataFrame:
    """Download OPSD stack once (cached) so the UI stays responsive."""
    # Older deployments of PlantStack may not accept include_renewables; fall back gracefully.
    try:
        stack = PlantStack.from_opsd(
            countries=None, min_capacity_mw=0, include_renewables=True
        )
    except TypeError:
        stack = PlantStack.from_opsd(countries=None, min_capacity_mw=0)
    df = stack.plants.copy()
    # Older cached stacks may not have bidding_zone; fall back to country to keep the UI usable.
    if "bidding_zone" not in df.columns:
        df["bidding_zone"] = df.get("country")
    return df


def _filter_plants(
    df: pd.DataFrame,
    min_capacity: float,
    include_chp: bool,
    bidding_zones: Tuple[str, ...],
) -> pd.DataFrame:
    filtered = df.copy()
    if bidding_zones:
        filtered = filtered[filtered["bidding_zone"].isin(bidding_zones)]
    filtered = filtered[filtered["capacity_mw"] >= min_capacity]
    if not include_chp and "is_chp" in filtered.columns:
        filtered = filtered[~filtered["is_chp"]]
    return filtered.reset_index(drop=True)


def _attach_srmc(
    df: pd.DataFrame, co2_price_override: Optional[float] = None
) -> pd.DataFrame:
    df = df.copy()

    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name]
        return pd.Series(pd.NA, index=df.index)

    eff = pd.to_numeric(_col("efficiency"), errors="coerce")
    fuel_price = pd.to_numeric(
        _col("fuel_price_eur_per_mwhth"), errors="coerce"
    ).fillna(0.0)

    vom_src = _col("variable_om_eur_per_mwh")
    if vom_src.isna().all():
        vom_src = _col("vom")
    vom = pd.to_numeric(vom_src, errors="coerce").fillna(0.0)

    co2_int = pd.to_numeric(_col("co2_intensity"), errors="coerce").fillna(0.0)
    if co2_price_override is not None:
        co2_price = pd.Series(float(co2_price_override), index=df.index)
    else:
        co2_price = pd.to_numeric(_col("co2_price_eur_per_t"), errors="coerce").fillna(
            0.0
        )

    srmc = (
        fuel_price.div(eff.replace(0, pd.NA)).fillna(pd.NA) + co2_price * co2_int + vom
    )
    df["srmc_eur_per_mwh"] = srmc
    return df


def _apply_table_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    with st.expander("Filter table"):
        name_filter = st.text_input("Name contains", "")
        fuel_opts = (
            sorted(filtered["fuel"].dropna().unique().tolist())
            if "fuel" in filtered
            else []
        )
        fuel_sel = st.multiselect("Fuel", options=fuel_opts, default=fuel_opts)
        stack_opts = (
            sorted(filtered["stack_type"].dropna().unique().tolist())
            if "stack_type" in filtered
            else []
        )
        stack_sel = st.multiselect("Stack type", options=stack_opts, default=stack_opts)
        cap_min, cap_max = (
            (float(filtered["capacity_mw"].min()), float(filtered["capacity_mw"].max()))
            if not filtered.empty
            else (0.0, 0.0)
        )
        cap_range = st.slider(
            "Capacity range (MW)",
            min_value=cap_min,
            max_value=cap_max,
            value=(cap_min, cap_max),
        )
        if (
            "srmc_eur_per_mwh" in filtered
            and filtered["srmc_eur_per_mwh"].dropna().size
        ):
            srmc_min = float(filtered["srmc_eur_per_mwh"].min())
            srmc_max = float(filtered["srmc_eur_per_mwh"].max())
            srmc_range = st.slider(
                "SRMC range (EUR/MWh)",
                min_value=srmc_min,
                max_value=srmc_max,
                value=(srmc_min, srmc_max),
            )
        else:
            srmc_range = None

    if name_filter:
        filtered = filtered[
            filtered["name"].str.contains(name_filter, case=False, na=False)
        ]
    if fuel_sel:
        filtered = filtered[filtered["fuel"].isin(fuel_sel)]
    if stack_sel:
        filtered = filtered[filtered["stack_type"].isin(stack_sel)]
    filtered = filtered[
        (filtered["capacity_mw"] >= cap_range[0])
        & (filtered["capacity_mw"] <= cap_range[1])
    ]
    if srmc_range:
        filtered = filtered[
            (filtered["srmc_eur_per_mwh"] >= srmc_range[0])
            & (filtered["srmc_eur_per_mwh"] <= srmc_range[1])
        ]
    return filtered.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def _load_demand_series_cached(area: str) -> pd.Series:
    s = load_demand_series(area)
    s = s.sort_index()
    s.index = pd.to_datetime(s.index)
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s


@st.cache_data(show_spinner=False)
def _list_areas_with_any_files(filenames: Tuple[str, ...]) -> List[str]:
    areas: List[str] = []
    for area_dir in DATA_DIR.iterdir():
        if not area_dir.is_dir():
            continue
        if any((area_dir / name).exists() for name in filenames):
            areas.append(area_dir.name)
    return sorted(areas)


def _series_value_at_or_nearest(series: pd.Series, ts: pd.Timestamp) -> Tuple[pd.Timestamp, float]:
    if series.empty:
        raise ValueError("Series is empty")
    series = series.sort_index()
    idx = series.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("Series index must be datetime-like")
    target_ts = pd.Timestamp(ts)
    pos = idx.get_indexer([target_ts], method="nearest")[0]
    actual_ts = pd.Timestamp(idx[pos])
    value = float(series.iloc[pos])
    return actual_ts, value


def _series_value_at_or_before(series: pd.Series, ts: pd.Timestamp) -> Tuple[pd.Timestamp, float]:
    if series.empty:
        raise ValueError("Series is empty")
    series = series.sort_index()
    idx = series.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise TypeError("Series index must be datetime-like")
    target_ts = pd.Timestamp(ts)
    pos = idx.get_indexer([target_ts], method="pad")[0]
    if pos < 0:
        raise ValueError(f"No value at or before {target_ts}")
    actual_ts = pd.Timestamp(idx[pos])
    value = float(series.iloc[pos])
    return actual_ts, value


def merit_order_rank_tab():
    st.subheader("Merit order rank")
    st.caption(
        "Estimate marginal unit and merit-order rank from OPSD plant SRMC and demand for a selected bidding zone and delivery hour (UTC)."
    )

    with st.spinner("Loading OPSD plant metadata..."):
        all_plants = load_all_plants()
    if all_plants.empty:
        st.error("No OPSD plants available. Check data/external cache.")
        return

    demand_areas = _list_areas_with_any_files(
        (
            "load_actual.parquet",
            "load_actual.csv",
            "load_real.parquet",
            "load_real.csv",
            "load.parquet",
            "load.csv",
        )
    )

    zone_options = sorted(all_plants["bidding_zone"].dropna().unique().tolist())
    default_zone = (
        "DE_LU" if "DE_LU" in zone_options else (zone_options[0] if zone_options else None)
    )
    zone = st.selectbox(
        "Bidding zone",
        options=zone_options,
        index=zone_options.index(default_zone) if default_zone in zone_options else 0,
        key="merit_zone",
    )

    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
    with col_cfg1:
        min_cap = st.slider(
            "Minimum unit size (MW)",
            min_value=1,
            max_value=1000,
            value=50,
            step=1,
            key="merit_min_unit_size_mw",
        )
        include_chp = st.checkbox("Include CHP", value=True, key="merit_include_chp")
    with col_cfg2:
        availability_multiplier = st.slider(
            "Availability multiplier",
            min_value=0.0,
            max_value=1.2,
            value=1.0,
            step=0.05,
            key="merit_availability_multiplier",
        )
    with col_cfg3:
        demand_source = st.selectbox(
            "Demand source",
            options=[
                "From saved load series (if available)",
                "Manual input",
            ],
            key="merit_demand_source",
        )

    demand_series: Optional[pd.Series] = None
    if demand_source == "From saved load series (if available)" and zone in demand_areas:
        try:
            demand_series = _load_demand_series_cached(zone).dropna()
        except FileNotFoundError:
            demand_series = None

    if demand_source == "From saved load series (if available)" and demand_series is None:
        st.warning(f"No saved load series found for `{zone}`; switch to manual demand.")
        demand_source = "Manual input"

    col_time1, col_time2 = st.columns(2)
    with col_time1:
        if demand_series is not None and not demand_series.empty:
            min_date = demand_series.index.min().date()
            max_date = demand_series.index.max().date()
            default_date = max_date
            delivery_date = st.date_input(
                "Delivery date (UTC)",
                value=default_date,
                min_value=min_date,
                max_value=max_date,
                key="merit_delivery_date",
            )
        else:
            delivery_date = st.date_input("Delivery date (UTC)", key="merit_delivery_date")
    with col_time2:
        period = st.selectbox(
            "Bidding period (UTC hour)",
            options=list(range(1, 25)),
            index=0,
            key="merit_bidding_period",
            format_func=lambda p: f"{p:02d} ({p-1:02d}:00–{p:02d}:00)",
        )

    ts_delivery = pd.Timestamp(delivery_date) + pd.Timedelta(hours=int(period) - 1)
    st.caption(f"Selected delivery hour: `{ts_delivery}` (UTC)")

    df_zone_base = _filter_plants(
        all_plants,
        min_capacity=min_cap,
        include_chp=include_chp,
        bidding_zones=(zone,),
    )
    if df_zone_base.empty:
        st.info("No plants in this zone after filters.")
        return

    if "is_dispatchable" in df_zone_base.columns:
        dispatchable_mask = df_zone_base["is_dispatchable"]
        if not isinstance(dispatchable_mask, pd.Series):
            dispatchable_mask = pd.Series(True, index=df_zone_base.index)
        dispatchable_mask = dispatchable_mask.fillna(True).astype(bool)
        df_zone_base = df_zone_base[dispatchable_mask]

    if "availability_factor" in df_zone_base.columns:
        avail_factor = pd.to_numeric(
            df_zone_base["availability_factor"], errors="coerce"
        ).fillna(1.0)
    else:
        avail_factor = pd.Series(1.0, index=df_zone_base.index)

    df_zone_base = df_zone_base.assign(
        available_mw=df_zone_base["capacity_mw"]
        * avail_factor
        * float(availability_multiplier)
    )
    df_zone_base = df_zone_base[df_zone_base["available_mw"] > 0].reset_index(drop=True)
    if df_zone_base.empty:
        st.info("No available capacity after applying availability settings.")
        return

    total_capacity = float(df_zone_base["available_mw"].sum())

    co2_col, demand_col = st.columns(2)
    with co2_col:
        co2_source = st.selectbox(
            "CO₂ price source",
            options=[
                "Front contract settlement (point-in-time)",
                "Manual",
            ],
            key="merit_co2_source",
        )

        co2_price_ui: float
        if co2_source == "Front contract settlement (point-in-time)":
            commodities = _load_market_commodities()
            eua_col = (
                "eua_price"
                if "eua_price" in commodities.columns
                else ("co2" if "co2" in commodities.columns else None)
            )
            if commodities.empty or eua_col is None:
                st.warning("No EUA/CO₂ series available in `data/market/commodities.csv`; using manual CO₂.")
                co2_source = "Manual"
            else:
                eua_series = pd.to_numeric(commodities[eua_col], errors="coerce").dropna()
                asof_ts = pd.Timestamp(delivery_date) - pd.Timedelta(days=1) + pd.Timedelta(hours=12)
                try:
                    co2_ts_used, co2_price_ui = _series_value_at_or_before(eua_series, asof_ts)
                    st.caption(f"As-of `{asof_ts}` → using `{co2_ts_used}`: {co2_price_ui:,.2f} EUR/t")
                except Exception as e:  # noqa: BLE001
                    st.warning(f"Could not resolve CO₂ price as-of `{asof_ts}` ({e}); using manual CO₂.")
                    co2_source = "Manual"
        if co2_source == "Manual":
            co2_price_ui = st.number_input(
                "CO₂ price (EUR/t)",
                min_value=0.0,
                max_value=500.0,
                value=80.0,
                step=5.0,
                key="merit_co2_price_eur_per_t",
            )

    with demand_col:
        demand_mw: Optional[float]
        ts_used: Optional[pd.Timestamp]
        if demand_source == "From saved load series (if available)" and demand_series is not None:
            ts_used, demand_mw = _series_value_at_or_nearest(demand_series, ts_delivery)
            st.caption(f"Using demand at `{ts_used}`: {demand_mw:,.0f} MW")
        else:
            ts_used = None
            demand_mw = st.number_input(
                "Demand for bidding period (MW)",
                min_value=0.0,
                max_value=max(total_capacity * 2.0, 1.0),
                value=min(total_capacity * 0.6, max(total_capacity - 1.0, 0.0)),
                step=100.0,
                key="merit_demand_mw_manual",
            )

    df_zone = _attach_srmc(df_zone_base, co2_price_override=co2_price_ui)
    df_zone = df_zone.dropna(subset=["srmc_eur_per_mwh", "capacity_mw", "available_mw"])
    if df_zone.empty:
        st.info("No plants with SRMC available after filters.")
        return

    df_zone = df_zone.sort_values(["srmc_eur_per_mwh", "available_mw"], ascending=[True, False]).reset_index(drop=True)
    df_zone["cum_capacity_mw"] = df_zone["available_mw"].cumsum()

    if demand_mw is None:
        return

    demand_mw = float(demand_mw)
    if demand_mw <= 0:
        st.info("Demand must be > 0 MW.")
        return

    pos = int((df_zone["cum_capacity_mw"] >= demand_mw).idxmax()) if demand_mw <= total_capacity else None
    if pos is None:
        st.error(f"Demand {demand_mw:,.0f} MW exceeds available stack {total_capacity:,.0f} MW.")
        st.dataframe(
            df_zone[["name", "stack_type", "fuel", "srmc_eur_per_mwh", "available_mw", "cum_capacity_mw"]].tail(25),
            use_container_width=True,
        )
        return

    marginal = df_zone.iloc[pos]
    clearing_price = float(marginal["srmc_eur_per_mwh"])
    rank = pos + 1
    util = demand_mw / total_capacity if total_capacity > 0 else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Clearing SRMC (EUR/MWh)", f"{clearing_price:,.1f}")
    m2.metric("Merit order rank", f"{rank:,} / {len(df_zone):,}")
    m3.metric("Stack utilization", f"{util:.1%}")
    m4.metric("Marginal unit", str(marginal.get("name", ""))[:40])

    # Supply curve chart
    x = df_zone["cum_capacity_mw"]
    y = df_zone["srmc_eur_per_mwh"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Merit order (SRMC)",
            line=dict(shape="hv"),
        )
    )
    fig.add_vline(x=demand_mw, line_dash="dot", line_color="#d62728")
    fig.add_hline(y=clearing_price, line_dash="dot", line_color="#d62728")
    fig.update_layout(
        height=450,
        xaxis_title="Cumulative available capacity (MW)",
        yaxis_title="SRMC (EUR/MWh)",
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.write("Merit order around the marginal unit")
    start = max(0, pos - 15)
    end = min(len(df_zone), pos + 16)
    view = df_zone.iloc[start:end].copy()
    view.insert(0, "rank", range(start + 1, end + 1))
    cols = [
        c
        for c in [
            "rank",
            "name",
            "bidding_zone",
            "fuel",
            "stack_type",
            "srmc_eur_per_mwh",
            "available_mw",
            "cum_capacity_mw",
        ]
        if c in view.columns
    ]
    st.dataframe(
        view[cols].style.format(
            {
                "srmc_eur_per_mwh": "{:.1f}",
                "available_mw": "{:,.1f}",
                "cum_capacity_mw": "{:,.1f}",
            }
        ),
        use_container_width=True,
    )


def plants_tab():
    st.subheader("Plant stack (OPSD conventional)")
    with st.spinner("Loading OPSD plant metadata..."):
        all_plants = load_all_plants()
    if all_plants.empty:
        st.error("No OPSD plants available. Check data/external cache.")
        return
    zone_options = sorted(all_plants["bidding_zone"].dropna().unique().tolist())
    default_zones = [z for z in ("DE_LU", "FR") if z in zone_options] or zone_options[
        :1
    ]
    zones = st.multiselect(
        "Bidding zones",
        options=zone_options,
        default=default_zones,
        key="plants_bidding_zones",
    )
    st.caption(
        "Plants are mapped to bidding zones when available; otherwise we fall back to country code."
    )
    min_cap = st.slider(
        "Minimum capacity (MW)",
        min_value=0,
        max_value=1000,
        value=50,
        step=10,
        key="plants_min_capacity_mw",
    )
    include_chp = st.checkbox("Include CHP", value=True, key="plants_include_chp")
    df = _filter_plants(
        all_plants,
        min_capacity=min_cap,
        include_chp=include_chp,
        bidding_zones=tuple(zones),
    )
    if df.empty:
        st.info("No plants after filters.")
        return

    co2_price_ui = st.number_input(
        "CO₂ price (EUR/t)",
        min_value=0.0,
        max_value=500.0,
        value=80.0,
        step=5.0,
        key="plants_co2_price_eur_per_t",
    )
    df = _attach_srmc(df, co2_price_override=co2_price_ui)
    df = _apply_table_filters(df)

    total_cap = df["capacity_mw"].sum()
    st.caption(
        f"{len(df)} plants | {total_cap:,.0f} MW total | bidding zones: {', '.join(zones)}"
    )

    col1, col2 = st.columns(2)
    with col1:
        if "fuel" in df:
            fuel_summary = (
                df.groupby("fuel")["capacity_mw"].sum().sort_values(ascending=False)
            )
            st.write("Capacity by fuel (MW):")
            st.dataframe(fuel_summary.round(1))
    with col2:
        if "stack_type" in df:
            type_summary = (
                df.groupby("stack_type")["capacity_mw"]
                .sum()
                .sort_values(ascending=False)
            )
            st.write("Capacity by stack type (MW):")
            st.dataframe(type_summary.round(1))
    st.write("Capacity by bidding zone (MW):")
    zone_summary = (
        df.groupby("bidding_zone")["capacity_mw"].sum().sort_values(ascending=False)
    )
    st.dataframe(zone_summary.round(1))

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
        fig.update_geos(
            fitbounds="locations",
            showcountries=True,
            lataxis_showgrid=True,
            lonaxis_showgrid=True,
        )
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.write("Plant table")
    display_cols = [
        c
        for c in [
            "name",
            "bidding_zone",
            "fuel",
            "stack_type",
            "srmc_eur_per_mwh",
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
            "fuel_price_eur_per_mwhth",
            "co2_price_eur_per_t",
            "availability_factor",
            "vom",
            "is_chp",
            "commissioned_year",
            "eic_code",
            "technology",
            "lat",
            "lon",
        ]
        if c in df.columns
    ]
    style = (
        df[display_cols]
        .style.format(
            {
                "srmc_eur_per_mwh": "{:.1f}",
                "capacity_mw": "{:,.1f}",
                "p_min_mw": "{:,.1f}",
                "p_max_mw": "{:,.1f}",
                "ramp_up_mw_per_min": "{:,.2f}",
                "ramp_down_mw_per_min": "{:,.2f}",
                "efficiency": "{:.2f}",
                "co2_intensity": "{:.2f}",
                "variable_om_eur_per_mwh": "{:.2f}",
                "fuel_price_eur_per_mwhth": "{:.2f}",
                "co2_price_eur_per_t": "{:.2f}",
                "availability_factor": "{:.2f}",
                "vom": "{:.2f}",
            }
        )
        .background_gradient(cmap="RdYlGn_r", subset=["srmc_eur_per_mwh"])
    )
    st.dataframe(style, use_container_width=True)


def main():
    st.set_page_config(page_title="Power forecasts", layout="wide")
    st.title("Power forecasts dashboard")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Demand forecasts",
            "Price forecasts",
            "Merit order rank",
            "Commodity prices",
            "Plants (OPSD)",
        ]
    )
    with tab1:
        demand_tab()
    with tab2:
        price_tab()
    with tab3:
        merit_order_rank_tab()
    with tab4:
        commodities_tab()
    with tab5:
        plants_tab()


if __name__ == "__main__":
    main()
