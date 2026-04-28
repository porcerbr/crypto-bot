import time
import requests
import threading
from datetime import datetime
from config import Config
from utils import log, fmt, is_jpy_pair, jpy_to_usd, max_leverage
from risk import calc_trade_plan, contract_size_for, calc_margin
from db import save_state

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
        self.signals_feed = []
        self.last_id = 0
        self.pending_counter = 0
        self._usdjpy_price = 0.0
        self._current_leverage = Config.DEFAULT_LEVERAGE
        self._processing_ai = set() 

    def next_pending_id(self):
        self.pending_counter += 1
        return self.pending_counter

    def is_paused(self):
        return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0
        self.consecutive_losses = 0

    def _get_used_margin(self):
        return sum(t.get("margin_required", 0) for t in self.active_trades)

    def _check_margin_safety(self, additional_margin):
        used = self._get_used_margin()
        total_required = used + additional_margin
        if self.balance <= 0: return False, "Saldo zerado"
        
        free_margin = self.balance - total_required
        if free_margin < 0:
            return False, f"Margem insuficiente. Necessário: ${round(total_required, 2)}"
        
        margin_level = (self.balance / total_required) * 100 if total_required > 0 else 1000
        if margin_level < Config.STOP_OUT_PCT:
            return False, f"Stop out iminente ({round(margin_level, 1)}%)"
        return True, ""

    def _update_usdjpy(self):
        try:
            from analysis import get_analysis
            res = get_analysis("USDJPY", self.timeframe)
            if res: self._usdjpy_price = res["price"]
        except Exception as e:
            log(f"[USDJPY] Erro: {e}")

    # --- NOVO: LÓGICA DE IA ASSÍNCRONA ---
    def add_pending_async(self, pend):
        """Chama a IA em uma thread separada para não travar o bot."""
        t = threading.Thread(target=self._process_ai_and_add, args=(pend,))
        t.start()

    def _process_ai_and_add(self, pend):
        symbol = pend["symbol"]
        if symbol in self._processing_ai: return
        self._processing_ai.add(symbol)
        
        try:
            from ai_validator import validate_signal
            log(f"[AI] Validando sinal para {symbol}...")
            ai_res = validate_signal(pend)
            
            pend["ai_approved"] = ai_res.get("approved", False)
            pend["ai_reason"] = ai_res.get("reason", "Sem justificativa")
            pend["ai_confidence"] = ai_res.get("confidence", 0)
            
            # Só adiciona se a IA aprovar OU se estiver em modo Manual (para você decidir)
            if pend["ai_approved"] or Config.MODE == "MANUAL":
                self.pending_trades.append(pend)
                self.send_pending_notification(pend)
                save_state(self)
            else:
                log(f"[AI] Sinal de {symbol} REJEITADO pela IA.")
        except Exception as e:
            log(f"[AI] Erro na thread de validação: {e}")
        finally:
            self._processing_ai.remove(symbol)

    # --- FUNÇÃO QUE ESTAVA FALTANDO ---
    def expire_pending_signals(self, max_age_seconds: int = 7200):
        """Remove sinais pendentes mais antigos que o limite (Padrão 2h)."""
        now = time.time()
        expired = [
            p for p in self.pending_trades
            if now - p.get("created_ts", now) > max_age_seconds
        ]
        for p in expired:
            self.pending_trades.remove(p)
            msg = f"⏱ Sinal expirado — {p['symbol']}\nContexto desatualizado (+{max_age_seconds//60}min)"
            self.send(msg)
            log(f"[EXPIRY] Sinal {p['pending_id']} removido por tempo.")
        if expired:
            save_state(self)

    def execute_pending(self, pending_id, margin_usd):
        from utils import (
            get_dynamic_leverage, get_dynamic_max_trades, get_max_risk_absolute,
            get_min_free_margin_pct, is_symbol_allowed, is_weekend_gap_risk
        )

        if is_weekend_gap_risk(): return False, "Proteção de fim de semana ativa."

        max_trades = get_dynamic_max_trades(self.balance)
        if len(self.active_trades) >= max_trades:
            return False, f"Limite de {max_trades} trades atingido."

        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if not pend: return False, "Sinal não encontrado."

        if not is_symbol_allowed(pend["symbol"], self.balance):
            return False, "Ativo bloqueado para sua banca atual."

        eff_lev = get_dynamic_leverage(self.balance)
        plan = calc_trade_plan(pend["symbol"], pend["entry"], eff_lev, self.balance, margin_usd)
        
        if not plan["ok"]: return False, plan["error"]

        ok, msg = self._check_margin_safety(plan["margin_required"])
        if not ok: return False, msg

        trade = {
            **pend,
            "lot": plan["lot"],
            "margin_required": plan["margin_required"],
            "commission": plan["commission"],
            "opened_at": datetime.now().strftime("%d/%m %H:%M"),
            "effective_leverage": eff_lev,
            "trailing_activated": False
        }
        
        self.balance -= plan["margin_required"]
        self.active_trades.append(trade)
        self.pending_trades.remove(pend)
        
        self.send(f"🚀 TRADE ABERTO: {pend['symbol']}\nLote: {round(plan['lot'], 2)}\nSaldo: ${round(self.balance, 2)}")
        save_state(self)
        return True, "Executado"

    def monitor_trades(self):
        """Monitora ordens abertas para Trailing Stop, TP e SL."""
        for t in self.active_trades[:]:
            try:
                from analysis import get_analysis
                res = get_analysis(t["symbol"], self.timeframe)
                if not res: continue
                
                cur = res["price"]
                atr = res["atr"]
                
                # Lógica de Trailing Stop
                if Config.TRAILING_ACTIVATION > 0 and not t.get("trailing_activated", False):
                    progress = abs(cur - t["entry"]) / abs(t["tp"] - t["entry"]) if t["tp"] != t["entry"] else 0
                    if progress >= Config.TRAILING_ACTIVATION:
                        t["trailing_activated"] = True
                        self.send(f"🛡️ Trailing ativado para {t['symbol']}")

                if t.get("trailing_activated"):
                    if t["dir"] == "BUY":
                        new_sl = round(cur - (Config.ATR_MULT_TRAIL * atr), 5)
                        if new_sl > t["sl"]: t["sl"] = new_sl
                    else:
                        new_sl = round(cur + (Config.ATR_MULT_TRAIL * atr), 5)
                        if new_sl < t["sl"]: t["sl"] = new_sl

                # Check de fechamento
                if t["dir"] == "BUY":
                    if cur <= t["sl"]: self.close_trade(t, cur, "LOSS")
                    elif cur >= t["tp"]: self.close_trade(t, cur, "WIN")
                else:
                    if cur >= t["sl"]: self.close_trade(t, cur, "LOSS")
                    elif cur <= t["tp"]: self.close_trade(t, cur, "WIN")
            except Exception as e:
                log(f"Erro monitor: {e}")

    def close_trade(self, trade, exit_price, result):
        margin = trade["margin_required"]
        cs = contract_size_for(trade["symbol"])
        
        diff = (exit_price - trade["entry"]) if trade["dir"] == "BUY" else (trade["entry"] - exit_price)
        profit = diff * cs * trade["lot"]
        
        if is_jpy_pair(trade["symbol"]):
            if self._usdjpy_price <= 0: self._update_usdjpy()
            profit = jpy_to_usd(profit, self._usdjpy_price)

        self.balance += (margin + profit)
        self.balance = round(self.balance, 2)
        
        self.history.append({
            "symbol": trade["symbol"],
            "dir": trade["dir"],
            "result": result,
            "pnl": round(profit, 2),
            "opened_at": trade.get("opened_at", ""),
            "closed_at": datetime.now().strftime("%d/%m %H:%M")
        })
        
        if result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                self.paused_until = time.time() + Config.PAUSE_DURATION
                self.send("🚨 CIRCUIT BREAKER: 3 losses seguidos. Pausa de 1h.")

        self.active_trades.remove(trade)
        save_state(self)
        self.send(f"🏁 TRADE FECHADO: {trade['symbol']}\nResultado: {result}\nP&L: ${round(profit, 2)}")

    def reject_pending(self, pending_id):
        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if pend:
            self.pending_trades.remove(pend)
            save_state(self)
            return True
        return False

    def send(self, text):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": Config.CHAT_ID, "text": text}, timeout=5)
        except: pass

    def send_pending_notification(self, pend):
        msg = (
            f"🎯 SINAL PENDENTE: {pend['symbol']} ({pend['dir']})\n"
            f"——————————————————\n"
            f"🤖 IA: {pend.get('ai_reason', '—')}\n"
            f"📍 Entrada: {fmt(pend['entry'])}\n"
            f"📊 RR: 1:{pend['rr']} | Confiança: {pend.get('ai_confidence', 0)}%\n"
            f"——————————————————\n"
            f"▶️ /executar_{pend['pending_id']}_10"
        )
        self.send(msg)

    def get_current_leverage(self):
        return self._current_leverage
