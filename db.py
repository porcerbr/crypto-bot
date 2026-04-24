# db.py
import json, os, sqlite3
from utils import log

DB_FILE = "bot_state.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    conn.close()

def db_get(key, default=None):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM state WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        if row: return json.loads(row[0])
    except Exception as e:
        log(f"[DB] read error: {e}")
    return default

def db_set(key, value):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                  (key, json.dumps(value)))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"[DB] write error: {e}")

def save_state(bot):
    data = {
        "mode": bot.mode, "timeframe": bot.timeframe,
        "wins": bot.wins, "losses": bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until,
        "active_trades": bot.active_trades,
        "pending_trades": bot.pending_trades,
        "pending_counter": bot.pending_counter,
        "last_pending_id": bot.last_pending_id,
        "radar_list": bot.radar_list, "gatilho_list": bot.gatilho_list,
        "reversal_list": bot.reversal_list, "asset_cooldown": bot.asset_cooldown,
        "history": bot.history,
        "signals_feed": bot.signals_feed,
        "balance": bot.balance,
        "leverage": bot.leverage,
        "risk_pct": bot.risk_pct,
        "account_currency": bot.account_currency,
        "account_type": bot.account_type,
        "platform": bot.platform,
    }
    db_set("state", data)
    # fallback JSON
    try:
        with open(Config.STATE_FILE, "w") as f: json.dump(data, f, indent=2)
    except Exception as e: log(f"[STATE] {e}")

def load_state(bot):
    data = db_get("state")
    if data is None and os.path.exists(Config.STATE_FILE):
        try:
            with open(Config.STATE_FILE) as f: data = json.load(f)
        except Exception as e: log(f"[STATE] Erro: {e}")
    if data:
        bot.mode = data.get("mode", "CRYPTO")
        bot.timeframe = data.get("timeframe", Config.TIMEFRAME)
        bot.wins = data.get("wins", 0); bot.losses = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until = data.get("paused_until", 0)
        bot.active_trades = data.get("active_trades", [])
        bot.pending_trades = data.get("pending_trades", [])
        bot.pending_counter = data.get("pending_counter", 0)
        bot.last_pending_id = data.get("last_pending_id", 0)
        bot.radar_list = data.get("radar_list", {}); bot.gatilho_list = data.get("gatilho_list", {})
        bot.reversal_list = data.get("reversal_list", {}); bot.asset_cooldown = data.get("asset_cooldown", {})
        bot.history = data.get("history", [])
        bot.signals_feed = data.get("signals_feed", [])
        bot.balance = float(data.get("balance", Config.INITIAL_BALANCE))
        bot.leverage = int(data.get("leverage", Config.DEFAULT_LEVERAGE))
        bot.risk_pct = float(data.get("risk_pct", Config.RISK_PERCENT_PER_TRADE))
        bot.account_currency = data.get("account_currency", Config.BASE_CURRENCY)
        bot.account_type = data.get("account_type", Config.ACCOUNT_TYPE)
        bot.platform = data.get("platform", Config.BROKER_PLATFORM)
        for t in bot.active_trades: t["session_alerted"] = False
        for t in bot.pending_trades: t["session_alerted"] = False
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s) | {len(bot.pending_trades)} pendente(s)")
        if bot.active_trades:
            lines = ["♻️ BOT REINICIADO – TRADES ATIVOS\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(f"📌 {t['symbol']} {dl} | Entrada: `{fmt(t['entry'])}` | TP: `{fmt(t['tp'])}` | SL: `{fmt(t['sl'])}`")
            bot._restore_msg = "\n".join(lines)
        else: bot._restore_msg = None
