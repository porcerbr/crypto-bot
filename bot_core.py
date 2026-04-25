# bot_core.py
import os, time, threading, requests, json, re, random
from datetime import datetime
from config import Config
from utils import fmt, log
from db import save_state, load_state, account_snapshot
from analysis import get_analysis, detect_reversal
from risk import calc_trade_plan, commission_for, get_sl_tp_pct, calc_lot_from_margin
from broker import mt5_send_order
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

# -------------------------------------------------------------------
# Funções internas (genética, hedge, inteligência)
# -------------------------------------------------------------------
GENOME_KEYS = [
    "MIN_CONFLUENCE", "ADX_MIN", "ATR_MULT_SL", "ATR_MULT_TP",
    "REVERSAL_MIN_SCORE", "RADAR_COOLDOWN", "GATILHO_COOLDOWN"
]

RANGES = {
    "MIN_CONFLUENCE": (3, 7),
    "ADX_MIN": (15, 35),
    "ATR_MULT_SL": (1.0, 2.5),
    "ATR_MULT_TP": (2.5, 5.0),
    "REVERSAL_MIN_SCORE": (4, 8),
    "RADAR_COOLDOWN": (600, 3600),
    "GATILHO_COOLDOWN": (120, 900),
}

def random_genome():
    return {
        k: (random.randint(*RANGES[k]) if isinstance(RANGES[k][0], int)
            else round(random.uniform(*RANGES[k]), 2))
        for k in GENOME_KEYS
    }

def crossover(g1, g2):
    child = {}
    for k in GENOME_KEYS:
        child[k] = g1[k] if random.random() < 0.5 else g2[k]
    if random.random() < 0.2:
        k = random.choice(GENOME_KEYS)
        child[k] = (random.randint(*RANGES[k]) if isinstance(RANGES[k][0], int)
                    else round(random.uniform(*RANGES[k]), 2))
    return child

def fitness(genome, history):
    if not history:
        return 0.0
    wins = sum(1 for h in history if h.get("result") == "WIN")
    total = len(history)
    wr = wins / total if total else 0.0
    avg_pnl = sum(h.get("pnl_money", 0.0) for h in history) / total
    return wr * 0.6 + avg_pnl / 100.0 * 0.4

def evolve(population, history):
    if not population:
        return [random_genome() for _ in range(10)]
    scored = sorted(
        [(g, fitness(g, history)) for g in population],
        key=lambda x: x[1], reverse=True
    )
    elites = [g for g, _ in scored[:3]]
    new_pop = elites.copy()
    while len(new_pop) < 10:
        p1, p2 = random.sample(elites, 2)
        new_pop.append(crossover(p1, p2))
    return new_pop

HEDGE_PAIRS = {
    "EURUSD": ["USDCHF", "USDCAD"],
    "GBPUSD": ["USDJPY"],
    "XAUUSD": ["XAGUSD", "USDCAD"],
    "BTCUSD": ["ETHUSD"],
}

def calc_hedge_score(active_trades):
    if len(active_trades) < 2:
        return None
    buy_syms = [t["symbol"] for t in active_trades if t["dir"] == "BUY"]
    sell_syms = [t["symbol"] for t in active_trades if t["dir"] == "SELL"]
    active_syms = [t["symbol"] for t in active_trades]
    if len(buy_syms) >= 2:
        for sym in buy_syms:
            if sym in HEDGE_PAIRS:
                for hedge_sym in HEDGE_PAIRS[sym]:
                    if hedge_sym not in active_syms:
                        return (hedge_sym, "SELL", sym)
    if len(sell_syms) >= 2:
        for sym in sell_syms:
            if sym in HEDGE_PAIRS:
                for hedge_sym in HEDGE_PAIRS[sym]:
                    if hedge_sym not in active_syms:
                        return (hedge_sym, "BUY", sym)
    return None

def get_whale_alerts():
    if not Config.WHALE_ALERT_API_KEY:
        return []
    try:
        url = f"https://api.whale-alert.io/v1/transactions?api_key={Config.WHALE_ALERT_API_KEY}&min_value=500000&limit=50"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            log(f"[WHALE] Erro API: {resp.status_code}")
            return []
        data = resp.json()
        whales = []
        for tx in data.get("transactions", []):
            symbol = tx.get("symbol", "")
            if not symbol:
                continue
            whales.append({
                "symbol": symbol,
                "amount_usd": tx.get("amount_usd", 0),
                "from_owner": tx.get("from", {}).get("owner_type", "unknown"),
                "to_owner": tx.get("to", {}).get("owner_type", "unknown"),
            })
        log(f"[WHALE] {len(whales)} alertas carregados")
        return whales
    except Exception as e:
        log(f"[WHALE] Erro: {e}")
        return []

def analyze_sentiment(texts):
    if not Config.HF_API_TOKEN or not texts:
        return 0, []
    try:
        headers = {"Authorization": f"Bearer {Config.HF_API_TOKEN}"}
        payload = {"inputs": texts}
        resp = requests.post(
            "https://api-inference.huggingface.co/models/ProsusAI/finbert",
            headers=headers, json=payload, timeout=10
        )
        if resp.status_code != 200:
            log(f"[SENTIMENT] Erro API: {resp.status_code}")
            return 0, []
        results = resp.json()
        scores, reasons = [], []
        for i, res in enumerate(results):
            if not res:
                continue
            pos = next((d["score"] for d in res if d["label"] == "positive"), 0)
            neg = next((d["score"] for d in res if d["label"] == "negative"), 0)
            s = pos - neg
            scores.append(s)
            if abs(s) > 0.5 and i < len(texts):
                reasons.append((texts[i][:100], round(s, 2)))
        avg = sum(scores) / len(scores) if scores else 0
        return avg, reasons[:3]
    except Exception as e:
        log(f"[SENTIMENT] Erro: {e}")
        return 0, []

# -------------------------------------------------------------------
# Classe do Bot (completa)
# -------------------------------------------------------------------
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
        # Inteligência de mercado
        self.intel_cache = {"whales": [], "sentiment_score": 0, "sentiment_reasons": [], "ts": 0}
        # Genética
        self.genomes = []
        self.best_genome = {}
        self.last_genetic_ts = 0
        if Config.GENETIC_ENABLED:
            self.genomes = [random_genome() for _ in range(Config.GENETIC_POPULATION)]
            self.best_genome = self.genomes[0]

    # ---------- Métodos auxiliares ----------
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
        eff_lev = min(self.leverage, max_leverage_for_sym(t["symbol"]))
        sl_pct = t.get("sl_pct", get_sl_tp_pct(eff_lev)[0])
        tp_pct = t.get("tp_pct", get_sl_tp_pct(eff_lev)[1])
        rr_ratio = t.get("rr_ratio", Config.TP_SL_RATIO)
        rr_label = t.get("rr_label", f"Padrao 1:{Config.TP_SL_RATIO}")
        premium_reasons = t.get("premium_reasons", [])
        premium_score   = t.get("premium_score", 0)
        if rr_ratio > Config.TP_SL_RATIO:
            rr_line = (f"RR AMPLIADO: <b>{rr_label}</b> ({premium_score} cond. premium)\n" +
                       "\n".join(f"   ✨ {r}" for r in premium_reasons))
        else:
            rr_line = f"RR padrao 1:{Config.TP_SL_RATIO} (mercado nao atingiu condicoes premium)"
        comm_info = ""
        if asset_cat(t["symbol"]) in ("FOREX", "COMMODITIES"):
            comm_info = f"\n💳 Comissao RT estimada: <code>${commission_for(t['symbol'], Config.MIN_LOT):.2f}</code>/lote (Raw ECN)"
        text = "\n".join([
            f"🎯 <b>SINAL PENDENTE – {t['symbol']}</b> ({t['name']}) [Tickmill MT5]",
            f"Conta: <b>{self.account_type}</b> {self.platform} | Moeda: <b>{self.account_currency}</b>",
            f"Alavancagem efetiva: <code>{eff_lev}x</code> (max. Tickmill: <code>{max_leverage_for_sym(t['symbol'])}x</code>)",
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

    # ... outros métodos do bot (mantenha exatamente como estavam no código original, sem alterações)
