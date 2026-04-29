import json
import os
from datetime import datetime
from utils import log
from config import Config

STATE_FILE = "state.json"
LOG_FILE = "bot_logs.jsonl"
METRICS_FILE = "bot_metrics.json"

def save_state(bot):
    data = {
        "balance": bot.balance,
        "wins": bot.wins,
        "losses": bot.losses,
        "active_trades": bot.active_trades,
        "pending_trades": bot.pending_trades,
        "history": bot.history[-100:],
        "saved_at": datetime.now().isoformat(),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_state(bot):
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            bot.balance = data.get("balance", bot.balance)
            bot.wins = data.get("wins", 0)
            bot.losses = data.get("losses", 0)
            bot.active_trades = data.get("active_trades", [])
            bot.pending_trades = data.get("pending_trades", [])
            bot.history = data.get("history", [])
            return True
        except: return False
    return False

def append_log(entry_type, message):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": entry_type,
        "message": str(message)
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def save_metrics(metrics):
    metrics["updated_at"] = datetime.now().isoformat()
    with open(METRICS_FILE, "w") as f:
        json.dump(metrics, f, indent=2)

def load_metrics():
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def calculate_metrics(bot):
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0
    wins_val = sum(h.get("pnl", 0) for h in bot.history if h.get("result") == "WIN")
    loss_val = abs(sum(h.get("pnl", 0) for h in bot.history if h.get("result") == "LOSS"))
    pf = round(wins_val / loss_val, 2) if loss_val > 0 else 0
    return {
        "profit_factor": pf,
        "winrate": wr,
        "total_trades": total,
        "expectancy": round((wins_val - loss_val) / total, 2) if total > 0 else 0
    }

def get_recent_logs(limit=50):
    if not os.path.exists(LOG_FILE): return []
    logs = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if len(logs) >= limit: break
                try:
                    d = json.loads(line)
                    logs.append({"time": d["timestamp"][11:19], "message": d["message"]})
                except: continue
    except: pass
    return logs
