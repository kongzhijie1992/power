import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from src.power_model.residual import ResidualModel


def test_rolling_cv_uses_past_only(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=120, freq="h", tz="UTC")
    structural = np.linspace(9, 19, len(idx))
    noise = np.sin(np.linspace(0, 10, len(idx))) * 0.5
    prices = structural + 1.0 + noise
    df = pd.DataFrame(
        {
            "price_da": prices,
            "structural_price": structural,
            "f1": np.sin(np.linspace(0, 3.14, len(idx))),
            "f2": np.cos(np.linspace(0, 3.14, len(idx))),
        },
        index=idx,
    )

    checks = []
    orig_split = TimeSeriesSplit.split

    def checked_split(self, X, y=None, groups=None):
        for train, test in orig_split(self, X, y, groups):
            assert train.max() < test.min()
            checks.append(True)
            yield train, test

    monkeypatch.setattr(TimeSeriesSplit, "split", checked_split)

    model = ResidualModel(feature_cols=["f1", "f2"])
    mae = model.rolling_cv_mae(
        df, n_splits=3, target_col="price_da", structural_col="structural_price"
    )
    assert checks  # at least one split inspected
    assert mae >= 0
