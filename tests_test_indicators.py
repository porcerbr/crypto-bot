import pandas as pd

from core_indicators import add_indicators


def test_add_indicators():
    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=250, freq="h"),
        "open": range(250),
        "high": [x + 1 for x in range(250)],
        "low": [x - 1 for x in range(250)],
        "close": [x + 0.5 for x in range(250)],
        "volume": [100] * 250,
    })
    out = add_indicators(df)
    assert "ema_20" in out.columns
    assert len(out) == 250
