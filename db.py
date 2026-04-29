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
    """Carrega estado do bot de state.json"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(bot, k) and k != "saved_at":
                    setattr(bot, k, v)
            saved_at = data.get("saved_at", "desconhecido")
            log("Estado carregado de " + str(saved_at))
            return True
        except Exception as e:
            log("[ERRO] Falha ao carregar estado: " + str(e))
            return False
    return False


def append_log(entry_type, data):
    """Adiciona entrada de log persistente em formato JSON Lines."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": entry_type,
        "data": data,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + chr(10))


def get_recent_logs(entry_type=None, hours=24, limit=100):
    """Retorna logs recentes do arquivo persistente."""
    if not os.path.exists(LOG_FILE):
        return []

    cutoff = time.time() - (hours * 3600)
    results = []

    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                    if entry_ts < cutoff:
                        continue
                    if entry_type and entry["type"] != entry_type:
                        continue
                    results.append(entry)
                except:
                    continue
    except Exception as e:
        log("[ERRO] Falha ao ler logs: " + str(e))

    return results[-limit:]


def save_metrics(metrics):
    """Salva metricas agregadas em arquivo separado."""
    data = {
        "updated_at": datetime.now().isoformat(),
        **metrics
    }
    temp_file = METRICS_FILE + ".tmp"
    with open(temp_file, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, METRICS_FILE)


def load_metrics():
    """Carrega metricas salvas."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}


def calculate_metrics(bot):
    """Calcula metricas de performance do bot."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    total_profit = sum(h["pnl"] for h in bot.history if h["result"] == "WIN")
    total_loss = abs(sum(h["pnl"] for h in bot.history if h["result"] == "LOSS"))
    profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else 0

    avg_win = total_profit / bot.wins if bot.wins > 0 else 0
    avg_loss = total_loss / bot.losses if bot.losses > 0 else 0

    expectancy = round((wr/100 * avg_win) - ((100-wr)/100 * avg_loss), 2) if total > 0 else 0

    peak = Config.INITIAL_BALANCE
    max_dd = 0
    running = Config.INITIAL_BALANCE
    for h in bot.history:
        running += h["pnl"]
        if running > peak:
            peak = running
        dd = (peak - running) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": total,
        "winrate": wr,
        "wins": bot.wins,
        "losses": bot.losses,
        "profit_factor": profit_factor,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": expectancy,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "current_balance": bot.balance,
        "total_pnl": round(bot.balance - Config.INITIAL_BALANCE, 2),
        "active_trades_count": len(bot.active_trades),
        "pending_trades_count": len(bot.pending_trades),
    }
