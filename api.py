import os
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
from config import Config

def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        try:
            with open("dashboard.html", "r", encoding="utf-8") as f:
                return render_template_string(f.read())
        except FileNotFoundError:
            return "Dashboard não encontrado", 404

    @app.route("/api/status")
    def status():
        from utils import get_dynamic_max_trades
        active = []
        for t in bot.active_trades:
            sym = t["symbol"]
            try:
                from analysis import _cache
                cur_price = float(_cache[sym][1]["Close"].iloc[-1]) if sym in _cache else t["entry"]
            except: cur_price = t["entry"]

            # Cálculo de Progresso para a Barra Visual
            total_range = abs(t["tp"] - t["entry"])
            moved = abs(cur_price - t["entry"])
            progress = round(min(moved / total_range * 100, 100), 1) if total_range > 0 else 0

            active.append({
                "symbol": sym,
                "dir": t["dir"],
                "entry": t["entry"],
                "current_price": cur_price,
                "pnl": t.get("pnl", 0), # Bot monitor_trades atualiza isso
                "tp_progress": progress
            })

        return jsonify({
            "balance": round(bot.balance, 2),
            "wins": bot.wins,
            "losses": bot.losses,
            "winrate": round(bot.wins/(bot.wins+bot.losses)*100, 1) if (bot.wins+bot.losses)>0 else 0,
            "mode": bot.mode,
            "leverage": bot.get_current_leverage(),
            "timeframe": bot.timeframe,
            "active_trades": active,
            "max_trades_allowed": get_dynamic_max_trades(bot.balance)
        })

    @app.route("/api/logs")
    def logs():
        from db import get_recent_logs
        return jsonify({"logs": get_recent_logs(limit=30)})

    @app.route("/api/metrics")
    def metrics():
        from db import calculate_metrics
        return jsonify({"current": calculate_metrics(bot)})

    @app.route("/api/pending")
    def pending():
        # Adiciona campos extras que a dashboard usa para mostrar a razão da IA
        return jsonify(bot.pending_trades)

    @app.route("/api/execute", methods=["POST"])
    def execute():
        data = request.get_json(force=True)
        ok, msg = bot.execute_pending(data.get("pending_id"), float(data.get("amount", 10)))
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/reject", methods=["POST"])
    def reject():
        data = request.get_json(force=True)
        ok = bot.reject_pending(data.get("pending_id"))
        return jsonify({"ok": ok})

    @app.route("/api/history")
    def history():
        return jsonify(bot.history[-20:])

    return app
