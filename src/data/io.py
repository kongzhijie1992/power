from pathlib import Path
import pandas as pd


DATA_DIR = Path(__file__).parents[1] / '..' / 'data'
DATA_DIR = Path(DATA_DIR).resolve()


def _read_series_from_path(path: Path) -> pd.Series:
    """Load a series from CSV/Parquet, being flexible about column names."""
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    df.index = pd.to_datetime(df.index)

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


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_series_csv(series: pd.Series, area: str, name: str = 'day_ahead'):
    ensure_data_dir()
    area_dir = DATA_DIR / area
    area_dir.mkdir(parents=True, exist_ok=True)
    path = area_dir / f"{name}.csv"
    series.to_frame('value').to_csv(path, index=True)
    return path


def load_series_csv(area: str, name: str = 'day_ahead'):
    path = DATA_DIR / area / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    s = df['value']
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
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")
        df.index = pd.to_datetime(df.index)
        return df["value"]

    raise FileNotFoundError(f"No price file found for area {area} in {DATA_DIR}")


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
        if not path.exists():
            continue
        series = _read_series_from_path(path)
        return series
    raise FileNotFoundError(f"No demand/load file found for area {area} in {DATA_DIR}")


def load_tso_forecast_series(area: str, prefer_parquet: bool = True) -> pd.Series:
    """
    Load TSO day-ahead load forecast series for an area.
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
        if not path.exists():
            continue
        series = _read_series_from_path(path)
        return series
    raise FileNotFoundError(f"No TSO forecast file found for area {area} in {DATA_DIR}")
