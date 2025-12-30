#!/usr/bin/env python3
"""Unified Streamlit dashboard for demand and price forecasts."""
import json
import math
import os
import subprocess
import importlib
import importlib.util
from datetime import timedelta
from pathlib import Path
from typing import Optional, Tuple, List, Union
import sys

_REQUIRED_MODULES = {
    "pandas": "pandas",
    "streamlit": "streamlit",
    "pyecharts": "pyecharts",
    "streamlit_echarts": "streamlit-echarts",
    "s3fs": "s3fs",
    "dotenv": "python-dotenv",
    "catboost": "catboost",
    "sklearn": "scikit-learn",
    "joblib": "joblib",
}
_missing = [
    pkg
    for mod, pkg in _REQUIRED_MODULES.items()
    if importlib.util.find_spec(mod) is None
]
if _missing:
    missing_list = ", ".join(sorted(set(_missing)))
    raise RuntimeError(
        "Missing required packages for the dashboard: "
        f"{missing_list}. Install with pip or poetry."
    )

import pandas as pd
import streamlit as st
from pyecharts import options as opts
from pyecharts.charts import Line, Scatter
from pyecharts.commons.utils import JsCode
from streamlit_echarts import st_pyecharts

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(ROOT / ".env", override=True)
if not os.getenv("AWS_DEFAULT_REGION") and not os.getenv("AWS_REGION"):
    os.environ["AWS_DEFAULT_REGION"] = "eu-north-1"
if not os.getenv("S3_BUCKET"):
    os.environ["S3_BUCKET"] = "zkong-power"
if not os.getenv("S3_PREFIX"):
    os.environ["S3_PREFIX"] = "stack-model/data"
if not os.getenv("S3_ONLY"):
    os.environ["S3_ONLY"] = "1"

from src.data import io as data_io

if not hasattr(data_io, "write_frame") or not hasattr(
    data_io, "resolve_write_path"
):
    data_io = importlib.reload(data_io)

DATA_DIR = data_io.DATA_DIR
io_list_areas_with_any_files = data_io.list_areas_with_any_files
io_list_areas_with_file = data_io.list_areas_with_file
load_demand_series = data_io.load_demand_series
load_tso_forecast_series = data_io.load_tso_forecast_series
load_tso_forecast_publication = data_io.load_tso_forecast_publication
load_price_series = data_io.load_price_series
read_frame = data_io.read_frame
resolve_write_path = getattr(data_io, "resolve_write_path", lambda p: p)
resolve_data_path = getattr(data_io, "resolve_data_path", lambda p: p)


def _fallback_write_frame(df, path, index_label=None, index=True):
    target = resolve_write_path(path)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    if str(target).endswith(".parquet"):
        df.to_parquet(target)
    else:
        df.to_csv(
            target, index=index, index_label=index_label if index else None
        )
    return target


write_frame = getattr(data_io, "write_frame", _fallback_write_frame)
path_exists = getattr(data_io, "path_exists", lambda p: Path(p).exists())
from src.power_model.plants import PlantStack

st.set_page_config(page_title="Power forecasts", layout="wide")

MARKET_DIR = DATA_DIR / "market"
TIMEZONE_OPTIONS = [
    "UTC",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/London",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Oslo",
    "Europe/Zurich",
]


def _downsample_indexed(obj, max_points: int):
    if obj is None:
        return None
    if max_points is None or max_points <= 0:
        return obj
    try:
        n = len(obj)
    except TypeError:
        return obj
    if n <= max_points:
        return obj
    step = max(2, int(math.ceil(n / max_points)))
    sampled = obj.iloc[::step]
    try:
        if len(sampled) > 0 and getattr(sampled, "index", None) is not None:
            if sampled.index[-1] != obj.index[-1]:
                sampled = pd.concat([sampled, obj.iloc[[-1]]])
    except Exception:
        pass
    return sampled


def _downsample_rows(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    if max_rows is None or max_rows <= 0:
        return df
    if df is None or df.empty:
        return df
    if len(df) <= max_rows:
        return df
    step = max(2, int(math.ceil(len(df) / max_rows)))
    return df.iloc[::step].copy()


def _format_index_as_strings(index: pd.Index) -> List[str]:
    idx = pd.to_datetime(index)
    return [pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M") for ts in idx]


def _pyecharts_timeseries_line(
    x: List[str],
    series: List[tuple[str, List, dict]],
    yaxis_title: str,
    height_px: int = 500,
    tooltip_formatter: Optional[JsCode] = None,
    legend_exclude: Optional[List[str]] = None,
) -> Line:
    chart = Line(
        init_opts=opts.InitOpts(
            height=f"{int(height_px)}px",
            width="100%",
            animation_opts=opts.AnimationOpts(animation=False),
        )
    )
    chart.add_xaxis(x)

    for name, y, style in series:
        style = style or {}
        line_width = style.get("width", 1.2)
        line_type = style.get("type_", "solid")
        line_color = style.get("color")
        line_opacity = style.get("line_opacity", 1.0)
        if style.get("hide_line"):
            line_width = 0
            line_opacity = 0

        line_opts = opts.LineStyleOpts(
            width=line_width,
            opacity=line_opacity,
            type_=line_type,
            color=line_color,
        )
        area_color = style.get("area_color")
        area_opacity = style.get("area_opacity", 0.2)
        area_opts = (
            opts.AreaStyleOpts(opacity=area_opacity, color=area_color)
            if area_color
            else None
        )
        stack = style.get("stack")
        is_symbol_show = style.get("is_symbol_show", False)

        chart.add_yaxis(
            name,
            y,
            is_connect_nones=True,
            is_symbol_show=is_symbol_show,
            symbol=None,
            is_hover_animation=False,
            sampling="lttb",
            label_opts=opts.LabelOpts(is_show=False),
            linestyle_opts=line_opts,
            areastyle_opts=area_opts,
            stack=stack,
        )

    tooltip_opts = opts.TooltipOpts(
        trigger="axis",
        axis_pointer_type="line",
        formatter=tooltip_formatter,
    )
    chart.set_global_opts(
        tooltip_opts=tooltip_opts,
        legend_opts=opts.LegendOpts(pos_top="2%"),
        datazoom_opts=[
            opts.DataZoomOpts(type_="inside"),
            opts.DataZoomOpts(type_="slider", pos_bottom="0%"),
        ],
        xaxis_opts=opts.AxisOpts(
            type_="category",
            boundary_gap=False,
            axislabel_opts=opts.LabelOpts(
                rotate=45, interval="auto", margin=14
            ),
        ),
        yaxis_opts=opts.AxisOpts(
            type_="value", name=yaxis_title, min_="dataMin", max_="dataMax"
        ),
    )
    if legend_exclude and chart.options.get("legend"):
        legend = chart.options["legend"][0]
        data = legend.get("data", [])
        legend["data"] = [
            name for name in data if name not in set(legend_exclude)
        ]
    return chart


def _render_chart(chart, height_px: int) -> None:
    with st.spinner("Rendering chart..."):
        st_pyecharts(chart, height=f"{int(height_px)}px", renderer="canvas")


def _series_to_list(series: pd.Series) -> List[Optional[float]]:
    return [None if pd.isna(v) else float(v) for v in series.tolist()]


def _series_band_base_diff(
    low: pd.Series, high: pd.Series
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    valid = low.notna() & high.notna()
    base = low.where(valid)
    diff = (high - low).where(valid)
    return _series_to_list(base), _series_to_list(diff)


def _demand_tooltip_formatter(
    actual_updates: List[str],
    tso_updates: List[str],
    q10_vals: List[Optional[float]],
    q90_vals: List[Optional[float]],
) -> JsCode:
    actual_json = json.dumps(actual_updates)
    tso_json = json.dumps(tso_updates)
    q10_json = json.dumps(q10_vals)
    q90_json = json.dumps(q90_vals)
    return JsCode(
        f"""
        function (params) {{
          if (!params || params.length === 0) {{
            return '';
          }}
          var axis = params[0].axisValue || '';
          var idx = params[0].dataIndex || 0;
          var actualUpdates = {actual_json};
          var tsoUpdates = {tso_json};
          var q10Vals = {q10_json};
          var q90Vals = {q90_json};

          function isNum(val) {{
            return !(val === null || val === undefined || val === '' || isNaN(Number(val)));
          }}

          var lines = [axis];
          for (var i = 0; i < params.length; i++) {{
            var p = params[i];
            if (p.seriesName === 'Model q10 base') {{
              continue;
            }}
            var val = p.value;
            if (Array.isArray(val) && val.length > 1) {{
              val = val[1];
            }}
            var lineVal = (isNum(val) ? Number(val).toFixed(2) : 'n/a');
            var line = p.marker + p.seriesName + ': ' + lineVal;
            if (p.seriesName === 'Model q10–q90') {{
              var lo = q10Vals[idx];
              var hi = q90Vals[idx];
              if (isNum(lo) && isNum(hi)) {{
                line = p.marker + p.seriesName + ': ' + Number(lo).toFixed(2) + '–' + Number(hi).toFixed(2);
              }}
            }}
            if (p.seriesName === 'Actual load') {{
              var upd = actualUpdates[idx] || axis || 'n/a';
              line += '<br/>UpdateTime (UTC): ' + upd;
            }}
            if (p.seriesName === 'TSO forecast') {{
              var upd2 = tsoUpdates[idx] || axis || 'n/a';
              line += '<br/>UpdateTime (UTC): ' + upd2;
            }}
            lines.push(line);
          }}
          return lines.join('<br/>');
        }}
        """
    )


def _load_secrets_into_env():
    """Propagate Streamlit secrets to env vars so ingestion code can read tokens locally."""
    needs_entsoe = not os.getenv("ENTSOE_API_TOKEN")
    needs_tv = (not os.getenv("TV_USERNAME")) or (not os.getenv("TV_PASSWORD"))
    s3_keys = [
        "S3_BUCKET",
        "S3_PREFIX",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
    ]
    needs_s3 = any(not os.getenv(k) for k in s3_keys)
    if not needs_entsoe and not needs_tv and not needs_s3:
        return
    try:
        token = st.secrets.get("ENTSOE_API_TOKEN") or st.secrets.get(
            "ENTSOE_TOKEN"
        )
        tv_user = st.secrets.get("TV_USERNAME")
        tv_pwd = st.secrets.get("TV_PASSWORD")
        s3_secret_map = {k: st.secrets.get(k) for k in s3_keys}
    except Exception:
        token = None
        tv_user = None
        tv_pwd = None
        s3_secret_map = {}
    if needs_entsoe and token:
        os.environ["ENTSOE_API_TOKEN"] = str(token)
    if needs_tv and tv_user and not os.getenv("TV_USERNAME"):
        os.environ["TV_USERNAME"] = str(tv_user)
    if needs_tv and tv_pwd and not os.getenv("TV_PASSWORD"):
        os.environ["TV_PASSWORD"] = str(tv_pwd)
    if needs_s3:
        for key in s3_keys:
            if os.getenv(key):
                continue
            val = s3_secret_map.get(key)
            if val:
                os.environ[key] = str(val)


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
            return (
                False,
                out.strip() or f"git lfs pull failed (code={proc.returncode})",
            )
        return True, out.strip() or "git lfs pull succeeded"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _list_areas_with_file(filename: str) -> List[str]:
    return io_list_areas_with_file(filename)


def _read_csv_indexed(path: Path) -> pd.DataFrame:
    df = read_frame(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def _path_last_modified(path: Union[str, Path]) -> Optional[pd.Timestamp]:
    try:
        if isinstance(path, str) and path.startswith("s3://"):
            info = data_io._get_s3_fs().info(path)
            ts = info.get("LastModified") or info.get("last_modified")
            if ts is None:
                return None
            return pd.to_datetime(ts, utc=True)
        return pd.Timestamp.fromtimestamp(
            Path(path).stat().st_mtime, tz="UTC"
        )
    except Exception:
        return None


def _latest_file_update(paths: List[Path]) -> Optional[pd.Timestamp]:
    latest = None
    for path in paths:
        try:
            resolved = resolve_data_path(path)
        except FileNotFoundError:
            continue
        if not path_exists(resolved):
            continue
        modified = _path_last_modified(resolved)
        if modified is None:
            continue
        if latest is None or modified > latest:
            latest = modified
    return latest


def _apply_horizon(df: pd.DataFrame, horizon: str) -> pd.DataFrame:
    if df.empty or horizon == "all":
        return df
    try:
        days = int(str(horizon).rstrip("d"))
        cutoff = df.index.max() - pd.Timedelta(days=days)
        return df[df.index >= cutoff]
    except Exception:
        return df


def _apply_date_range(obj, start_date, end_date):
    if obj is None:
        return None
    if getattr(obj, "empty", False):
        return obj
    if not hasattr(obj, "index"):
        return obj
    start_ts = pd.Timestamp(start_date)
    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    if isinstance(obj.index, pd.DatetimeIndex) and obj.index.tz is not None:
        start_ts = start_ts.tz_localize(obj.index.tz)
        end_exclusive = end_exclusive.tz_localize(obj.index.tz)
    return obj[(obj.index >= start_ts) & (obj.index < end_exclusive)]


def _convert_index_timezone(obj, tz_name: str):
    if obj is None:
        return None
    if not hasattr(obj, "index"):
        return obj
    idx = pd.to_datetime(obj.index)
    if isinstance(idx, pd.DatetimeIndex):
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        try:
            idx = idx.tz_convert(tz_name) if tz_name else idx.tz_convert("UTC")
        except Exception:
            idx = idx.tz_convert("UTC")
        out = obj.copy()
        out.index = idx
        return out
    return obj


def _format_timestamp_series(
    series: pd.Series,
    tz_name: str,
    default: str = "n/a",
    include_tz_label: bool = False,
    fmt: str = "%Y-%m-%d %H:%M",
) -> pd.Series:
    if series is None:
        return pd.Series([], dtype="object")
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.empty:
        return pd.Series([], dtype="object")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize("UTC")
    try:
        parsed = parsed.dt.tz_convert(tz_name) if tz_name else parsed
    except Exception:
        parsed = parsed.dt.tz_convert("UTC")
    out = parsed.dt.strftime(fmt).fillna(default)
    if include_tz_label and tz_name:
        out = out.where(out == default, out + f" ({tz_name})")
    return out


def _load_raw_update_time_series(area: str, filename: str) -> pd.Series:
    path = DATA_DIR / area / filename
    try:
        resolved = resolve_data_path(path)
    except FileNotFoundError:
        return pd.Series(dtype="datetime64[ns]")
    if not path_exists(resolved):
        return pd.Series(dtype="datetime64[ns]")
    df = read_frame(resolved)
    if df.empty:
        return pd.Series(dtype="datetime64[ns]")
    if "DateTime(UTC)" not in df.columns or "UpdateTime(UTC)" not in df.columns:
        return pd.Series(dtype="datetime64[ns]")
    times = pd.to_datetime(
        df["DateTime(UTC)"], dayfirst=True, errors="coerce", utc=True
    )
    updates = pd.to_datetime(
        df["UpdateTime(UTC)"], dayfirst=True, errors="coerce", utc=True
    )
    series = pd.Series(updates.values, index=times)
    series = series[~series.index.isna()]
    series = series[~series.index.duplicated(keep="last")]
    return series.sort_index()


def load_demand_data(area: str) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    fc_path = DATA_DIR / area / "demand_forecast.csv"
    try:
        fc = _read_csv_indexed(fc_path)
    except FileNotFoundError:
        return pd.DataFrame(), None

    try:
        actual = load_demand_series(area, prefer_parquet=False)
    except FileNotFoundError:
        actual = pd.Series(dtype=float)
    try:
        tso = load_tso_forecast_series(area, prefer_parquet=False)
    except FileNotFoundError:
        tso = pd.Series(dtype=float)
    try:
        tso_pub = load_tso_forecast_publication(area, prefer_parquet=False)
    except FileNotFoundError:
        tso_pub = pd.Series(dtype="datetime64[ns]")

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
        if tso_pub is not None and not tso_pub.empty:
            merged["tso_publication_time_utc"] = tso_pub.reindex(idx_union)
        elif "tso_publication_time_utc" in fc.columns:
            pub = pd.to_datetime(
                fc["tso_publication_time_utc"], errors="coerce"
            )
            if getattr(pub.dt, "tz", None) is not None:
                pub = pub.dt.tz_convert("UTC").dt.tz_localize(None)
            merged["tso_publication_time_utc"] = pub.reindex(idx_union)
    elif not tso.empty:
        merged["tso_forecast"] = tso.reindex(idx_union)
        if tso_pub is not None and not tso_pub.empty:
            merged["tso_publication_time_utc"] = tso_pub.reindex(idx_union)
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
    try:
        actual = load_price_series(area, prefer_parquet=False).sort_index()
    except FileNotFoundError:
        actual = pd.Series(dtype=float)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Failed to load actual price series for {area}: {exc}")
        actual = pd.Series(dtype=float)
    if (
        isinstance(actual.index, pd.DatetimeIndex)
        and actual.index.tz is not None
    ):
        actual.index = actual.index.tz_convert("UTC").tz_localize(None)

    fwd_path = DATA_DIR / area / "price_forecast.csv"
    history_path = DATA_DIR / area / "price_history_predictions.csv"

    try:
        forward = _read_csv_indexed(fwd_path)
    except FileNotFoundError:
        forward = None
    try:
        history = _read_csv_indexed(history_path)
    except FileNotFoundError:
        history = None
    if history is not None and "pred" not in history.columns:
        if "mean" in history.columns:
            history = history.rename(columns={"mean": "pred"})
        elif "corrected_mean" in history.columns:
            history = history.rename(columns={"corrected_mean": "pred"})
    return actual, forward, history


def demand_tab():
    # Keep tab header clean; the controls below act as the section header.
    areas = _list_areas_with_file("demand_forecast.csv")
    if not areas:
        cfg = data_io._s3_config()
        region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION")
        has_key = bool(os.getenv("AWS_ACCESS_KEY_ID"))
        has_secret = bool(os.getenv("AWS_SECRET_ACCESS_KEY"))
        if cfg:
            bucket, prefix = cfg
            st.info(
                "No demand forecasts available. "
                f"S3 bucket={bucket}, prefix={prefix}, "
                f"region={region or 'n/a'}, "
                f"aws_key_set={has_key}, aws_secret_set={has_secret}."
            )
        else:
            st.info(
                "No demand forecasts available. "
                "S3 is not configured; check S3_BUCKET and S3_PREFIX."
            )
        return
    col_area, col_tz, col_range = st.columns([1.2, 1.0, 2.0])
    with col_area:
        area = st.selectbox(
            "Bidding zone",
            options=areas,
            index=(areas.index("DE_LU") if "DE_LU" in areas else 0),
        )
    with col_tz:
        timezone = st.selectbox(
            "Timezone",
            options=TIMEZONE_OPTIONS,
            index=0,
            key="demand_timezone",
        )

    df, quantiles = load_demand_data(area)
    if df.empty:
        st.info("No demand data available for this zone.")
        return

    df = _convert_index_timezone(df, timezone)
    if quantiles is not None:
        quantiles = _convert_index_timezone(quantiles, timezone)

    min_date = df.index.min().date()
    max_date = df.index.max().date()
    default_end = max_date
    default_start = max(min_date, max_date - timedelta(days=2))
    with col_range:
        date_range = st.date_input(
            "Date range (inclusive)",
            value=(default_start, default_end),
            min_value=min_date,
            max_value=max_date,
            key="demand_date_range",
        )
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select a start and end date.")
        return
    start_date, end_date = date_range
    if start_date > end_date:
        st.error("Start date must be <= end date.")
        return

    df = _apply_date_range(df, start_date, end_date)
    if quantiles is not None:
        quantiles = _apply_date_range(quantiles, start_date, end_date)

    actual_update_series = _load_raw_update_time_series(
        area, "load_actual_raw.csv"
    )
    if actual_update_series is not None and not actual_update_series.empty:
        update_frame = actual_update_series.to_frame("upd")
        update_frame = _convert_index_timezone(update_frame, timezone)
        df["actual_update_time_utc"] = update_frame["upd"].reindex(df.index)

    tso_update_series = _load_raw_update_time_series(
        area, "load_forecast_raw.csv"
    )
    if tso_update_series is not None and not tso_update_series.empty:
        update_frame = tso_update_series.to_frame("upd")
        update_frame = _convert_index_timezone(update_frame, timezone)
        df["tso_update_time_utc"] = update_frame["upd"].reindex(df.index)

    # Keep the demand tab responsive by default without exposing UI controls.
    fast_plot = True
    max_plot_points = 25_000
    max_table_rows = 10_000

    plot_df = df.copy()
    if quantiles is not None:
        plot_df = plot_df.join(quantiles, how="left")
    if "tso_update_time_utc" in plot_df.columns:
        plot_df["tso_pub_local"] = _format_timestamp_series(
            plot_df["tso_update_time_utc"],
            "UTC",
            include_tz_label=False,
            fmt="%d/%m/%Y %H:%M",
        )
    else:
        tso_pub_series = load_tso_forecast_publication(
            area, prefer_parquet=False
        )
        if tso_pub_series is not None and not tso_pub_series.empty:
            pub_frame = tso_pub_series.to_frame("pub")
            pub_frame = _convert_index_timezone(pub_frame, timezone)
            pub_aligned = pub_frame["pub"].reindex(plot_df.index)
            plot_df["tso_pub_local"] = _format_timestamp_series(
                pub_aligned,
                timezone,
                include_tz_label=True,
            )
        elif "tso_publication_time_utc" in plot_df.columns:
            plot_df["tso_pub_local"] = _format_timestamp_series(
                plot_df["tso_publication_time_utc"],
                timezone,
                include_tz_label=True,
            )
    if fast_plot:
        plot_df = _downsample_indexed(plot_df, max_plot_points)

    x = _format_index_as_strings(plot_df.index)
    tz_label = f" ({timezone})" if timezone else ""
    series: List[tuple[str, List, dict]] = []
    actual_updates: List[str] = []
    tso_updates: List[str] = []
    q10_vals: List[Optional[float]] = []
    q90_vals: List[Optional[float]] = []
    plot_len = len(plot_df)

    if {"corrected_q10", "corrected_q90"}.issubset(plot_df.columns):
        q10 = plot_df["corrected_q10"]
        q90 = plot_df["corrected_q90"]
        q10_vals = _series_to_list(q10)
        q90_vals = _series_to_list(q90)
        base, diff = _series_band_base_diff(q10, q90)
        series.append(
            (
                "Model q10 base",
                base,
                {"stack": "q_band", "hide_line": True, "line_opacity": 0},
            )
        )
        series.append(
            (
                "Model q10–q90",
                diff,
                {
                    "stack": "q_band",
                    "hide_line": True,
                    "color": "#f2a3a3",
                    "area_color": "rgba(242,163,163,0.45)",
                    "area_opacity": 0.45,
                },
            )
        )
    if "actual_load" in plot_df:
        actual_updates = ["n/a"] * plot_len
        if "actual_update_time_utc" in plot_df.columns:
            formatted = _format_timestamp_series(
                plot_df["actual_update_time_utc"],
                "UTC",
                include_tz_label=False,
                fmt="%d/%m/%Y %H:%M",
            )
            actual_updates = formatted.fillna("n/a").tolist()
        else:
            actual_update_ts = _latest_file_update(
                [
                    DATA_DIR / area / "load_actual.parquet",
                    DATA_DIR / area / "load_actual.csv",
                    DATA_DIR / area / "load_real.parquet",
                    DATA_DIR / area / "load_real.csv",
                    DATA_DIR / area / "load.parquet",
                    DATA_DIR / area / "load.csv",
                ]
            )
            if actual_update_ts is not None:
                formatted = _format_timestamp_series(
                    pd.Series([actual_update_ts]),
                    timezone,
                    include_tz_label=True,
                )
                if not formatted.empty:
                    actual_updates = [formatted.iloc[0]] * plot_len
            elif "actual_load" in df and df["actual_load"].notna().any():
                last_actual = df["actual_load"].dropna().index.max()
                formatted = _format_timestamp_series(
                    pd.Series([last_actual]),
                    timezone,
                    include_tz_label=True,
                )
                if not formatted.empty:
                    actual_updates = [formatted.iloc[0]] * plot_len
        series.append(
            (
                "Actual load",
                _series_to_list(plot_df["actual_load"]),
                {"width": 1.5},
            )
        )
    if "tso_forecast" in plot_df:
        tso_updates = ["n/a"] * plot_len
        if "tso_pub_local" in plot_df:
            tso_updates = (
                plot_df["tso_pub_local"]
                .fillna("n/a")
                .astype(str)
                .tolist()
            )
        tso_update_ts = _latest_file_update(
            [
                DATA_DIR / area / "load_forecast.parquet",
                DATA_DIR / area / "load_forecast.csv",
            ]
        )
        tso_fallback = None
        if tso_update_ts is not None:
            formatted = _format_timestamp_series(
                pd.Series([tso_update_ts]),
                timezone,
                include_tz_label=True,
            )
            if not formatted.empty:
                tso_fallback = formatted.iloc[0]
        if tso_fallback:
            if tso_updates:
                tso_updates = [
                    tso_fallback if val in {"", "n/a"} else val
                    for val in tso_updates
                ]
            else:
                tso_updates = [tso_fallback] * plot_len
        elif (
            "tso_publication_time_utc" in df
            and df["tso_publication_time_utc"].notna().any()
        ):
            last_pub = df["tso_publication_time_utc"].dropna().max()
            formatted = _format_timestamp_series(
                pd.Series([last_pub]),
                timezone,
                include_tz_label=True,
            )
            if not formatted.empty:
                tso_updates = [formatted.iloc[0]] * plot_len
        series.append(
            (
                "TSO forecast",
                _series_to_list(plot_df["tso_forecast"]),
                {"type_": "dotted", "width": 1.2},
            )
        )
    if "corrected_mean" in plot_df:
        series.append(
            (
                "Model (corrected)",
                _series_to_list(plot_df["corrected_mean"]),
                {"color": "#1f77b4", "width": 1.5, "type_": "dashed"},
            )
        )

    tooltip_formatter = _demand_tooltip_formatter(
        actual_updates=actual_updates,
        tso_updates=tso_updates,
        q10_vals=q10_vals,
        q90_vals=q90_vals,
    )
    chart = _pyecharts_timeseries_line(
        x=x,
        series=series,
        yaxis_title="MW",
        height_px=500,
        tooltip_formatter=tooltip_formatter,
        legend_exclude=["Model q10 base"],
    )
    _render_chart(chart, 500)

    table = df.copy()
    if quantiles is not None:
        table = table.join(quantiles, how="left")
    table = table.sort_index()
    tso_pub_raw = None
    if "tso_publication_time_utc" in table.columns:
        tso_pub_raw = table["tso_publication_time_utc"]
        table = table.drop(columns=["tso_publication_time_utc"])
    if (
        "tso_update_time_utc" not in table.columns
        and tso_pub_raw is not None
    ):
        table["tso_update_time_utc"] = tso_pub_raw
    if "tso_update_time_utc" in table.columns:
        table["tso_update_time_utc"] = _format_timestamp_series(
            table["tso_update_time_utc"],
            "UTC",
            include_tz_label=False,
            fmt="%d/%m/%Y %H:%M",
        )
    if "actual_update_time_utc" in table.columns:
        table["actual_update_time_utc"] = _format_timestamp_series(
            table["actual_update_time_utc"],
            "UTC",
            include_tz_label=False,
            fmt="%d/%m/%Y %H:%M",
        )
    preferred_cols = [
        "actual_load",
        "tso_forecast",
        "actual_update_time_utc",
        "tso_update_time_utc",
        "corrected_mean",
        "corrected_q10",
        "corrected_q50",
        "corrected_q90",
    ]
    ordered = [c for c in preferred_cols if c in table.columns]
    ordered += [c for c in table.columns if c not in ordered]
    table = table[ordered]
    table_out = table.reset_index()
    if "index" in table_out.columns:
        table_out = table_out.rename(columns={"index": "datetime"})
    st.write("Data table")
    if len(table_out) > max_table_rows:
        st.caption(
            f"Showing last {max_table_rows:,} rows (of {len(table_out):,}) for performance."
        )
        table_out = table_out.tail(max_table_rows)
    st.dataframe(table_out, width="stretch")

    st.caption(
        f"{area} | timezone: {timezone} | points: {len(df):,} | span: {df.index.min()} → {df.index.max()}"
    )


def price_tab():
    st.subheader("Price forecasts")
    areas = _list_areas_with_any_files(
        (
            "day_ahead_real.parquet",
            "day_ahead_real.csv",
            "day_ahead.parquet",
            "day_ahead.csv",
        )
    )
    if not areas:
        cfg = data_io._s3_config()
        region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION")
        has_key = bool(os.getenv("AWS_ACCESS_KEY_ID"))
        has_secret = bool(os.getenv("AWS_SECRET_ACCESS_KEY"))
        if cfg:
            bucket, prefix = cfg
            st.info(
                "No price data available. "
                f"S3 bucket={bucket}, prefix={prefix}, "
                f"region={region or 'n/a'}, "
                f"aws_key_set={has_key}, aws_secret_set={has_secret}."
            )
        else:
            st.info(
                "No price data available. "
                "S3 is not configured; check S3_BUCKET and S3_PREFIX."
            )
        return
    area = st.selectbox(
        "Price area",
        options=areas,
        index=(areas.index("DE_LU") if "DE_LU" in areas else 0),
    )

    actual, forward, history = load_price_data(area)
    if (
        actual.empty
        and (forward is None or forward.empty)
        and (history is None or history.empty)
    ):
        st.info("No price data available for this area.")
        return

    idx_min = None
    idx_max = None
    for obj in [actual, forward, history]:
        if obj is None or getattr(obj, "empty", True):
            continue
        cur_min = obj.index.min()
        cur_max = obj.index.max()
        idx_min = cur_min if idx_min is None else min(idx_min, cur_min)
        idx_max = cur_max if idx_max is None else max(idx_max, cur_max)
    if idx_min is None or idx_max is None:
        st.info("No timestamped price data available for this area.")
        return

    min_date = pd.Timestamp(idx_min).date()
    max_date = pd.Timestamp(idx_max).date()
    default_end = max_date
    default_start = max(min_date, max_date - timedelta(days=90))
    date_range = st.date_input(
        "Date range (inclusive)",
        value=(default_start, default_end),
        min_value=min_date,
        max_value=max_date,
        key="price_date_range",
    )
    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select a start and end date.")
        return
    start_date, end_date = date_range
    if start_date > end_date:
        st.error("Start date must be <= end date.")
        return

    actual = _apply_date_range(actual, start_date, end_date)
    forward = _apply_date_range(forward, start_date, end_date)
    history = _apply_date_range(history, start_date, end_date)

    # Keep the price tab responsive by default without exposing UI controls.
    fast_plot = True
    max_plot_points = 25_000

    if fast_plot:
        actual_plot = actual
        forward_plot = forward
        history_plot = history
    else:
        actual_plot, forward_plot, history_plot = actual, forward, history

    idx_union = None
    for obj in [actual_plot, history_plot, forward_plot]:
        if obj is None or getattr(obj, "empty", True):
            continue
        idx_union = (
            obj.index if idx_union is None else idx_union.union(obj.index)
        )
    if idx_union is None or len(idx_union) == 0:
        st.info("No price data to plot.")
        return
    idx_union = idx_union.sort_values()

    merged = pd.DataFrame(index=idx_union)
    if len(actual_plot) > 0:
        merged["actual"] = actual_plot.reindex(idx_union)
    if history_plot is not None and "pred" in history_plot:
        merged["hist_pred"] = history_plot["pred"].reindex(idx_union)
    if forward_plot is not None and "mean" in forward_plot:
        merged["fwd_mean"] = forward_plot["mean"].reindex(idx_union)
    if forward_plot is not None and {"q10", "q90"}.issubset(
        forward_plot.columns
    ):
        merged["fwd_q10"] = forward_plot["q10"].reindex(idx_union)
        merged["fwd_q90"] = forward_plot["q90"].reindex(idx_union)

    if fast_plot:
        merged = _downsample_indexed(merged, max_plot_points)

    x = _format_index_as_strings(merged.index)
    series: List[tuple[str, List[Optional[float]], dict]] = []
    if "fwd_q10" in merged and "fwd_q90" in merged:
        q10 = merged["fwd_q10"]
        q90 = merged["fwd_q90"]
        base, diff = _series_band_base_diff(q10, q90)
        series.append(
            (
                "Forward q10 base",
                base,
                {"stack": "q_band", "hide_line": True, "line_opacity": 0},
            )
        )
        series.append(
            (
                "Forward q10–q90",
                diff,
                {
                    "stack": "q_band",
                    "hide_line": True,
                    "color": "#f2a3a3",
                    "area_color": "rgba(242,163,163,0.45)",
                    "area_opacity": 0.45,
                },
            )
        )
    if "actual" in merged:
        series.append(
            ("Actual price", _series_to_list(merged["actual"]), {"width": 1.5})
        )
    if "hist_pred" in merged:
        series.append(
            (
                "Historical pred",
                _series_to_list(merged["hist_pred"]),
                {"color": "#ff7f0e", "width": 1.2},
            )
        )
    if "fwd_mean" in merged:
        series.append(
            (
                "Forward pred",
                _series_to_list(merged["fwd_mean"]),
                {"color": "#d62728", "width": 1.5},
            )
        )

    chart = _pyecharts_timeseries_line(
        x=x,
        series=series,
        yaxis_title="EUR/MWh",
        height_px=500,
        legend_exclude=["Forward q10 base"],
    )
    _render_chart(chart, 500)

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


def _load_market_commodities() -> pd.DataFrame:
    candidates = [
        MARKET_DIR / "commodities.parquet",
        MARKET_DIR / "commodities.csv",
    ]
    for path in candidates:
        if (
            isinstance(path, Path)
            and path.exists()
            and _is_git_lfs_pointer(path)
        ):
            continue
        try:
            df = read_frame(path)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index)
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        df = df.sort_index()
        return df
    return pd.DataFrame()


def _fetch_market_commodities_from_tradingview() -> pd.DataFrame:
    """
    Fetch commodity proxies from TradingView via tvdatafeed (daily settlement).
    Returns a DataFrame indexed by datetime with columns gas, coal, co2.
    """
    try:
        from tvDatafeed import Interval, TvDatafeed  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "tvdatafeed is not available; install dependencies or upload a CSV."
        ) from e

    user = os.getenv("TV_USERNAME")
    pwd = os.getenv("TV_PASSWORD")
    tv = (
        TvDatafeed(username=user, password=pwd)
        if user and pwd
        else TvDatafeed()
    )

    symbols = {
        "gas": ("TFM1!", "ICEEUR"),  # TTF front month, EUR/MWh
        "coal": ("API2!", "ICEEUR"),  # API2 front, EUR/ton (proxy)
        "co2": ("EUA1!", "ICEEUR"),  # EUA front, EUR/t
    }

    rows = []
    for name, (symbol, exchange) in symbols.items():
        df = tv.get_hist(
            symbol=symbol,
            exchange=exchange,
            interval=Interval.in_daily,
            n_bars=900,
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
    return out


def commodities_tab():
    st.subheader("Commodity prices")

    lfs_candidate = None
    for p in [
        MARKET_DIR / "commodities.parquet",
        MARKET_DIR / "commodities.csv",
    ]:
        if isinstance(p, Path) and p.exists() and _is_git_lfs_pointer(p):
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
            if not df.empty and st.button(
                "Save to `data/market/commodities.csv`"
            ):
                out = df.copy()
                out = out.reset_index().rename(columns={"index": "datetime"})
                out_path = resolve_write_path(MARKET_DIR / "commodities.csv")
                write_frame(out, out_path, index=False)
                st.success("Saved `data/market/commodities.csv`.")

        if df.empty:
            st.caption(
                "Expected columns: `datetime, gas, coal, co2`. "
                "To generate locally: `python scripts/fetch_tradingview.py`."
            )
            return

    show_daily = st.checkbox(
        "Show daily settlement only",
        value=True,
        key="commodities_daily_only",
    )

    # Date range selector (inclusive).
    min_date = df.index.min().date() if not df.empty else None
    max_date = df.index.max().date() if not df.empty else None
    default_end = max_date
    default_start = (
        max(min_date, max_date - timedelta(days=90)) if min_date else max_date
    )

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
    end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    df = df[(df.index >= start_ts) & (df.index < end_exclusive)]
    if show_daily and not df.empty:
        df = df.resample("1D").last().dropna(how="all")
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        st.warning("Commodity file has no numeric columns to plot.")
        return

    default_cols = [
        c for c in ["gas", "coal", "co2"] if c in numeric_cols
    ] or numeric_cols[: min(3, len(numeric_cols))]
    cols = st.multiselect(
        "Series",
        options=numeric_cols,
        default=default_cols,
        key="commodities_series",
    )
    if not cols:
        st.info("Select at least one series.")
        return

    with st.expander("Performance"):
        fast_plot = st.checkbox(
            "Fast plotting (downsample)",
            value=True,
            key="commodities_fast_plot",
        )
        max_plot_points = int(
            st.number_input(
                "Max plot points (per series)",
                min_value=1_000,
                max_value=200_000,
                value=25_000,
                step=1_000,
                key="commodities_max_plot_points",
            )
        )

    df_plot = _downsample_indexed(df, max_plot_points) if fast_plot else df
    x = _format_index_as_strings(df_plot.index)
    series = [(c, df_plot[c].tolist(), {"width": 1.2}) for c in cols]
    chart = _pyecharts_timeseries_line(
        x=x, series=series, yaxis_title="", height_px=450
    )
    _render_chart(chart, 450)


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
        co2_price = pd.to_numeric(
            _col("co2_price_eur_per_t"), errors="coerce"
        ).fillna(0.0)

    srmc = (
        fuel_price.div(eff.replace(0, pd.NA)).fillna(pd.NA)
        + co2_price * co2_int
        + vom
    )
    df["srmc_eur_per_mwh"] = srmc
    return df


def _apply_table_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    with st.expander("Filter table"):
        name_filter = st.text_input(
            "Name contains", "", key="plants_table_name_contains"
        )
        fuel_opts = (
            sorted(filtered["fuel"].dropna().unique().tolist())
            if "fuel" in filtered
            else []
        )
        fuel_sel = st.multiselect(
            "Fuel",
            options=fuel_opts,
            default=fuel_opts,
            key="plants_table_fuel",
        )
        stack_opts = (
            sorted(filtered["stack_type"].dropna().unique().tolist())
            if "stack_type" in filtered
            else []
        )
        stack_type_labels = {
            "hydro_run_of_river": "hydro RoR",
            "solar_pv_distributed": "solar PV dist",
            "solar_pv_utility": "solar PV util",
        }

        def _fmt_stack_type(value: str) -> str:
            if value in stack_type_labels:
                return stack_type_labels[value]
            return str(value).replace("_", " ")

        stack_sel = st.multiselect(
            "Stack type",
            options=stack_opts,
            default=stack_opts,
            key="plants_table_stack_type",
            format_func=_fmt_stack_type,
        )
        cap_min, cap_max = (
            (
                float(filtered["capacity_mw"].min()),
                float(filtered["capacity_mw"].max()),
            )
            if not filtered.empty
            else (0.0, 0.0)
        )
        cap_range = st.slider(
            "Capacity range (MW)",
            min_value=cap_min,
            max_value=cap_max,
            value=(cap_min, cap_max),
            key="plants_table_capacity_range",
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
                key="plants_table_srmc_range",
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


def _load_demand_series_cached(area: str) -> pd.Series:
    s = load_demand_series(area)
    s = s.sort_index()
    s.index = pd.to_datetime(s.index)
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s


def _list_areas_with_any_files(filenames: Tuple[str, ...]) -> List[str]:
    return io_list_areas_with_any_files(filenames)


def _series_value_at_or_nearest(
    series: pd.Series, ts: pd.Timestamp
) -> Tuple[pd.Timestamp, float]:
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


def _series_value_at_or_before(
    series: pd.Series, ts: pd.Timestamp
) -> Tuple[pd.Timestamp, float]:
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

    zone_options = sorted(
        all_plants["bidding_zone"].dropna().unique().tolist()
    )
    default_zone = (
        "DE_LU"
        if "DE_LU" in zone_options
        else (zone_options[0] if zone_options else None)
    )
    zone = st.selectbox(
        "Bidding zone",
        options=zone_options,
        index=(
            zone_options.index(default_zone)
            if default_zone in zone_options
            else 0
        ),
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
        include_chp = st.checkbox(
            "Include CHP", value=True, key="merit_include_chp"
        )
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
    if (
        demand_source == "From saved load series (if available)"
        and zone in demand_areas
    ):
        try:
            demand_series = _load_demand_series_cached(zone).dropna()
        except FileNotFoundError:
            demand_series = None

    if (
        demand_source == "From saved load series (if available)"
        and demand_series is None
    ):
        st.warning(
            f"No saved load series found for `{zone}`; switch to manual demand."
        )
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
            delivery_date = st.date_input(
                "Delivery date (UTC)", key="merit_delivery_date"
            )
    with col_time2:
        period = st.selectbox(
            "Bidding period (UTC hour)",
            options=list(range(1, 25)),
            index=0,
            key="merit_bidding_period",
            format_func=lambda p: f"{p:02d} ({p-1:02d}:00–{p:02d}:00)",
        )

    ts_delivery = pd.Timestamp(delivery_date) + pd.Timedelta(
        hours=int(period) - 1
    )
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
    df_zone_base = df_zone_base[df_zone_base["available_mw"] > 0].reset_index(
        drop=True
    )
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
            if commodities.empty or "co2" not in commodities.columns:
                st.warning(
                    "No `co2` series available in `data/market/commodities.csv`; using manual CO₂."
                )
                co2_source = "Manual"
            else:
                eua_series = pd.to_numeric(
                    commodities["co2"], errors="coerce"
                ).dropna()
                if not eua_series.empty:
                    eua_series = eua_series.resample("1D").last().dropna()
                asof_ts = (
                    pd.Timestamp(delivery_date)
                    - pd.Timedelta(days=1)
                    + pd.Timedelta(hours=12)
                )
                try:
                    co2_ts_used, co2_price_ui = _series_value_at_or_before(
                        eua_series, asof_ts
                    )
                    st.caption(
                        f"As-of `{asof_ts}` → using `{co2_ts_used}`: {co2_price_ui:,.2f} EUR/t"
                    )
                except Exception as e:  # noqa: BLE001
                    st.warning(
                        f"Could not resolve CO₂ price as-of `{asof_ts}` ({e}); using manual CO₂."
                    )
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
        if (
            demand_source == "From saved load series (if available)"
            and demand_series is not None
        ):
            ts_used, demand_mw = _series_value_at_or_nearest(
                demand_series, ts_delivery
            )
            st.caption(f"Using demand at `{ts_used}`: {demand_mw:,.0f} MW")
        else:
            ts_used = None
            demand_mw = st.number_input(
                "Demand for bidding period (MW)",
                min_value=0.0,
                max_value=max(total_capacity * 2.0, 1.0),
                value=min(
                    total_capacity * 0.6, max(total_capacity - 1.0, 0.0)
                ),
                step=100.0,
                key="merit_demand_mw_manual",
            )

    df_zone = _attach_srmc(df_zone_base, co2_price_override=co2_price_ui)
    df_zone = df_zone.dropna(
        subset=["srmc_eur_per_mwh", "capacity_mw", "available_mw"]
    )
    if df_zone.empty:
        st.info("No plants with SRMC available after filters.")
        return

    df_zone = df_zone.sort_values(
        ["srmc_eur_per_mwh", "available_mw"], ascending=[True, False]
    ).reset_index(drop=True)
    df_zone["cum_capacity_mw"] = df_zone["available_mw"].cumsum()

    if demand_mw is None:
        return

    demand_mw = float(demand_mw)
    if demand_mw <= 0:
        st.info("Demand must be > 0 MW.")
        return

    pos = (
        int((df_zone["cum_capacity_mw"] >= demand_mw).idxmax())
        if demand_mw <= total_capacity
        else None
    )
    if pos is None:
        st.error(
            f"Demand {demand_mw:,.0f} MW exceeds available stack {total_capacity:,.0f} MW."
        )
        st.dataframe(
            df_zone[
                [
                    "name",
                    "stack_type",
                    "fuel",
                    "srmc_eur_per_mwh",
                    "available_mw",
                    "cum_capacity_mw",
                ]
            ].tail(25),
            width="stretch",
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
    x_vals = pd.to_numeric(x, errors="coerce").fillna(0.0).tolist()
    y_vals = pd.to_numeric(y, errors="coerce").fillna(0.0).tolist()

    supply = Line(
        init_opts=opts.InitOpts(
            height="450px",
            width="100%",
            animation_opts=opts.AnimationOpts(animation=False),
        )
    )
    supply.add_xaxis(x_vals)
    supply.add_yaxis(
        "Merit order (SRMC)",
        y_vals,
        is_step=True,
        is_symbol_show=False,
        symbol=None,
        is_hover_animation=False,
        label_opts=opts.LabelOpts(is_show=False),
        linestyle_opts=opts.LineStyleOpts(width=1.5),
        markline_opts=opts.MarkLineOpts(
            data=[
                opts.MarkLineItem(x=demand_mw, name="Demand"),
                opts.MarkLineItem(y=clearing_price, name="Clearing SRMC"),
            ],
            linestyle_opts=opts.LineStyleOpts(
                type_="dotted", color="#d62728", width=1.2
            ),
        ),
    )
    supply.set_global_opts(
        tooltip_opts=opts.TooltipOpts(trigger="axis"),
        legend_opts=opts.LegendOpts(is_show=False),
        datazoom_opts=[opts.DataZoomOpts(type_="inside")],
        xaxis_opts=opts.AxisOpts(
            type_="value", name="Cumulative available capacity (MW)"
        ),
        yaxis_opts=opts.AxisOpts(type_="value", name="SRMC (EUR/MWh)"),
    )
    _render_chart(supply, 450)

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
        width="stretch",
    )


def plants_tab():
    st.subheader("Plant stack (OPSD conventional)")
    with st.spinner("Loading OPSD plant metadata..."):
        all_plants = load_all_plants()
    if all_plants.empty:
        st.error("No OPSD plants available. Check data/external cache.")
        return
    zone_options = sorted(
        all_plants["bidding_zone"].dropna().unique().tolist()
    )
    default_zones = [
        z for z in ("DE_LU", "FR") if z in zone_options
    ] or zone_options[:1]
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
    include_chp = st.checkbox(
        "Include CHP", value=True, key="plants_include_chp"
    )
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
                df.groupby("fuel")["capacity_mw"]
                .sum()
                .sort_values(ascending=False)
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
        df.groupby("bidding_zone")["capacity_mw"]
        .sum()
        .sort_values(ascending=False)
    )
    st.dataframe(zone_summary.round(1))

    map_df = df.dropna(subset=["lat", "lon"])
    if not map_df.empty:
        st.caption("Plant locations (lon/lat scatter; zoom with mouse wheel)")
        map_df = _downsample_rows(map_df, 5000)
        points = []
        for row in map_df.itertuples(index=False):
            name = getattr(row, "name", "")
            lon = getattr(row, "lon", None)
            lat = getattr(row, "lat", None)
            if lon is None or lat is None or pd.isna(lon) or pd.isna(lat):
                continue
            points.append(
                {"name": str(name)[:80], "value": [float(lon), float(lat)]}
            )

        scatter = Scatter(
            init_opts=opts.InitOpts(
                height="400px",
                width="100%",
                animation_opts=opts.AnimationOpts(animation=False),
            )
        )
        scatter.add_xaxis([])
        scatter.add_yaxis(
            "Plants",
            points,
            symbol_size=6,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(color="red", opacity=0.7),
        )
        if len(points) >= 2000 and scatter.options.get("series"):
            scatter.options["series"][0]["large"] = True
            scatter.options["series"][0]["largeThreshold"] = 2000
        scatter.set_global_opts(
            tooltip_opts=opts.TooltipOpts(formatter="{b}: {c}"),
            legend_opts=opts.LegendOpts(is_show=False),
            datazoom_opts=[opts.DataZoomOpts(type_="inside")],
            xaxis_opts=opts.AxisOpts(type_="value", name="Longitude"),
            yaxis_opts=opts.AxisOpts(type_="value", name="Latitude"),
        )
        _render_chart(scatter, 400)

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
    st.dataframe(style, width="stretch")


def plant_status_tab():
    st.subheader("Plants: status & constraints")
    st.caption(
        "Status/constraints are derived from OPSD metadata + model defaults (not real-time outages)."
    )
    with st.spinner("Loading OPSD plant metadata..."):
        all_plants = load_all_plants()
    if all_plants.empty:
        st.error("No OPSD plants available. Check data/external cache.")
        return

    zone_options = sorted(
        all_plants["bidding_zone"].dropna().unique().tolist()
    )
    default_zones = [
        z for z in ("DE_LU", "FR") if z in zone_options
    ] or zone_options[:1]
    zones = st.multiselect(
        "Bidding zones",
        options=zone_options,
        default=default_zones,
        key="status_bidding_zones",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        min_cap = st.slider(
            "Minimum capacity (MW)",
            min_value=0,
            max_value=1000,
            value=0,
            step=10,
            key="status_min_capacity_mw",
        )
        include_chp = st.checkbox(
            "Include CHP", value=True, key="status_include_chp"
        )
    with col2:
        include_non_dispatchable = st.checkbox(
            "Include non-dispatchable",
            value=True,
            key="status_include_non_dispatchable",
        )
        availability_multiplier = st.slider(
            "Availability multiplier",
            min_value=0.0,
            max_value=1.2,
            value=1.0,
            step=0.05,
            key="status_availability_multiplier",
        )
    with col3:
        co2_price_ui = st.number_input(
            "CO₂ price (EUR/t)",
            min_value=0.0,
            max_value=500.0,
            value=80.0,
            step=5.0,
            key="status_co2_price_eur_per_t",
        )
        name_filter = st.text_input(
            "Name contains", "", key="status_name_contains"
        )

    df = _filter_plants(
        all_plants,
        min_capacity=min_cap,
        include_chp=include_chp,
        bidding_zones=tuple(zones),
    )
    if df.empty:
        st.info("No plants after filters.")
        return

    if not include_non_dispatchable and "is_dispatchable" in df.columns:
        dispatchable_mask = df["is_dispatchable"]
        dispatchable_mask = dispatchable_mask.fillna(True).astype(bool)
        df = df[dispatchable_mask].reset_index(drop=True)
        if df.empty:
            st.info("No dispatchable plants after filters.")
            return

    if name_filter:
        df = df[
            df["name"]
            .astype(str)
            .str.contains(name_filter, case=False, na=False)
        ]
        if df.empty:
            st.info("No plants match the name filter.")
            return

    df = _attach_srmc(df, co2_price_override=co2_price_ui)

    if "availability_factor" in df.columns:
        avail_factor = pd.to_numeric(
            df["availability_factor"], errors="coerce"
        ).fillna(1.0)
    else:
        avail_factor = pd.Series(1.0, index=df.index)
    df["available_mw"] = (
        df["capacity_mw"] * avail_factor * float(availability_multiplier)
    )

    current_year = pd.Timestamp.utcnow().year
    commissioned = pd.to_numeric(
        df.get("commissioned_year", pd.NA), errors="coerce"
    )
    comment = (
        df.get("comment", pd.Series("", index=df.index)).fillna("").astype(str)
    )
    tech = (
        df.get("technology", pd.Series("", index=df.index))
        .fillna("")
        .astype(str)
    )
    name = df.get("name", pd.Series("", index=df.index)).fillna("").astype(str)
    status_text = (comment + " " + tech + " " + name).str.lower()

    retired_kw = r"decommission|de-?commission|shutdown|shut down|closed|mothball|retir|dismantl|scrapp"
    planned_kw = r"planned|under construction|construction|commissioning|to be built|projekt|project"

    df["plant_status"] = "unknown"

    retired_mask = status_text.str.contains(retired_kw, regex=True, na=False)
    planned_mask = (
        commissioned.notna() & (commissioned > current_year)
    ) | status_text.str.contains(planned_kw, regex=True, na=False)
    operational_mask = (
        commissioned.notna() & (commissioned <= current_year)
    ) | (commissioned.isna() & ~retired_mask & ~planned_mask)

    df.loc[retired_mask, "plant_status"] = "retired"

    df.loc[planned_mask & ~retired_mask, "plant_status"] = "planned"

    df.loc[
        operational_mask & ~retired_mask & ~planned_mask, "plant_status"
    ] = "operational"

    # Split commissioned year into historical vs expected (future) for display clarity.
    df["expected_commissioned_year"] = commissioned.where(
        commissioned > current_year
    )
    df["commissioned_year"] = commissioned.where(commissioned <= current_year)
    if "is_dispatchable" in df.columns:
        df["dispatchability"] = (
            df["is_dispatchable"]
            .fillna(True)
            .map({True: "dispatchable", False: "non-dispatchable"})
        )
    else:
        df["dispatchability"] = "dispatchable"

    ramp_up = pd.to_numeric(
        df.get("ramp_up_mw_per_min", pd.NA), errors="coerce"
    )
    pmax = pd.to_numeric(
        df.get("p_max_mw", df.get("capacity_mw", pd.NA)), errors="coerce"
    )
    df["ramp_up_pct_per_min"] = (ramp_up / pmax.replace(0, pd.NA)) * 100.0

    df = df.sort_values(
        [
            "bidding_zone",
            "plant_status",
            "dispatchability",
            "srmc_eur_per_mwh",
        ],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)

    st.caption(f"{len(df):,} plants")
    cols = [
        c
        for c in [
            "name",
            "bidding_zone",
            "country",
            "plant_status",
            "dispatchability",
            "fuel",
            "stack_type",
            "capacity_mw",
            "available_mw",
            "p_min_mw",
            "p_max_mw",
            "ramp_up_mw_per_min",
            "ramp_down_mw_per_min",
            "ramp_up_pct_per_min",
            "min_up_hours",
            "min_down_hours",
            "startup_cost_eur",
            "srmc_eur_per_mwh",
            "efficiency",
            "co2_intensity",
            "availability_factor",
            "is_chp",
            "commissioned_year",
            "expected_commissioned_year",
            "eic_code",
            "technology",
            "lat",
            "lon",
        ]
        if c in df.columns
    ]
    st.dataframe(
        df[cols].style.format(
            {
                "capacity_mw": "{:,.1f}",
                "available_mw": "{:,.1f}",
                "p_min_mw": "{:,.1f}",
                "p_max_mw": "{:,.1f}",
                "ramp_up_mw_per_min": "{:,.2f}",
                "ramp_down_mw_per_min": "{:,.2f}",
                "ramp_up_pct_per_min": "{:.2f}",
                "startup_cost_eur": "{:,.0f}",
                "srmc_eur_per_mwh": "{:,.1f}",
                "efficiency": "{:.2f}",
                "co2_intensity": "{:.2f}",
                "availability_factor": "{:.2f}",
            }
        ),
        width="stretch",
    )


def _render_help_panel() -> None:
    st.markdown(
        """
**Quick help**
- Contact: Zhijie Kong
- Email: kong.zhijie1992@gmail.com
- Contract me for **AWS_ACCESS_KEY_ID** and **AWS_SECRET_ACCESS_KEY** to access the data
- Whatsapp: +44 - 07539119773""".strip()
    )


def _render_help_button() -> None:
    if hasattr(st, "popover"):
        with st.popover("Help"):
            _render_help_panel()
    else:
        with st.expander("Help", expanded=False):
            _render_help_panel()


def main():
    bar_left, bar_right = st.columns([0.85, 0.15])
    with bar_left:
        st.write("")
    with bar_right:
        _render_help_button()
    st.markdown(
        """
        <style>
        .hero-title {
          background-image: url("https://met.com/media/tknc3bvb/importance-of-electricity.jpg?width=1920&v=1dbd157654963b0&rmode=min&format=webp&quality=100");
          background-size: cover;
          background-position: center;
          border-radius: 12px;
          padding: 36px 28px;
          margin: 6px 0 18px 0;
        }
        .hero-title__text {
          color: #ffffff;
          font-size: 2.0rem;
          font-weight: 700;
          text-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
        }
        </style>
        <div class="hero-title">
          <div class="hero-title__text">Power forecasts dashboard</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Demand forecasts",
            "Price forecasts",
            "Merit order rank",
            "Commodity prices",
            "Plants (status)",
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
        plant_status_tab()
    with tab6:
        plants_tab()


if __name__ == "__main__":
    main()
