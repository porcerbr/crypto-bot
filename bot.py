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
        self.pending_trades = []   # mantido para compatibilidade com state.json legado
        self.history = []
        self.asset_cooldown = {}
        self.signals_feed = []
        self.last_id = 0
        self.pending_counter = 0
        self._usdjpy_price = 0.0
        self._current_leverage = Config.DEFAULT_LEVERAGE
        self.telegram_desk = None

    def next_pending_id(self):
        self.pending_counter += 1
        return self.pending_counter

    def is_paused(self):
        return time.time() < self.paused_until

    def pause_for(self, seconds: int, reason: str = ""):
        seconds = max(1, int(seconds))
        self.paused_until = time.time() + seconds
        if reason:
            log(f"[PAUSE] {reason} ({seconds}s)")

    def resume(self):
        self.paused_until = 0
        self.consecutive_losses = 0
        log("[PAUSE] Bot retomado manualmente")

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
            # Usa o preço USDJPY em cache, com fallback para 150.0 apenas se
            # o cache ainda não estiver populado (primeiros segundos de startup)
            usdjpy_rate = self._usdjpy_price if self._usdjpy_price > 0 else 150.0
            for t in self.active_trades:
                if t["symbol"] in symbols:
                    dist = abs(t["entry"] - t["sl"])
                    cs = contract_size_for(t["symbol"])
                    risk = t["lot"] * dist * cs
                    if is_jpy_pair(t["symbol"]):
                        risk = risk / usdjpy_rate
                    total_risk_usd += risk
            total_risk_usd += additional_risk_usd
            if self.balance > 0:
                corr_pct = (total_risk_usd / self.balance) * 100
                if corr_pct >= Config.MAX_CORRELATED_RISK_PCT:
                    return False, group_name + " " + str(round(corr_pct, 1)) + "%"
        return True, ""

    # ═══════════════════════════════════════════════════════
    # EXECUCAO AUTOMATICA DE SINAIS (sem confirmacao manual)
    # ═══════════════════════════════════════════════════════

    def execute_signal(self, pend: dict) -> bool:
        """
        Executa um sinal diretamente, sem confirmacao manual.
        Adiciona a lista de trades ativos para monitoramento automatico de WIN/LOSS.
        Retorna True se executado com sucesso.
        """
        from utils import (
            get_dynamic_leverage, get_dynamic_max_trades, get_max_risk_absolute,
            get_min_free_margin_pct, is_symbol_allowed, is_weekend_gap_risk,
        )

        sym = pend["symbol"]

        if is_weekend_gap_risk():
            log(f"[SIGNAL] {sym}: protecao de fim de semana ativa")
            return False

        max_trades = get_dynamic_max_trades(self.balance)
        if len(self.active_trades) >= max_trades:
            log(f"[SIGNAL] {sym}: limite de {max_trades} trades atingido")
            return False

        if not is_symbol_allowed(sym, self.balance):
            log(f"[SIGNAL] {sym}: ativo bloqueado para banca atual")
            return False

        est_risk = pend.get("suggested_risk_usd", 0)
        ok_corr, msg_corr = self.check_correlation_exposure(sym, est_risk)
        if not ok_corr:
            log(f"[SIGNAL] {sym}: correlacao — {msg_corr}")
            return False

        eff_lev = get_dynamic_leverage(self.balance)
        self._current_leverage = eff_lev

        max_risk_usd = get_max_risk_absolute(self.balance)
        if pend.get("suggested_risk_usd", 0) > max_risk_usd:
            log(f"[SIGNAL] {sym}: risco excede limite de ${round(max_risk_usd, 2)}")
            return False

        # Usa o lote sugerido pelo motor técnico para evitar plano com margem zerada.
        lot = float(pend.get("suggested_lot", Config.MIN_LOT) or Config.MIN_LOT)
        if lot < Config.MIN_LOT:
            lot = Config.MIN_LOT

        margin_required = calc_margin(sym, pend["entry"], eff_lev, lot)
        try:
            from risk import commission_for
            commission = commission_for(sym, lot)
        except Exception:
            commission = 0

        if margin_required <= 0:
            log(f"[SIGNAL] {sym}: margem calculada inválida")
            return False
        if margin_required > self.balance * 0.8:
            log(f"[SIGNAL] {sym}: margem excede 80% do saldo")
            return False

        used = self._get_used_margin()
        free_margin = self.balance - used - margin_required
        min_free_pct = get_min_free_margin_pct(self.balance)
        if free_margin < self.balance * min_free_pct:
            log(f"[SIGNAL] {sym}: margem livre insuficiente")
            return False

        ok, msg = self._check_margin_safety(margin_required)
        if not ok:
            log(f"[SIGNAL] {sym}: {msg}")
            return False

        # ── Spread + Slippage (simulação realista de execução) ────────────────
        entry_simulated = pend["entry"]
        if Config.USE_SPREAD_MODEL or Config.USE_SLIPPAGE_MODEL:
            import random
            pf = 0.01 if is_jpy_pair(sym) or sym == "XAUUSD" else 0.0001
            spread_cost = 0.0
            slip_cost   = 0.0
            if Config.USE_SPREAD_MODEL:
                spread_pips = Config.SPREAD_PIPS.get(sym, 1.0)
                spread_cost = spread_pips * pf
            if Config.USE_SLIPPAGE_MODEL:
                slip_pips = Config.SLIPPAGE_PIPS.get(sym, 0.3)
                # Slippage aleatório entre 0 e slip_pips (sempre contra a posição)
                slip_cost = random.uniform(0, slip_pips) * pf
            total_cost = spread_cost + slip_cost
            # Para BUY: entrada efetiva é maior; para SELL: menor
            if pend.get("dir") == "BUY":
                entry_simulated = round(pend["entry"] + total_cost, 5)
            else:
                entry_simulated = round(pend["entry"] - total_cost, 5)

        trade = {
            **pend,
            "entry":              entry_simulated,
            "lot":                round(lot, 2),
            "margin_required":    round(margin_required, 2),
            "commission":         round(commission, 2),
            "opened_at":          pend["created_at"],
            "wallet_before":      self.balance,
            "trailing_activated": False,
            "effective_leverage": eff_lev,
            "ai_approved":        pend.get("ai_approved", True),
            "ai_confidence":      pend.get("ai_confidence", 0),
        }
        self.balance -= margin_required
        self.active_trades.append(trade)

        self.send_signal_notification(trade)
        save_state(self)
        return True

    def send_signal_notification(self, trade: dict):
        """Envia notificacao de sinal ativo — automatico, sem confirmacao."""
        try:
            desk = getattr(self, "telegram_desk", None)
            if desk:
                desk.push_signal(trade, self)
                return
        except Exception as e:
            log(f"[TELEGRAM] Desk sinal falhou: {e}")

        checks_lines = []
        for c in trade.get("checks", []):
            icon = "✅" if c["ok"] else "❌"
            checks_lines.append(icon + " " + c["name"])
        checks_str = chr(10).join(checks_lines)

        kz        = trade.get("kill_zone")
        bias      = trade.get("daily_bias", "NEUTRO")
        ote       = trade.get("ote_active", False)
        kz_str    = f"⚡ Kill Zone: {kz}" if kz else "💤 Fora da Kill Zone"
        bias_str  = f"📅 Daily Bias: {bias}"
        ote_str   = "🎯 OTE: ✅ Retrace ideal (62–79%)" if ote else "🎯 OTE: ⬜ Fora da zona"

        direction = trade.get("dir", "—")
        sl_pips   = trade.get("sl_pips", "—")
        tp_pips   = trade.get("tp_pips", "—")
        sl_dir    = "−" if direction == "BUY" else "+"
        tp_dir    = "+" if direction == "BUY" else "−"

        ai_conf   = trade.get("ai_confidence", 0)
        ai_reason = trade.get("ai_reason", "—")
        regime    = trade.get("market_regime", "neutral").upper()
        setup     = trade.get("setup_type", "—").upper()
        conf_bar  = "🟩" * ai_conf + "⬜" * (10 - ai_conf)

        lines = [
            "🎯 NOVO SINAL — " + trade["symbol"] + " (" + trade["name"] + ")",
            "——————————————————",
            "📌 Direção: " + direction,
            "📍 Entrada:  " + fmt(trade["entry"]),
            "🛑 SL:       " + fmt(trade["sl"]) + "  (" + sl_dir + str(sl_pips) + " pips)",
            "🎯 TP:       " + fmt(trade["tp"]) + "  (" + tp_dir + str(tp_pips) + " pips)",
            "📊 RR: 1:" + str(trade["rr"]) + " | Score: " + str(trade["score"]) + "/" + str(trade["max_score"]),
            "🔄 Regime: " + regime + " | Setup: " + setup,
            "——————————————————",
            kz_str,
            bias_str,
            ote_str,
            "🤖 IA: " + conf_bar + " " + str(ai_conf) + "/10",
            "   " + ai_reason,
            "——————————————————",
            "💸 Risco: $" + str(round(trade.get("suggested_risk_usd", 0), 2))
                + " (" + str(round(trade.get("suggested_risk_pct", 0), 1)) + "%)",
            "📦 Lote: " + str(trade.get("lot", "—")),
            "——————————————————",
            checks_str,
            "——————————————————",
            "🔔 Monitorando SL/TP automaticamente...",
        ]
        self.send(chr(10).join(lines))

    # ═══════════════════════════════════════════════════════
    # COMPATIBILIDADE LEGADA
    # ═══════════════════════════════════════════════════════

    def add_pending(self, pend):
        """Legado — redireciona para execute_signal."""
        self.execute_signal(pend)

    def expire_pending_signals(self, max_age_seconds: int = 7200):
        """Legado — limpa pending_trades do state.json antigo."""
        now = time.time()
        expired = [p for p in self.pending_trades if now - p.get("created_ts", now) > max_age_seconds]
        for p in expired:
            self.pending_trades.remove(p)
        if expired:
            save_state(self)

    # ═══════════════════════════════════════════════════════
    # MONITORAMENTO E FECHAMENTO (WIN/LOSS)
    # ═══════════════════════════════════════════════════════

    def monitor_trades(self):
        for t in self.active_trades[:]:
            try:
                from analysis import get_analysis
                res = get_analysis(t["symbol"], self.timeframe)
                if not res:
                    continue
                cur = res["price"]
                atr = res["atr"]
                sl  = t["sl"]
                tp  = t["tp"]
                entry     = t["entry"]
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
        lot    = trade["lot"]
        entry  = trade["entry"]
        symbol = trade["symbol"]
        cs     = contract_size_for(symbol)

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

        # Salva no histórico — usado pelo aprendizado da IA
        self.history.append({
            "symbol":        symbol,
            "dir":           trade["dir"],
            "result":        result,
            "pnl":           round(profit, 2),
            "closed_at":     datetime.now().strftime("%d/%m %H:%M"),
            "opened_at":     trade.get("opened_at", ""),
            "adx":           trade.get("adx", 0),
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

        total   = self.wins + self.losses
        new_wr  = round(self.wins / total * 100, 1) if total > 0 else 0

        pip_factor = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
        pips = round((exit_price - entry) / pip_factor if trade["dir"] == "BUY"
                     else (entry - exit_price) / pip_factor, 1)

        duration_str = "—"
        try:
            opened_str = trade.get("opened_at", "")
            if opened_str:
                opened_dt = datetime.strptime(opened_str, "%d/%m %H:%M").replace(year=datetime.now().year)
                delta     = datetime.now() - opened_dt
                h, m      = divmod(int(delta.total_seconds() // 60), 60)
                duration_str = f"{h}h {m}min" if h > 0 else f"{m}min"
        except Exception:
            pass

        pnl_sign  = "+" if profit >= 0 else ""
        pips_sign = "+" if pips >= 0 else ""
        emoji     = "✅" if result == "WIN" else "❌"
        wr_emoji  = "📈" if new_wr >= 55 else "📊"

        # Feedback IA vs resultado — alimenta aprendizado visual
        ai_conf = trade.get("ai_confidence", 0)
        ai_feedback = ""
        if ai_conf > 0:
            if result == "WIN" and ai_conf >= 7:
                ai_feedback = f"\n🤖 IA acertou (confiança {ai_conf}/10 ✅)"
            elif result == "LOSS" and ai_conf >= 7:
                ai_feedback = f"\n🤖 IA confiou e perdeu ({ai_conf}/10 ❌)"
            elif result == "WIN" and ai_conf < 5:
                ai_feedback = f"\n🤖 IA subestimou ({ai_conf}/10 → WIN ✅)"
            elif result == "LOSS" and ai_conf <= 4:
                ai_feedback = f"\n🤖 IA desconfiou e perdeu ({ai_conf}/10 ❌)"

        try:
            desk = getattr(self, "telegram_desk", None)
            if desk:
                desk.push_result(trade, self, result)
            else:
                msg = "\n".join([
                    f"{emoji} RESULTADO — {symbol} {trade['dir']}",
                    "——————————————————",
                    f"📍 Entrada: {fmt(entry)} → Saída: {fmt(exit_price)}",
                    f"💰 P&L: {pnl_sign}${round(profit, 2)} ({pips_sign}{pips} pips)",
                    f"⏱ Duração: {duration_str}",
                    f"💼 Lote: {lot} | Margem liberada: ${round(margin, 2)}",
                    "——————————————————",
                    f"🏦 Saldo: ${round(self.balance, 2)}",
                    f"{wr_emoji} Win Rate: {new_wr}% ({self.wins}W / {self.losses}L){ai_feedback}",
                ])
                self.send(msg)
        except Exception as e:
            log(f"[TELEGRAM] Desk resultado falhou: {e}")
            msg = "\n".join([
                f"{emoji} RESULTADO — {symbol} {trade['dir']}",
                "——————————————————",
                f"📍 Entrada: {fmt(entry)} → Saída: {fmt(exit_price)}",
                f"💰 P&L: {pnl_sign}${round(profit, 2)} ({pips_sign}{pips} pips)",
                f"⏱ Duração: {duration_str}",
                f"💼 Lote: {lot} | Margem liberada: ${round(margin, 2)}",
                "——————————————————",
                f"🏦 Saldo: ${round(self.balance, 2)}",
                f"{wr_emoji} Win Rate: {new_wr}% ({self.wins}W / {self.losses}L){ai_feedback}",
            ])
            self.send(msg)
        save_state(self)

    # ═══════════════════════════════════════════════════════
    # ENVIO
    # ═══════════════════════════════════════════════════════

    def send(self, text):
        url = "https://api.telegram.org/bot" + Config.BOT_TOKEN + "/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "disable_web_page_preview": True}
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log("[SEND] Erro: " + str(e))
        self.send_push(text)

    def send_html(self, text, reply_markup=None):
        url = "https://api.telegram.org/bot" + Config.BOT_TOKEN + "/sendMessage"
        payload = {
            "chat_id": Config.CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log("[SEND_HTML] Erro: " + str(e))
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

    def get_current_leverage(self):
        from utils import get_dynamic_leverage
        if Config.USE_DYNAMIC_LEVERAGE:
            return get_dynamic_leverage(self.balance)
        return self.leverage
