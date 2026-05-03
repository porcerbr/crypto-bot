"""
api.py — Endpoints HTTP do Sniper Bot (modo sinalizador).

SEGURANÇA:
  Todos os endpoints /api/* exigem o header:
    Authorization: Bearer <DASHBOARD_API_TOKEN>
  ou o query param:
    ?token=<DASHBOARD_API_TOKEN>

  Se DASHBOARD_API_TOKEN estiver vazio, a API opera sem autenticação
  (útil em desenvolvimento local, mas NÃO recomendado em produção).
"""

import os
import functools
from pathlib import Path
from flask import Flask, jsonify, request, Response

from config import Config
from utils import (
    calc_pnl_usd,
    calc_pnl_pips,
    pip_factor,
    is_jpy_pair,
    get_allowed_symbols,
    get_selected_symbols,
    save_asset_settings,
    load_trade_settings,
    save_trade_settings,
    get_trade_limit_override,
    get_dynamic_max_trades,
)


def _get_cached_price(symbol: str, fallback: float) -> float:
    """Lê o último Close do cache local. Se falhar, usa fallback."""
    try:
        from analysis import _cache
        if symbol in _cache:
            return float(_cache[symbol][1]["Close"].iloc[-1])
    except Exception:
        pass
    return fallback


def _get_usdjpy_price() -> float:
    """Cotação USDJPY do cache — usada para converter P&L de pares JPY."""
    return _get_cached_price("USDJPY", 150.0)


def _check_token() -> bool:
    """Valida token de autenticação. Retorna True se OK ou se token não configurado."""
    expected = Config.DASHBOARD_API_TOKEN
    if not expected:
        return True   # modo dev: sem token configurado = aberto

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == expected
    return request.args.get("token", "") == expected


def require_auth(f):
    """Decorator que exige autenticação em todos os endpoints /api/*."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not _check_token():
            return jsonify({"error": "Unauthorized — token inválido ou ausente"}), 401
        return f(*args, **kwargs)
    return wrapper


def create_api(bot):
    app = Flask(__name__)

    # ═══════════════════════════════════════════════════════════════════════════════
    # DASHBOARD HTML
    # ═══════════════════════════════════════════════════════════════════════════════
    _dashboard_candidates = [
        Path(__file__).with_name("dashboard.html"),
        Path.cwd() / "dashboard.html",
    ]

    def _load_dashboard_html() -> str:
        for candidate in _dashboard_candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    html = candidate.read_text(encoding="utf-8")
                    if html.strip():
                        return html
            except Exception:
                continue

        return """<!doctype html>
<html lang='pt-BR'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <title>Sniper Bot Dashboard</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0f14;color:#e6edf3;margin:0;padding:32px}
    .card{max-width:720px;margin:48px auto;background:#111827;border:1px solid #253041;border-radius:20px;padding:24px;box-shadow:0 20px 80px rgba(0,0,0,.35)}
    h1{margin:0 0 8px;font-size:28px} p{color:#a7b4c3;line-height:1.6}
    code{background:#0f1720;padding:2px 6px;border-radius:6px}
  </style>
</head>
<body>
  <div class='card'>
    <h1>Dashboard indisponível</h1>
    <p>O arquivo <code>dashboard.html</code> não foi encontrado no deploy atual.</p>
    <p>Coloque o arquivo na raiz do projeto ou acesse <code>/api/health</code> para confirmar que o bot está vivo.</p>
  </div>
</body>
</html>"""

    def _dashboard_response():
        html = _load_dashboard_html()
        return Response(html, content_type="text/html; charset=utf-8")

    @app.route("/")
    @app.route("/dashboard")
    @app.route("/dashboard.html")
    def index():
        return _dashboard_response()

    @app.route("/api/status")
    @require_auth
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

        # Segurança dinâmica + drawdown
        from utils import get_dynamic_leverage
        from db import calculate_metrics

        try:
            metrics = calculate_metrics(bot)
            drawdown_pct = metrics.get("drawdown_pct", 0)
            max_drawdown_pct = metrics.get("max_drawdown_pct", 0)
        except Exception:
            drawdown_pct = 0
            max_drawdown_pct = 0

        max_trades_allowed = get_dynamic_max_trades(bot.balance)
        max_trades_override = get_trade_limit_override()
        trade_limit_source = "auto" if max_trades_override is None else "manual"

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

            # Segurança dinâmica
            "dynamic_leverage":    get_dynamic_leverage(bot.balance),
            "max_trades_allowed":  max_trades_allowed,
            "max_trades_default":  Config.MAX_TRADES,
            "max_trades_override": max_trades_override,
            "max_trades_source":   trade_limit_source,
            "allowed_symbols":     get_allowed_symbols(bot.balance),
            "selected_symbols":    get_selected_symbols(),
            "consecutive_losses":  bot.consecutive_losses,

            # Drawdown — exigido pelo dashboard
            "drawdown_pct":        drawdown_pct,
            "max_drawdown_pct":    max_drawdown_pct,
        })

    @app.route("/api/assets", methods=["GET", "POST"])
    @require_auth
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


    @app.route("/api/trade-settings", methods=["GET", "POST"])
    @require_auth
    def trade_settings():
        if request.method == "GET":
            settings = load_trade_settings()
            return jsonify({
                "ok": True,
                "settings": settings,
                "max_active_trades": settings.get("max_active_trades"),
                "mode": "auto" if settings.get("max_active_trades") is None else "manual",
                "default_max_active_trades": Config.MAX_TRADES,
                "max_manual_active_trades": 10,
            })

        data = request.get_json(force=True) or {}
        raw = data.get("max_active_trades", data.get("trade_limit"))

        if raw in (None, "", "auto", "AUTO"):
            saved = save_trade_settings(None)
        else:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "message": "max_active_trades inválido"}), 400
            saved = save_trade_settings(value)

        current = saved.get("max_active_trades")
        return jsonify({
            "ok": True,
            "message": "Limite de trades atualizado",
            "settings": saved,
            "max_active_trades": current,
            "mode": "auto" if current is None else "manual",
            "default_max_active_trades": Config.MAX_TRADES,
            "max_manual_active_trades": 10,
        })

    @app.route("/api/pending")
    @require_auth
    def pending():
        try:
            return jsonify(list(getattr(bot, "pending_trades", []) or []))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "pending": []})

    @app.route("/api/execute", methods=["POST"])
    @require_auth
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
    @require_auth
    def reject():
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        ok = bot.reject_pending(pid)
        return jsonify({"ok": ok})

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # FECHAMENTO MANUAL \u2014 com P&L real
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @app.route("/api/close_trade", methods=["POST"])
    @require_auth
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
    @require_auth
    def history():
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = max(1, min(limit, 500))
            return jsonify(list(getattr(bot, "history", [])[-limit:]))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "history": []})

    @app.route("/api/logs")
    @require_auth
    def logs():
        try:
            from db import get_recent_logs
            entry_type = request.args.get("type")
            hours = request.args.get("hours", 24, type=int)
            limit = request.args.get("limit", 100, type=int)

            logs_data = get_recent_logs(entry_type=entry_type, hours=hours, limit=limit)
            return jsonify({
                "ok": True,
                "logs": logs_data,
                "count": len(logs_data),
                "filter": {"type": entry_type, "hours": hours},
            })
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": str(e),
                "logs": [],
                "count": 0,
                "filter": {"type": request.args.get("type"), "hours": request.args.get("hours", 24, type=int)},
            })

    @app.route("/api/metrics")
    @require_auth
    def metrics():
        try:
            from db import calculate_metrics, load_metrics
            current = calculate_metrics(bot)
            saved = load_metrics()
            return jsonify({
                "ok": True,
                "current": current,
                "last_saved": saved.get("updated_at") if saved else None,
                "initial_balance": Config.INITIAL_BALANCE,
            })
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": str(e),
                "current": {},
                "last_saved": None,
                "initial_balance": Config.INITIAL_BALANCE,
            })

    @app.route("/api/equity_curve")
    @require_auth
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
    @require_auth
    def force_save():
        try:
            from db import save_state
            save_state(bot)
            return jsonify({"ok": True, "message": "Estado salvo com sucesso"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)})

    @app.route("/api/ai_params")
    @require_auth
    def ai_params():
        defaults = {
            "live_confluence": Config.MIN_CONFLUENCE,
            "strategy_bias": "balanced",
            "live_regime": "neutral",
            "live_adx_avg": 0,
            "min_rr": Config.REGIME_MIN_RR.get("neutral", Config.TP_SL_RATIO),
            "opus_summary": "IA indisponível no momento.",
            "last_suggestion": "",
        }
        try:
            from ai_validator import load_ai_params
            data = load_ai_params() or {}
            defaults.update(data)
            defaults["ok"] = True
            return jsonify(defaults)
        except Exception as e:
            defaults["ok"] = False
            defaults["error"] = str(e)
            return jsonify(defaults)

    @app.route("/api/confluence")
    @require_auth
    def confluence():
        try:
            from signals import get_confluence_snapshot
            snapshot = get_confluence_snapshot()
            allowed  = get_allowed_symbols(bot.balance)
            for item in snapshot:
                item["locked"] = item["symbol"] not in allowed
            return jsonify(snapshot)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "confluence": []})

    @app.route("/api/health")
    @require_auth
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

    @app.route("/api/backtest/upload", methods=["POST"])
    @require_auth
    def backtest_upload():
        """
        Aceita CSV do Investing.com (formato PT-BR) e roda backtest.
        Multipart: arquivo 'csv' + campo 'symbol' (opcional — autodetecta).
        """
        try:
            from csv_parser import parse_investing_csv, detect_symbol
            from backtester import run_backtest, bars_from_dicts, detect_timeframe

            # Lê arquivo
            if "csv" not in request.files:
                return jsonify({"ok": False, "error": "Nenhum arquivo 'csv' enviado"}), 400

            file    = request.files["csv"]
            content = file.read()
            if not content:
                return jsonify({"ok": False, "error": "Arquivo vazio"}), 400

            # Parse do formato Investing.com
            raw_bars = parse_investing_csv(content)
            if len(raw_bars) < 30:
                return jsonify({
                    "ok":    False,
                    "error": f"Apenas {len(raw_bars)} barras válidas. Verifique se o arquivo é do Investing.com."
                }), 400

            # Símbolo: do form ou autodetectado
            symbol = (request.form.get("symbol") or "").upper().strip()
            if not symbol:
                symbol = detect_symbol(raw_bars) or "EURUSD"

            from analysis import TD_SYMBOLS
            if symbol not in TD_SYMBOLS and symbol not in ["USDCHF"]:
                symbol = detect_symbol(raw_bars) or "EURUSD"

            balance        = float(request.form.get("balance",       Config.INITIAL_BALANCE))
            min_confluence = int(request.form.get("min_confluence",  5))

            bars = bars_from_dicts(raw_bars)
            tf   = detect_timeframe(bars)

            result = run_backtest(
                bars,
                symbol=symbol,
                initial_balance=balance,
                min_confluence=min_confluence,
            )

            m  = result.metrics
            ec = result.equity_curve

            if not ec and result.trades:
                bal = balance
                ec  = [{"i": 0, "balance": round(bal, 2)}]
                for i_t, t in enumerate(result.trades, 1):
                    bal += t.get("pnl", 0)
                    ec.append({"i": i_t, "balance": round(bal, 2)})

            return jsonify({
                "ok":             True,
                "symbol":         symbol,
                "timeframe":      tf,
                "bars":           len(bars),
                "start":          bars[0].timestamp.strftime("%d/%m/%Y"),
                "end":            bars[-1].timestamp.strftime("%d/%m/%Y"),
                "balance":        balance,
                "min_confluence": min_confluence,
                "metrics": {
                    "total_trades":     m.get("total_trades",     0),
                    "wins":             m.get("wins",             0),
                    "losses":           m.get("losses",           0),
                    "winrate":          m.get("winrate",          0),
                    "profit_factor":    m.get("profit_factor",    0),
                    "expectancy":       m.get("expectancy",       0),
                    "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                    "sharpe_ratio":     m.get("sharpe_ratio",     0),
                    "initial_balance":  m.get("initial_balance",  balance),
                    "current_balance":  m.get("current_balance",  balance),
                    "total_pnl":        m.get("total_pnl",        0),
                },
                "equity_curve": ec,
                "trades":        result.trades[-100:],
            })

        except Exception as e:
            import traceback
            log(f"[BACKTEST-UPLOAD] Erro: {e}\n{traceback.format_exc()}")
            return jsonify({"ok": False, "error": f"Erro interno: {str(e)}"}), 500

    @app.route("/api/backtest/test")
    @require_auth
    def backtest_test():
        """Endpoint de diagnóstico — testa fonte de dados do backtest."""
        from analysis import TD_SYMBOLS
        results = {
            "twelve_data_key": "configurada" if Config.TWELVE_DATA_API_KEY else "AUSENTE",
            "symbols_supported": list(TD_SYMBOLS.keys()),
        }
        # Testa uma chamada real ao Twelve Data
        if Config.TWELVE_DATA_API_KEY:
            try:
                import requests as req_lib
                resp = req_lib.get(
                    "https://api.twelvedata.com/time_series",
                    params={
                        "symbol":     "EUR/USD",
                        "interval":   "1h",
                        "outputsize": 5,
                        "apikey":     Config.TWELVE_DATA_API_KEY,
                        "format":     "JSON",
                    },
                    timeout=10,
                )
                data = resp.json()
                ok = "values" in data and len(data["values"]) > 0
                results["twelve_data_test"] = {
                    "ok":   ok,
                    "bars": len(data.get("values", [])),
                    "status": data.get("status", ""),
                }
            except Exception as e:
                results["twelve_data_test"] = {"ok": False, "error": str(e)}
        return jsonify({"ok": True, "diagnostics": results})

    def _fetch_twelvedata_for_backtest(symbol: str, outputsize: int = 5000) -> list:
        """
        Busca dados históricos do Twelve Data para backtest.
        Retorna lista de dicts com open/high/low/close/datetime.
        outputsize máximo: 5000 barras H1 ≈ 7 meses de histórico.
        """
        from analysis import TD_SYMBOLS
        import requests as req_lib

        td_sym = TD_SYMBOLS.get(symbol)
        if not td_sym or not Config.TWELVE_DATA_API_KEY:
            return []

        try:
            resp = req_lib.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol":     td_sym,
                    "interval":   "1h",
                    "outputsize": outputsize,
                    "apikey":     Config.TWELVE_DATA_API_KEY,
                    "format":     "JSON",
                    "timezone":   "UTC",
                },
                timeout=30,
            )
            data = resp.json()
            if data.get("status") == "error":
                log(f"[BACKTEST] Twelve Data erro: {data.get('message', '')}")
                return []
            return list(reversed(data.get("values", [])))  # mais antigo primeiro
        except Exception as e:
            log(f"[BACKTEST] Falha ao buscar Twelve Data: {e}")
            return []

    @app.route("/api/backtest", methods=["POST"])
    @require_auth
    def run_backtest_endpoint():
        """
        Busca dados históricos via Twelve Data e roda o backtester integrado.
        Body JSON: { symbol, outputsize, balance, min_confluence }
        """
        try:
            from backtester import run_backtest, Bar
        except Exception as e:
            return jsonify({"ok": False, "error": f"Erro ao carregar backtester: {e}"}), 500

        try:
            body           = request.get_json(force=True, silent=True) or {}
            symbol         = str(body.get("symbol",         "EURUSD")).upper().strip()
            outputsize     = int(body.get("outputsize",     5000))
            balance        = float(body.get("balance",      Config.INITIAL_BALANCE))
            min_confluence = int(body.get("min_confluence", 6))

            # Limites de segurança
            outputsize = max(200, min(outputsize, 5000))

            from analysis import TD_SYMBOLS
            if symbol not in TD_SYMBOLS:
                return jsonify({"ok": False, "error": f"Símbolo {symbol} não suportado"}), 400

            if not Config.TWELVE_DATA_API_KEY:
                return jsonify({"ok": False,
                                "error": "TWELVE_DATA_API_KEY não configurada no Railway"}), 500

            # ── Busca dados ───────────────────────────────────────────────────
            raw = _fetch_twelvedata_for_backtest(symbol, outputsize)
            if not raw:
                return jsonify({"ok": False,
                                "error": "Twelve Data não retornou dados. "
                                         "Verifique se TWELVE_DATA_API_KEY está correta."}), 400

            # ── Converte para lista de Bar ────────────────────────────────────
            from datetime import datetime, timezone
            bars = []
            for row in raw:
                try:
                    bars.append(Bar(
                        timestamp=datetime.strptime(
                            row["datetime"], "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=timezone.utc),
                        open= float(row["open"]),
                        high= float(row["high"]),
                        low=  float(row["low"]),
                        close=float(row["close"]),
                    ))
                except Exception:
                    continue

            if len(bars) < 100:
                return jsonify({"ok": False,
                                "error": f"Apenas {len(bars)} barras válidas — dados insuficientes"}), 400

            # ── Roda backtest ─────────────────────────────────────────────────
            result = run_backtest(
                bars,
                symbol=symbol,
                initial_balance=balance,
                min_confluence=min_confluence,
                warmup_bars=60,
            )

            m  = result.metrics
            ec = result.equity_curve

            if not ec and result.trades:
                bal = balance
                ec  = [{"i": 0, "balance": round(bal, 2)}]
                for i, t in enumerate(result.trades, 1):
                    bal += t.get("pnl", 0)
                    ec.append({"i": i, "balance": round(bal, 2)})

            # Período aproximado
            period_label = f"~{round(len(bars)/24/5)} semanas H1"

            return jsonify({
                "ok":             True,
                "symbol":         symbol,
                "period":         period_label,
                "interval":       "1h",
                "bars":           len(bars),
                "start":          bars[0].timestamp.strftime("%d/%m/%Y"),
                "end":            bars[-1].timestamp.strftime("%d/%m/%Y"),
                "balance":        balance,
                "min_confluence": min_confluence,
                "metrics": {
                    "total_trades":     m.get("total_trades",     0),
                    "wins":             m.get("wins",             0),
                    "losses":           m.get("losses",           0),
                    "winrate":          m.get("winrate",          0),
                    "profit_factor":    m.get("profit_factor",    0),
                    "expectancy":       m.get("expectancy",       0),
                    "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                    "sharpe_ratio":     m.get("sharpe_ratio",     0),
                    "initial_balance":  m.get("initial_balance",  balance),
                    "current_balance":  m.get("current_balance",  balance),
                    "total_pnl":        m.get("total_pnl",        0),
                },
                "equity_curve": ec,
                "trades":        result.trades[-50:],
            })

        except Exception as e:
            import traceback
            log(f"[BACKTEST] Erro: {e}\n{traceback.format_exc()}")
            return jsonify({"ok": False, "error": f"Erro interno: {str(e)}"}), 500
        """Endpoint de diagnóstico — testa conectividade com Yahoo Finance."""
        results = {}
        try:
            import yfinance as yf
            import requests as req_lib
            results["yfinance_version"] = yf.__version__

            session = req_lib.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/json,*/*",
            })

            # Testa download com session customizada
            try:
                df = yf.download("EURUSD=X", period="1mo", interval="1h",
                                 progress=False, session=session)
                results["download_with_session"] = {
                    "ok":      df is not None and len(df) > 0,
                    "rows":    len(df) if df is not None else 0,
                    "columns": list(df.columns) if df is not None else [],
                }
            except Exception as e:
                results["download_with_session"] = {"ok": False, "error": str(e)}

            # Testa sem session (para comparar)
            try:
                df2 = yf.download("EURUSD=X", period="1mo", interval="1h", progress=False)
                results["download_no_session"] = {
                    "ok":   df2 is not None and len(df2) > 0,
                    "rows": len(df2) if df2 is not None else 0,
                }
            except Exception as e:
                results["download_no_session"] = {"ok": False, "error": str(e)}

        except ImportError as e:
            return jsonify({"ok": False, "error": f"yfinance não instalado: {e}"})

        return jsonify({"ok": True, "diagnostics": results})


    return app
