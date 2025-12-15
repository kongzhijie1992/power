import pandas as pd

from src.power_model.timeutils import add_local_time_features, ensure_utc_index


def test_dst_transitions_have_23_and_25_hours():
    # Spring forward: missing 02:00 local
    idx_spring = pd.date_range("2023-03-26 00:00", periods=24, freq="1h", tz="UTC")
    df_spring = ensure_utc_index(pd.DataFrame(index=idx_spring))
    out_spring = add_local_time_features(df_spring)
    spring_hours = set(out_spring.loc[idx_spring, "berlin_hour_local"])
    assert 2 not in spring_hours  # skipped local hour

    # Fall back: repeated 02:00 local
    idx_fall = pd.date_range("2023-10-29 00:00", periods=25, freq="1h", tz="UTC")
    df_fall = ensure_utc_index(pd.DataFrame(index=idx_fall))
    out_fall = add_local_time_features(df_fall)
    hours_fall = out_fall.loc[idx_fall, "berlin_hour_local"]
    assert (hours_fall == 2).sum() == 2  # double 02:00
    assert set(out_fall["berlin_dst_offset_hours"]).issubset({1.0, 2.0})
