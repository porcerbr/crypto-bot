import json, os
from utils import log

STATE_FILE = "state.json"

def save_state(bot):
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
        "history": bot.history[-100:],
        "asset_cooldown": bot.asset_cooldown,
        "pending_counter": bot.pending_counter,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log("Estado salvo.")

def load_state(bot):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
        for k, v in data.items():
            if hasattr(bot, k):
                setattr(bot, k, v)
