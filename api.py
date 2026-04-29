from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return render_template_string(f.read())

    @app.route("/api/status")
    def status():
        return jsonify({
            "balance": round(bot.balance, 2),
            "wins": bot.wins,
            "losses": bot.losses,
            "active_trades": bot.active_trades,
            "mode": bot.mode,
            "leverage": bot.get_current_leverage()
        })

    @app.route("/api/metrics")
    def metrics():
        from db import calculate_metrics, save_metrics
        m = calculate_metrics(bot)
        save_metrics(m) # Isso resolve o problema de persistência
        return jsonify({"current": m})

    @app.route("/api/logs")
    def logs():
        from db import get_recent_logs
        return jsonify({"logs": get_recent_logs()})

    return app
