import time
import requests
from datetime import datetime
from config import Config
from utils import log, fmt
from risk import calc_trade_plan, contract_size_for
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

    def next_pending_id(self):
        self.pending_counter += 1
        return self.pending_counter

    def is_paused(self):
        return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0
        self.consecutive_losses = 0

    def add_pending(self, pend):
        self.pending_trades.append(pend)
        self.send_pending_notification(pend)
        save_state(self)

    def execute_pending(self, pending_id, margin_usd):
        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if not pend:
            return False, "Sinal não encontrado"
        plan = calc_trade_plan(pend["symbol"], pend["entry"], self.leverage, self.balance, margin_usd)
        if not plan["ok"]:
            return False, plan["error"]
        if plan["margin_required"] > self.balance * 0.8:
            return False, "Margem excede 80% do saldo"
        trade = {
            **pend,
            "lot": plan["lot"],
            "margin_required": plan["margin_required"],
            "commission": plan["commission"],
            "opened_at": pend["created_at"],
            "wallet_before": self.balance,
        }
        self.balance -= plan["margin_required"]
        self.active_trades.append(trade)
        self.pending_trades.remove(pend)
        self.send(f"✅ TRADE ABERTO — {pend['symbol']}\n"
                  f"{pend['dir']} | Entrada: {fmt(pend['entry'])}\n"
                  f"Lote: {plan['lot']:.2f} | Margem: ${plan['margin_required']:.2f}\n"
                  f"SL: {fmt(plan['sl'])} | TP: {fmt(plan['tp'])}\n"
                  f"Saldo restante: ${self.balance:.2f}")
        save_state(self)
        return True, "Trade executado"

    def reject_pending(self, pending_id):
        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if pend:
            self.pending_trades.remove(pend)
            save_state(self)
            return True
        return False

    def monitor_trades(self):
        for t in self.active_trades[:]:
            try:
                from analysis import get_analysis
                res = get_analysis(t["symbol"], self.timeframe)
                if not res:
                    continue
                cur = res["price"]
                sl = t["sl"]
                tp = t["tp"]
                if t["dir"] == "BUY":
                    if cur <= sl or cur >= tp:
                        self.close_trade(t, cur, "WIN" if cur >= tp else "LOSS")
                else:
                    if cur >= sl or cur <= tp:
                        self.close_trade(t, cur, "WIN" if cur <= tp else "LOSS")
            except Exception as e:
                log(f"Erro monitor: {e}")

    def close_trade(self, trade, exit_price, result):
        margin = trade["margin_required"]
        lot = trade["lot"]
        entry = trade["entry"]
        cs = contract_size_for(trade["symbol"])
        if trade["dir"] == "BUY":
            profit = (exit_price - entry) * cs * lot - trade.get("commission", 0)
        else:
            profit = (entry - exit_price) * cs * lot - trade.get("commission", 0)
        self.balance += margin + profit
        self.balance = round(self.balance, 2)
        self.history.append({
            "symbol": trade["symbol"],
            "dir": trade["dir"],
            "result": result,
            "pnl": round(profit, 2),
            "closed_at": datetime.now().strftime("%d/%m %H:%M"),
        })
        if result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            self.asset_cooldown[trade["symbol"]] = time.time()
            if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                self.paused_until = time.time() + Config.PAUSE_DURATION
                self.send("⛔ CIRCUIT BREAKER – 3 losses consecutivos. Pausa de 1h.")
        self.active_trades.remove(trade)
        self.send(f"🏁 Trade fechado: {trade['symbol']} — {result}\nP&L: ${profit:.2f}\nSaldo: ${self.balance:.2f}")
        save_state(self)

    def send(self, text):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            log(f"[SEND] Erro: {e}")

    def send_pending_notification(self, pend):
        checks_str = "\n".join([f"{'✅' if c['ok'] else '❌'} {c['name']}" for c in pend["checks"]])
        msg = (
            f"🎯 SINAL PENDENTE — {pend['symbol']} ({pend['name']})\n"
            f"{pend['dir']} | Entrada: {fmt(pend['entry'])}\n"
            f"SL: {fmt(pend['sl'])} ({pend['sl_pct']}%) | TP: {fmt(pend['tp'])} (+{pend['tp_pct']}%)\n"
            f"RR: 1:{pend['rr']} | Score: {pend['score']}/{pend['max_score']}\n"
            f"------------------------------\n"
            f"💰 Custo (0.01 lote): margem ${pend['min_lot_margin']:.2f}\n"
            f"⚠️  Risco (0.01 lote): ${pend['risk_001_lot']:.2f} ({pend['risk_pct_001']:.1f}% da banca)\n"
            f"------------------------------\n"
            f"{checks_str}\n"
            f"Para executar: /executar_{pend['pending_id']}_VALOR"
        )
        self.send(msg)
