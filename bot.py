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
            return False, f"Margem insuficiente. Necessário: ${total_required:.2f}"
        if total_required > 0:
            margin_level = (self.balance / total_required) * 100
            if margin_level < Config.STOP_OUT_PCT:
                return False, f"Stop out iminente (nível {margin_level:.1f}%)"
            if margin_level < Config.MARGIN_CALL_PCT:
                log(f"[AVISO] Margin call próximo (nível {margin_level:.1f}%)")
        return True, ""

    def _update_usdjpy(self):
        try:
            from analysis import get_analysis
            res = get_analysis("USDJPY", self.timeframe)
            if res:
                self._usdjpy_price = res["price"]
        except Exception as e:
            log(f"[USDJPY] Erro ao atualizar: {e}")

    # ── NOVO: Filtro de correlação (regra 3-5-7) ──────────────────────
    def check_correlation_exposure(self, symbol, additional_risk_usd=0.0):
        """
        Verifica se adicionar 'symbol' ultrapassa o limite de risco
        correlacionado (MAX_CORRELATED_RISK_PCT).
        """
        for group_name, symbols in Config.CORRELATION_GROUPS.items():
            if symbol not in symbols:
                continue

            total_risk_usd = 0.0
            for t in self.active_trades:
                if t["symbol"] in symbols:
                    dist = abs(t["entry"] - t["sl"])
                    cs = contract_size_for(t["symbol"])
                    risk = t["lot"] * dist * cs
                    # Estimativa JPY → USD (USDJPY ~150)
                    if is_jpy_pair(t["symbol"]):
                        risk = risk / 150.0
                    total_risk_usd += risk

            total_risk_usd += additional_risk_usd

            if self.balance > 0:
                corr_pct = (total_risk_usd / self.balance) * 100
                if corr_pct >= Config.MAX_CORRELATED_RISK_PCT:
                    return False, f"{group_name} {corr_pct:.1f}%"
        return True, ""

    def add_pending(self, pend):
        self.pending_trades.append(pend)
        self.send_pending_notification(pend)
        save_state(self)

    def execute_pending(self, pending_id, margin_usd):
        """Versão com alavancagem dinâmica e proteções de segurança."""
        from utils import (
            get_dynamic_leverage, get_dynamic_max_trades, get_max_risk_absolute,
            get_min_free_margin_pct, is_symbol_allowed, is_weekend_gap_risk,
            get_allowed_symbols
        )

        # ── NOVO: Proteção de fim de semana ──────────────────────────
        if is_weekend_gap_risk():
            return False, "Proteção de fim de semana ativa — não abrindo novos trades"

        # ── NOVO: Limite de trades por banca ─────────────────────────
        max_trades = get_dynamic_max_trades(self.balance)
        if len(self.active_trades) >= max_trades:
            return False, f"Limite de {max_trades} trade(s) ativo(s) para banca atual"

        pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
        if not pend:
            return False, "Sinal não encontrado"

        # ── NOVO: Verifica se ativo é permitido para banca atual ─────
        if not is_symbol_allowed(pend["symbol"], self.balance):
            allowed = get_allowed_symbols(self.balance)
            return False, f"{pend['symbol']} bloqueado para banca ${self.balance:.0f}. Permitidos: {', '.join(allowed)}"

        # ── Verificação de correlação na execução ─────────────────────
        est_risk = pend.get("suggested_risk_usd", 0)
        ok_corr, msg_corr = self.check_correlation_exposure(pend["symbol"], est_risk)
        if not ok_corr:
            return False, f"Correlação: {msg_corr}"

        # ── NOVO: Alavancagem dinâmica ───────────────────────────────
        eff_lev = get_dynamic_leverage(self.balance)
        self._current_leverage = eff_lev

        # ── NOVO: Risco absoluto máximo ──────────────────────────────
        max_risk_usd = get_max_risk_absolute(self.balance)
        if pend.get("suggested_risk_usd", 0) > max_risk_usd:
            return False, f"Risco ${pend['suggested_risk_usd']:.2f} excede limite de ${max_risk_usd:.2f} para banca atual"

        plan = calc_trade_plan(pend["symbol"], pend["entry"], eff_lev, self.balance, margin_usd)
        if not plan["ok"]:
            return False, plan["error"]
        if plan["margin_required"] > self.balance * 0.8:
            return False, "Margem excede 80% do saldo"

        # ── NOVO: Margem livre mínima obrigatória ────────────────────
        used = self._get_used_margin()
        free_margin = self.balance - used - plan["margin_required"]
        min_free_pct = get_min_free_margin_pct(self.balance)
        if free_margin < self.balance * min_free_pct:
            return False, f"Margem livre insuficiente. Necessário: {min_free_pct*100:.0f}% livre"

        ok, msg = self._check_margin_safety(plan["margin_required"])
        if not ok:
            return False, msg

        trade = {
            **pend,
            "lot": plan["lot"],
            "margin_required": plan["margin_required"],
            "commission": plan["commission"],
            "opened_at": pend["created_at"],
            "wallet_before": self.balance,
            "trailing_activated": False,
            "effective_leverage": eff_lev,
        }
        self.balance -= plan["margin_required"]
        self.active_trades.append(trade)
        self.pending_trades.remove(pend)
        self.send(f"✅ TRADE ABERTO — {pend['symbol']}
"
                  f"{pend['dir']} | Entrada: {fmt(pend['entry'])}
"
                  f"Lote: {plan['lot']:.2f} | Margem: ${plan['margin_required']:.2f} | Alav: {eff_lev}:1
"
                  f"SL: {fmt(plan['sl'])} | TP: {fmt(plan['tp'])}
"
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
                            self.send(f"🔁 Trailing Stop ajustado: {fmt(new_sl)}")
                    else:
                        new_sl = cur + Config.ATR_MULT_TRAIL * atr
                        if new_sl < sl:
                            t["sl"] = round(new_sl, 5)
                            self.send(f"🔁 Trailing Stop ajustado: {fmt(new_sl)}")

                if direction == "BUY":
                    if cur <= t["sl"] or cur >= tp:
                        self.close_trade(t, cur, "WIN" if cur >= tp else "LOSS")
                else:
                    if cur >= t["sl"] or cur <= tp:
                        self.close_trade(t, cur, "WIN" if cur <= tp else "LOSS")
            except Exception as e:
                log(f"Erro monitor: {e}")

    def close_trade(self, trade, exit_price, result):
        """Versão com cooldown dinâmico baseado no capital."""
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
            "symbol": symbol,
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

            # ── NOVO: Cooldown dinâmico após loss ──────────────────────
            cooldown = get_dynamic_cooldown(self.balance)
            self.asset_cooldown[symbol] = time.time() + cooldown

            if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                self.paused_until = time.time() + Config.PAUSE_DURATION
                self.send("⛔ CIRCUIT BREAKER – 3 losses consecutivos. Pausa de 1h.")
        self.active_trades.remove(trade)
        self.send(f"🏁 Trade fechado: {symbol} — {result}
P&L: ${profit:.2f}
Saldo: ${self.balance:.2f}")
        save_state(self)

    def send(self, text):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            log(f"[SEND] Erro: {e}")
        self.send_push(text)

    def send_push(self, text):
        if Config.NTFY_TOPIC:
            try:
                requests.post(f"https://ntfy.sh/{Config.NTFY_TOPIC}",
                              data=text.encode("utf-8"),
                              headers={"Title": "Sniper Bot Signal"},
                              timeout=5)
            except Exception as e:
                log(f"[PUSH] Erro: {e}")

    def send_pending_notification(self, pend):
        checks_str = "
".join([f"{'✅' if c['ok'] else '❌'} {c['name']}" for c in pend["checks"]])
        msg = (
            f"🎯 SINAL PENDENTE — {pend['symbol']} ({pend['name']})
"
            f"{pend['dir']} | Entrada: {fmt(pend['entry'])}
"
            f"SL: {fmt(pend['sl'])} ({pend['sl_pct']}%) | TP: {fmt(pend['tp'])} (+{pend['tp_pct']}%)
"
            f"RR: 1:{pend['rr']} | Score: {pend['score']}/{pend['max_score']}
"
            f"------------------------------
"
            f"💰 Margem p/ 0.01 lote: ${pend['min_lot_margin']:.2f}
"
            f"⚠️  Risco c/ lote mínimo: ${pend['risk_001_lot']:.2f} ({pend['risk_pct_001']:.1f}%)
"
            f"🎯 Lote sugerido (risco {Config.ATR_RISK_PCT}%): {pend['suggested_lot']} lote(s)
"
            f"   → Risco real: ${pend['suggested_risk_usd']:.2f} ({pend['suggested_risk_pct']:.1f}%)
"
            f"------------------------------
"
            f"{checks_str}
"
            f"Para executar: /executar_{pend['pending_id']}_VALOR"
        )
        self.send(msg)

    # ── NOVO: Retorna alavancagem efetiva atual ──────────────────────
    def get_current_leverage(self):
        """Retorna alavancagem efetiva atual (dinâmica ou fixa)."""
        from utils import get_dynamic_leverage
        if Config.USE_DYNAMIC_LEVERAGE:
            return get_dynamic_leverage(self.balance)
        return self.leverage
