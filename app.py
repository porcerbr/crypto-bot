"""Dashboard web profissional com Flask e SocketIO.

Fornece interface em tempo real via WebSocket para:
- Status do bot
- Sinais e trades
- Métricas de performance
- Logs e alertas

A arquitetura separa o engine (thread) do servidor web,
comunicando-se via callbacks thread-safe.
"""
import logging
import os
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit

# Adicionar raiz ao path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings
from core.engine import BotState, TradingEngine

logger = logging.getLogger("Dashboard")

# Instância global do engine (compartilhada entre threads)
engine_instance: TradingEngine = None


def create_app() -> Flask:
    """Factory do aplicativo Flask."""
    settings = get_settings()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = settings.secret_key
    CORS(app)

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/health")
    def health():
        """Endpoint de healthcheck para Docker/Railway."""
        if engine_instance is None:
            return jsonify({"status": "no_engine", "timestamp": datetime.now(timezone.utc).isoformat()}), 503
        state = engine_instance.get_state()
        code = 200 if state.status in ("running", "paused") else 503
        return jsonify({
            "status": state.status,
            "uptime": state.uptime_seconds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), code

    @app.route("/api/state")
    def api_state():
        if engine_instance is None:
            return jsonify({"error": "Engine não iniciado"}), 503
        return jsonify(_state_to_dict(engine_instance.get_state()))

    @app.route("/api/trades")
    def api_trades():
        if engine_instance is None:
            return jsonify([])
        from storage.database import TradeDatabase
        db = TradeDatabase()
        return jsonify(db.get_recent_trades(50))

    @app.route("/api/start")
    def api_start():
        if engine_instance:
            engine_instance.start()
            return jsonify({"status": "starting"})
        return jsonify({"error": "Engine não disponível"}), 503

    @app.route("/api/stop")
    def api_stop():
        if engine_instance:
            engine_instance.stop()
            return jsonify({"status": "stopping"})
        return jsonify({"error": "Engine não disponível"}), 503

    @app.route("/api/pause")
    def api_pause():
        if engine_instance:
            engine_instance.pause()
            return jsonify({"status": "paused"})
        return jsonify({"error": "Engine não disponível"}), 503

    @app.route("/api/resume")
    def api_resume():
        if engine_instance:
            engine_instance.resume()
            return jsonify({"status": "resuming"})
        return jsonify({"error": "Engine não disponível"}), 503

    @socketio.on("connect")
    def handle_connect():
        logger.info("Cliente conectado ao dashboard")
        if engine_instance:
            emit("state_update", _state_to_dict(engine_instance.get_state()))

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("Cliente desconectado")

    # Callback para broadcast de estado
    def broadcast_state(state: BotState):
        try:
            socketio.emit("state_update", _state_to_dict(state))
        except Exception as e:
            logger.debug(f"Broadcast ignorado: {e}")

    app.broadcast_state = broadcast_state
    app.socketio = socketio
    return app


def _state_to_dict(state: BotState) -> dict:
    """Serializa estado para JSON."""
    return {
        "status": state.status,
        "symbol": state.symbol,
        "last_update": state.last_update,
        "last_signal": state.last_signal,
        "open_trades": state.open_trades,
        "daily_pnl": round(state.daily_pnl, 2),
        "weekly_pnl": round(state.weekly_pnl, 2),
        "monthly_pnl": round(state.monthly_pnl, 2),
        "total_trades": state.total_trades,
        "win_count": state.win_count,
        "loss_count": state.loss_count,
        "win_rate": round(state.win_rate, 1),
        "active_filters": state.active_filters,
        "recent_errors": state.recent_errors,
        "alerts": state.alerts,
        "uptime_seconds": int(state.uptime_seconds),
    }


def run_dashboard(engine: TradingEngine):
    """Inicia o servidor web vinculado ao engine."""
    global engine_instance
    engine_instance = engine

    settings = get_settings()
    app = create_app()

    # Registrar callback do engine para broadcast
    engine.register_callback(app.broadcast_state)

    logger.info(f"Iniciando dashboard em {settings.dashboard_host}:{settings.dashboard_port}")
    app.socketio.run(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        debug=settings.dashboard_debug,
        use_reloader=False,  # Crucial: evita double-start em debug
    )
