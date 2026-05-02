from __future__ import annotations
from typing import List, Optional
from dataclasses import dataclass

from config import BotConfig
from indicators import ema, rsi, atr, bullish_engulfing, bearish_engulfing
from models import Candle, Signal, Side
from utils import pip_size, round_price, in_session, is_high_impact_news_window, utc_now, candle_range

@dataclass
class StrategyResult:
    signal: Optional[Signal]
    score: int = 0
    reasons: str = ""

class SignalEngine:
    def __init__(self, config: BotConfig):
        self.config = config

    def evaluate(self, symbol: str, candles: List[Candle], spread_pips: float = 0.0) -> Optional[Signal]:
        if len(candles) < 50:
            return None

        closes = [c.close for c in candles]
        atr_value = atr(candles, 14)
        if atr_value <= 0:
            return None

        if self.config.use_volatility_filter:
            if candle_range(candles[-1]) < atr_value * 0.4:
                return None

        if self.config.use_spread_filter and spread_pips > max(1.5, atr_value / pip_size(symbol) * 0.15):
            return None

        if self.config.use_session_filter and not in_session(
            utc_now(),
            self.config.london_start_utc,
            self.config.london_end_utc,
            self.config.new_york_start_utc,
            self.config.new_york_end_utc,
        ):
            return None

        if self.config.use_news_filter and is_high_impact_news_window(symbol):
            return None

        fast = ema(closes, 9)
        slow = ema(closes, 21)
        rsi_vals = rsi(closes, 14)
        if not fast or not slow or not rsi_vals:
            return None

        last_close = closes[-1]
        prev_close = closes[-2]
        last_fast = fast[-1]
        last_slow = slow[-1]
        last_rsi = rsi_vals[-1]
        prev_rsi = rsi_vals[-2] if len(rsi_vals) >= 2 else last_rsi

        direction = Side.NONE
        score = 0
        reasons = []

        if last_fast > last_slow and last_close > last_slow:
            score += 3
            direction = Side.BUY
            reasons.append("tendência de alta")
        elif last_fast < last_slow and last_close < last_slow:
            score += 3
            direction = Side.SELL
            reasons.append("tendência de baixa")

        if direction == Side.BUY and last_rsi > 50 and last_rsi > prev_rsi:
            score += 2
            reasons.append("RSI confirmando compra")
        elif direction == Side.SELL and last_rsi < 50 and last_rsi < prev_rsi:
            score += 2
            reasons.append("RSI confirmando venda")

        prev, curr = candles[-2], candles[-1]
        if direction == Side.BUY and bullish_engulfing(prev, curr):
            score += 2
            reasons.append("engolfo de alta")
        elif direction == Side.SELL and bearish_engulfing(prev, curr):
            score += 2
            reasons.append("engolfo de baixa")

        if direction == Side.BUY and curr.close > prev.high:
            score += 1
            reasons.append("quebra de máxima recente")
        elif direction == Side.SELL and curr.close < prev.low:
            score += 1
            reasons.append("quebra de mínima recente")

        if score < self.config.min_score_to_signal or direction == Side.NONE:
            return None

        entry = last_close
        p = pip_size(symbol)
        rr = min(max(self.config.default_rr, self.config.min_rr), self.config.max_rr)

        if direction == Side.BUY:
            stop_loss = entry - ((atr_value * self.config.sl_atr_multiplier) + self.config.sl_buffer_pips * p)
            take_profit = entry + abs(entry - stop_loss) * rr
        else:
            stop_loss = entry + ((atr_value * self.config.sl_atr_multiplier) + self.config.sl_buffer_pips * p)
            take_profit = entry - abs(stop_loss - entry) * rr

        return Signal(
            symbol=symbol,
            side=direction,
            timeframe=self.config.timeframe,
            entry=round_price(symbol, entry),
            stop_loss=round_price(symbol, stop_loss),
            take_profit=round_price(symbol, take_profit),
            score=score,
            rr=round(abs(take_profit - entry) / max(abs(entry - stop_loss), 1e-12), 2),
            reason="; ".join(reasons),
            timestamp=utc_now(),
            atr=atr_value,
            spread_pips=spread_pips,
        )
