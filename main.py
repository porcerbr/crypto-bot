# -*- coding: utf-8 -*-
"""
BOT SNIPER – ESTRATÉGIA CURINGA (v4.0)
─────────────────────────────────────────────────────────────────
MELHORIAS v4 (anti-loss):
  • SL/TP dinâmicos baseados em ATR (substitui % fixo)
  • Circuit Breaker: pausa automática após N losses consecutivos
  • ADX 14: só opera quando há tendência forte (evita mercado lateral)
  • Filtro H1: alinha operação com tendência do timeframe superior
  • Cooldown por ativo após loss (1h sem reentrar no mesmo ativo)
  • MAX_TRADES simultâneos limitado
  • Trailing Stop via ATR (mais largo que o fixo anterior)
  • MIN_CONFLUENCE elevado de 3 → 5 (de 7 possíveis)
  • Comando /resetpausa para desativar circuit breaker manualmente
─────────────────────────────────────────────────────────────────
"""
import os, time, json, math, requests, pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    BOT_TOKEN      = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TIMEZONE    = timezone(timedelta(hours=-3))

    FOREX_ASSETS   = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS  = ["BTC-USD", "ETH-USD", "SOL-USD"]

    # ── Gestão de risco via ATR (substitui % fixo) ───────────
    ATR_MULT_SL    = 1.5   # Stop Loss  = preço ± (1.5 × ATR)
    ATR_MULT_TP    = 3.0   # Take Profit= preço ± (3.0 × ATR) → ratio 2:1
    ATR_MULT_TRAIL = 1.2   # Trailing Stop = pico ± (1.2 × ATR)

    # ── Circuit Breaker ───────────────────────────────────────
    MAX_CONSECUTIVE_LOSSES = 2         # Pausar após 2 losses seguidos
    PAUSE_DURATION         = 3600      # Pausa de 1 hora (segundos)

    # ── Filtros adicionais ────────────────────────────────────
    ADX_MIN        = 22    # ADX mínimo para operar (força de tendência)
    MAX_TRADES     = 2     # Máx. operações abertas ao mesmo tempo
    ASSET_COOLDOWN = 3600  # Cooldown por ativo após loss (segundos)

    TIMEFRAME      = "15m"
    NEWS_INTERVAL  = 7200   # Notícias automáticas a cada 2h
    SCAN_INTERVAL  = 30     # Scan a cada 30s
    STATE_FILE     = "bot_state.json"

    # Horário de liquidez FOREX (UTC): 07h–17h
    FOREX_OPEN_UTC  = 7
    FOREX_CLOSE_UTC = 17

    # Confluências mínimas para disparar sinal (de 7 possíveis)
    MIN_CONFLUENCE  = 5


def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ========================================
# PERSISTÊNCIA (JSON)
# ========================================
def save_state(bot):
    data = {
        "wins":               bot.wins,
        "losses":             bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until":       bot.paused_until,
        "active_trades":      bot.active_trades,
        "radar_list":         bot.radar_list,
        "asset_cooldown":     bot.asset_cooldown,
        "history":            bot.history,
    }
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"[STATE] Erro ao salvar: {e}")


def load_state(bot):
    if not os.path.exists(Config.STATE_FILE):
        return
    try:
        with open(Config.STATE_FILE) as f:
            data = json.load(f)
        bot.wins               = data.get("wins", 0)
        bot.losses             = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until       = data.get("paused_until", 0)
        bot.active_trades      = data.get("active_trades", [])
        bot.radar_list         = data.get("radar_list", {})
        bot.asset_cooldown     = data.get("asset_cooldown", {})
        bot.history            = data.get("history", [])
        log(f"[STATE] Restaurado: {bot.wins}W / {bot.losses}L | "
            f"{len(bot.active_trades)} trade(s) ativo(s) | "
            f"Losses seguidos: {bot.consecutive_losses}")
    except Exception as e:
        log(f"[STATE] Erro ao carregar: {e}")


# ========================================
# NOTÍCIAS VIA RSS
# ========================================
RSS_FEEDS = [
    ("Investing.com BR", "https://br.investing.com/rss/news.rss"),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Reuters Markets",  "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",      "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("Cointelegraph",    "https://cointelegraph.com/rss"),
]

def _parse_rss(url, source_name, max_results=3):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
    r       = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    root    = ET.fromstring(r.content)
    items   = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    articles = []
    for item in items[:max_results]:
        title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "").strip()
        if title and link:
            articles.append({"title": title, "url": link, "source": source_name})
    return articles

def get_news(max_results=5):
    articles = []
    for source_name, url in RSS_FEEDS:
        if len(articles) >= max_results:
            break
        try:
            fetched = _parse_rss(url, source_name, max_results=2)
            articles.extend(fetched)
            log(f"[RSS] {source_name}: {len(fetched)} notícia(s)")
        except Exception as e:
            log(f"[RSS] {source_name} falhou: {e}")
    return articles[:max_results]

def get_fear_greed():
    try:
        r    = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6)
        data = r.json()["data"][0]
        return f"{data['value']} – {data['value_classification']}"
    except:
        return "N/D"

def build_news_message():
    articles = get_news()
    fg       = get_fear_greed()
    if not articles:
        return (
            "📰 <b>NOTÍCIAS DO MERCADO</b>\n\n"
            "Nenhum feed disponível no momento.\n"
            f"😱 <b>Fear &amp; Greed:</b> {fg}"
        )
    lines = ["📰 <b>NOTÍCIAS RELEVANTES DO MERCADO</b>\n"]
    for i, a in enumerate(articles, 1):
        title = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{title}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 <b>Fear &amp; Greed (Cripto):</b> {fg}")
    lines.append(f"🕐 {datetime.now(Config.BR_TIMEZONE).strftime('%H:%M')} (Brasília)")
    return "\n".join(lines)


# ========================================
# HORÁRIO DE MERCADO
# ========================================
def forex_market_open():
    hour_utc = datetime.now(timezone.utc).hour
    return Config.FOREX_OPEN_UTC <= hour_utc < Config.FOREX_CLOSE_UTC


# ========================================
# MOTOR DE ANÁLISE
# ========================================
def get_analysis(symbol):
    import yfinance as yf

    yf_symbol = f"{symbol}=X" if "-" not in symbol else symbol

    try:
        df = yf.Ticker(yf_symbol).history(period="5d", interval=Config.TIMEFRAME)
        if len(df) < 200:
            return None

        closes = df["Close"]
        highs  = df["High"]
        lows   = df["Low"]
        volume = df["Volume"]

        # ── EMA verdadeira (ewm) ──────────────────────────────
        ema9   = closes.ewm(span=9,   adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21,  adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]

        # ── Bandas de Bollinger 20,2 ──────────────────────────
        sma20      = closes.rolling(20).mean().iloc[-1]
        std20      = closes.rolling(20).std().iloc[-1]
        upper_band = sma20 + std20 * 2
        lower_band = sma20 - std20 * 2

        # ── RSI 14 ───────────────────────────────────────────
        delta   = closes.diff()
        gain    = delta.where(delta > 0, 0).rolling(14).mean()
        loss    = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs      = gain / loss
        cur_rsi = (100 - 100 / (1 + rs)).iloc[-1]

        # ── MACD (12, 26, 9) ─────────────────────────────────
        ema12       = closes.ewm(span=12, adjust=False).mean()
        ema26       = closes.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist   = macd_line - signal_line
        macd_bull   = macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]
        macd_bear   = macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2]

        # ── Volume (acima da média de 20 períodos) ────────────
        vol_avg   = volume.rolling(20).mean().iloc[-1]
        vol_cur   = volume.iloc[-1]
        vol_ok    = bool(vol_cur > vol_avg) if vol_avg > 0 else False
        vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 0

        # ── ATR 14 ───────────────────────────────────────────
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        # ── ADX 14 (Wilder) ──────────────────────────────────
        # Calcula +DM e -DM
        high_diff    = highs.diff()
        low_diff     = lows.diff()
        plus_dm_raw  = high_diff.where((high_diff > 0) & (high_diff > -low_diff), 0.0)
        minus_dm_raw = (-low_diff).where((-low_diff > 0) & (-low_diff > high_diff), 0.0)
        atr_smooth   = tr.ewm(alpha=1/14, adjust=False).mean()
        plus_di      = 100 * plus_dm_raw.ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
        minus_di     = 100 * minus_dm_raw.ewm(alpha=1/14, adjust=False).mean() / (atr_smooth + 1e-10)
        dx           = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx          = dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]

        cur_price    = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        # ── Cenário base (15m) ────────────────────────────────
        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        # ── Filtro H1: tendência do timeframe superior ────────
        # Só abre BUY se H1 também está em alta, e vice-versa
        h1_bull = False
        h1_bear = False
        try:
            df_h1 = yf.Ticker(yf_symbol).history(period="60d", interval="1h")
            if len(df_h1) >= 50:
                c_h1      = df_h1["Close"]
                ema21_h1  = c_h1.ewm(span=21,  adjust=False).mean().iloc[-1]
                span_h1   = 200 if len(df_h1) >= 200 else 50
                ema_h1    = c_h1.ewm(span=span_h1, adjust=False).mean().iloc[-1]
                price_h1  = c_h1.iloc[-1]
                h1_bull   = price_h1 > ema21_h1 and ema21_h1 > ema_h1
                h1_bear   = price_h1 < ema21_h1 and ema21_h1 < ema_h1
        except Exception as e_h1:
            log(f"[H1] {symbol}: {e_h1}")

        return {
            "symbol":    symbol,
            "price":     cur_price,
            "cenario":   cenario,
            "rsi":       cur_rsi,
            "atr":       atr,
            "adx":       adx,
            "ema9":      ema9,
            "ema21":     ema21,
            "ema200":    ema200,
            "upper":     upper_band,
            "lower":     lower_band,
            "macd_bull": macd_bull,
            "macd_bear": macd_bear,
            "vol_ok":    vol_ok,
            "vol_ratio": vol_ratio,
            "t_buy":     trigger_buy,
            "t_sell":    trigger_sell,
            "h1_bull":   h1_bull,
            "h1_bear":   h1_bear,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}")
        return None


# ========================================
# CONFLUÊNCIA (7 fatores)
# ========================================
def calc_confluence(res, direcao):
    """Conta confluências. Retorna (score, total, lista de checks)."""
    if direcao == "BUY":
        checks = [
            ("EMA 200 (15m)",   res["price"]  > res["ema200"]),
            ("EMA 9 > 21",      res["ema9"]   > res["ema21"]),
            ("MACD Alta",       res["macd_bull"]),
            ("Volume acima avg",res["vol_ok"]),
            ("RSI < 65",        res["rsi"] < 65),
            ("H1 Bullish",      res["h1_bull"]),       # NOVO
            ("ADX Tendência",   res["adx"] > Config.ADX_MIN),  # NOVO
        ]
    else:
        checks = [
            ("EMA 200 (15m)",   res["price"]  < res["ema200"]),
            ("EMA 9 < 21",      res["ema9"]   < res["ema21"]),
            ("MACD Baixa",      res["macd_bear"]),
            ("Volume acima avg",res["vol_ok"]),
            ("RSI > 35",        res["rsi"] > 35),
            ("H1 Bearish",      res["h1_bear"]),       # NOVO
            ("ADX Tendência",   res["adx"] > Config.ADX_MIN),  # NOVO
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks


def confluence_bar(score, total):
    filled = math.floor(score / total * 5)
    return "█" * filled + "░" * (5 - filled)


# ========================================
# BOT PRINCIPAL
# ========================================
class TradingBot:
    def __init__(self):
        self.mode               = "CRYPTO"
        self.wins               = 0
        self.losses             = 0
        self.consecutive_losses = 0      # NOVO: contador losses seguidos
        self.paused_until       = 0      # NOVO: timestamp de pausa (circuit breaker)
        self.active_trades      = []
        self.radar_list         = {}
        self.asset_cooldown     = {}     # NOVO: {symbol: timestamp_last_loss}
        self.history            = []
        self.last_id            = 0
        self.last_news_ts       = 0

    # ── Telegram ──────────────────────────────────────────────
    def send(self, text, markup=None, disable_preview=False):
        url     = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id":                  Config.CHAT_ID,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log(f"[SEND] {e}")

    # ── Menu ──────────────────────────────────────────────────
    def build_menu(self):
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX",        "callback_data": "set_fx"},
             {"text": "₿ CRIPTO",        "callback_data": "set_crypto"}],
            [{"text": "📊 Status",        "callback_data": "status"},
             {"text": "🏆 Placar",        "callback_data": "placar"}],
            [{"text": "📰 Notícias",      "callback_data": "news"},
             {"text": "🔄 Atualizar",     "callback_data": "refresh"}],
        ]}
        total   = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        fg      = get_fear_greed()
        forex_status = "🟢 Aberto" if forex_market_open() else "🔴 Fechado"

        # Status do circuit breaker
        paused = time.time() < self.paused_until
        cb_status = ""
        if paused:
            mins_left = int((self.paused_until - time.time()) / 60)
            cb_status = f"\n⛔ <b>CIRCUIT BREAKER ATIVO</b> – retoma em {mins_left}min"

        msg = (
            f"<b>🎛 BOT SNIPER – ESTRATÉGIA CURINGA v4</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code> ({winrate:.1f}%)\n"
            f"Losses seguidos: <code>{self.consecutive_losses}</code>  "
            f"(limite: {Config.MAX_CONSECUTIVE_LOSSES})\n"
            f"Modo: <b>{self.mode}</b>  |  TF: <code>{Config.TIMEFRAME}</code>\n"
            f"Gestão: SL={Config.ATR_MULT_SL}×ATR  TP={Config.ATR_MULT_TP}×ATR\n"
            f"FOREX: {forex_status}\n"
            f"😱 Fear &amp; Greed: <b>{fg}</b>"
            f"{cb_status}"
        )
        self.send(msg, markup)

    # ── Notícias ──────────────────────────────────────────────
    def send_news(self):
        log("📰 Enviando notícias...")
        self.send(build_news_message(), disable_preview=True)
        self.last_news_ts = time.time()

    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL:
            self.send_news()

    # ── /status ───────────────────────────────────────────────
    def send_status(self):
        paused = time.time() < self.paused_until
        lines  = ["📊 <b>OPERAÇÕES ABERTAS</b>\n"]

        if paused:
            mins_left = int((self.paused_until - time.time()) / 60)
            lines.append(f"⛔ <b>Circuit Breaker ativo</b> – retoma em {mins_left}min\n")

        if not self.active_trades:
            lines.append("Nenhuma operação aberta no momento.")
            self.send("\n".join(lines))
            return

        for t in self.active_trades:
            res = get_analysis(t["symbol"])
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL":
                pnl = -pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{emoji} <b>{t['symbol']}</b> {t['dir']} | desde {t.get('opened_at','?')}\n"
                f"   Entrada: <code>{t['entry']:.5f}</code>  Atual: <code>{cur:.5f}</code>\n"
                f"   P&amp;L: <code>{pnl:+.2f}%</code>  "
                f"SL: <code>{t['sl']:.5f}</code>  TP: <code>{t['tp']:.5f}</code>"
            )
        self.send("\n".join(lines))

    # ── /placar ───────────────────────────────────────────────
    def send_placar(self):
        total   = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        lines   = [
            "<b>🏆 PLACAR DETALHADO</b>\n",
            f"✅ Wins:           <code>{self.wins}</code>",
            f"❌ Losses:         <code>{self.losses}</code>",
            f"📊 Total:          <code>{total}</code>",
            f"🎯 Winrate:        <code>{winrate:.1f}%</code>",
            f"🔴 Losses seguidos:<code>{self.consecutive_losses}</code>",
        ]
        if self.history:
            lines.append("\n<b>Últimas 5 operações:</b>")
            for h in self.history[-5:][::-1]:
                icon = "✅" if h["result"] == "WIN" else "❌"
                lines.append(
                    f"{icon} {h['symbol']} {h['dir']}  "
                    f"P&amp;L: <code>{h['pnl']:+.2f}%</code>  {h['closed_at']}"
                )
        self.send("\n".join(lines))

    # ── Circuit Breaker ───────────────────────────────────────
    def is_paused(self):
        return time.time() < self.paused_until

    def reset_pause(self):
        """Reseta manualmente o circuit breaker."""
        self.paused_until       = 0
        self.consecutive_losses = 0
        save_state(self)
        self.send("✅ <b>Circuit Breaker resetado.</b> Bot liberado para operar.")
        log("[CB] Circuit breaker resetado manualmente.")

    # ── Scan ──────────────────────────────────────────────────
    def scan(self):
        # ── Circuit Breaker: verifica pausa ───────────────────
        if self.is_paused():
            mins_left = int((self.paused_until - time.time()) / 60)
            log(f"⛔ Bot pausado (circuit breaker). Retoma em {mins_left}min.")
            return

        if self.mode == "FOREX" and not forex_market_open():
            log("⏸ FOREX fora do horário de liquidez.")
            return

        # ── Limite de trades simultâneos ──────────────────────
        if len(self.active_trades) >= Config.MAX_TRADES:
            log(f"⚠️ Limite de {Config.MAX_TRADES} trades simultâneos atingido.")
            return

        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS

        for s in universe:
            # Pular se já tem trade aberto nesse ativo
            if any(t["symbol"] == s for t in self.active_trades):
                continue

            # ── Cooldown por ativo após loss ──────────────────
            last_loss_ts = self.asset_cooldown.get(s, 0)
            cooldown_remaining = Config.ASSET_COOLDOWN - (time.time() - last_loss_ts)
            if cooldown_remaining > 0:
                mins = int(cooldown_remaining / 60)
                log(f"[COOL] {s} em cooldown por {mins}min após loss.")
                continue

            res = get_analysis(s)
            if not res or res["cenario"] == "NEUTRO":
                continue

            price = res["price"]

            # ── RADAR ─────────────────────────────────────────
            last_alert = self.radar_list.get(s, 0)
            if time.time() - last_alert > 1800:
                gatilho   = res["t_buy"] if res["cenario"] == "ALTA" else res["t_sell"]
                macd_icon = "🟢" if res["macd_bull"] else ("🔴" if res["macd_bear"] else "⚪")
                adx_icon  = "💪" if res["adx"] > Config.ADX_MIN else "😴"
                h1_icon   = "🟢" if res["h1_bull"] else ("🔴" if res["h1_bear"] else "⚪")
                self.send(
                    f"⚠️ <b>RADAR SNIPER: {s}</b>\n"
                    f"Tendência: <b>{res['cenario']}</b> (EMA 200)\n"
                    f"Gatilho: <code>{gatilho:.5f}</code>  |  ATR: <code>{res['atr']:.5f}</code>\n"
                    f"RSI: <code>{res['rsi']:.1f}</code>  |  MACD: {macd_icon}  "
                    f"|  ADX: <code>{res['adx']:.1f}</code> {adx_icon}  |  H1: {h1_icon}"
                )
                self.radar_list[s] = time.time()

            # ── GATILHO ────────────────────────────────────────
            pode_comprar = (
                res["cenario"] == "ALTA"
                and price >= res["t_buy"]
                and price < res["upper"]
                and res["rsi"] < 70
            )
            pode_vender = (
                res["cenario"] == "BAIXA"
                and price <= res["t_sell"]
                and price > res["lower"]
                and res["rsi"] > 30
            )
            if not (pode_comprar or pode_vender):
                continue

            dir_simple = "BUY" if pode_comprar else "SELL"

            # ── CONFLUÊNCIA (mínimo 5/7) ───────────────────────
            score, total_c, checks = calc_confluence(res, dir_simple)
            if score < Config.MIN_CONFLUENCE:
                log(f"[SINAL] {s} {dir_simple} ignorado – confluência {score}/{total_c}")
                continue

            bar      = confluence_bar(score, total_c)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {name}" for name, ok in checks)
            vol_txt  = f"{res['vol_ratio']:.1f}x média" if res["vol_ratio"] > 0 else "N/D"

            # ── SL / TP via ATR (dinâmico) ────────────────────
            atr = res["atr"]
            if dir_simple == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr

            sl_pct = abs(price - sl) / price * 100
            tp_pct = abs(tp - price) / price * 100

            dir_label = "BUY 🟢" if dir_simple == "BUY" else "SELL 🔴"

            self.send(
                f"🎯 <b>SINAL CONFIRMADO – {s}</b>\n\n"
                f"Ação: <b>{dir_label}</b>\n"
                f"Entrada: <code>{price:.5f}</code>\n"
                f"ATR(14): <code>{atr:.5f}</code>  |  ADX: <code>{res['adx']:.1f}</code>  "
                f"|  RSI: <code>{res['rsi']:.1f}</code>\n"
                f"Volume:  <code>{vol_txt}</code>\n"
                f"──────────────────────\n"
                f"🎯 Take Profit: <code>{tp:.5f}</code>  ({tp_pct:+.2f}%)\n"
                f"🛡 Stop Loss:   <code>{sl:.5f}</code>  ({-sl_pct:.2f}%)\n"
                f"──────────────────────\n"
                f"<b>Confluência: {score}/{total_c}  [{bar}]</b>\n"
                f"{conf_txt}"
            )

            self.active_trades.append({
                "symbol":    s,
                "entry":     price,
                "tp":        tp,
                "sl":        sl,
                "dir":       dir_simple,
                "peak":      price,
                "atr":       atr,
                "opened_at": datetime.now(Config.BR_TIMEZONE).strftime("%d/%m %H:%M"),
            })
            self.radar_list[s] = time.time()
            save_state(self)

    # ── Monitor + Trailing Stop (ATR) ─────────────────────────
    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"])
            if not res:
                continue
            cur = res["price"]
            atr = res["atr"]

            # ── Trailing Stop via ATR ──────────────────────────
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl    = cur - Config.ATR_MULT_TRAIL * atr
                if new_sl > t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL: {t['sl']:.5f} → {new_sl:.5f}")
                    t["sl"]  = new_sl
                    changed  = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl    = cur + Config.ATR_MULT_TRAIL * atr
                if new_sl < t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL: {t['sl']:.5f} → {new_sl:.5f}")
                    t["sl"]  = new_sl
                    changed  = True

            # ── Encerramento ───────────────────────────────────
            is_win  = (
                (t["dir"] == "BUY"  and cur >= t["tp"]) or
                (t["dir"] == "SELL" and cur <= t["tp"])
            )
            is_loss = (
                (t["dir"] == "BUY"  and cur <= t["sl"]) or
                (t["dir"] == "SELL" and cur >= t["sl"])
            )

            if is_win or is_loss:
                status = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                pnl    = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL":
                    pnl = -pnl

                closed_at = datetime.now(Config.BR_TIMEZONE).strftime("%d/%m %H:%M")

                if is_win:
                    self.wins               += 1
                    self.consecutive_losses  = 0   # Reset no win
                else:
                    self.losses             += 1
                    self.consecutive_losses += 1
                    # Cooldown por ativo
                    self.asset_cooldown[t["symbol"]] = time.time()
                    log(f"[COOL] Cooldown ativado para {t['symbol']} (1h)")

                self.history.append({
                    "symbol":    t["symbol"],
                    "dir":       t["dir"],
                    "result":    "WIN" if is_win else "LOSS",
                    "pnl":       round(pnl, 2),
                    "closed_at": closed_at,
                })

                self.send(
                    f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                    f"Ativo: <b>{t['symbol']}</b>  |  {t['dir']}\n"
                    f"Resultado: <b>{status}</b>\n\n"
                    f"Entrada: <code>{t['entry']:.5f}</code>\n"
                    f"Saída:   <code>{cur:.5f}</code>\n"
                    f"P&amp;L:  <code>{pnl:+.2f}%</code>"
                )
                self.active_trades.remove(t)
                changed = True
                self.build_menu()

                # ── Circuit Breaker ────────────────────────────
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    log(f"[CB] ⛔ Circuit breaker ativado! {self.consecutive_losses} losses seguidos. Pausa: {mins}min.")
                    self.send(
                        f"⛔ <b>CIRCUIT BREAKER ATIVADO</b>\n\n"
                        f"🔴 {self.consecutive_losses} losses consecutivos detectados.\n"
                        f"🕐 Bot pausado por <b>{mins} minutos</b> para proteção de capital.\n\n"
                        f"Use /resetpausa para retomar antes do prazo."
                    )

        if changed:
            save_state(self)


# ========================================
# LOOP PRINCIPAL
# ========================================
def main():
    log("🔌 Iniciando Bot Sniper v4 – Estratégia Curinga (anti-loss)...")
    requests.get(
        f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook",
        timeout=8
    )
    bot = TradingBot()
    load_state(bot)
    bot.build_menu()
    bot.send_news()

    while True:
        try:
            url = (
                f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                f"/getUpdates?offset={bot.last_id + 1}&timeout=5"
            )
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]

                    # Comandos de texto
                    if "message" in u:
                        text = u["message"].get("text", "").strip().lower()
                        if text in ("/noticias", "/news"):
                            bot.send_news()
                        elif text == "/status":
                            bot.send_status()
                        elif text in ("/placar", "/score"):
                            bot.send_placar()
                        elif text in ("/menu", "/start"):
                            bot.build_menu()
                        elif text == "/resetpausa":          # NOVO
                            bot.reset_pause()

                    # Botões inline
                    if "callback_query" in u:
                        data = u["callback_query"]["data"]
                        cid  = u["callback_query"]["id"]
                        requests.post(
                            f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cid}, timeout=5,
                        )
                        if data == "set_fx":
                            bot.mode = "FOREX"
                        elif data == "set_crypto":
                            bot.mode = "CRYPTO"
                        elif data == "news":
                            bot.send_news(); continue
                        elif data == "status":
                            bot.send_status(); continue
                        elif data == "placar":
                            bot.send_placar(); continue
                        bot.build_menu()

            bot.maybe_send_news()
            bot.scan()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)

        except Exception as e:
            log(f"Erro no loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
