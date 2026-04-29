import time
import threading
from datetime import datetime
from config import Config
from utils import log, fmt
from db import save_state, append_log

class TradingBot:
    def __init__(self):
        self.mode = Config.MODE
        self.timeframe = Config.TIMEFRAME
        self.balance = Config.INITIAL_BALANCE
        self.leverage = Config.DEFAULT_LEVERAGE
        self.wins = 0
        self.losses = 0
        self.active_trades = []
        self.pending_trades = []
        self.history = []
        self.pending_counter = 0
        self._processing_ai = set()

    def next_pending_id(self):
        self.pending_counter += 1
        return self.pending_counter

    def add_pending_async(self, pend):
        """Valida o sinal com IA em segundo plano."""
        if pend["symbol"] in self._processing_ai: return
        t = threading.Thread(target=self._ai_worker, args=(pend,))
        t.start()

    def _ai_worker(self, pend):
        self._processing_ai.add(pend["symbol"])
        try:
            from ai_validator import validate_signal
            res = validate_signal(pend)
            pend["ai_approved"] = res.get("approved", False)
            pend["ai_reason"] = res.get("reason", "Analisado")
            if pend["ai_approved"] or self.mode == "MANUAL":
                self.pending_trades.append(pend)
                append_log("INFO", f"Novo sinal: {pend['symbol']}")
                save_state(self)
        finally:
            self._processing_ai.remove(pend["symbol"])

    def monitor_trades(self):
        """Verifica se trades ativos bateram no SL ou TP (ESSENCIAL)."""
        from analysis import _cache
        for t in self.active_trades[:]:
            sym = t["symbol"]
            if sym not in _cache: continue
            
            cur_price = float(_cache[sym][1]["Close"].iloc[-1])
            is_win = False
            is_loss = False

            if t["dir"] == "BUY":
                if cur_price >= t["tp"]: is_win = True
                elif cur_price <= t["sl"]: is_loss = True
            else:
                if cur_price <= t["tp"]: is_win = True
                elif cur_price >= t["sl"]: is_loss = True

            if is_win or is_loss:
                self.close_trade(t, cur_price, "WIN" if is_win else "LOSS")

    def close_trade(self, trade, price, result):
        if result == "WIN": self.wins += 1
        else: self.losses += 1
        
        # Cálculo simplificado de PnL para histórico
        pip_factor = 0.01 if (trade["symbol"].endswith("JPY") or trade["symbol"] == "XAUUSD") else 0.0001
        pips = (price - trade["entry"]) / pip_factor if trade["dir"] == "BUY" else (trade["entry"] - price) / pip_factor
        pnl = pips * trade.get("lot", 0.01) * 10
        
        self.balance += (trade.get("margin_required", 0) + pnl)
        trade["result"] = result
        trade["pnl"] = round(pnl, 2)
        trade["close_price"] = price
        
        self.history.append(trade)
        self.active_trades.remove(trade)
        append_log("TRADE", f"Fechado {trade['symbol']}: {result} (${pnl:.2f})")
        save_state(self)

    def expire_pending_signals(self, age=7200):
        now = time.time()
        self.pending_trades = [p for p in self.pending_trades if now - p.get("created_ts", now) < age]

    def get_current_leverage(self):
        return getattr(self, "leverage", 100)
