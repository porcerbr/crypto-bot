from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import Config
from performance import calculate_metrics_from_history, equity_curve_from_history
from utils import log

STATE_FILE = "state.json"
LOG_FILE = "bot_logs.jsonl"
METRICS_FILE = "bot_metrics.json"


def _atomic_write_json(path: str, data: dict):
    temp_file = path + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(temp_file, path)


def save_state(bot):
    """Salva estado completo do bot em state.json."""
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
        "history": bot.history[-500:],
        "asset_cooldown": bot.asset_cooldown,
        "pending_counter": bot.pending_counter,
        "last_id": getattr(bot, "last_id", 0),
        "_current_leverage": getattr(bot, "_current_leverage", bot.leverage),
        "_peak_balance": getattr(bot, "_peak_balance", bot.balance),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _atomic_write_json(STATE_FILE, data)
        log("Estado salvo.")
    except Exception as e:
        log(f"[ERRO] Falha ao salvar estado: {e}")


def load_state(bot):
    """Carrega estado do bot de state.json."""
    if not os.path.exists(STATE_FILE):
        return False

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)

        for k, v in data.items():
            if hasattr(bot, k) and k != "saved_at":
                setattr(bot, k, v)

        if not hasattr(bot, "_peak_balance") or not getattr(bot, "_peak_balance", None):
            bot._peak_balance = max(float(bot.balance), float(getattr(bot, "_peak_balance", bot.balance)))

        saved_at = data.get("saved_at", "desconhecido")
        log("Estado carregado de " + str(saved_at))
        return True
    except Exception as e:
        log("[ERRO] Falha ao carregar estado: " + str(e))
        return False


def append_log(entry_type, data):
    """Adiciona entrada de log persistente em formato JSON Lines."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": entry_type,
        "data": data,
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"[ERRO] Falha ao gravar log: {e}")


def get_recent_logs(entry_type=None, hours=24, limit=100):
    """Retorna logs recentes do arquivo persistente."""
    if not os.path.exists(LOG_FILE):
        return []

    cutoff = time.time() - (hours * 3600)
    results = []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                    if entry_ts < cutoff:
                        continue
                    if entry_type and entry.get("type") != entry_type:
                        continue
                    results.append(entry)
                except Exception:
                    continue
    except Exception as e:
        log("[ERRO] Falha ao ler logs: " + str(e))

    return results[-limit:]


def save_metrics(metrics):
    """Salva métricas agregadas em arquivo separado."""
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), **metrics}
    try:
        _atomic_write_json(METRICS_FILE, data)
    except Exception as e:
        log(f"[ERRO] Falha ao salvar métricas: {e}")


def load_metrics():
    """Carrega métricas salvas."""
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def calculate_metrics(bot):
    """Calcula métricas de performance do bot."""
    return calculate_metrics_from_history(
        bot.history,
        initial_balance=Config.INITIAL_BALANCE,
        current_balance=bot.balance,
        active_trades_count=len(bot.active_trades),
        pending_trades_count=len(bot.pending_trades),
    )


def load_equity_curve(bot=None):
    """Carrega curva de equity do state.json, do bot atual ou do histórico salvo em métricas."""
    history = []
    balance = Config.INITIAL_BALANCE

    try:
        if bot is not None:
            history = list(getattr(bot, "history", []) or [])
            balance = float(getattr(bot, "balance", Config.INITIAL_BALANCE))
        elif os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
            history = state.get("history", []) or []
            balance = float(state.get("balance", Config.INITIAL_BALANCE))
        else:
            metrics = load_metrics()
            history = metrics.get("history", []) or []
            balance = float(metrics.get("current_balance", Config.INITIAL_BALANCE))

        curve = equity_curve_from_history(history, initial_balance=Config.INITIAL_BALANCE)
        if curve:
            return curve
        return [{"t": "", "balance": round(balance, 2), "pnl": 0.0, "drawdown_pct": 0.0}]
    except Exception as e:
        log(f"[ERRO] Falha ao montar equity curve: {e}")
        return []
