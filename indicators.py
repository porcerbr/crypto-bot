from __future__ import annotations
from typing import List
from statistics import mean
from models import Candle

def ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out

def rsi(values: List[float], period: int = 14) -> List[float]:
    if len(values) <= period:
        return []
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))
    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    rsis = [50.0] * period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
        rsis.append(100 - (100 / (1 + rs)))
    return rsis

def atr(candles: List[Candle], period: int = 14) -> float:
    if len(candles) <= period:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    return sum(trs[-period:]) / period

def candle_range(c: Candle) -> float:
    return max(c.high - c.low, 1e-12)

def bullish_engulfing(prev: Candle, curr: Candle) -> bool:
    return prev.close < prev.open and curr.close > curr.open and curr.close >= prev.open and curr.open <= prev.close

def bearish_engulfing(prev: Candle, curr: Candle) -> bool:
    return prev.close > prev.open and curr.close < curr.open and curr.open >= prev.close and curr.close <= prev.open
