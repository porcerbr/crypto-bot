# api.py
import os, time, json
from datetime import datetime
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from config import Config
from utils import log, fmt, all_syms, mkt_open, asset_cat, asset_name, contract_size_for, max_leverage_for
from analysis import get_analysis, detect_reversal
from risk import calc_trade_plan, commission_for, get_sl_tp_pct
from news import get_news, get_fear_greed
from dashboard import dashboard_html, sw_js
from db import account_snapshot

def create_api(bot):
    app = Flask(__name__)
    CORS(app)
    @app.after_request
    def cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.route("/")
    def index(): return Response(dashboard_html, mimetype="text/html")
    @app.route("/sw.js")
    def sw(): return Response(sw_js, mimetype="application/javascript")
    @app.route("/icon-192.png")
    @app.route("/icon-512.png")
    def icon():
        size = 192 if "192" in request.path else 512
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="{size//6}" fill="#06090f"/><text x="{size//2}" y="{int(size*.72)}" font-size="{int(size*.55)}" text-anchor="middle" fill="#00e676" font-family="monospace" font-weight="700">S</text></svg>'
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/api/health")
    def api_health(): return jsonify({"status": "ok", "version": "11.0 MODULAR", "broker": Config.BROKER_NAME})

    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        wr = round(bot.wins/total*100, 1) if total > 0 else 0
        now_br = datetime.now(Config.BR_TZ)
        today = now_br.strftime("%d/%m")
        balance = float(bot.balance) or 1.0

        def parse_closed_at(s):
            try:
                parts = s.strip().split(" ")
                d, m = parts[0].split("/")
                return int(m), int(d)
            except: return None, None

        today_trades, week_trades, month_trades = [], [], []
        for h in bot.history:
            ca = h.get("closed_at", "")
            if ca.startswith(today): today_trades.append(h)
            m, d = parse_closed_at(ca)
            if m is not None:
                if m == int(now_br.strftime("%m")):
                    month_trades.append(h)
                    week_day_limit = now_br.day - 7
                    if d > week_day_limit: week_trades.append(h)

        def period_stats(trades):
            usd = round(sum(h.get("pnl_money", 0) for h in trades), 2)
            pct = round(usd / balance * 100, 2) if balance else 0
            wins = sum(1 for h in trades if h.get("result") == "WIN")
            losses = sum(1 for h in trades if h.get("result") == "LOSS")
            return {"usd": usd, "pct": pct, "wins": wins, "losses": losses, "count": len(trades)}

        daily, weekly, monthly = period_stats(today_trades), period_stats(week_trades), period_stats(month_trades)
        snap = account_snapshot(bot)
        trades_out = []
        for t in bot.active_trades:
            try: res = get_analysis(t["symbol"], bot.timeframe); cur = res["price"] if res else t["entry"]
            except: cur = t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            dist_sl = abs(cur - t["sl"]) / abs(t["entry"] - t["sl"]) * 100 if t["entry"] != t["sl"] else 0
            dist_tp = abs(cur - t["tp"]) / abs(t["tp"] - t["entry"]) * 100 if t["tp"] != t["entry"] else 0
            progress = min(max(100 - dist_tp, 0), 100) if t["tp"] != t["entry"] else 0
            lot_rt = float(t.get("lot", Config.MIN_LOT))
            cs_rt  = float(t.get("contract_size", contract_size_for(t["symbol"])))
            if t["dir"] == "BUY":
                pnl_money_rt = (cur - t["entry"]) * cs_rt * lot_rt - t.get("commission", commission_for(t["symbol"], lot_rt))
            else:
                pnl_money_rt = (t["entry"] - cur) * cs_rt * lot_rt - t.get("commission", commission_for(t["symbol"], lot_rt))
            trades_out.append({
                "symbol": t["symbol"], "name": t.get("name", " "), "dir": t["dir"],
                "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                "current": cur, "pnl": round(pnl, 2), "pnl_money": round(pnl_money_rt, 2),
                "opened_at": t.get("opened_at", " "),
                "dist_sl": round(dist_sl, 1), "dist_tp": round(dist_tp, 1), "progress": round(progress, 1),
                "lot": round(lot_rt, 2), "margin_required": round(float(t.get("margin_required", 0)), 2),
                "capital_base": round(float(t.get("capital_base", 0)), 2),
                "commission": round(float(t.get("commission", 0)), 2),
                "sl_pct": t.get("sl_pct", 0), "tp_pct": t.get("tp_pct", 0),
                "max_leverage": max_leverage_for(t["symbol"]),
            })
        sl_pct, tp_pct = get_sl_tp_pct(bot.leverage)
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0, int((bot.paused_until - time.time()) / 60)) if bot.is_paused() else 0,
            "active_trades": trades_out, "pending_count": len(bot.pending_trades),
            "daily_pnl": daily["pct"], "daily_pnl_usd": daily["usd"],
            "daily_wins": daily["wins"], "daily_losses": daily["losses"],
            "today_closed": daily["count"], "history_today": today_trades,
            "weekly_pnl": weekly["pct"], "weekly_pnl_usd": weekly["usd"],
            "weekly_wins": weekly["wins"], "weekly_losses": weekly["losses"],
            "monthly_pnl": monthly["pct"], "monthly_pnl_usd": monthly["usd"],
            "monthly_wins": monthly["wins"], "monthly_losses": monthly["losses"],
            "balance": snap["balance"], "equity": snap["equity"],
            "used_margin": snap["used_margin"], "free_margin": snap["free_margin"],
            "margin_level": snap["margin_level"],
            "leverage": bot.leverage, "risk_pct": bot.risk_pct,
            "margin_call_level": Config.MARGIN_CALL_LEVEL, "stop_out_level": Config.STOP_OUT_LEVEL,
            "broker": Config.BROKER_NAME, "account_type": bot.account_type, "platform": bot.platform,
            "sl_auto": sl_pct, "tp_auto": tp_pct,
        })

    @app.route("/api/trade_plan", methods=["POST"])
    def api_trade_plan():
        data = request.get_json(force=True) or {}
        symbol = data.get("symbol"); entry = data.get("entry"); amount = data.get("amount")
        try: amount = float(amount); entry = float(entry)
        except: return jsonify({"error": "Parâmetros inválidos"}), 400
        plan = calc_trade_plan(symbol, entry, bot.leverage, bot.balance, bot.risk_pct, amount)
        return jsonify(plan)

    @app.route("/api/pending")
    def api_pending():
        snap = account_snapshot(bot)
        pending = []
        for p in bot.pending_trades:
            item = dict(p)
            # Calcula o plano para o lote mínimo e pega a margem mínima
            plan_min = calc_trade_plan(p["symbol"], p["entry"], bot.leverage, bot.balance, bot.risk_pct, Config.MIN_LOT)
            item["min_margin_for_min_lot"] = plan_min.get("min_margin_for_min_lot", 0) if plan_min.get("ok") else None
            item.update({
                "balance": snap["balance"],
                "equity": snap["equity"],
                "used_margin": snap["used_margin"],
                "free_margin": snap["free_margin"],
                "margin_level": snap["margin_level"]
            })
            pending.append(item)
        return jsonify(pending)

    @app.route("/api/execute_pending", methods=["POST", "OPTIONS"])
    def api_execute_pending():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id"); amount = data.get("amount")
        try: amount = float(amount)
        except: return jsonify({"error": "amount inválido"}), 400
        return jsonify({"ok": True}) if bot.execute_pending_with_amount(pid, amount, source="dashboard") else (jsonify({"error": "not found"}), 404)

    @app.route("/api/reject", methods=["POST", "OPTIONS"])
    def api_reject():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}; pid = data.get("pending_id")
        return jsonify({"ok": True}) if bot.reject_pending(pid) else (jsonify({"error": "not found"}), 404)

    @app.route("/api/news")
    def api_news():
        now = time.time()
        if now - bot.news_cache_ts > 600 or not bot.news_cache:
            try: bot.news_cache = {"fg": get_fear_greed(), "articles": get_news(15)}; bot.news_cache_ts = now
            except Exception as e: log(f"[NEWS] {e}")
        return jsonify(bot.news_cache if bot.news_cache else {"fg": {}, "articles": []})

    @app.route("/api/trends")
    def api_trends():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            d = entry["data"]
            out.append({"symbol": sym, "name": d["name"], "category": asset_cat(sym), "price": d["price"],
                        "cenario": d["cenario"], "rsi": round(d["rsi"],1), "adx": round(d["adx"],1),
                        "change_pct": round(d["change_pct"],2)})
        out.sort(key=lambda x: ({"ALTA":0,"BAIXA":1,"NEUTRO":2}.get(x["cenario"],9), -abs(x["change_pct"])))
        return jsonify(out)

    @app.route("/api/reversals")
    def api_reversals():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            rev = entry.get("reversal", {})
            if rev.get("has"):
                d = entry["data"]
                out.append({"symbol": sym, "name": d["name"], "price": d["price"], "rsi": round(d["rsi"],1),
                            "adx": round(d["adx"],1), "direction": rev["dir"], "strength": rev["strength"],
                            "reasons": rev["reasons"]})
        out.sort(key=lambda x: -x["strength"])
        return jsonify(out)

    @app.route("/api/signals")
    def api_signals(): return jsonify(list(reversed(bot.signals_feed)))

    @app.route("/api/config")
    def api_config():
        sl_pct, tp_pct = get_sl_tp_pct(bot.leverage)
        return jsonify({
            "sl_auto": sl_pct, "tp_auto": tp_pct,
            "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE,
            "balance": bot.balance, "leverage": bot.leverage, "risk_pct": bot.risk_pct,
            "broker": Config.BROKER_NAME, "platform": Config.BROKER_PLATFORM,
            "account_type": bot.account_type,
            "margin_call_level": Config.MARGIN_CALL_LEVEL, "stop_out_level": Config.STOP_OUT_LEVEL,
            "commission_rt_forex": Config.COMMISSION_PER_LOT_SIDE["FOREX"] * 2,
            "min_lot": Config.MIN_LOT,
        })

    @app.route("/api/mode", methods=["POST", "OPTIONS"])
    def api_mode():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        mode = data.get("mode", "").strip()
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]:
            return jsonify({"error": "inválido"}), 400
        bot.set_mode(mode)
        return jsonify({"ok": True})

    @app.route("/api/timeframe", methods=["POST", "OPTIONS"])
    def api_timeframe():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe", "").strip()
        if tf not in Config.TIMEFRAMES:
            return jsonify({"error": "inválido"}), 400
        bot.set_timeframe(tf)
        return jsonify({"ok": True})

    @app.route("/api/balance", methods=["POST", "OPTIONS"])
    def api_balance():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        try: value = float(data.get("balance"))
        except: return jsonify({"error": "balance inválido"}), 400
        if value <= 0: return jsonify({"error": "saldo precisa ser maior que zero"}), 400
        bot.set_balance(value)
        return jsonify({"ok": True, "balance": round(bot.balance, 2)})

    @app.route("/api/leverage", methods=["POST", "OPTIONS"])
    def api_leverage():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        try: value = int(data.get("leverage"))
        except: return jsonify({"error": "alavancagem inválida"}), 400
        if value < 1 or value > 1000: return jsonify({"error": "alavancagem deve ser entre 1 e 1000"}), 400
        bot.set_leverage(value)
        return jsonify({"ok": True, "leverage": bot.leverage})

    @app.route("/api/resetpausa", methods=["POST", "OPTIONS"])
    def api_reset():
        if request.method == "OPTIONS": return jsonify({}), 200
        bot.reset_pause(); return jsonify({"ok": True})

    @app.route("/api/vapid-public-key")
    def api_vapid_key(): return jsonify({"key": os.getenv("VAPID_PUBLIC_KEY", "")})

    @app.route("/api/subscribe", methods=["POST", "OPTIONS"])
    def api_subscribe():
        if request.method == "OPTIONS": return jsonify({}), 200
        sub = request.get_json(force=True)
        from bot_core import _push_subscriptions
        if sub and sub not in _push_subscriptions: _push_subscriptions.append(sub)
        return jsonify({"ok": True})

    return app

def run_api(bot):
    port = int(os.getenv("PORT", 8080))
    app = create_api(bot)
    log(f"🌐 Flask rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
