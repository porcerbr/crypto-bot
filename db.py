import json
import os
import time
import math
import pandas as pd
from datetime import datetime
from utils import log
from config import Config

STATE_FILE = "state.json"
LOG_FILE = "bot_logs.jsonl"
METRICS_FILE = "bot_metrics.json"


def save_state(bot):
    """Salva estado completo do bot em state.json com backup temporário."""
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
    """
    Carrega estado do bot de state.json com validação.
    Ordena o histórico cronologicamente para evitar problemas na equity curve.
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            
            for k, v in data.items():
                if hasattr(bot, k) and k != "saved_at":
                    setattr(bot, k, v)
            
            # ── VALIDAÇÃO: Ordena histórico cronologicamente ──
            if bot.history:
                try:
                    # Tenta ordenar por timestamp ISO primeiro, depois por formato legado
                    bot.history = sorted(
                        bot.history,
                        key=lambda h: h.get('closed_ts_iso', '') or h.get('closed_at', '')
                    )
                    log(f"Histórico carregado e validado ({len(bot.history)} trades)")
                except Exception as e:
                    log(f"[WARN] Erro ao ordenar histórico: {e}")
            
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
    """Salva métricas agregadas em arquivo separado."""
    data = {
        "updated_at": datetime.now().isoformat(),
        **metrics
    }
    temp_file = METRICS_FILE + ".tmp"
    with open(temp_file, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, METRICS_FILE)


def load_metrics():
    """Carrega métricas salvas."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}


def load_equity_curve():
    """Carrega curva de equity do histórico (para dashboard)."""
    # Será reconstruído no endpoint /api/equity_curve
    return []


def calculate_metrics(bot):
    """
    Calcula métricas de performance do bot com validações de segurança.
    
    Retorna dicionário com:
    - total_trades, winrate, wins, losses
    - profit_factor, avg_win, avg_loss, expectancy
    - max_drawdown_pct, current_balance, total_pnl
    - active_trades_count, pending_trades_count
    """
    # ── Validação: histórico vazio ──
    if not bot.history:
        return {
            "total_trades": 0,
            "winrate": 0,
            "wins": bot.wins,
            "losses": bot.losses,
            "profit_factor": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "expectancy": 0,
            "max_drawdown_pct": 0,
            "current_balance": round(bot.balance, 2),
            "total_pnl": 0,
            "active_trades_count": len(bot.active_trades),
            "pending_trades_count": len(bot.pending_trades),
        }
    
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    # ── Win/Loss Amount ──
    total_profit = sum(h.get("pnl", 0) for h in bot.history if h.get("result") == "WIN")
    total_loss = abs(sum(h.get("pnl", 0) for h in bot.history if h.get("result") == "LOSS"))
    profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else 0

    avg_win = total_profit / bot.wins if bot.wins > 0 else 0
    avg_loss = total_loss / bot.losses if bot.losses > 0 else 0

    expectancy = round((wr/100 * avg_win) - ((100-wr)/100 * avg_loss), 2) if total > 0 else 0

    # ── Drawdown com validação ──
    peak = Config.INITIAL_BALANCE
    max_dd = 0.0
    running = Config.INITIAL_BALANCE
    
    for h in bot.history:
        pnl = h.get("pnl", 0)
        
        # Validação: PnL não deve ser NaN ou infinito
        if isinstance(pnl, float):
            if math.isnan(pnl) or math.isinf(pnl):
                log(f"[METRICS] PnL inválido detectado: {pnl}")
                continue
        
        running += pnl
        if running > peak:
            peak = running
        
        if peak > 0:
            dd = (peak - running) / peak
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
        "current_balance": round(bot.balance, 2),
        "total_pnl": round(bot.balance - Config.INITIAL_BALANCE, 2),
        "active_trades_count": len(bot.active_trades),
        "pending_trades_count": len(bot.pending_trades),
    }
