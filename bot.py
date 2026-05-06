import time
import requests
from datetime import datetime
from config import Config
from utils import log, fmt, is_jpy_pair, jpy_to_usd, max_leverage
from risk import calc_trade_plan, contract_size_for, calc_margin
from db import save_state
from portfolio import init_accounts, ensure_accounts, choose_account, account_risk_pct, can_trade_account, reserve_margin, release_margin, portfolio_snapshot, portfolio_report_lines, total_equity

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
        self.signal_only = Config.BOT_IS_SIGNAL_ONLY
        self.signal_cooldown = {}
        self.accounts = init_accounts(self.balance)
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

    # ═══════════════════════════════════════════════════════
    # MULTI-CONTA / CAPITAL MANAGEMENT
    # ═══════════════════════════════════════════════════════

    def sync_accounts(self):
        self.accounts = ensure_accounts(getattr(self, "accounts", None), self.balance)
        return self.accounts

    def portfolio_snapshot(self):
        return portfolio_snapshot(self.sync_accounts())

    def portfolio_summary_lines(self):
        return portfolio_report_lines(self.sync_accounts())

    def choose_account_for_signal(self, pend: dict) -> str:
        return choose_account(pend, self.sync_accounts(), self.balance)

    def account_risk_pct(self, account_id: str, pend: dict | None = None) -> float:
        return account_risk_pct(account_id, self.sync_accounts(), self.balance, pend or {})

    def account_can_trade(self, account_id: str, margin_required: float) -> tuple[bool, str]:
        return can_trade_account(account_id, self.sync_accounts(), self.balance, margin_required)

    def account_reserve(self, account_id: str, margin_required: float):
        self.accounts = reserve_margin(account_id, self.sync_accounts(), margin_required)
        self.balance = round(total_equity(self.accounts), 2)
        return self.accounts

    def account_release(self, account_id: str, margin_required: float, pnl: float, result: str):
        self.accounts = release_margin(account_id, self.sync_accounts(), margin_required, pnl, result)
        self.balance = round(total_equity(self.accounts), 2)
        return self.accounts

    def global_drawdown_pct(self) -> float:
        snap = self.portfolio_snapshot()
        total_eq = snap.get("total_equity", self.balance)
        if not hasattr(self, "_equity_peak"):
            self._equity_peak = total_eq
        self._equity_peak = max(getattr(self, "_equity_peak", total_eq), total_eq)
        if self._equity_peak <= 0:
            return 0.0
        return round(max(0.0, (self._equity_peak - total_eq) / self._equity_peak * 100), 2)

    def protection_status(self) -> str:
        dd = self.global_drawdown_pct()
        if dd >= getattr(Config, "EQUITY_PROTECTION_DD_PCT", 12.0):
            return f"Equity DD {dd}% acima do limite"
        return "OK"

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
        """Limita excesso de sinais correlacionados sem depender de capital."""
        max_group = getattr(Config, "MAX_CORRELATED_SIGNALS_PER_GROUP", 2)
        for group_name, symbols in Config.CORRELATION_GROUPS.items():
            if symbol not in symbols:
                continue
            same_group_active = sum(1 for t in self.active_trades if t.get("symbol") in symbols)
            if same_group_active >= max_group:
                return False, f"{group_name} com {same_group_active} sinais ativos"
        return True, ""

    # ═══════════════════════════════════════════════════════
    # EXECUCAO AUTOMATICA DE SINAIS (sem confirmacao manual)
    # ═══════════════════════════════════════════════════════

    def execute_signal(self, pend: dict) -> bool:
        """
        Executa um sinal diretamente, sem confirmação manual.
        No modo signal-only, não reserva capital e não depende de margem.
        """
        from utils import is_weekend_gap_risk

        sym = pend["symbol"]
        direction = pend.get("dir", "—")

        if is_weekend_gap_risk():
            log(f"[SIGNAL] {sym}: protecao de fim de semana ativa")
            return False

        ok_corr, msg_corr = self.check_correlation_exposure(sym, pend.get("suggested_risk_usd", 0))
        if not ok_corr:
            log(f"[SIGNAL] {sym}: correlacao — {msg_corr}")
            return False

        lot = float(pend.get("suggested_lot", Config.MIN_LOT) or Config.MIN_LOT)
        if lot < Config.MIN_LOT:
            lot = Config.MIN_LOT

        # ── Spread + Slippage (execução simulada, sem relação com capital) ─────
        entry_simulated = pend["entry"]
        if Config.USE_SPREAD_MODEL or Config.USE_SLIPPAGE_MODEL:
            import random
            pf = 0.01 if is_jpy_pair(sym) or sym == "XAUUSD" else 0.0001
            spread_cost = 0.0
            slip_cost = 0.0
            if Config.USE_SPREAD_MODEL:
                spread_cost = random.uniform(Config.MIN_SPREAD_PIPS, Config.MAX_SPREAD_PIPS) * pf
            if Config.USE_SLIPPAGE_MODEL:
                slip_cost = random.uniform(0, Config.SLIPPAGE_MAX_PIPS) * pf
            if direction == "BUY":
                entry_simulated += (spread_cost / 2.0) + slip_cost
            else:
                entry_simulated -= (spread_cost / 2.0) + slip_cost
            pend["spread_cost"] = round(spread_cost / pf, 2) if pf > 0 else 0
            pend["slippage_cost"] = round(slip_cost / pf, 2) if pf > 0 else 0

        score = float(pend.get("score", 0) or 0)
        max_score = float(pend.get("max_score", 0) or 0)
        quality_10 = max(1, min(10, int(round((score / max_score) * 10)))) if max_score > 0 else 1

        trade = {
            **pend,
            "entry": entry_simulated,
            "lot": round(lot, 2),
            "margin_required": 0.0,
            "commission": 0.0,
            "opened_at": pend["created_at"],
            "wallet_before": 0.0,
            "trailing_activated": False,
            "effective_leverage": Config.DEFAULT_LEVERAGE,
            "ai_approved": pend.get("ai_approved", True),
            "ai_confidence": pend.get("ai_confidence", 0),
            "account_id": "signal_only",
            "account_name": "Signal Desk",
            "account_risk_pct": 0.0,
            "signal_only": True,
            "quality_10": quality_10,
        }

        # Cooldown do par/direção para evitar spam e melhorar a filtragem.
        cooldown = int(getattr(Config, "SIGNAL_COOLDOWN_SECONDS", Config.ASSET_COOLDOWN))
        self.asset_cooldown[sym] = time.time() + cooldown
        self.signal_cooldown[f"{sym}|{direction}"] = time.time() + cooldown

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

        kz = trade.get("kill_zone")
        bias = trade.get("daily_bias", "NEUTRO")
        ote = trade.get("ote_active", False)
        kz_str = f"⚡ Kill Zone: {kz}" if kz else "💤 Fora da Kill Zone"
        bias_str = f"📅 Daily Bias: {bias}"
        ote_str = "🎯 OTE: ✅ Retrace ideal (62–79%)" if ote else "🎯 OTE: ⬜ Fora da zona"

        direction = trade.get("dir", "—")
        sl_pips = trade.get("sl_pips", "—")
        tp_pips = trade.get("tp_pips", "—")
        sl_dir = "−" if direction == "BUY" else "+"
        tp_dir = "+" if direction == "BUY" else "−"

        ai_conf = trade.get("ai_confidence", 0)
        ai_reason = trade.get("ai_reason", "—")
        regime = trade.get("market_regime", "neutral").upper()
        setup = trade.get("setup_type", "—").upper()
        conf_bar = "🟩" * ai_conf + "⬜" * (10 - ai_conf)

        lines = [
            "🎯 NOVO SINAL — " + trade["symbol"] + " (" + trade["name"] + ")",
            "——————————————————",
            "📌 Direção: " + direction,
            "📍 Entrada:  " + fmt(trade["entry"]),
            "🛑 SL:       " + fmt(trade["sl"]) + "  (" + sl_dir + str(sl_pips) + " pips)",
            "🎯 TP:       " + fmt(trade["tp"]) + "  (" + tp_dir + str(tp_pips) + " pips)",
            "📊 RR: 1:" + str(trade["rr"]) + " | Score: " + str(trade["score"]) + "/" + str(trade["max_score"]),
            "🔄 Regime: " + regime + " | Setup: " + setup,
            "🧮 Qualidade: " + str(trade.get("quality_10", 1)) + "/10",
            "——————————————————",
            kz_str,
            bias_str,
            ote_str,
            "🤖 IA: " + conf_bar + " " + str(ai_conf) + "/10",
            "   " + ai_reason,
            "——————————————————",
            checks_str,
            "——————————————————",
            "🚦 Monitorando SL/TP automaticamente...",
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

    def _partial_close(self, trade: dict, cur_price: float):
        """Fecha 50% da posição no TP1 e move SL para breakeven com TP2 = 2× distância original."""
        entry     = trade["entry"]
        direction = trade["dir"]
        lot       = trade.get("lot", Config.MIN_LOT)
        symbol    = trade["symbol"]

        # Lote da saída parcial (50%)
        half_lot = max(Config.MIN_LOT, round(lot * 0.5, 2))

        # P&L do parcial
        cs = contract_size_for(symbol)
        if direction == "BUY":
            profit_raw = (cur_price - entry) * cs * half_lot
        else:
            profit_raw = (entry - cur_price) * cs * half_lot
        profit = jpy_to_usd(profit_raw, self._usdjpy_price) if is_jpy_pair(symbol) else profit_raw

        # Registra histórico do parcial
        self.history.append({
            "symbol": symbol, "dir": direction, "result": "WIN",
            "pnl": round(profit, 2), "partial": True,
            "closed_at": datetime.now().strftime("%d/%m %H:%M"),
            "opened_at": trade.get("opened_at", ""),
        })
        self.wins += 1
        self.consecutive_losses = 0

        # Atualiza o trade: reduz lote, move SL para breakeven, estende TP para TP2
        tp1 = trade["tp"]
        tp1_dist = abs(tp1 - entry)
        tp2 = round(entry + 2 * tp1_dist, 5) if direction == "BUY" else round(entry - 2 * tp1_dist, 5)

        trade["lot"]            = round(lot - half_lot, 2)
        trade["sl"]             = entry                  # breakeven
        trade["tp"]             = tp2                    # TP2 = 2× distância original
        trade["partial_closed"] = True
        trade["partial_pnl"]    = round(profit, 2)
        trade["tp1_hit"]        = round(cur_price, 5)

        pip_f = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
        pips  = round(abs(cur_price - entry) / pip_f, 1)

        msg = "\n".join([
            f"🔰 <b>SAÍDA PARCIAL — {symbol} {direction}</b>",
            f"<b>Fechado:</b> 50% do lote ({half_lot}) no TP1",
            f"<b>Preço:</b> {fmt(cur_price)} | <b>+{pips} pips</b>",
            f"<b>P&L parcial:</b> ${profit:+.2f}",
            f"<b>Restante:</b> {trade['lot']} lote(s)",
            f"<b>SL →</b> Breakeven ({fmt(entry)})",
            f"<b>TP2 →</b> {fmt(tp2)} (2× objetivo original)",
        ])
        self.send(msg)
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
                    hit_tp = cur >= tp
                    hit_sl = cur <= t["sl"]
                    if hit_tp and not t.get("partial_closed", False):
                        self._partial_close(t, cur)
                        continue
                    if hit_tp or hit_sl:
                        self.close_trade(t, cur, "WIN" if hit_tp else "LOSS")
                else:
                    hit_tp = cur <= tp
                    hit_sl = cur >= t["sl"]
                    if hit_tp and not t.get("partial_closed", False):
                        self._partial_close(t, cur)
                        continue
                    if hit_tp or hit_sl:
                        self.close_trade(t, cur, "WIN" if hit_tp else "LOSS")
            except Exception as e:
                log("Erro monitor: " + str(e))

    def close_trade(self, trade, exit_price, result):
        from utils import get_dynamic_cooldown

        lot = trade.get("lot", Config.MIN_LOT)
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

        # Histórico usado pelo relatório e aprendizado do bot.
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
            "score":         trade.get("score", 0),
            "score_total":   trade.get("max_score", 0),
            "quality_10":    trade.get("quality_10", 1),
        })

        if result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            cooldown = get_dynamic_cooldown(None)
            self.asset_cooldown[symbol] = time.time() + cooldown
            self.signal_cooldown[f"{symbol}|{trade['dir']}"] = time.time() + cooldown
            if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                self.paused_until = time.time() + Config.PAUSE_DURATION
                self.send("CIRCUIT BREAKER – 3 losses consecutivos. Pausa de 1h.")
        self.active_trades.remove(trade)

        total = self.wins + self.losses
        new_wr = round(self.wins / total * 100, 1) if total > 0 else 0

        pip_factor = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
        pips = round((exit_price - entry) / pip_factor if trade["dir"] == "BUY"
                     else (entry - exit_price) / pip_factor, 1)

        duration_str = "—"
        try:
            opened_str = trade.get("opened_at", "")
            if opened_str:
                opened_dt = datetime.strptime(opened_str, "%d/%m %H:%M").replace(year=datetime.now().year)
                delta = datetime.now() - opened_dt
                h, m = divmod(int(delta.total_seconds() // 60), 60)
                duration_str = f"{h}h {m}min" if h > 0 else f"{m}min"
        except Exception:
            pass

        emoji = "✅" if result == "WIN" else "❌"
        wr_emoji = "📈" if new_wr >= 55 else "📊"

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
                    f"📉 Resultado: {result} | {pips:+.1f} pips",
                    f"⏱ Duração: {duration_str}",
                    f"🏷 Qualidade: {trade.get('quality_10', 1)}/10",
                    f"{wr_emoji} Win Rate: {new_wr}% ({self.wins}W / {self.losses}L){ai_feedback}",
                ])
                self.send(msg)
        except Exception as e:
            log(f"[TELEGRAM] Desk resultado falhou: {e}")
            msg = "\n".join([
                f"{emoji} RESULTADO — {symbol} {trade['dir']}",
                "——————————————————",
                f"📍 Entrada: {fmt(entry)} → Saída: {fmt(exit_price)}",
                f"📉 Resultado: {result} | {pips:+.1f} pips",
                f"⏱ Duração: {duration_str}",
                f"🏷 Qualidade: {trade.get('quality_10', 1)}/10",
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
