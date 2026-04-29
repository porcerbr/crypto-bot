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
    """Salva o estado completo do bot."""
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
        "saved_at": datetime.now().isoformat(),
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"Erro ao salvar estado: {e}")

def load_state(bot):
    """Carrega o estado do bot."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(bot, k): setattr(bot, k, v)
            return True
        except: return False
    return False

def append_log(entry_type, message):
    """Adiciona uma linha ao arquivo de logs (usado pela dashboard)."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": entry_type,
        "message": str(message)
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def save_metrics(metrics):
    """Salva as métricas calculadas (Função que estava faltando!)."""
    try:
        metrics["updated_at"] = datetime.now().isoformat()
        with open(METRICS_FILE, "w") as f:
            json.dump(metrics, f, indent=2)
    except Exception as e:
        log(f"Erro ao salvar métricas: {e}")

def load_metrics():
    """Carrega métricas do disco."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def calculate_metrics(bot):
    """Gera o dicionário de métricas para a dashboard."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0
    
    wins_val = sum(h["pnl"] for h in bot.history if h["result"] == "WIN")
    loss_val = abs(sum(h["pnl"] for h in bot.history if h["result"] == "LOSS"))
    pf = round(wins_val / loss_val, 2) if loss_val > 0 else 0
    
    return {
        "profit_factor": pf,
        "winrate": wr,
        "wins": bot.wins,
        "losses": bot.losses,
        "total_trades": total,
        "expectancy": round((wins_val - loss_val) / total, 2) if total > 0 else 0,
        "max_drawdown": 0.0 # Pode ser implementado com lógica de pico
    }

def get_recent_logs(limit=50):
    """Lê logs para a API da dashboard."""
    if not os.path.exists(LOG_FILE): return []
    logs = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if len(logs) >= limit: break
                try:
                    data = json.loads(line)
                    logs.append({
                        "time": datetime.fromisoformat(data["timestamp"]).strftime("%H:%M"),
                        "message": data["message"]
                    })
                except: continue
    except: pass
    return logs
