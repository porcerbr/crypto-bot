import time
import requests
import threading
from datetime import datetime
from config import Config
from utils import log, fmt, is_jpy_pair, jpy_to_usd
from risk import calc_trade_plan, contract_size_for
from db import save_state, append_log

class TradingBot:
    def __init__(self):
        self.mode = Config.MODE
        self.timeframe = Config.TIMEFRAME
        self.leverage = Config.DEFAULT_LEVERAGE
        self.balance = Config.INITIAL_BALANCE
        self.wins = 0
        self.losses = 0
        self.consecutive_losses = 0
        self.paused_until = 0.0
        self.active_trades = []
        self.pending_trades = []
        self.history = []
        self.asset_cooldown = {}
        self.pending_counter = 0
        self._usdjpy_price = 0.0
        self._current_leverage = Config.DEFAULT_LEVERAGE
        self._processing_ai = set()

    def next_pending_id(self):
        self.pending_counter += 1
        return self.pending_counter

    def is_paused(self):
        return time.time() < self.paused_until

    def get_current_leverage(self):
        return self._current_leverage

    # --- NOVO: Lógica de IA Assíncrona ---
    def add_pending_async(self, pend):
        """Chama a IA em uma thread separada."""
        t = threading.Thread(target=self._process_ai_and_add, args=(pend,))
        t.start()

    def _process_ai_and_add(self, pend):
        symbol = pend["symbol"]
        if symbol in self._processing_ai: return
        self._processing_ai.add(symbol)
        try:
            from ai_validator import validate_signal
            log(f"[AI] Analisando {symbol}...")
            res = validate_signal(pend)
            
            pend["ai_approved"] = res.get("approved", False)
            pend["ai_reason"] = res.get("reason", "Sem análise")
            pend["ai_confidence"] = res.get("confidence", 0)
            
            if pend["ai_approved"] or Config.MODE == "MANUAL":
                self.pending_trades.append(pend)
                self.send_pending_notification(pend)
                save_state(self)
                append_log("INFO", f"Sinal {symbol} adicionado via IA.")
        except Exception as e:
            log(f"Erro IA: {e}")
        finally:
            self._processing_ai.remove(symbol)

    def expire_pending_signals(self, max_age_seconds: int = 7200):
        now = time.time()
        expired = [p for p in self.pending_trades if now - p.get("created_ts", now) > max_age_seconds]
        for p in expired:
            self.pending_trades.remove(p)
            log(f"[EXPIRY] Removido: {p['symbol']}")
        if expired: save_state(self)

    def execute_pending(self, pending_id, margin_usd):
        from utils import get_dynamic_leverage, get_dynamic_max_trades, is_symbol_allowed
        
        max_trades = get_dynamic_max_trades(self.balance)
        if len(self.active_trades) >= max_trades:
            return False, f"Limite de {max_trades} trades atingido."

        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if not pend: return False, "Sinal expirado ou não encontrado."

        if not is_symbol_allowed(pend["symbol"], self.balance):
            return False, "Ativo bloqueado para sua banca."

        eff_lev = get_dynamic_leverage(self.balance)
        plan = calc_trade_plan(pend["symbol"], pend["entry"], eff_lev, self.balance, margin_usd)
        
        if not plan["ok"]: return False, plan["error"]

        trade = {
            **pend,
            "lot": plan["lot"],
            "margin_required": plan["margin_required"],
            "opened_at": datetime.now().strftime("%H:%M"),
            "pnl": 0
        }
        
        self.balance -= plan["margin_required"]
        self.active_trades.append(trade)
        self.pending_trades.remove(pend)
        save_state(self)
        append_log("TRADE", f"Executado {trade['symbol']} {trade['dir']}")
        return True, "Executado com sucesso"

    def close_trade(self, trade, exit_price, result):
        # ... (sua lógica de fechamento existente aqui)
        # Lembre-se de chamar append_log("INFO", f"Trade {trade['symbol']} fechado: {result}")
        pass

    def reject_pending(self, pending_id):
        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if pend:
            self.pending_trades.remove(pend)
            save_state(self)
            return True
        return False

    def send(self, text):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        try: requests.post(url, json={"chat_id": Config.CHAT_ID, "text": text}, timeout=5)
        except: pass

    def send_pending_notification(self, pend):
        msg = f"🎯 SINAL: {pend['symbol']}\nIA: {pend.get('ai_reason', '—')}\n▶️ /executar_{pend['pending_id']}_10"
        self.send(msg)
