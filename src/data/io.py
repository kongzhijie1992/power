import os
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import pandas as pd


DATA_DIR = Path(__file__).parents[1] / ".." / "data"
DATA_DIR = Path(DATA_DIR).resolve()

_S3_FS = None
_READ_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}


def _s3_only() -> bool:
    if not _s3_enabled():
        return False
    val = os.getenv("S3_ONLY")
    if val is None:
        return True
    return val.strip().lower() not in {"0", "false", "no"}


def _cache_ttl_s() -> int:
    if not _s3_enabled():
        return 0
    val = os.getenv("S3_CACHE_TTL", "120")
    try:
        return max(0, int(val))
    except ValueError:
        return 120


def _cache_max_items() -> int:
    val = os.getenv("S3_CACHE_MAX", "64")
    try:
        return max(1, int(val))
    except ValueError:
        return 64


def _cache_get(key: str) -> Optional[pd.DataFrame]:
    ttl = _cache_ttl_s()
    if ttl <= 0:
        return None
    entry = _READ_CACHE.get(key)
    if not entry:
        return None
    ts, df = entry
    if time.monotonic() - ts > ttl:
        _READ_CACHE.pop(key, None)
        return None
    return df


def _cache_set(key: str, df: pd.DataFrame) -> None:
    ttl = _cache_ttl_s()
    if ttl <= 0:
        return
    if len(_READ_CACHE) >= _cache_max_items():
        oldest = next(iter(_READ_CACHE))
        _READ_CACHE.pop(oldest, None)
    _READ_CACHE[key] = (time.monotonic(), df)


def _s3_config() -> Optional[Tuple[str, str]]:
    bucket = os.getenv("S3_BUCKET") or "zkong-power"
    if not bucket:
        return None
    prefix = os.getenv("S3_PREFIX", "").strip("/")
    return bucket, prefix


def _s3_storage_options() -> dict:
    opts: dict = {}
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    token = os.getenv("AWS_SESSION_TOKEN")
    region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or "eu-north-1"
    if key and secret:
        opts["key"] = key
        opts["secret"] = secret
    if token:
        opts["token"] = token
    if region:
        opts["client_kwargs"] = {"region_name": region}
    return opts


def _s3_enabled() -> bool:
    return _s3_config() is not None


def _get_s3_fs():
    global _S3_FS
    if _S3_FS is None:
        import s3fs

        _S3_FS = s3fs.S3FileSystem(**_s3_storage_options())
    return _S3_FS


def _is_s3_path(path: Union[str, Path]) -> bool:
    return isinstance(path, str) and path.startswith("s3://")


def _s3_path_for_local(path: Path) -> Optional[str]:
    cfg = _s3_config()
    if not cfg:
        return None
    bucket, prefix = cfg
    try:
        rel = path.resolve().relative_to(DATA_DIR)
    except Exception:
        return None
    key = f"{prefix}/{rel.as_posix()}" if prefix else rel.as_posix()
    return f"s3://{bucket}/{key}"


def _path_exists(path: Union[str, Path]) -> bool:
    if _is_s3_path(path):
        return _get_s3_fs().exists(path)
    return Path(path).exists()


def _read_frame_from_path(path: Union[str, Path]) -> pd.DataFrame:
    if _is_s3_path(path):
        cached = _cache_get(str(path))
        if cached is not None:
            return cached
    storage_options = _s3_storage_options() if _is_s3_path(path) else None
    suffix = Path(str(path)).suffix
    if suffix == ".parquet":
        df = pd.read_parquet(path, storage_options=storage_options)
    else:
        df = pd.read_csv(path, storage_options=storage_options)
    if _is_s3_path(path):
        _cache_set(str(path), df)
    return df


def resolve_data_path(path: Path) -> Union[str, Path]:
    s3_path = _s3_path_for_local(path)
    if s3_path and _path_exists(s3_path):
        return s3_path
    if _s3_only():
        raise FileNotFoundError(f"S3 object not found: {s3_path}")
    return path


def resolve_write_path(path: Union[str, Path]) -> Union[str, Path]:
    if _is_s3_path(path):
        return path
    s3_path = _s3_path_for_local(Path(path))
    if s3_path and _s3_enabled():
        return s3_path
    return Path(path)


def read_frame(path: Union[str, Path]) -> pd.DataFrame:
    if _is_s3_path(path):
        return _read_frame_from_path(path)
    resolved = resolve_data_path(Path(path))
    return _read_frame_from_path(resolved)


def read_csv_indexed(path: Union[str, Path]) -> pd.DataFrame:
    if _is_s3_path(path):
        resolved = path
    else:
        resolved = resolve_data_path(Path(path))
    if _is_s3_path(resolved):
        cached = _cache_get(f"indexed:{resolved}")
        if cached is not None:
            return cached
    storage_options = _s3_storage_options() if _is_s3_path(resolved) else None
    df = pd.read_csv(
        resolved, index_col=0, parse_dates=True, storage_options=storage_options
    )
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[~df.index.isna()]
    df.index.name = "datetime"
    if _is_s3_path(resolved):
        _cache_set(f"indexed:{resolved}", df)
    return df


def write_frame(
    df: pd.DataFrame,
    path: Union[str, Path],
    index_label: Optional[str] = None,
    index: bool = True,
) -> Union[str, Path]:
    target = resolve_write_path(path)
    if not _is_s3_path(target):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    storage_options = _s3_storage_options() if _is_s3_path(target) else None
    suffix = Path(str(target)).suffix
    if suffix == ".parquet":
        df.to_parquet(target, storage_options=storage_options)
    else:
        df.to_csv(
            target,
            index=index,
            index_label=index_label if index else None,
            storage_options=storage_options,
        )
    return target


def path_exists(path: Union[str, Path]) -> bool:
    return _path_exists(path)


def list_areas_with_file(filename: str) -> List[str]:
    areas: set[str] = set()
    if _s3_enabled():
        try:
            fs = _get_s3_fs()
            bucket, prefix = _s3_config()  # type: ignore[misc]
            base = f"{bucket}/{prefix}".strip("/")
            pattern = f"{base}/*/{filename}" if base else f"{bucket}/*/{filename}"
            for match in fs.glob(pattern):
                parts = match.split("/")
                if len(parts) >= 2:
                    areas.add(parts[-2])
        except Exception:
            pass

    if not _s3_only() and DATA_DIR.exists():
        for area_dir in DATA_DIR.iterdir():
            if not area_dir.is_dir():
                continue
            if (area_dir / filename).exists():
                areas.add(area_dir.name)
    return sorted(areas)


def list_areas_with_any_files(filenames: Sequence[str]) -> List[str]:
    areas: set[str] = set()
    for name in filenames:
        areas.update(list_areas_with_file(name))
    return sorted(areas)


def _select_series_from_frame(df: pd.DataFrame) -> pd.Series:
    preferred = [
        "value",
        "actual_load",
        "tso_day_ahead_forecast",
        "Forecasted Load",
        "Load",
        "Actual Load",
        "load",
    ]
    for col in preferred:
        if col in df.columns:
            return df[col]
    numeric_cols = df.select_dtypes(include="number").columns
    if len(numeric_cols) > 0:
        return df[numeric_cols[0]]
    return df.iloc[:, 0]


def _read_series_from_path(path: Union[str, Path]) -> pd.Series:
    """Load a series from CSV/Parquet, being flexible about column names."""
    df = _read_frame_from_path(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    return _select_series_from_frame(df)


def ensure_data_dir():
    if _s3_only():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_series_csv(series: pd.Series, area: str, name: str = "day_ahead"):
    ensure_data_dir()
    area_dir = DATA_DIR / area
    path = area_dir / f"{name}.csv"
    return write_frame(series.to_frame("value"), path, index_label="datetime")


def load_series_csv(area: str, name: str = "day_ahead"):
    path = DATA_DIR / area / f"{name}.csv"
    resolved = resolve_data_path(path)
    if _is_s3_path(resolved):
        df = read_csv_indexed(resolved)
    else:
        if not Path(resolved).exists():
            raise FileNotFoundError(resolved)
        df = pd.read_csv(resolved, index_col=0, parse_dates=True)
    s = df["value"]
    s.index.name = None
    return s


def load_price_series(area: str, prefer_parquet: bool = True):
    """
    Load price series for an area, preferring the day_ahead_real files.
    Fallback order:
      1) day_ahead_real.parquet
      2) day_ahead_real.csv
      3) day_ahead.parquet
      4) day_ahead.csv
    Returns a pandas Series with datetime index.
    """
    candidates = [
        DATA_DIR / area / "day_ahead_real.parquet",
        DATA_DIR / area / "day_ahead_real.csv",
        DATA_DIR / area / "day_ahead.parquet",
        DATA_DIR / area / "day_ahead.csv",
    ]

    if not prefer_parquet:
        # move parquet candidates behind csv if caller prefers csv
        candidates = [
            DATA_DIR / area / "day_ahead_real.csv",
            DATA_DIR / area / "day_ahead_real.parquet",
            DATA_DIR / area / "day_ahead.csv",
            DATA_DIR / area / "day_ahead.parquet",
        ]

    for path in candidates:
        if _s3_only():
            s3_path = _s3_path_for_local(path)
            if not s3_path or not _path_exists(s3_path):
                continue
            df = _read_frame_from_path(s3_path)
        else:
            s3_path = _s3_path_for_local(path) if _s3_enabled() else None
            if s3_path and _path_exists(s3_path):
                df = _read_frame_from_path(s3_path)
            elif path.exists():
                df = _read_frame_from_path(path)
            else:
                continue
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index)
        return df["value"]

    raise FileNotFoundError(f"No price file found for area {area}")


def load_demand_series(area: str, prefer_parquet: bool = True):
    """
    Load demand/load series for an area.
    Fallback order:
      1) load_actual.parquet
      2) load_actual.csv
      3) load_real.parquet
      4) load_real.csv
      5) load.parquet
      6) load.csv
    """
    candidates = [
        DATA_DIR / area / "load_actual.parquet",
        DATA_DIR / area / "load_actual.csv",
        DATA_DIR / area / "load_real.parquet",
        DATA_DIR / area / "load_real.csv",
        DATA_DIR / area / "load.parquet",
        DATA_DIR / area / "load.csv",
    ]
    if not prefer_parquet:
        candidates = [
            DATA_DIR / area / "load_actual.csv",
            DATA_DIR / area / "load_real.csv",
            DATA_DIR / area / "load_actual.parquet",
            DATA_DIR / area / "load_real.parquet",
            DATA_DIR / area / "load.csv",
            DATA_DIR / area / "load.parquet",
        ]
    for path in candidates:
        if _s3_only():
            s3_path = _s3_path_for_local(path)
            if s3_path and _path_exists(s3_path):
                return _read_series_from_path(s3_path)
            continue
        s3_path = _s3_path_for_local(path) if _s3_enabled() else None
        if s3_path and _path_exists(s3_path):
            return _read_series_from_path(s3_path)
        if path.exists():
            return _read_series_from_path(path)
    raise FileNotFoundError(f"No demand/load file found for area {area} in {DATA_DIR}")


def load_tso_forecast_series(area: str, prefer_parquet: bool = True) -> pd.Series:
    """
    Load TSO day-ahead load forecast series for an area.
    Fallback order:
      1) load_forecast.parquet
      2) load_forecast.csv
    """
    df = load_tso_forecast_frame(area, prefer_parquet=prefer_parquet)
    return _select_series_from_frame(df)


def load_tso_forecast_frame(area: str, prefer_parquet: bool = True) -> pd.DataFrame:
    """
    Load the raw TSO forecast frame for an area (including any metadata columns).
    Fallback order:
      1) load_forecast.parquet
      2) load_forecast.csv
    """
    candidates = [
        DATA_DIR / area / "load_forecast.parquet",
        DATA_DIR / area / "load_forecast.csv",
    ]
    if not prefer_parquet:
        candidates = candidates[::-1]

    for path in candidates:
        if _s3_only():
            s3_path = _s3_path_for_local(path)
            if s3_path and _path_exists(s3_path):
                return _read_forecast_frame_from_path(s3_path)
            continue
        s3_path = _s3_path_for_local(path) if _s3_enabled() else None
        if s3_path and _path_exists(s3_path):
            return _read_forecast_frame_from_path(s3_path)
        if path.exists():
            return _read_forecast_frame_from_path(path)
    raise FileNotFoundError(f"No TSO forecast file found for area {area} in {DATA_DIR}")


def load_tso_forecast_publication(area: str, prefer_parquet: bool = True) -> pd.Series:
    """Load publication timestamps for the TSO forecast, if present."""
    candidates = [
        DATA_DIR / area / "load_forecast.parquet",
        DATA_DIR / area / "load_forecast.csv",
    ]
    if not prefer_parquet:
        candidates = candidates[::-1]

    preferred_cols = [
        "tso_publication_time_utc",
        "publication_time_utc",
        "publication_time",
        "created_datetime",
    ]

    for path in candidates:
        if _s3_only():
            s3_path = _s3_path_for_local(path)
            if s3_path and _path_exists(s3_path):
                df = _read_forecast_frame_from_path(s3_path)
            else:
                continue
        else:
            s3_path = _s3_path_for_local(path) if _s3_enabled() else None
            if s3_path and _path_exists(s3_path):
                df = _read_forecast_frame_from_path(s3_path)
            elif path.exists():
                df = _read_forecast_frame_from_path(path)
            else:
                continue
        for col in preferred_cols:
            if col in df.columns:
                series = pd.to_datetime(df[col], errors="coerce")
                if series.notna().any():
                    if getattr(series.dt, "tz", None) is not None:
                        series = series.dt.tz_convert("UTC").dt.tz_localize(None)
                    return series
        for col in df.columns:
            if "publication" in col:
                series = pd.to_datetime(df[col], errors="coerce")
                if series.notna().any():
                    if getattr(series.dt, "tz", None) is not None:
                        series = series.dt.tz_convert("UTC").dt.tz_localize(None)
                    return series
    return pd.Series(dtype="datetime64[ns]")


def _read_forecast_frame_from_path(path: Union[str, Path]) -> pd.DataFrame:
    df = _read_frame_from_path(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    for col in df.columns:
        if "publication" in col:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().any():
                df[col] = parsed
                if getattr(parsed.dt, "tz", None) is not None:
                    df[col] = df[col].dt.tz_convert("UTC").dt.tz_localize(None)
    return df
