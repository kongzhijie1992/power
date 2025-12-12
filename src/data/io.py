from pathlib import Path
import pandas as pd


DATA_DIR = Path(__file__).parents[1] / '..' / 'data'
DATA_DIR = Path(DATA_DIR).resolve()


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
