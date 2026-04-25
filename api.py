# api.py
import os
from flask import Flask, jsonify, request
from flask_cors import CORS

def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.route("/api/status")
    def status():
        active = [{
            "symbol": t["symbol"],
            "name": t.get("name"),
            "dir": t["dir"],
            "entry": t["entry"],
            "sl": t["sl"],
            "tp": t["tp"],
            "lot": t.get("lot"),
            "pnl": t.get("pnl", 0),
        } for t in bot.active_trades]
        return jsonify({
            "active_trades": active,
            "pending_count": len(bot.pending_trades),
            "balance": bot.balance,
            "leverage": bot.leverage,
            "winrate": round(bot.wins/(bot.wins+bot.losses)*100, 1) if (bot.wins+bot.losses) else 0,
            "wins": bot.wins,
            "losses": bot.losses,
            "mode": bot.mode,
            "timeframe": bot.timeframe,
            "paused": bot.is_paused(),
        })

    @app.route("/api/pending")
    def pending():
        return jsonify(bot.pending_trades)

    @app.route("/api/execute", methods=["POST"])
    def execute():
        data = request.get_json(force=True)
        pid = data.get("pending_id")
        amount = float(data.get("amount", 0))
        ok, msg = bot.execute_pending(pid, amount)
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/reject", methods=["POST"])
    def reject():
        data = request.get_json(force=True)
        pid = data.get("pending_id")
        ok = bot.reject_pending(pid)
        return jsonify({"ok": ok})

    return app
