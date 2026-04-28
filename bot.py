import time
import requests
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
        free_margin = self.balance - total_required
        if free_margin < 0:
            return False, "Margem insuficiente. Necessario: $" + str(round(total_required, 2))
        if total_required > 0:
            margin_level = (self.balance / total_required) * 100
            if margin_level < Config.STOP_OUT_PCT:
                return False, "Stop out iminente (nivel " + str(round(margin_level, 1)) + "%)"
            if margin_level < Config.MARGIN_CALL_PCT:
                log("[AVISO] Margin call proximo (nivel " + str(round(margin_level, 1)) + "%)")
        return True, ""

    def _update_usdjpy(self):
        try:
            from analysis import get_analysis
            res = get_analysis("USDJPY", self.timeframe)
            if res:
                self._usdjpy_price = res["price"]
        except Exception as e:
            log("[USDJPY] Erro ao atualizar: " + str(e))

    def check_correlation_exposure(self, symbol, additional_risk_usd=0.0):
        for group_name, symbols in Config.CORRELATION_GROUPS.items():
            if symbol not in symbols:
                continue
            total_risk_usd = 0.0
            for t in self.active_trades:
                if t["symbol"] in symbols:
                    dist = abs(t["entry"] - t["sl"])
                    cs = contract_size_for(t["symbol"])
                    risk = t["lot"] * dist * cs
                    if is_jpy_pair(t["symbol"]):
                        risk = risk / 150.0
                    total_risk_usd += risk
            total_risk_usd += additional_risk_usd
            if self.balance > 0:
                corr_pct = (total_risk_usd / self.balance) * 100
                if corr_pct >= Config.MAX_CORRELATED_RISK_PCT:
                    return False, group_name + " " + str(round(corr_pct, 1)) + "%"
        return True, ""

    def add_pending(self, pend):
        self.pending_trades.append(pend)
        self.send_pending_notification(pend)
        save_state(self)

    def execute_pending(self, pending_id, margin_usd):
        from utils import (
            get_dynamic_leverage, get_dynamic_max_trades, get_max_risk_absolute,
            get_min_free_margin_pct, is_symbol_allowed, is_weekend_gap_risk,
            get_allowed_symbols
        )

        if is_weekend_gap_risk():
            return False, "Protecao de fim de semana ativa — nao abrindo novos trades"

        max_trades = get_dynamic_max_trades(self.balance)
        if len(self.active_trades) >= max_trades:
            return False, "Limite de " + str(max_trades) + " trade(s) ativo(s) para banca atual"

        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if not pend:
            return False, "Sinal nao encontrado"

        if not is_symbol_allowed(pend["symbol"], self.balance):
            allowed = get_allowed_symbols(self.balance)
            return False, pend["symbol"] + " bloqueado para banca $" + str(round(self.balance, 0)) + ". Permitidos: " + ", ".join(allowed)

        est_risk = pend.get("suggested_risk_usd", 0)
        ok_corr, msg_corr = self.check_correlation_exposure(pend["symbol"], est_risk)
        if not ok_corr:
            return False, "Correlacao: " + msg_corr

        eff_lev = get_dynamic_leverage(self.balance)
        self._current_leverage = eff_lev

        max_risk_usd = get_max_risk_absolute(self.balance)
        if pend.get("suggested_risk_usd", 0) > max_risk_usd:
            return False, "Risco $" + str(round(pend["suggested_risk_usd"], 2)) + " excede limite de $" + str(round(max_risk_usd, 2)) + " para banca atual"

        plan = calc_trade_plan(pend["symbol"], pend["entry"], eff_lev, self.balance, margin_usd)
        if not plan["ok"]:
            return False, plan["error"]
        if plan["margin_required"] > self.balance * 0.8:
            return False, "Margem excede 80% do saldo"

        used = self._get_used_margin()
        free_margin = self.balance - used - plan["margin_required"]
        min_free_pct = get_min_free_margin_pct(self.balance)
        if free_margin < self.balance * min_free_pct:
            return False, "Margem livre insuficiente. Necessario: " + str(round(min_free_pct*100, 0)) + "% livre"

        ok, msg = self._check_margin_safety(plan["margin_required"])
        if not ok:
            return False, msg

        trade = {
            **pend,
            "lot":               plan["lot"],
            "margin_required":   plan["margin_required"],
            "commission":        plan["commission"],
            "opened_at":         pend["created_at"],
            "wallet_before":     self.balance,
            "trailing_activated":False,
            "effective_leverage":eff_lev,
            # propaga metadados da IA para o trade (usados no close_trade → history)
            "ai_approved":       pend.get("ai_approved", True),
            "ai_confidence":     pend.get("ai_confidence", 0),
        }
        self.balance -= plan["margin_required"]
        self.active_trades.append(trade)
        self.pending_trades.remove(pend)

        msg_lines = [
            "TRADE ABERTO — " + pend["symbol"],
            pend["dir"] + " | Entrada: " + fmt(pend["entry"]),
            "Lote: " + str(round(plan["lot"], 2)) + " | Margem: $" + str(round(plan["margin_required"], 2)) + " | Alav: " + str(eff_lev) + ":1",
            "SL: " + fmt(plan["sl"]) + " | TP: " + fmt(plan["tp"]),
            "Saldo restante: $" + str(round(self.balance, 2))
        ]
        self.send(chr(10).join(msg_lines))

        save_state(self)
        return True, "Trade executado"

    def reject_pending(self, pending_id):
        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if pend:
            self.pending_trades.remove(pend)
            save_state(self)
            return True
        return False

    def expire_pending_signals(self, max_age_seconds: int = 7200):
        """
        Remove sinais pendentes mais antigos que max_age_seconds (padrão: 2h).
        Sinais H1 gerados há mais de 2h são baseados em contexto de mercado
        desatualizado — manter aumenta o risco de entrar em momento errado.
        """
        now = time.time()
        expired = [
            p for p in self.pending_trades
            if now - p.get("created_ts", now) > max_age_seconds
        ]
        for p in expired:
            self.pending_trades.remove(p)
            msg = (
                f"⏱ Sinal expirado — {p['symbol']} {p['dir']}\n"
                f"Gerado às {p['created_at']} | Expirado após {max_age_seconds // 60}min\n"
                f"Entrada era: {fmt(p['entry'])}"
            )
            self.send(msg)
            log(f"[EXPIRY] Sinal {p['pending_id']} ({p['symbol']}) expirado")
        if expired:
            save_state(self)

    def monitor_trades(self):
        for t in self.active_trades[:]:
            try:
                from analysis import get_analysis
                res = get_analysis(t["symbol"], self.timeframe)
                if not res:
                    continue
                cur = res["price"]
                atr = res["atr"]
                sl = t["sl"]
                tp = t["tp"]
                entry = t["entry"]
                direction = t["dir"]

                if Config.TRAILING_ACTIVATION > 0 and not t.get("trailing_activated", False):
                    if direction == "BUY":
                        progress = (cur - entry) / (tp - entry) if tp != entry else 0
                        if progress >= Config.TRAILING_ACTIVATION:
                            t["trailing_activated"] = True
                    else:
                        progress = (entry - cur) / (entry - tp) if entry != tp else 0
                        if progress >= Config.TRAILING_ACTIVATION:
                            t["trailing_activated"] = True

                if t.get("trailing_activated"):
                    if direction == "BUY":
                        new_sl = cur - Config.ATR_MULT_TRAIL * atr
                        if new_sl > sl:
                            t["sl"] = round(new_sl, 5)
                            self.send("Trailing Stop ajustado: " + fmt(new_sl))
                    else:
                        new_sl = cur + Config.ATR_MULT_TRAIL * atr
                        if new_sl < sl:
                            t["sl"] = round(new_sl, 5)
                            self.send("Trailing Stop ajustado: " + fmt(new_sl))

                if direction == "BUY":
                    if cur <= t["sl"] or cur >= tp:
                        self.close_trade(t, cur, "WIN" if cur >= tp else "LOSS")
                else:
                    if cur >= t["sl"] or cur <= tp:
                        self.close_trade(t, cur, "WIN" if cur <= tp else "LOSS")
            except Exception as e:
                log("Erro monitor: " + str(e))

    def close_trade(self, trade, exit_price, result):
        from utils import get_dynamic_cooldown

        margin = trade["margin_required"]
        lot = trade["lot"]
        entry = trade["entry"]
        symbol = trade["symbol"]
        cs = contract_size_for(symbol)

        if trade["dir"] == "BUY":
            profit_raw = (exit_price - entry) * cs * lot - trade.get("commission", 0)
        else:
            profit_raw = (entry - exit_price) * cs * lot - trade.get("commission", 0)

        if is_jpy_pair(symbol):
            if self._usdjpy_price <= 0:
                self._update_usdjpy()
            profit = jpy_to_usd(profit_raw, self._usdjpy_price)
        else:
            profit = profit_raw

        self.balance += margin + profit
        self.balance = round(self.balance, 2)
        self.history.append({
            "symbol":        symbol,
            "dir":           trade["dir"],
            "result":        result,
            "pnl":           round(profit, 2),
            "closed_at":     datetime.now().strftime("%d/%m %H:%M"),
            "opened_at":     trade.get("opened_at", ""),
            "adx":           trade.get("adx", 0),
            # Feedback loop — IA aprovou? Com qual confiança?
            # Permite ao aprendizado semanal correlacionar confiança com resultado
            "ai_approved":   trade.get("ai_approved", True),
            "ai_confidence": trade.get("ai_confidence", 0),
        })
        if result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            cooldown = get_dynamic_cooldown(self.balance)
            self.asset_cooldown[symbol] = time.time() + cooldown
            if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                self.paused_until = time.time() + Config.PAUSE_DURATION
                self.send("CIRCUIT BREAKER – 3 losses consecutivos. Pausa de 1h.")
        self.active_trades.remove(trade)
        msg = "Trade fechado: " + symbol + " — " + result + chr(10) + "P&L: $" + str(round(profit, 2)) + chr(10) + "Saldo: $" + str(round(self.balance, 2))
        self.send(msg)
        save_state(self)

    def send(self, text):
        url = "https://api.telegram.org/bot" + Config.BOT_TOKEN + "/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            log("[SEND] Erro: " + str(e))
        self.send_push(text)

    def send_push(self, text):
        if Config.NTFY_TOPIC:
            try:
                requests.post("https://ntfy.sh/" + Config.NTFY_TOPIC,
                              data=text.encode("utf-8"),
                              headers={"Title": "Sniper Bot Signal"},
                              timeout=5)
            except Exception as e:
                log("[PUSH] Erro: " + str(e))

    def send_pending_notification(self, pend):
        checks_lines = []
        for c in pend["checks"]:
            icon = "OK" if c["ok"] else "X"
            checks_lines.append(icon + " " + c["name"])
        checks_str = chr(10).join(checks_lines)

        lines = [
            "SINAL PENDENTE — " + pend["symbol"] + " (" + pend["name"] + ")",
            pend["dir"] + " | Entrada: " + fmt(pend["entry"]),
            "SL: " + fmt(pend["sl"]) + " (" + str(pend["sl_pct"]) + "%) | TP: " + fmt(pend["tp"]) + " (+" + str(pend["tp_pct"]) + "%)",
            "RR: 1:" + str(pend["rr"]) + " | Score: " + str(pend["score"]) + "/" + str(pend["max_score"]),
            "🤖 IA: " + pend.get("ai_reason", "—"),
            "------------------------------",
            "Margem p/ 0.01 lote: $" + str(round(pend["min_lot_margin"], 2)),
            "Risco c/ lote minimo: $" + str(round(pend["risk_001_lot"], 2)) + " (" + str(round(pend["risk_pct_001"], 1)) + "%)",
            "Lote sugerido (risco " + str(Config.ATR_RISK_PCT) + "%): " + str(pend["suggested_lot"]) + " lote(s)",
            "   -> Risco real: $" + str(round(pend["suggested_risk_usd"], 2)) + " (" + str(round(pend["suggested_risk_pct"], 1)) + "%)",
            "------------------------------",
            checks_str,
            "Para executar: /executar_" + str(pend["pending_id"]) + "_VALOR"
        ]
        self.send(chr(10).join(lines))

    def get_current_leverage(self):
        from utils import get_dynamic_leverage
        if Config.USE_DYNAMIC_LEVERAGE:
            return get_dynamic_leverage(self.balance)
        return self.leverage
