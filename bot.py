from __future__ import annotations
import dataclasses
import logging
import queue
import threading
import time
from typing import Any, Dict, Optional, List

from config import BotConfig
from data_provider import TwelveDataProvider
from strategy import SignalEngine
from risk import RiskManager
from execution import ExecutionEngine
from storage import StateStore
from metrics import win_rate, profit_factor
from models import BotState, TradeState, Side, utc_now, to_iso
from models import from_iso

def build_logger(logs_dir: str) -> logging.Logger:
    import os
    from pathlib import Path
    os.makedirs(logs_dir, exist_ok=True)
    logger = logging.getLogger("signal_bot")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        fh = logging.FileHandler(Path(logs_dir) / "bot.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

class TradingBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.logger = build_logger(config.logs_dir)
        self.store = StateStore(config.state_path)
        self.state = self.store.load()
        self.provider = TwelveDataProvider(config.api_key, config.base_url)
        self.strategy = SignalEngine(config)
        self.risk = RiskManager(config)
        self.execution = ExecutionEngine()
        self.stop_event = threading.Event()
        self.loop_thread: Optional[threading.Thread] = None
        self.events: "queue.Queue[Dict[str, Any]]" = queue.Queue()

    def log_event(self, kind: str, payload: Dict[str, Any]) -> None:
        event = {"kind": kind, "time": to_iso(utc_now()), **payload}
        self.events.put(event)
        self.logger.info("%s %s", kind, payload)

    def refresh_day_if_needed(self) -> None:
        now = utc_now()
        if not self.state.last_run_at_utc:
            self.state.day_start_equity = self.state.equity
            return
        last = from_iso(self.state.last_run_at_utc)
        if now.date() != last.date():
            self.state.day_start_equity = self.state.equity
            self.state.daily_pnl = 0.0

    def fetch_market_snapshot(self, symbol: str):
        candles = self.provider.get_candles(symbol, self.config.timeframe, self.config.lookback_bars)
        spread = self.provider.get_spread_pips(symbol)
        return candles, spread

    def process_symbol(self, symbol: str):
        candles, spread = self.fetch_market_snapshot(symbol)
        signal = self.strategy.evaluate(symbol, candles, spread)
        if signal:
            self.state.recent_signals.append(signal)
            self.state.recent_signals = self.state.recent_signals[-200:]
            self.log_event("signal", {**dataclasses.asdict(signal), "side": signal.side.value})
        return signal

    def maybe_open_trade_from_signal(self, signal):
        can_open, reason = self.risk.can_open_trade(self.state)
        if not can_open:
            self.log_event("blocked", {"symbol": signal.symbol, "reason": reason})
            return None

        volume = self.risk.position_size(signal.symbol, signal.entry, signal.stop_loss, self.state.balance)
        if volume <= 0:
            self.log_event("blocked", {"symbol": signal.symbol, "reason": "volume inválido"})
            return None

        trade = self.execution.open_trade(signal, volume)
        self.state.open_trades.append(trade)
        self.log_event("trade_opened", {**dataclasses.asdict(trade), "side": trade.side.value})
        return trade

    def update_open_trades(self) -> None:
        for trade in self.state.open_trades:
            if trade.status != "OPEN":
                continue
            candles = self.provider.get_candles(trade.symbol, self.config.timeframe, 5)
            if not candles:
                continue
            last_price = candles[-1].close
            result = self.execution.simulate_update(trade, last_price)
            if not result:
                continue
            outcome, close_price = result
            trade.status = "CLOSED"
            trade.close_price = close_price
            trade.closed_at = to_iso(utc_now())
            from execution import calculate_pnl
            trade.pnl = calculate_pnl(trade, close_price)
            trade.result = outcome

            self.state.equity += trade.pnl
            self.state.daily_pnl += trade.pnl
            if outcome == "WIN":
                self.state.total_wins += 1
            elif outcome == "LOSS":
                self.state.total_losses += 1
                self.state.last_loss_at_utc = to_iso(utc_now())
            else:
                self.state.total_breakeven += 1
            self.log_event("trade_closed", {**dataclasses.asdict(trade), "side": trade.side.value})

        self.state.open_trades = [t for t in self.state.open_trades if t.status == "OPEN"]

    def run_once(self) -> Dict[str, Any]:
        self.refresh_day_if_needed()
        self.update_open_trades()

        decisions = []
        for symbol in self.config.symbols:
            try:
                signal = self.process_symbol(symbol)
                if signal:
                    decisions.append({"symbol": symbol, "signal": {**dataclasses.asdict(signal), "side": signal.side.value}})
                    if self.config.mode in ("execution", "paper"):
                        self.maybe_open_trade_from_signal(signal)
            except Exception as exc:
                self.log_event("error", {"symbol": symbol, "error": str(exc)})

        self.state.last_run_at_utc = to_iso(utc_now())
        self.store.save(self.state)
        return {
            "bot_name": self.config.bot_name,
            "mode": self.config.mode,
            "balance": self.state.balance,
            "equity": self.state.equity,
            "daily_pnl": self.state.daily_pnl,
            "open_trades": len(self.state.open_trades),
            "win_rate": win_rate(self.state),
            "profit_factor": profit_factor(self.state),
            "signals": decisions,
            "last_run_at_utc": self.state.last_run_at_utc,
        }

    def loop(self) -> None:
        self.logger.info("Iniciando %s em modo %s", self.config.bot_name, self.config.mode)
        while not self.stop_event.is_set():
            start = time.time()
            try:
                summary = self.run_once()
                self.logger.info(
                    "Resumo: equity=%.2f pnl_dia=%.2f trades_abertos=%d win_rate=%.1f%%",
                    summary["equity"],
                    summary["daily_pnl"],
                    summary["open_trades"],
                    summary["win_rate"],
                )
            except Exception as exc:
                self.logger.exception("Erro no loop principal: %s", exc)
            elapsed = time.time() - start
            sleep_for = max(5, self.config.poll_seconds - elapsed)
            self.stop_event.wait(sleep_for)

    def start(self) -> None:
        if self.loop_thread and self.loop_thread.is_alive():
            return
        self.stop_event.clear()
        self.loop_thread = threading.Thread(target=self.loop, daemon=True)
        self.loop_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.loop_thread:
            self.loop_thread.join(timeout=10)
