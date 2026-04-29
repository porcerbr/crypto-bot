import json
import os
import time
from datetime import datetime
from utils import log
from config import Config

STATE_FILE = "state.json"
LOG_FILE = "bot_logs.jsonl"
METRICS_FILE = "bot_metrics.json"

def save_state(bot):
    """Salva estado completo do bot em state.json"""
    data = {
        "mode": bot.mode,
        "timeframe": bot.timeframe,
        "leverage": bot.leverage,
        "balance": bot.balance,
        "wins": bot.wins,
        "losses": bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until,
        "active_trades": bot.active_trades,
        "pending_trades": bot.pending_trades,
        "history": bot.history[-200:],
        "asset_cooldown": bot.asset_cooldown,
        "pending_counter": bot.pending_counter,
        "last_id": getattr(bot, 'last_id', 0),
        "_current_leverage": getattr(bot, '_current_leverage', bot.leverage),
        "saved_at": datetime.now().isoformat(),
    }
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, STATE_FILE)
    log("Estado salvo.")

def load_state(bot):
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(bot, k) and k != "saved_at":
                    setattr(bot, k, v)
            return True
        except Exception as e:
            log("[ERRO] Falha ao carregar estado: " + str(e))
    return False

def append_log(entry_type, data):
    """Adiciona entrada de log persistente."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": entry_type,
        "message": str(data), # Garantir que o JS leia como 'message'
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def get_recent_logs(limit=50):
    """Retorna logs formatados para a dashboard."""
    if not os.path.exists(LOG_FILE): return []
    results = []
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if len(results) >= limit: break
                try:
                    entry = json.loads(line)
                    results.append({
                        "time": datetime.fromisoformat(entry["timestamp"]).strftime("%H:%M:%S"),
                        "message": entry.get("message", entry.get("data", ""))
                    })
                except: continue
    except: pass
    return results

def calculate_metrics(bot):
    """Calcula métricas de performance (Profit Factor, Winrate, etc)."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    wins_val = sum(h["pnl"] for h in bot.history if h["result"] == "WIN")
    loss_val = abs(sum(h["pnl"] for h in bot.history if h["result"] == "LOSS"))
    pf = round(wins_val / loss_val, 2) if loss_val > 0 else 0
    
    # Cálculo de Drawdown
    peak = Config.INITIAL_BALANCE
    current_val = bot.balance
    max_dd = 0
    running = Config.INITIAL_BALANCE
    for h in bot.history:
        running += h["pnl"]
        if running > peak: peak = running
        dd = (peak - running) / peak if peak > 0 else 0
        if dd > max_dd: max_dd = dd

    return {
        "profit_factor": pf,
        "winrate": wr,
        "expectancy": round((wins_val - loss_val) / total, 2) if total > 0 else 0,
        "max_drawdown": round(max_dd, 4),
        "total_trades": total
    }

def load_metrics():
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE) as f: return json.load(f)
        except: return {}
    return {}
