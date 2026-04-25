# api.py
import os
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    # ── Rota do Dashboard (HTML) ────────────────────────────────
    @app.route("/")
    def index():
        try:
            with open("dashboard.html", "r", encoding="utf-8") as f:
                html = f.read()
            return render_template_string(html)
        except FileNotFoundError:
            return "<h1>Dashboard não encontrado</h1><p>Coloque o arquivo dashboard.html na raiz do projeto.</p>", 404

    # ── Status da conta e trades ativos ─────────────────────────
    @app.route("/api/status")
    def status():
        active = []
        for t in bot.active_trades:
            active.append({
                "symbol": t["symbol"],
                "name": t.get("name", ""),
                "dir": t["dir"],
                "entry": t["entry"],
                "sl": t["sl"],
                "tp": t["tp"],
                "lot": t.get("lot", 0),
                "pnl": t.get("pnl", 0),
                "opened_at": t.get("opened_at", ""),
            })
        total = bot.wins + bot.losses
        wr = round(bot.wins / total * 100, 1) if total > 0 else 0
        return jsonify({
            "active_trades": active,
            "pending_count": len(bot.pending_trades),
            "balance": round(bot.balance, 2),
            "leverage": bot.leverage,
            "winrate": wr,
            "wins": bot.wins,
            "losses": bot.losses,
            "mode": bot.mode,
            "timeframe": bot.timeframe,
            "paused": bot.is_paused(),
        })

    # ── Sinais pendentes ────────────────────────────────────────
    @app.route("/api/pending")
    def pending():
        return jsonify(bot.pending_trades)

    # ── Executar sinal pendente ─────────────────────────────────
    @app.route("/api/execute", methods=["POST"])
    def execute():
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "Valor inválido"}), 400
        ok, msg = bot.execute_pending(pid, amount)
        return jsonify({"ok": ok, "message": msg})

    # ── Rejeitar sinal pendente ─────────────────────────────────
    @app.route("/api/reject", methods=["POST"])
    def reject():
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        ok = bot.reject_pending(pid)
        return jsonify({"ok": ok})

    return app
