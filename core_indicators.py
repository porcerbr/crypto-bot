from __future__ import annotations

import numpy as np
import pandas as pd


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean().bfill()


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = (typical * df["volume"]).cumsum()
    vol = df["volume"].cumsum().replace(0, np.nan)
    return (pv / vol).fillna(method="bfill").fillna(df["close"])


def bollinger_bands(series: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = _sma(series, period)
    std = series.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return upper.bfill(), mid.bfill(), lower.bfill(), width.bfill()


def adx(df: pd.DataFrame, period: int = 14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = low.diff().abs()

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

    tr = atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    adx_line = dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)
    return adx_line, plus_di.fillna(0), minus_di.fillna(0)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.sort_values("time").reset_index(drop=True)

    out["ema_20"] = ema(out["close"], 20)
    out["ema_50"] = ema(out["close"], 50)
    out["ema_200"] = ema(out["close"], 200)
    out["sma_20"] = _sma(out["close"], 20)
    out["rsi_14"] = rsi(out["close"], 14)
    out["macd_line"], out["macd_signal"], out["macd_hist"] = macd(out["close"])
    out["atr_14"] = atr(out, 14)
    out["vwap"] = vwap(out)
    out["bb_upper"], out["bb_mid"], out["bb_lower"], out["bb_width"] = bollinger_bands(out["close"])
    out["adx_14"], out["plus_di"], out["minus_di"] = adx(out)
    out["returns"] = out["close"].pct_change().fillna(0)
    out["volatility"] = out["returns"].rolling(20, min_periods=5).std().fillna(0)
    out["range"] = out["high"] - out["low"]
    return out.ffill().bfill()
