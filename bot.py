
import time
import threading
import requests
from datetime import datetime, timezone
from config import Config
from utils import (
    log, fmt, is_jpy_pair, pip_factor, calc_pnl_usd, calc_pnl_pips,
    get_dynamic_leverage, get_dynamic_max_trades, get_max_risk_absolute,
    get_min_free_margin_pct, is_symbol_allowed, is_weekend_gap_risk,
    get_allowed_symbols, get_dynamic_cooldown,
)
from risk import calc_trade_plan, contract_size_for, calc_margin
from db import save_state


class TradingBot:
    def __init__(self):
        self.mode                = Config.MODE
        self.timeframe           = Config.TIMEFRAME
        self.leverage            = Config.DEFAULT_LEVERAGE
        self.balance             = Config.INITIAL_BALANCE
        self.wins                = 0
        self.losses              = 0
        self.consecutive_losses  = 0
        self.paused_until        = 0.0
        self.active_trades       = []
        self.pending_trades      = []
        self.history             = []
        self.asset_cooldown      = {}
        self.signals_feed        = []
        self.last_id             = 0
        self.pending_counter     = 0
        self._usdjpy_price       = 0.0
        self._current_leverage   = Config.DEFAULT_LEVERAGE
        # Lock para proteger o estado em opera\u00e7\u00f5es concorrentes
        # (loop principal + endpoints Flask acessam as mesmas estruturas)
        self._lock               = threading.RLock()

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # HELPERS DE ESTADO
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    def next_pending_id(self) -> int:
        with self._lock:
            self.pending_counter += 1
            return self.pending_counter

    def is_paused(self) -> bool:
        return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0
        self.consecutive_losses = 0

    def _get_used_margin(self) -> float:
        return sum(t.get("margin_required", 0) for t in self.active_trades)

    def _check_margin_safety(self, additional_margin: float) -> tuple[bool, str]:
        used = self._get_used_margin()
        total_required = used + additional_margin
        free_margin = self.balance - total_required
        if free_margin < 0:
            return False, f"Margem insuficiente. Necess\u00e1rio: ${round(total_required, 2)}"
        if total_required > 0:
            margin_level = (self.balance / total_required) * 100
            if margin_level < Config.STOP_OUT_PCT:
                return False, f"Stop out iminente (n\u00edvel {round(margin_level, 1)}%)"
            if margin_level < Config.MARGIN_CALL_PCT:
                log(f"[AVISO] Margin call pr\u00f3ximo (n\u00edvel {round(margin_level, 1)}%)")
        return True, ""

    def _update_usdjpy(self):
        """Atualiza cota\u00e7\u00e3o USDJPY para convers\u00e3o de P&L em pares JPY."""
        try:
            from analysis import get_analysis
            res = get_analysis("USDJPY", self.timeframe)
            if res:
                self._usdjpy_price = res["price"]
        except Exception as e:
            log(f"[USDJPY] Erro ao atualizar: {e}")

    def check_correlation_exposure(
        self, symbol: str, additional_risk_usd: float = 0.0
    ) -> tuple[bool, str]:
        """Verifica se o novo trade n\u00e3o estoura MAX_CORRELATED_RISK_PCT no grupo."""
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
                        # converte risco JPY \u2192 USD aproximado
                        usdjpy = self._usdjpy_price or 150.0
                        risk = risk / usdjpy
                    total_risk_usd += risk
            total_risk_usd += additional_risk_usd
            if self.balance > 0:
                corr_pct = (total_risk_usd / self.balance) * 100
                if corr_pct >= Config.MAX_CORRELATED_RISK_PCT:
                    return False, f"{group_name} {round(corr_pct, 1)}%"
        return True, ""

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # PENDING / EXECU\u00c7\u00c3O
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    def add_pending(self, pend: dict):
        with self._lock:
            self.pending_trades.append(pend)
            self.send_pending_notification(pend)
            save_state(self)

    def execute_pending(self, pending_id: int, margin_usd: float) -> tuple[bool, str]:
        with self._lock:
            if is_weekend_gap_risk():
                return False, "Prote\u00e7\u00e3o de fim de semana ativa"

            max_trades = get_dynamic_max_trades(self.balance)
            if len(self.active_trades) >= max_trades:
                return False, f"Limite de {max_trades} trade(s) ativo(s) para banca atual"

            pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
            if not pend:
                return False, "Sinal n\u00e3o encontrado"

            if not is_symbol_allowed(pend["symbol"], self.balance):
                allowed = get_allowed_symbols(self.balance)
                return False, (
                    f"{pend['symbol']} bloqueado para banca ${round(self.balance, 0)}. "
                    f"Permitidos: {', '.join(allowed)}"
                )

            est_risk = pend.get("suggested_risk_usd", 0)
            ok_corr, msg_corr = self.check_correlation_exposure(pend["symbol"], est_risk)
            if not ok_corr:
                return False, f"Correla\u00e7\u00e3o: {msg_corr}"

            eff_lev = get_dynamic_leverage(self.balance)
            self._current_leverage = eff_lev

            max_risk_usd = get_max_risk_absolute(self.balance)
            if pend.get("suggested_risk_usd", 0) > max_risk_usd:
                return False, (
                    f"Risco ${round(pend['suggested_risk_usd'], 2)} excede limite de "
                    f"${round(max_risk_usd, 2)} para banca atual"
                )

            plan = calc_trade_plan(pend["symbol"], pend["entry"], eff_lev, self.balance, margin_usd)
            if not plan["ok"]:
                return False, plan["error"]
            if plan["margin_required"] > self.balance * 0.8:
                return False, "Margem excede 80% do saldo"

            used = self._get_used_margin()
            free_margin = self.balance - used - plan["margin_required"]
            min_free_pct = get_min_free_margin_pct(self.balance)
            if free_margin < self.balance * min_free_pct:
                return False, (
                    f"Margem livre insuficiente. Necess\u00e1rio: "
                    f"{round(min_free_pct * 100, 0)}% livre"
                )

            ok, msg = self._check_margin_safety(plan["margin_required"])
            if not ok:
                return False, msg

            # ISO timestamp para facilitar parse pela IA
            opened_ts_iso = datetime.now(timezone.utc).isoformat()

            trade = {
                **pend,
                "lot":                plan["lot"],
                "margin_required":    plan["margin_required"],
                "commission":         plan["commission"],
                "opened_at":          pend["created_at"],       # legado (dd/mm HH:MM)
                "opened_ts_iso":      opened_ts_iso,             # novo: ISO 8601
                "opened_ts":          time.time(),
                "wallet_before":      self.balance,
                "trailing_activated": False,
                "effective_leverage": eff_lev,
                "ai_approved":        pend.get("ai_approved", True),
                "ai_confidence":      pend.get("ai_confidence", 0),
            }
            self.balance -= plan["margin_required"]
            self.active_trades.append(trade)
            self.pending_trades.remove(pend)

            msg_lines = [
                f"\u2705 TRADE ABERTO \u2014 {pend['symbol']}",
                f"{pend['dir']} | Entrada: {fmt(pend['entry'])}",
                f"Lote: {round(plan['lot'], 2)} | Margem: ${round(plan['margin_required'], 2)} | Alav: {eff_lev}:1",
                f"SL: {fmt(pend['sl'])} | TP: {fmt(pend['tp'])}",
                f"Saldo restante: ${round(self.balance, 2)}",
            ]
            self.send("\
".join(msg_lines))

            save_state(self)
            return True, "Trade executado"

    def reject_pending(self, pending_id: int) -> bool:
        with self._lock:
            pend = next((p for p in self.pending_trades if p["pending_id"] == pending_id), None)
            if pend:
                self.pending_trades.remove(pend)
                save_state(self)
                return True
            return False

    def expire_pending_signals(self, max_age_seconds: int = 7200):
        """Remove sinais pendentes gerados h\u00e1 mais de max_age_seconds (padr\u00e3o: 2h)."""
        with self._lock:
            now = time.time()
            expired = [
                p for p in self.pending_trades
                if now - p.get("created_ts", now) > max_age_seconds
            ]
            for p in expired:
                self.pending_trades.remove(p)
                self.send(
                    f"\u23f1 Sinal expirado \u2014 {p['symbol']} {p['dir']}\
"
                    f"Gerado \u00e0s {p['created_at']} | Expirado ap\u00f3s {max_age_seconds // 60}min\
"
                    f"Entrada era: {fmt(p['entry'])}"
                )
                log(f"[EXPIRY] Sinal {p['pending_id']} ({p['symbol']}) expirado")
            if expired:
                save_state(self)

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # MONITOR DE TRADES (l\u00f3gica corrigida)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    def monitor_trades(self):
        """
        Verifica cada trade ativo.
        CORRIGIDO: fecha usando SL ou TP (pre\u00e7o da ordem), n\u00e3o o tick atual.
        Isso simula corretamente o que aconteceria no broker.
        """
        from analysis import get_analysis

        # Iteramos sobre uma c\u00f3pia pois podemos remover itens
        for t in list(self.active_trades):
            try:
                res = get_analysis(t["symbol"], self.timeframe)
                if not res:
                    continue

                cur = res["price"]
                atr = res.get("atr", 0) or 0
                direction = t["dir"]
                entry = t["entry"]
                tp = t["tp"]
                sl = t["sl"]

                # \u2500\u2500 TRAILING STOP \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                if (
                    Config.TRAILING_ACTIVATION > 0
                    and not t.get("trailing_activated", False)
                    and atr > 0
                ):
                    if direction == "BUY" and tp != entry:
                        progress = (cur - entry) / (tp - entry)
                    elif direction == "SELL" and entry != tp:
                        progress = (entry - cur) / (entry - tp)
                    else:
                        progress = 0
                    if progress >= Config.TRAILING_ACTIVATION:
                        t["trailing_activated"] = True

                if t.get("trailing_activated") and atr > 0:
                    if direction == "BUY":
                        new_sl = cur - Config.ATR_MULT_TRAIL * atr
                        if new_sl > t["sl"]:
                            t["sl"] = round(new_sl, 5)
                            sl = t["sl"]
                            self.send(f"\ud83d\udcc8 Trailing Stop {t['symbol']}: {fmt(new_sl)}")
                    else:
                        new_sl = cur + Config.ATR_MULT_TRAIL * atr
                        if new_sl < t["sl"]:
                            t["sl"] = round(new_sl, 5)
                            sl = t["sl"]
                            self.send(f"\ud83d\udcc9 Trailing Stop {t['symbol']}: {fmt(new_sl)}")

                # \u2500\u2500 FECHAMENTO POR SL/TP \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                # CR\u00cdTICO: fechamos no pre\u00e7o da ORDEM (sl ou tp),
                # n\u00e3o no tick atual \u2014 simula execu\u00e7\u00e3o real do broker.
                if direction == "BUY":
                    if cur >= tp:
                        self.close_trade(t, tp, "WIN")
                    elif cur <= sl:
                        self.close_trade(t, sl, "LOSS")
                else:  # SELL
                    if cur <= tp:
                        self.close_trade(t, tp, "WIN")
                    elif cur >= sl:
                        self.close_trade(t, sl, "LOSS")

            except Exception as e:
                log(f"[MONITOR] Erro em {t.get('symbol', '?')}: {e}")

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # FECHAMENTO DE TRADE (P&L unificado)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    def close_trade(self, trade: dict, exit_price: float, result: str):
    with self._lock:
        if trade not in self.active_trades:
            return  # já foi fechado

        symbol = trade["symbol"]
        margin = trade["margin_required"]
        lot = trade["lot"]
        entry = trade["entry"]
        commission = trade.get("commission", 0)
        direction = trade["dir"]

        if is_jpy_pair(symbol) and self._usdjpy_price <= 0:
            self._update_usdjpy()

        profit = calc_pnl_usd(
            symbol=symbol,
            direction=direction,
            entry=entry,
            exit_price=exit_price,
            lot=lot,
            usdjpy_price=self._usdjpy_price or 150.0,
            commission=commission,
        )

        self.balance += margin + profit
        self.balance = round(self.balance, 2)

        closed_at_iso = datetime.now(timezone.utc).isoformat()
        self.history.append({
            "symbol":        symbol,
            "dir":           direction,
            "result":        result,
            "pnl":           round(profit, 2),
            "closed_at":     datetime.now().strftime("%d/%m %H:%M"),
            "closed_ts_iso": closed_at_iso,
            "opened_at":     trade.get("opened_at", ""),
            "opened_ts_iso": trade.get("opened_ts_iso", ""),
            "adx":           trade.get("adx", 0),
            "ai_approved":   trade.get("ai_approved", True),
            "ai_confidence": trade.get("ai_confidence", 0),
            "entry":         entry,
            "exit":          exit_price,
            "lot":           lot,
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
                self.send(
                    f"⛔ CIRCUIT BREAKER — {Config.MAX_CONSECUTIVE_LOSSES} losses "
                    f"consecutivos. Pausa de {Config.PAUSE_DURATION // 60}min."
                )

        self.active_trades.remove(trade)

        total = self.wins + self.losses
        new_wr = round(self.wins / total * 100, 1) if total > 0 else 0

        pips = calc_pnl_pips(symbol, direction, entry, exit_price)

        duration_str = "—"
        try:
            opened_iso = trade.get("opened_ts_iso")
            if opened_iso:
                opened_dt = datetime.fromisoformat(opened_iso)
                delta = datetime.now(timezone.utc) - opened_dt
                total_min = int(delta.total_seconds() // 60)
                h, m = divmod(total_min, 60)
                duration_str = f"{h}h {m}min" if h > 0 else f"{m}min"
        except Exception:
            pass

        pnl_sign = "+" if profit >= 0 else ""
        pips_sign = "+" if pips >= 0 else ""
        emoji = "✅" if result == "WIN" else "❌"
        wr_emoji = "📈" if new_wr >= 55 else "📊"

        self.send(
            f"{emoji} TRADE FECHADO — {symbol} {direction}\n"
            f"────────────────────────────────\n"
            f"📍 Entrada: {fmt(entry)} → Saída: {fmt(exit_price)}\n"
            f"💰 P&L: {pnl_sign}${round(profit, 2)} ({pips_sign}{pips} pips)\n"
            f"⏱ Duração: {duration_str}\n"
            f"💼 Lote: {lot} | Margem liberada: ${round(margin, 2)}\n"
            f"────────────────────────────────\n"
            f"🏦 Saldo: ${round(self.balance, 2)}\n"
            f"{wr_emoji} Win Rate: {new_wr}% ({self.wins}W / {self.losses}L)"
        )
        save_state(self)


    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # COMUNICA\u00c7\u00c3O
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    def send(self, text: str):
        if not Config.BOT_TOKEN or not Config.CHAT_ID:
            log("[SEND] Token/chat_id n\u00e3o configurado \u2014 mensagem descartada")
            return
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text}
        try:
            requests.post(url, json=payload, timeout=5)
        except requests.RequestException as e:
            log(f"[SEND] Erro Telegram: {type(e).__name__}: {str(e)[:100]}")
        self.send_push(text)

    def send_push(self, text: str):
        if not Config.NTFY_TOPIC:
            return
        try:
            requests.post(
                f"https://ntfy.sh/{Config.NTFY_TOPIC}",
                data=text.encode("utf-8"),
                headers={"Title": "Sniper Bot Signal"},
                timeout=5,
            )
        except requests.RequestException as e:
            log(f"[PUSH] Erro: {type(e).__name__}: {str(e)[:100]}")

    def send_pending_notification(self, pend: dict):
        direc = pend["dir"]
        sl_pips = pend.get("sl_pips", "?")
        tp_pips = pend.get("tp_pips", "?")
        sl_dir = "\u2212" if direc == "BUY" else "+"
        tp_dir = "+" if direc == "BUY" else "\u2212"

        checks_lines = [
            f"{'\u2705' if c['ok'] else '\u274c'} {c['name']}"
            for c in pend["checks"]
        ]
        checks_str = "\
".join(checks_lines)

        lines = [
            f"\ud83c\udfaf SINAL PENDENTE \u2014 {pend['symbol']} ({pend['name']})",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            f"\ud83d\udccc Dire\u00e7\u00e3o: {direc}",
            f"\ud83d\udccd Entrada:  {fmt(pend['entry'])}",
            f"\ud83d\uded1 SL:       {fmt(pend['sl'])}  ({sl_dir}{sl_pips} pips)",
            f"\ud83c\udfaf TP:       {fmt(pend['tp'])}  ({tp_dir}{tp_pips} pips)",
            f"\ud83d\udcca RR: 1:{pend['rr']} | Score: {pend['score']}/{pend['max_score']}",
            f"\ud83e\udd16 IA: {pend.get('ai_reason', '\u2014')}",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            "\u26a0\ufe0f Se der erro de SL/TP inv\u00e1lido:",
            "   Pre\u00e7o mudou \u2014 use a dist\u00e2ncia em pips",
            "   como refer\u00eancia e ajuste no broker.",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            f"\ud83d\udcb0 Margem p/ 0.01 lote: ${round(pend['min_lot_margin'], 2)}",
            f"\ud83d\udcb8 Risco c/ lote m\u00ednimo: ${round(pend['risk_001_lot'], 2)} "
            f"({round(pend['risk_pct_001'], 1)}%)",
            f"\ud83d\udce6 Lote sugerido ({Config.ATR_RISK_PCT}% risco): "
            f"{pend['suggested_lot']} lote(s)",
            f"   \u2192 Risco real: ${round(pend['suggested_risk_usd'], 2)} "
            f"({round(pend['suggested_risk_pct'], 1)}%)",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            checks_str,
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            f"\u25b6\ufe0f Para executar: /executar_{pend['pending_id']}_VALOR",
        ]
        self.send("\
".join(lines))

    def get_current_leverage(self) -> int:
        if Config.USE_DYNAMIC_LEVERAGE:
            return get_dynamic_leverage(self.balance)
        return self.leverage
