from __future__ import annotations
from flask import Flask, jsonify, request
import dataclasses

from bot import TradingBot
from metrics import win_rate, profit_factor
from models import utc_now, to_iso

def create_app(bot: TradingBot):
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "bot": bot.config.bot_name, "time": to_iso(utc_now())})

    @app.get("/status")
    def status():
        state = bot.state
        return jsonify({
            "bot_name": bot.config.bot_name,
            "mode": bot.config.mode,
            "equity": state.equity,
            "balance": state.balance,
            "daily_pnl": state.daily_pnl,
            "open_trades": [dataclasses.asdict(t) | {"side": t.side.value} for t in state.open_trades],
            "recent_signals": [
                {**dataclasses.asdict(s), "side": s.side.value, "timestamp": to_iso(s.timestamp)}
                for s in state.recent_signals[-20:]
            ],
            "win_rate": win_rate(state),
            "profit_factor": profit_factor(state),
            "last_run_at_utc": state.last_run_at_utc,
        })

    @app.get("/metrics")
    def metrics():
        s = bot.state
        return jsonify({
            "wins": s.total_wins,
            "losses": s.total_losses,
            "breakeven": s.total_breakeven,
            "win_rate": win_rate(s),
            "profit_factor": profit_factor(s),
            "daily_drawdown_pct": bot.risk.daily_drawdown_pct(s),
            "open_trades": len(s.open_trades),
            "last_loss_at_utc": s.last_loss_at_utc,
        })

    @app.post("/run-once")
    def run_once():
        return jsonify(bot.run_once())

    @app.post("/start")
    def start():
        bot.start()
        return jsonify({"status": "started"})

    @app.post("/stop")
    def stop():
        bot.stop()
        return jsonify({"status": "stopped"})

    @app.post("/config")
    def update_config():
        data = request.get_json(force=True) or {}
        for key, value in data.items():
            if hasattr(bot.config, key):
                setattr(bot.config, key, value)
        bot.store.save(bot.state)
        return jsonify({"status": "updated", "config": dataclasses.asdict(bot.config)})

    return app
