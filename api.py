import os
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        try:
            with open("dashboard.html", "r", encoding="utf-8") as f:
                html = f.read()
            return render_template_string(html)
        except FileNotFoundError:
            return "<h1>Dashboard não encontrado</h1><p>Coloque o arquivo dashboard.html na raiz do projeto.</p>", 404

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
                "effective_leverage": t.get("effective_leverage", bot.leverage),
            })
        total = bot.wins + bot.losses
        wr = round(bot.wins / total * 100, 1) if total > 0 else 0

        # NOVO: Informações de segurança dinâmica
        from utils import get_dynamic_leverage, get_dynamic_max_trades, get_allowed_symbols

        return jsonify({
            "active_trades": active,
            "pending_count": len(bot.pending_trades),
            "balance": round(bot.balance, 2),
            "leverage": bot.get_current_leverage(),
            "winrate": wr,
            "wins": bot.wins,
            "losses": bot.losses,
            "mode": bot.mode,
            "timeframe": bot.timeframe,
            "paused": bot.is_paused(),
            # NOVO: Dados de segurança
            "dynamic_leverage": get_dynamic_leverage(bot.balance),
            "max_trades_allowed": get_dynamic_max_trades(bot.balance),
            "allowed_symbols": get_allowed_symbols(bot.balance),
            "consecutive_losses": bot.consecutive_losses,
        })

    @app.route("/api/pending")
    def pending():
        return jsonify(bot.pending_trades)

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

    @app.route("/api/reject", methods=["POST"])
    def reject():
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        ok = bot.reject_pending(pid)
        return jsonify({"ok": ok})

    @app.route("/api/history")
    def history():
        return jsonify(bot.history[-20:])

    # ═══════════════════════════════════════════════════════════
    # NOVOS ENDPOINTS: Logs e Métricas
    # ═══════════════════════════════════════════════════════════

    @app.route("/api/logs")
    def logs():
        """Retorna logs recentes do bot."""
        from db import get_recent_logs
        entry_type = request.args.get("type")
        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 100, type=int)

        logs_data = get_recent_logs(entry_type=entry_type, hours=hours, limit=limit)
        return jsonify({
            "logs": logs_data,
            "count": len(logs_data),
            "filter": {"type": entry_type, "hours": hours}
        })

    @app.route("/api/metrics")
    def metrics():
        """Retorna métricas de performance calculadas."""
        from db import calculate_metrics, load_metrics

        current = calculate_metrics(bot)
        saved = load_metrics()

        return jsonify({
            "current": current,
            "last_saved": saved.get("updated_at") if saved else None,
            "initial_balance": Config.INITIAL_BALANCE,
        })

    @app.route("/api/force-save", methods=["POST"])
    def force_save():
        """Força salvamento do estado imediatamente."""
        from db import save_state
        try:
            save_state(bot)
            return jsonify({"ok": True, "message": "Estado salvo com sucesso"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    return app
