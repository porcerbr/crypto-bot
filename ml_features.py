from __future__ import annotations

import pandas as pd

from core_indicators import add_indicators


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = add_indicators(df)
    columns = [
        "ema_20", "ema_50", "ema_200", "sma_20", "rsi_14", "macd_line", "macd_signal", "macd_hist",
        "atr_14", "vwap", "bb_upper", "bb_mid", "bb_lower", "bb_width", "adx_14", "plus_di", "minus_di",
        "returns", "volatility", "range",
    ]
    return out[columns].replace([float("inf"), float("-inf")], 0).fillna(0)


def create_labels(df: pd.DataFrame, horizon: int = 5, threshold: float = 0.001) -> pd.Series:
    future_return = df["close"].shift(-horizon) / df["close"] - 1.0
    return (future_return > threshold).astype(int)
