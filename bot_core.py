# bot_core.py
import time, threading, requests, json, re
from datetime import datetime
from config import Config
from utils import fmt, log
from db import save_state, load_state, account_snapshot
from analysis import get_analysis, detect_reversal
from risk import calc_trade_plan, commission_for, get_sl_tp_pct
from broker import mt5_send_order
from signals import scan, scan_reversal_forex, check_correlation
from utils import all_syms, mkt_open

_push_subscriptions = []

def send_push(title, body, icon="/icon-192.png"):
    try:
        from pywebpush import webpush, WebPushException
        priv_key = os.getenv("VAPID_PRIVATE_KEY", ""); pub_key = os.getenv("VAPID_PUBLIC_KEY", "")
        email = os.getenv("VAPID_EMAIL", "mailto:admin@sniperbot.app")
        if not priv_key or not pub_key: return
        data = json.dumps({"title": title, "body": body, "icon": icon})
        dead = []
        for sub in _push_subscriptions:
            try:
                webpush(subscription_info=sub, data=data, vapid_private_key=priv_key,
                        vapid_claims={"sub": email, "aud": sub["endpoint"].split("/")[0]+"//"+sub["endpoint"].split("/")[2]})
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e): dead.append(sub)
            except Exception as e: log(f"[PUSH] {e}")
        for d in dead: _push_subscriptions.remove(d)
    except ImportError: pass
    except Exception as e: log(f"[PUSH] {e}")

class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO"; self.timeframe = Config.TIMEFRAME
        self.wins = 0; self.losses = 0; self.consecutive_losses = 0
        self.paused_until = 0; self.active_trades = []; self.pending_trades = []
        self.pending_counter = 0; self.last_pending_id = 0
        self.radar_list = {}; self.gatilho_list = {}
        self.reversal_list = {}; self.asset_cooldown = {}; self.history = []
        self.last_id = 0; self.last_news_ts = 0; self._restore_msg = None
        self.trend_cache = {}; self.last_trends_update = 0
        self.signals_feed = []; self.news_cache = []; self.news_cache_ts = 0
        self.balance = Config.INITIAL_BALANCE
        self.leverage = Config.DEFAULT_LEVERAGE
        self.risk_pct = Config.RISK_PERCENT_PER_TRADE
        self.account_currency = Config.BASE_CURRENCY
        self.account_type = Config.ACCOUNT_TYPE
        self.platform = Config.BROKER_PLATFORM
        self.margin_call_level = Config.MARGIN_CALL_LEVEL
        self.stop_out_level = Config.STOP_OUT_LEVEL
        self.awaiting_custom_amount = None

    def send(self, text, markup=None, disable_preview=False):
        clean = re.sub(r"<[^>]+>", " ", text).strip()
        tipo = push_title = push_body = None
        if "RADAR" in text: tipo="radar"; push_title="⚠ RADAR"
        elif "GATILHO ATINGIDO" in text: tipo="gatilho"; push_title="🔔 GATILHO ATINGIDO!"
        elif "SINAL CONFIRMADO" in text: tipo="sinal"; push_title="🎯 SINAL CONFIRMADO!"
        elif "SINAL PENDENTE" in text: tipo="sinal"; push_title="🎯 SINAL PENDENTE!"
        elif "CONTRA-TENDÊNCIA" in text: tipo="ct"; push_title="⚡ Contra-Tendência!"
        elif "CONFLUÊNCIA INSUF" in text: tipo="insuf"
        elif "OPERAÇÃO ENCERRADA" in text: tipo="close"; push_title="🏁 Operação Encerrada"; push_body=clean[:80]
        elif "CIRCUIT BREAKER" in text: tipo="cb"; push_title="⛔ Circuit Breaker Ativado"
        if tipo:
            self.signals_feed.append({"tipo": tipo, "texto": clean[:300], "ts": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")})
            self.signals_feed = self.signals_feed[-50:]
            if push_title:
                body = push_body or clean[:100]
                threading.Thread(target=send_push, args=(push_title, body), daemon=True).start()
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": disable_preview}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[SEND] {e}")

    def send_pending_notification(self, t):
        dl = "COMPRAR (BUY) 🟢" if t["dir"] == "BUY" else "VENDER (SELL) 🔴"
        snap = account_snapshot(self)
        max_lev = max_leverage_for(t["symbol"])
        eff_lev = min(self.leverage, max_lev)
        sl_pct = t.get("sl_pct", get_sl_tp_pct(eff_lev)[0])
        tp_pct = t.get("tp_pct", get_sl_tp_pct(eff_lev)[1])
        rr_ratio = t.get("rr_ratio", Config.TP_SL_RATIO)
        rr_label = t.get("rr_label", f"Padrao 1:{Config.TP_SL_RATIO}")
        premium_reasons = t.get("premium_reasons", [])
        premium_score   = t.get("premium_score", 0)
        if rr_ratio > Config.TP_SL_RATIO:
            rr_line = (
                f"RR AMPLIADO: <b>{rr_label}</b> ({premium_score} cond. premium)\n"
                + "\n".join(f"   ✨ {r}" for r in premium_reasons)
            )
        else:
            rr_line = f"RR padrao 1:{Config.TP_SL_RATIO} (mercado nao atingiu condicoes premium)"
        comm_info = ""
        if asset_cat(t["symbol"]) in ("FOREX", "COMMODITIES"):
            comm_info = f"\n💳 Comissao RT estimada: <code>${commission_for(t['symbol'], Config.MIN_LOT):.2f}</code>/lote (Raw ECN)"
        text = "\n".join([
            f"🎯 <b>SINAL PENDENTE – {t['symbol']}</b> ({t['name']}) [Tickmill MT5]",
            f"Conta: <b>{self.account_type}</b> {self.platform} | Moeda: <b>{self.account_currency}</b>",
            f"Alavancagem efetiva: <code>{eff_lev}x</code> (max. Tickmill: <code>{max_lev}x</code>)",
            f"SL/TP: <code>-{sl_pct}%</code> / <code>+{tp_pct}%</code>",
            rr_line,
            f"Escolha quanto deseja investir (margem em USD):{comm_info}",
            "",
            f"▶️ <b>{dl}</b>",
            "",
            f"💰 <b>Entrada:</b> <code>{fmt(t['entry'])}</code>",
            f"🛡 <b>SL:</b> <code>{fmt(t['sl'])}</code> ({-sl_pct}%)",
            f"🎯 <b>TP:</b> <code>{fmt(t['tp'])}</code> (+{tp_pct}%)",
            "",
            f"🏦 <b>Saldo:</b> <code>{fmt(snap['balance'])}</code> | <b>Equity:</b> <code>{fmt(snap['equity'])}</code>",
            f"📉 <b>Margem usada:</b> <code>{fmt(snap['used_margin'])}</code> | <b>Free margin:</b> <code>{fmt(snap['free_margin'])}</code>",
            f"📊 <b>Margin level:</b> <code>{snap['margin_level']:.1f}%</code>",
            "",
        ])
        if t.get("conf_txt"):
            text += f"\n<b>Confluencia: {t.get('sc','')}/{t.get('tot_c',t.get('tc',''))} [{t['bar']}]</b>\n{t['conf_txt']}"
        markup = {"inline_keyboard": [
            [{"text": "$50", "callback_data": f"amt_50_{t['pending_id']}"},
             {"text": "$100", "callback_data": f"amt_100_{t['pending_id']}"},
             {"text": "$250", "callback_data": f"amt_250_{t['pending_id']}"}],
            [{"text": "$500", "callback_data": f"amt_500_{t['pending_id']}"},
             {"text": "$1000", "callback_data": f"amt_1000_{t['pending_id']}"},
             {"text": "Custom", "callback_data": f"amtcustom_{t['pending_id']}"}],
            [{"text": "❌ Recusar", "callback_data": f"reject_{t['pending_id']}"}]
        ]}
        self.send(text, markup=markup)

    def _open_trade_with_plan(self, pending_trade, plan, source="telegram"):
        trade = {k: v for k, v in pending_trade.items() if k not in ("conf_txt", "sc", "tot_c", "tc", "bar", "ratio", "vol_txt", "sinais", "pending_id")}
        trade.update({
            "capital_base": plan["margin_usd"],
            "margin_required": plan["margin_required"],
            "lot": plan["lot"],
            "contract_size": plan["contract_size"],
            "base_ccy": Config.BASE_CURRENCY,
            "quote_ccy": Config.BASE_CURRENCY,
            "risk_pct": plan["risk_pct_of_balance"],
            "risk_money": plan["risk_money"],
            "tp_gain": plan["potential_profit"],
            "leverage": plan["leverage"],
            "commission": plan["commission"],
            "sl_pct": plan["sl_pct"],
            "tp_pct": plan["tp_pct"],
            "source": source,
        })
        self.balance -= plan["margin_required"]
        self.balance = round(self.balance, 2)
        self.active_trades.append(trade)
        save_state(self)
        return trade

    def execute_pending_with_amount(self, pending_id, amount, source="dashboard"):
        for t in self.pending_trades[:]:
            if t.get("pending_id") != pending_id:
                continue
            if check_correlation(self, t["symbol"]):
                self.send(f"⚠️ <b>ALERTA DE CORRELAÇÃO – {t['symbol']}</b>\nVocê já possui trade aberto em ativo correlacionado. Operação cancelada.")
                return False
            plan = calc_trade_plan(t["symbol"], t["entry"], self.leverage, self.balance, self.risk_pct, amount)
            if not plan.get("ok"):
                self.send(f"❌ <b>Não foi possível abrir {t['symbol']}</b>\n{plan.get('error','Erro desconhecido')}")
                return False
            self.pending_trades.remove(t)
            opened = self._open_trade_with_plan(t, plan, source=source)
            if not opened:
                save_state(self)
                return False
            dl = "BUY 🟢" if opened["dir"] == "BUY" else "SELL 🔴"
            self.send(
                f"✅ <b>TRADE ABERTO – {opened['symbol']}</b> [Tickmill MT5]\n"
                f"{dl} | Entrada: <code>{fmt(opened['entry'])}</code>\n"
                f"💵 Margem alocada: <code>${plan['margin_required']:.2f}</code> | Alav.: <code>{int(plan['leverage'])}x</code>\n"
                f"📦 Lote: <code>{plan['lot']:.2f}</code> | Comissão: <code>${plan['commission']:.2f}</code>\n"
                f"🛡 SL: <code>{fmt(opened['sl'])}</code> ({-plan['sl_pct']}%) | 🎯 TP: <code>{fmt(opened['tp'])}</code> (+{plan['tp_pct']}%)\n"
                f"📉 Risco: <code>${plan['risk_money']:.2f}</code> ({plan['risk_pct_of_balance']:.2f}% do saldo)\n"
                f"📈 Potencial: <code>${plan['potential_profit']:.2f}</code>\n"
                f"🏦 Saldo após reservar margem: <code>{fmt(self.balance)}</code>"
            )
            ok, msg = mt5_send_order(opened["symbol"], opened["dir"], plan["lot"], opened["sl"], opened["tp"])
            if ok:
                self.send(f"✅ <b>ORDEM ENVIADA AO MT5</b>\n{msg}")
            else:
                self.active_trades.remove(opened)
                self.balance += plan["margin_required"]
                self.send(f"⚠️ <b>FALHA NO MT5:</b> {msg}\nTrade revertido.")
            save_state(self)
            return True
        return False

    def request_custom_amount(self, pending_id):
        self.awaiting_custom_amount = pending_id
        self.send(
            f"💬 <b>Valor custom solicitado</b>\n\nEnvie agora o valor em dólares que deseja investir (margem).\n"
            f"Exemplo: <code>500</code>\n\nVocê pode cancelar enviando <code>cancelar</code>."
        )

    def confirm_pending(self, pending_id, amount=None):
        if amount is None:
            amount = max(100.0, self.balance * 0.10)
        return self.execute_pending_with_amount(pending_id, amount, source="dashboard")

    def reject_pending(self, pending_id):
        for t in self.pending_trades[:]:
            if t.get("pending_id") == pending_id:
                self.pending_trades.remove(t); save_state(self)
                self.send(f"❌ <b>TRADE RECUSADO – {t['symbol']}</b>\nSinal ignorado.")
                return True
        return False

    def build_menu(self):
        tfl = Config.TIMEFRAMES.get(self.timeframe, ("?", "  "))[0]
        ml  = Config.MARKET_CATEGORIES[self.mode]["label"] if self.mode != "TUDO" else "TUDO"
        markup = {"inline_keyboard": [
            [{"text": f"Mercado: {ml}", "callback_data": "ignore"}],
            [{"text": "FOREX", "callback_data": "set_FOREX"}, {"text": "CRIPTO", "callback_data": "set_CRYPTO"}],
            [{"text": "COMM.", "callback_data": "set_COMMODITIES"}, {"text": "INDICES", "callback_data": "set_INDICES"}],
            [{"text": "TUDO", "callback_data": "set_TUDO"}],
            [{"text": f"TF: {self.timeframe} {tfl}", "callback_data": "tf_menu"}],
            [{"text": "Status", "callback_data": "status"}, {"text": "Placar", "callback_data": "placar"}],
            [{"text": "Noticias", "callback_data": "news"}],
        ]}
        tot = self.wins + self.losses; wr = (self.wins/tot*100) if tot > 0 else 0
        cb = f"\n⛔ CB – retoma em {int((self.paused_until-time.time())/60)}min  " if self.is_paused() else "  "
        self.send(f"<b>BOT SNIPER v11.0 PRO</b>\n{self.wins}W / {self.losses}L ({wr:.1f}%)\nModo: {ml} | TF: {self.timeframe}{cb}", markup)

    def build_tf_menu(self):
        rows = [[{"text": f"{tf} {lb}{'✅' if tf==self.timeframe else ''}", "callback_data": f"set_tf_{tf}"}] for tf, (lb, _) in Config.TIMEFRAMES.items()]
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send("Selecione o Timeframe", {"inline_keyboard": rows})

    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES: return
        old = self.timeframe; self.timeframe = tf; save_state(self)
        self.send(f"✅ TF: {old} → {tf}")

    def set_mode(self, mode):
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return
        self.mode = mode; save_state(self); self.send(f"✅ Modo: {mode}")

    def set_balance(self, value):
        try: value = float(value)
        except: return False
        if value <= 0: return False
        self.balance = round(value, 2); save_state(self)
        self.send(f"🏦 <b>Saldo atualizado</b>\nNovo saldo: <code>{fmt(self.balance)}</code>")
        return True

    def set_leverage(self, value):
        try: value = int(value)
        except: return False
        if value < 1 or value > 1000: return False
        self.leverage = value; save_state(self)
        self.send(f"⚙️ <b>Alavancagem atualizada</b>\nNova alavancagem: <code>{self.leverage}x</code>")
        return True

    def send_news(self): self.send(build_news_msg(), disable_preview=True); self.last_news_ts = time.time()
    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL: self.send_news()

    def send_status(self):
        snap = account_snapshot(self)
        lines = [
            "<b>OPERAÇÕES ABERTAS</b>",
            f"🏦 Saldo: <code>{fmt(self.balance)}</code> | Equity: <code>{fmt(snap['equity'])}</code>",
            f"📉 Margem usada: <code>{fmt(snap['used_margin'])}</code> | Free: <code>{fmt(snap['free_margin'])}</code>",
            f"📊 Margin Level: <code>{snap['margin_level']:.1f}%</code>",
            ""
        ]
        if not self.active_trades:
            lines.append("Nenhuma."); self.send("\n".join(lines)); return
        for t in self.active_trades:
            res = get_analysis(t["symbol"], self.timeframe)
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            lot = float(t.get("lot", Config.MIN_LOT))
            cs = float(t.get("contract_size", contract_size_for(t["symbol"])))
            if t["dir"] == "BUY":
                pnl_money = (cur - t["entry"]) * cs * lot - t.get("commission", 0)
            else:
                pnl_money = (t["entry"] - cur) * cs * lot - t.get("commission", 0)
            lines.append(f"{'🟢' if pnl>=0 else '🔴'} {t['symbol']} {t['dir']} | P&L: {pnl:+.2f}% | ${pnl_money:+.2f}")
        self.send("\n".join(lines))

    def send_placar(self):
        tot = self.wins + self.losses
        wr = (self.wins/tot*100) if tot > 0 else 0
        self.send(f"📊 <b>PLACAR</b>\n{self.wins}W / {self.losses}L\nWin Rate: {wr:.1f}%")

    def is_paused(self):
        return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0; self.consecutive_losses = 0; save_state(self)
        self.send("✅ Circuit Breaker resetado.")

    def update_trends_cache(self):
        if time.time() - self.last_trends_update < Config.TRENDS_INTERVAL: return
        log("📡 Atualizando cache tendências...")
        for s in all_syms():
            try:
                res = get_analysis(s, self.timeframe)
                if res:
                    rev = detect_reversal(res)
                    self.trend_cache[s] = {
                        "data": res,
                        "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]},
                        "ts": time.time(),
                    }
            except Exception as e: log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = time.time()

    def monitor_trades(self):
        changed = False
        now_ts = time.time()
        for t in self.pending_trades[:]:
            created_at = t.get("created_at", now_ts)
            if now_ts - created_at > 900:
                self.pending_trades.remove(t)
                self.send(f"⏳ <b>SINAL EXPIRADO – {t['symbol']}</b>\nO sinal não foi respondido em 15 minutos.")
                changed = True
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]; atr = res["atr"]
            # Trailing stop baseado em ATR
            if t["dir"] == "BUY":
                new_sl = cur - Config.ATR_MULT_TRAIL * atr
                if new_sl > t["sl"]:
                    t["sl"] = new_sl; changed = True
            else:
                new_sl = cur + Config.ATR_MULT_TRAIL * atr
                if new_sl < t["sl"]:
                    t["sl"] = new_sl; changed = True
            if not t.get("session_alerted", True):
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                self.send(
                    f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\n"
                    f"Ação: <b>{dl}</b> | Aberto: {t.get('opened_at','?')}\n"
                    f"Entrada: <code>{fmt(t['entry'])}</code> | Atual: <code>{fmt(cur)}</code>\n"
                    f"🎯 TP: <code>{fmt(t['tp'])}</code> | 🛡 SL: <code>{fmt(t['sl'])}</code>"
                )
                t["session_alerted"] = True; changed = True
            is_win = (t["dir"] == "BUY" and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY" and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])
            if is_win or is_loss:
                lot = float(t.get("lot", Config.MIN_LOT))
                cs = float(t.get("contract_size", contract_size_for(t["symbol"])))
                if t["dir"] == "BUY":
                    raw_pnl = (cur - t["entry"]) * cs * lot
                else:
                    raw_pnl = (t["entry"] - cur) * cs * lot
                comm = t.get("commission", commission_for(t["symbol"], lot))
                pnl_money_net = round(raw_pnl - comm, 2)
                margin_required = float(t.get("margin_required", 0))
                self.balance = round(self.balance + margin_required + pnl_money_net, 2)
                st = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                closed_at = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")
                pnl_pct = round(pnl_money_net / margin_required * 100, 2) if margin_required else 0
                if is_win:
                    self.wins += 1; self.consecutive_losses = 0
                else:
                    self.losses += 1; self.consecutive_losses += 1
                    self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({
                    "symbol": t["symbol"], "dir": t["dir"], "result": "WIN" if is_win else "LOSS",
                    "pnl": pnl_pct, "pnl_money": pnl_money_net, "commission": round(comm, 2),
                    "closed_at": closed_at, "lot": lot, "margin_required": round(margin_required, 2)
                })
                self.send("\n".join([
                    "🏁 <b>OPERAÇÃO ENCERRADA</b> [Tickmill MT5]",
                    f"Ativo: <b>{t['symbol']}</b> ({t.get('name','')}) | {t['dir']}",
                    f"Resultado: <b>{st}</b>", "",
                    f"💰 Entrada: <code>{fmt(t['entry'])}</code>",
                    f"🔚 Saída: <code>{fmt(cur)}</code>",
                    f"P&L: <code>{pnl_pct:+.2f}%</code> | <b>${pnl_money_net:+.2f}</b>",
                    f"🏦 Saldo atual: <code>{fmt(self.balance)}</code>",
                ]))
                self.active_trades.remove(t); changed = True
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    self.send("\n".join([
                        "⛔ <b>CIRCUIT BREAKER ATIVADO</b>", "",
                        f"{self.consecutive_losses} losses consecutivos.",
                        f"Pausado por <b>{mins} minutos</b>.", "",
                        "Use /resetpausa para retomar.",
                    ]))
        if changed: save_state(self)

# Funções auxiliares que o bot precisa
def build_news_msg():
    from news import get_news, get_fear_greed  # será criado depois
    arts = get_news(5); fg = get_fear_greed()
    lines = ["📰 NOTÍCIAS\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "  ")
        lines.append(f"{i}. <a href='{a['url']}'>{t} ({a['source']})")
    lines.append(f"\n😱 F&G: {fg['value']} – {fg['label']}")
    return "\n".join(lines)
