
"""
api.py \u2014 Endpoints HTTP do Sniper Bot (modo sinalizador).

Todos os n\u00fameros de saldo / P&L s\u00e3o SIMULADOS para estat\u00edstica.
Este bot n\u00e3o executa ordens em corretora real.
"""

import os
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

from config import Config
from utils import (
    calc_pnl_usd,
    calc_pnl_pips,
    pip_factor,
    is_jpy_pair,
    get_allowed_symbols,
    get_selected_symbols,
    save_asset_settings,
)


def _get_cached_price(symbol: str, fallback: float) -> float:
    """L\u00ea o \u00faltimo Close do cache local. Se falhar, usa fallback."""
    try:
        from analysis import _cache
        if symbol in _cache:
            return float(_cache[symbol][1]["Close"].iloc[-1])
    except Exception:
        pass
    return fallback


def _get_usdjpy_price() -> float:
    """Cota\u00e7\u00e3o USDJPY do cache \u2014 usada para converter P&L de pares JPY."""
    return _get_cached_price("USDJPY", 150.0)


def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # DASHBOARD HTML
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    _dashboard_path = Path(__file__).with_name("dashboard.html")

    @app.route("/")
    @app.route("/dashboard")
    def index():
        try:
            html = _dashboard_path.read_text(encoding="utf-8")
            return render_template_string(html)
        except FileNotFoundError:
            return (
                "<h1>Dashboard não encontrado</h1>"
                "<p>Coloque o arquivo dashboard.html na mesma pasta de api.py.</p>"
            ), 404

    # STATUS \u2014 estado geral + trades ativos com P&L unificado
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app.route("/api/status")
    def status():
        usdjpy = _get_usdjpy_price()
        active = []

        for t in bot.active_trades:
            sym   = t["symbol"]
            entry = t["entry"]
            sl    = t["sl"]
            tp    = t["tp"]
            lot   = t.get("lot", 0.01)
            direction = t.get("dir") or t.get("direction") or t.get("direc", "—")
            margin = t.get("margin_required", 0)

            cur_price = _get_cached_price(sym, entry)
            pf = pip_factor(sym)

            # P&L unificado (mesma fun\u00e7\u00e3o usada em bot.close_trade)
            pnl_usd = round(
                calc_pnl_usd(sym, direction, entry, cur_price, lot, usdjpy_price=usdjpy),
                2,
            )
            pnl_pips = calc_pnl_pips(sym, direction, entry, cur_price)
            pnl_pct  = round(pnl_usd / margin * 100, 1) if margin > 0 else 0.0

            # Dist\u00e2ncias em pips (sempre positivas)
            sl_dist_pips = round(abs(cur_price - sl) / pf, 1)
            tp_dist_pips = round(abs(tp - cur_price) / pf, 1)

            # Progresso at\u00e9 TP (0\u2013100%), considerando dire\u00e7\u00e3o
            total_range = abs(tp - entry)
            if direction == "BUY":
                moved = max(0, cur_price - entry)
            else:
                moved = max(0, entry - cur_price)
            tp_progress = round(min(moved / total_range * 100, 100), 1) if total_range > 0 else 0.0

            active.append({
                "symbol":             sym,
                "name":               t.get("name", ""),
                "dir":                direction,
                "entry":              entry,
                "sl":                 sl,
                "tp":                 tp,
                "lot":                lot,
                "margin_required":    margin,
                "current_price":      cur_price,
                "pnl":                pnl_usd,
                "pnl_pct":            pnl_pct,
                "pnl_pips":           pnl_pips,
                "sl_dist_pips":       sl_dist_pips,
                "tp_dist_pips":       tp_dist_pips,
                "tp_progress":        tp_progress,
                "opened_at":          t.get("opened_at", ""),
                "effective_leverage": t.get("effective_leverage", bot.leverage),
                "trailing_activated": t.get("trailing_activated", False),
                "score":              t.get("score", 0),
                "score_total":        t.get("score_total", 0),
                "rr":                 t.get("rr", 0),
                "ai_confidence":      t.get("ai_confidence", 0),
            })

        total = bot.wins + bot.losses
        wr    = round(bot.wins / total * 100, 1) if total > 0 else 0

        # Seguran\u00e7a din\u00e2mica + drawdown
        from utils import get_dynamic_leverage, get_dynamic_max_trades
        from db import calculate_metrics

        try:
            metrics = calculate_metrics(bot)
            drawdown_pct = metrics.get("drawdown_pct", 0)
            max_drawdown_pct = metrics.get("max_drawdown_pct", 0)
        except Exception:
            drawdown_pct = 0
            max_drawdown_pct = 0

        return jsonify({
            # Trades
            "active_trades":       active,
            "pending_count":       len(bot.pending_trades),

            # Conta (simulada)
            "balance":             round(bot.balance, 2),
            "initial_balance":     Config.INITIAL_BALANCE,
            "leverage":            bot.get_current_leverage(),
            "winrate":             wr,
            "wins":                bot.wins,
            "losses":              bot.losses,

            # Modo / status
            "mode":                bot.mode,
            "timeframe":           bot.timeframe,
            "paused":              bot.is_paused(),
            "signal_only":         Config.BOT_IS_SIGNAL_ONLY,

            # Seguran\u00e7a din\u00e2mica
            "dynamic_leverage":    get_dynamic_leverage(bot.balance),
            "max_trades_allowed":  get_dynamic_max_trades(bot.balance),
            "allowed_symbols":     get_allowed_symbols(bot.balance),
            "selected_symbols":    get_selected_symbols(),
            "consecutive_losses":  bot.consecutive_losses,

            # Drawdown \u2014 exigido pelo dashboard
            "drawdown_pct":        drawdown_pct,
            "max_drawdown_pct":    max_drawdown_pct,
        })

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # PENDENTES
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app.route("/api/assets", methods=["GET", "POST"])
    def assets():
        from config import Config

        if request.method == "GET":
            allowed = set(get_allowed_symbols(bot.balance))
            selected = set(get_selected_symbols())
            data = []
            for sym, label in Config.FXGOLD_ASSETS.items():
                data.append({
                    "symbol": sym,
                    "name": label,
                    "selected": sym in selected,
                    "allowed": sym in allowed,
                })
            return jsonify({
                "assets": data,
                "selected_symbols": list(selected),
                "allowed_symbols": list(allowed),
            })

        data = request.get_json(force=True) or {}
        selected = data.get("selected_symbols")
        if not isinstance(selected, list):
            return jsonify({"ok": False, "message": "selected_symbols inválido"}), 400

        saved = save_asset_settings(selected)
        return jsonify({
            "ok": True,
            "message": "Ativos atualizados",
            "selected_symbols": saved["selected_symbols"],
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
            return jsonify({"ok": False, "message": "Valor inv\u00e1lido"}), 400
        ok, msg = bot.execute_pending(pid, amount)
        return jsonify({"ok": ok, "message": msg})

    @app.route("/api/reject", methods=["POST"])
    def reject():
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        ok = bot.reject_pending(pid)
        return jsonify({"ok": ok})

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # FECHAMENTO MANUAL \u2014 com P&L real
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app.route("/api/close_trade", methods=["POST"])
    def close_trade():
        """Fecha um trade ativo manualmente pelo s\u00edmbolo."""
        data   = request.get_json(force=True) or {}
        symbol = data.get("symbol")
        if not symbol:
            return jsonify({"ok": False, "message": "S\u00edmbolo n\u00e3o informado"}), 400

        trade = next((t for t in bot.active_trades if t["symbol"] == symbol), None)
        if not trade:
            return jsonify({"ok": False, "message": f"Trade {symbol} n\u00e3o encontrado"}), 404

        cur_price = _get_cached_price(symbol, trade["entry"])
        usdjpy    = _get_usdjpy_price()

        # \ud83d\udd34 FIX: decidir WIN/LOSS pelo P&L real, n\u00e3o pelo pre\u00e7o bruto.
        pnl_usd = calc_pnl_usd(
            trade["symbol"], trade["dir"],
            trade["entry"], cur_price,
            trade.get("lot", 0.01),
            usdjpy_price=usdjpy,
        )
        result = "WIN" if pnl_usd > 0 else "LOSS"

        bot.close_trade(trade, cur_price, result)
        return jsonify({
            "ok": True,
            "message": f"Trade {symbol} fechado manualmente ({result}, P&L ${pnl_usd:+.2f})",
            "pnl": round(pnl_usd, 2),
        })

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # HIST\u00d3RICO / LOGS / M\u00c9TRICAS
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app.route("/api/history")
    def history():
        limit = request.args.get("limit", 20, type=int)
        limit = max(1, min(limit, 500))
        return jsonify(bot.history[-limit:])

    @app.route("/api/logs")
    def logs():
        from db import get_recent_logs
        entry_type = request.args.get("type")
        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 100, type=int)

        logs_data = get_recent_logs(entry_type=entry_type, hours=hours, limit=limit)
        return jsonify({
            "logs":   logs_data,
            "count":  len(logs_data),
            "filter": {"type": entry_type, "hours": hours},
        })

    @app.route("/api/metrics")
    def metrics():
        from db import calculate_metrics, load_metrics
        current = calculate_metrics(bot)
        saved   = load_metrics()
        return jsonify({
            "current":         current,
            "last_saved":      saved.get("updated_at") if saved else None,
            "initial_balance": Config.INITIAL_BALANCE,
        })

    @app.route("/api/equity_curve")
    def equity_curve():
        """Curva de equity \u2014 usada pelo dashboard para gr\u00e1fico."""
        try:
            from db import load_equity_curve
            curve = load_equity_curve()
        except Exception:
            # Fallback: reconstr\u00f3i da history
            curve = []
            balance = Config.INITIAL_BALANCE
            for h in bot.history:
                balance += h.get("pnl", 0)
                curve.append({
                    "t":       h.get("closed_at", ""),
                    "balance": round(balance, 2),
                    "pnl":     h.get("pnl", 0),
                })
        return jsonify(curve)

    @app.route("/api/force-save", methods=["POST"])
    def force_save():
        from db import save_state
        try:
            save_state(bot)
            return jsonify({"ok": True, "message": "Estado salvo com sucesso"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    @app.route("/api/ai_params")
    def ai_params():
        try:
            from ai_validator import load_ai_params
            return jsonify(load_ai_params())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/confluence")
    def confluence():
        try:
            from signals import get_confluence_snapshot
            snapshot = get_confluence_snapshot()
            allowed  = get_allowed_symbols(bot.balance)
            for item in snapshot:
                item["locked"] = item["symbol"] not in allowed
            return jsonify(snapshot)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/health")
    def health():
        """Endpoint leve para Railway health-check."""
        return jsonify({
            "ok":          True,
            "balance":     round(bot.balance, 2),
            "active":      len(bot.active_trades),
            "pending":     len(bot.pending_trades),
            "paused":      bot.is_paused(),
            "signal_only": Config.BOT_IS_SIGNAL_ONLY,
        })

    return app
