#!/usr/bin/env python3
"""
Interactive dashboard to visualize load time series per country:
  - actual load (ENTSO-E A65)
  - TSO day-ahead forecast
  - model-corrected forecast (bias-corrected)
  - error series (actual error and predicted error)

Run:
  python scripts/dashboard.py
Then open http://127.0.0.1:8050/ in your browser.
"""
from pathlib import Path
from typing import Tuple, Optional
import sys

import pandas as pd
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go

# Ensure local src package is importable when running as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.io import load_demand_series, load_tso_forecast_series

DATA_DIR = Path("data")


def _default_area(areas):
    return "DE_LU" if "DE_LU" in areas else (areas[0] if areas else None)


def _read_csv_or_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    return df


def load_area_data(area: str) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    Returns (merged_df, quantiles_df or None)
    merged_df columns: actual_load, tso_forecast, corrected_mean, actual_error, predicted_error
    quantiles_df columns (optional): corrected_q10, corrected_q50, corrected_q90
    """
    # demand_forecast contains tso_forecast and corrected_*
    fc_path_csv = DATA_DIR / area / "demand_forecast.csv"
    fc_path_pq = DATA_DIR / area / "demand_forecast.parquet"
    if fc_path_csv.exists():
        fc = _read_csv_or_parquet(fc_path_csv)
    elif fc_path_pq.exists():
        fc = _read_csv_or_parquet(fc_path_pq)
    else:
        raise FileNotFoundError(f"No forecast file for {area}")

    # actual load
    try:
        actual = load_demand_series(area)
    except FileNotFoundError:
        actual = None

    # tso forecast (historic)
    try:
        tso = load_tso_forecast_series(area)
    except FileNotFoundError:
        tso = None

    # Align on union of timestamps so actual history is visible
    idx_union = fc.index
    if actual is not None:
        idx_union = idx_union.union(actual.index)
    if tso is not None:
        idx_union = idx_union.union(tso.index)
    idx_union = idx_union.sort_values()

    merged = pd.DataFrame(index=idx_union)
    if actual is not None:
        merged["actual_load"] = actual.reindex(idx_union)
    if "tso_forecast" in fc.columns:
        merged["tso_forecast"] = fc["tso_forecast"].reindex(idx_union)
    elif tso is not None:
        merged["tso_forecast"] = tso.reindex(idx_union)
    if "corrected_mean" in fc.columns:
        merged["corrected_mean"] = fc["corrected_mean"].reindex(idx_union)
    elif "mean" in fc.columns:
        merged["corrected_mean"] = fc["mean"].reindex(idx_union)

    # errors
    if "actual_load" in merged:
        if "tso_forecast" in merged:
            merged["actual_error"] = merged["actual_load"] - merged["tso_forecast"]
            merged["tso_error"] = merged["tso_forecast"] - merged["actual_load"]
        if "corrected_mean" in merged:
            merged["predicted_error"] = merged["corrected_mean"] - merged.get("tso_forecast", 0)
            merged["model_error"] = merged["corrected_mean"] - merged["actual_load"]

    quantiles = None
    q_cols = [c for c in fc.columns if c.startswith("corrected_q")]
    if q_cols:
        quantiles = fc[q_cols].reindex(idx_union)

    return merged.dropna(how="all"), quantiles


def build_series_figure(df: pd.DataFrame, quantiles: Optional[pd.DataFrame]) -> go.Figure:
    fig = go.Figure()
    if "actual_load" in df:
        series = df["actual_load"].dropna()
        fig.add_trace(go.Scatter(x=series.index, y=series, mode="lines", name="Actual load"))
    if "tso_forecast" in df:
        series = df["tso_forecast"].dropna()
        fig.add_trace(go.Scatter(x=series.index, y=series, mode="lines", name="TSO forecast", line=dict(dash="dot")))
    if "corrected_mean" in df:
        fig.add_trace(
            go.Scatter(
                x=df["corrected_mean"].dropna().index,
                y=df["corrected_mean"].dropna(),
                mode="lines",
                name="Model (corrected)",
                line=dict(color="#d62728"),
            )
        )
    if quantiles is not None:
        if "corrected_q90" in quantiles and "corrected_q10" in quantiles:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=quantiles["corrected_q90"],
                    mode="lines",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=quantiles["corrected_q10"],
                    mode="lines",
                    line=dict(width=0),
                    fill="tonexty",
                    fillcolor="rgba(214,39,40,0.15)",
                    name="Model q10–q90",
                )
            )
        if "corrected_q50" in quantiles and "corrected_mean" not in df:
            fig.add_trace(go.Scatter(x=df.index, y=quantiles["corrected_q50"], mode="lines", name="Model (q50)"))

    fig.update_layout(
        title="Load and forecasts",
        xaxis_title="Time",
        yaxis_title="MW",
        legend_orientation="h",
        height=480,
        margin=dict(l=30, r=10, t=30, b=30),
    )
    return fig


def build_error_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if "model_error" in df:
        series = df["model_error"].dropna()
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series,
                mode="lines",
                name="Model error (model - actual)",
                line=dict(color="#d62728"),
            )
        )
    if "tso_error" in df:
        series = df["tso_error"].dropna()
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series,
                mode="lines",
                name="TSO error (tso - actual)",
                line=dict(color="#1f77b4", dash="dot"),
            )
        )
    fig.update_layout(
        title="Error series",
        xaxis_title="Time",
        yaxis_title="MW",
        legend_orientation="h",
        height=280,
        margin=dict(l=30, r=10, t=30, b=30),
    )
    return fig


def build_app(refresh_seconds: int = 0):
    areas = sorted([p.name for p in DATA_DIR.iterdir() if p.is_dir() and (p / "demand_forecast.csv").exists()])
    default_area = _default_area(areas)

    app = dash.Dash(__name__)
    app.layout = html.Div(
        [
            html.H2("Demand forecast dashboard"),
            dcc.Interval(
                id="refresh-interval",
                interval=max(int(refresh_seconds), 1) * 1000,
                n_intervals=0,
                disabled=(not refresh_seconds),
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Bidding zone"),
                            html.Div(
                                dcc.RadioItems(
                                    id="area",
                                    options=[{"label": a, "value": a} for a in areas],
                                    value=default_area,
                                    labelStyle={"display": "block", "padding": "2px 0"},
                                    inputStyle={"marginRight": "6px"},
                                ),
                                style={
                                    "border": "1px solid #ddd",
                                    "borderRadius": "4px",
                                    "padding": "6px 8px",
                                    "maxHeight": "520px",
                                    "overflowY": "auto",
                                    "backgroundColor": "white",
                                },
                            ),
                        ],
                        style={"width": "260px", "flexShrink": 0},
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label("Time horizon"),
                                            dcc.Dropdown(
                                                id="horizon",
                                                options=[
                                                    {"label": "Last 7 days", "value": "7d"},
                                                    {"label": "Last 30 days", "value": "30d"},
                                                    {"label": "Last 90 days", "value": "90d"},
                                                    {"label": "Last 180 days", "value": "180d"},
                                                    {"label": "Last 365 days", "value": "365d"},
                                                    {"label": "All history", "value": "all"},
                                                ],
                                                value="90d",
                                                clearable=False,
                                            ),
                                        ],
                                        style={"width": "180px"},
                                    ),
                                    html.Div(
                                        [
                                            html.Label("Start date / time"),
                                            dcc.DatePickerSingle(id="start-date", display_format="YYYY-MM-DD"),
                                            dcc.Input(
                                                id="start-time",
                                                type="time",
                                                placeholder="HH:MM",
                                                style={"width": "120px", "marginLeft": "6px"},
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        [
                                            html.Label("End date / time"),
                                            dcc.DatePickerSingle(id="end-date", display_format="YYYY-MM-DD"),
                                            dcc.Input(
                                                id="end-time",
                                                type="time",
                                                placeholder="HH:MM",
                                                style={"width": "120px", "marginLeft": "6px"},
                                            ),
                                        ],
                                    ),
                                ],
                                style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "8px"},
                            ),
                            dcc.Graph(id="series-graph"),
                            dcc.Graph(id="error-graph"),
                            html.Div(id="meta-text", style={"marginTop": "8px", "fontSize": "12px", "color": "#444"}),
                        ],
                        style={"minWidth": "480px", "flex": "1 1 auto"},
                    ),
                ],
                style={"display": "flex", "gap": "16px", "alignItems": "flex-start", "flexWrap": "wrap"},
            ),
        ],
        style={"maxWidth": "1400px", "margin": "0 auto", "padding": "8px 8px 4px 8px"},
    )

    @app.callback(
        [Output("series-graph", "figure"), Output("error-graph", "figure"), Output("meta-text", "children")],
        [
            Input("area", "value"),
            Input("horizon", "value"),
            Input("start-date", "date"),
            Input("start-time", "value"),
            Input("end-date", "date"),
            Input("end-time", "value"),
            Input("refresh-interval", "n_intervals"),
        ],
    )
    def update_graphs(area, horizon, start_date, start_time, end_date, end_time, _n):
        if not area:
            return go.Figure(), go.Figure(), "No area selected"
        try:
            df, quantiles = load_area_data(area)
        except Exception as e:
            return go.Figure(), go.Figure(), f"Failed to load data for {area}: {e}"

        # apply explicit datetime range if provided; otherwise use horizon
        def parse_dt(date_val, time_val, is_end=False):
            if not date_val:
                return None
            try:
                base = pd.to_datetime(date_val)
                if time_val:
                    base = pd.to_datetime(f"{date_val} {time_val}")
                elif is_end:
                    base = base + pd.Timedelta(hours=23, minutes=59)
                return base
            except Exception:
                return None

        start = parse_dt(start_date, start_time, is_end=False)
        end = parse_dt(end_date, end_time, is_end=True)
        if start or end:
            if start is None:
                start = df.index.min()
            if end is None:
                end = df.index.max()
            df = df[(df.index >= start) & (df.index <= end)]
            if quantiles is not None:
                quantiles = quantiles.reindex(df.index)
        elif horizon and horizon != "all" and len(df) > 0:
            try:
                days = int(str(horizon).rstrip("d"))
                cutoff = df.index.max() - pd.Timedelta(days=days)
                df = df[df.index >= cutoff]
                if quantiles is not None:
                    quantiles = quantiles.reindex(df.index)
            except Exception:
                pass

        if df.empty:
            return go.Figure(), go.Figure(), f"{area}: no data for selected range"

        fig_series = build_series_figure(df, quantiles)
        fig_error = build_error_figure(df)
        meta_parts = [f"{area}: {len(df):,} points", f"{df.index.min()} → {df.index.max()}"]
        present_cols = [c for c in ("actual_load", "tso_forecast", "corrected_mean") if c in df.columns and df[c].notna().any()]
        if present_cols:
            meta_parts.append(f"series: {', '.join(present_cols)}")
        missing_cols = [c for c in ("actual_load", "tso_forecast", "corrected_mean") if c not in present_cols]
        nonnull_counts = {c: int(df[c].notna().sum()) for c in ("actual_load", "tso_forecast", "corrected_mean") if c in df}
        if nonnull_counts:
            meta_parts.append("counts: " + ", ".join([f"{k}={v}" for k, v in nonnull_counts.items()]))
        if missing_cols:
            meta_parts.append(f"missing: {', '.join(missing_cols)}")
        meta = " | ".join(meta_parts)
        return fig_series, fig_error, meta

    return app


if __name__ == "__main__":
    import argparse
    import subprocess
    import os

    def _find_listening_pids(port: int) -> set[int]:
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, encoding="utf-8", errors="ignore")
        except Exception:
            return set()
        pids: set[int] = set()
        for line in out.splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            local = parts[1]
            state = parts[3].upper()
            pid_str = parts[4]
            if state != "LISTENING":
                continue
            if not (local.endswith(f":{port}") or local.endswith(f"]:{port}")):
                continue
            try:
                pids.add(int(pid_str))
            except ValueError:
                continue
        return pids

    def _kill_pids(pids: set[int]) -> None:
        for pid in sorted(pids):
            try:
                subprocess.check_call(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Killed process PID {pid} (was listening on dashboard port).")
            except Exception as e:
                print(f"Failed to kill PID {pid}: {e}")

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1", help="Host to bind (use 0.0.0.0 to allow LAN access)")
    p.add_argument("--port", type=int, default=8050)
    p.add_argument("--dev", action="store_true", help="Enable Dash dev tools (hot reload)")
    p.add_argument("--kill-port", action="store_true", help="Kill any process currently listening on --port before starting")
    p.add_argument("--refresh-seconds", type=int, default=0, help="Auto-refresh charts every N seconds (0 disables)")
    args = p.parse_args()

    if args.kill_port:
        _kill_pids(_find_listening_pids(args.port))

    dash_app = build_app(refresh_seconds=max(int(args.refresh_seconds), 0))
    url = f"http://{args.host}:{args.port}"
    print(f"Starting dashboard on {url}")
    dash_app.run(host=args.host, port=args.port, debug=bool(args.dev))
