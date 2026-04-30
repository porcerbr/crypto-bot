"""
main.py — Entrypoint do Sniper Bot (somente sinais).

Responsabilidades:
  • Carregar estado (state.json → memória do bot)
  • Disparar thread do loop principal
  • Subir API Flask (dashboard e endpoints)
  • Agendar heartbeat, relatório diário, aprendizado semanal e mensal
  • Processar comandos do Telegram (/executar_, /confluencia)

⚠️  Este bot é SINALIZADOR: ele NÃO executa ordens em corretora real.
    Todos os cálculos de saldo / P&L são simulados para fins de estatística.
"""

import sys
import time
import threading
import traceback
import os
import schedule
from datetime import datetime, timezone

import requests

from config import Config
from utils import log
from db import load_state, append_log, save_metrics, calculate_metrics
from bot import TradingBot
from signals import scan
from api import create_api

# Pandas .ewm() em séries longas pode aprofundar a pilha — aumenta o limite
sys.setrecursionlimit(5000)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES DE CICLO
# ═══════════════════════════════════════════════════════════════════════════════
HEARTBEAT_INTERVAL  = 3600          # 1 h
DAILY_REPORT_HOUR   = 21            # 21:00 UTC
WEEK_SECS           = 7  * 24 * 3600
MONTH_SECS          = 30 * 24 * 3600
SCAN_INTERVAL       = 60            # Padrão do Config
STARTUP_NOTIFICATION = True

# Agendador de tarefas assíncronas
scheduler_thread = None


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICAÇÕES
# ═══════════════════════════════════════════════════════════════════════════════

def send_startup_notification(bot):
    """Envia notificação de inicialização com resumo do estado."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    msg = (
        "🚀 SNIPER BOT INICIADO\
"
        "------------------------------\
"
        f"💰 Saldo simulado: ${round(bot.balance, 2)}\
"
        f"📊 Win Rate: {wr}% ({bot.wins}W / {bot.losses}L)\
"
        f"📈 Trades ativos: {len(bot.active_trades)}\
"
        f"⏳ Pendentes: {len(bot.pending_trades)}\
"
        f"⚡ Alavancagem: {bot.get_current_leverage()}x\
"
    )
    if bot.is_paused():
        msg += "🚫 Status: PAUSADO (circuit breaker)\
"
    else:
        msg += "✅ Status: OPERANDO\
"
    
    msg += f"🕐 Iniciado: {datetime.now().strftime('%d/%m %H:%M UTC')}"

    bot.send(msg)
    append_log("startup", {"balance": bot.balance, "winrate": wr})


def send_heartbeat(bot, regime_info: dict | None = None, ai_params: dict | None = None):
    """
    Heartbeat periódico confirmando que o bot está vivo.
    Inclui informações do regime de mercado em tempo real.
    """
    total = bot.wins + bot.losses
    wr    = round(bot.wins / total * 100, 1) if total > 0 else 0

    regime_info = regime_info or {}
    live_regime = (regime_info.get("live_regime") or "neutral").upper()
    avg_adx     = regime_info.get("avg_adx", 0)
    eff_conf    = regime_info.get("effective_conf", Config.MIN_CONFLUENCE)

    # Validação: Se avg_adx é 0, regime pode estar inválido
    regime_status = ""
    if avg_adx == 0:
        regime_status = " ⚠️ (dados insuficientes)"
    
    emoji = {
        "RANGING":  "〰️",
        "TRENDING": "📈",
        "NEUTRAL":  "➡️",
        "VOLATILE": "⚡",
    }.get(live_regime, "➡️")

    bot.send(
        "💓 HEARTBEAT — Bot operando\
"
        "------------------------------\
"
        f"💰 Saldo: ${round(bot.balance, 2)}\
"
        f"📊 WR: {wr}% | {bot.wins}W / {bot.losses}L\
"
        f"📈 Ativos: {len(bot.active_trades)} | Pendentes: {len(bot.pending_trades)}\
"
        f"{emoji} Regime: {live_regime}{regime_status} (ADX={avg_adx})\
"
        f"🎯 Confluência mínima efetiva: {eff_conf} pts"
    )
    
    append_log("heartbeat", {
        "balance": bot.balance,
        "winrate": wr,
        "regime": live_regime,
        "adx": avg_adx,
        "confluence": eff_conf,
    })


def send_daily_report(bot):
    """Relatório diário de performance."""
    metrics = calculate_metrics(bot)

    now = datetime.now(timezone.utc)
    day_pnl = 0.0
    day_trades = 0
    day_wins = 0
    day_losses = 0

    for h in bot.history:
        try:
            trade_time = datetime.strptime(h["closed_at"], "%d/%m %H:%M").replace(year=now.year)
            if trade_time.date() == now.date():
                day_pnl += h.get("pnl", 0)
                day_trades += 1
                if h.get("result") == "WIN":
                    day_wins += 1
                else:
                    day_losses += 1
        except Exception:
            continue

    msg = (
        f"📊 RELATÓRIO DIÁRIO — {now.strftime('%d/%m/%Y')}\
"
        "------------------------------\
"
        "📈 Hoje:\
"
        f"   Trades: {day_trades} ({day_wins}W / {day_losses}L)\
"
        f"   P&L: ${round(day_pnl, 2)}\
"
        "\
"
        "💰 Geral:\
"
        f"   Saldo: ${round(bot.balance, 2)}\
"
        f"   Total trades: {metrics['total_trades']}\
"
        f"   WR: {metrics['winrate']}%\
"
        f"   Profit Factor: {metrics['profit_factor']}\
"
        f"   Expectancy: ${metrics['expectancy']}/trade\
"
        f"   Max Drawdown: {metrics['max_drawdown_pct']}%"
    )
    bot.send(msg)
    save_metrics(metrics)
    append_log("daily_report", metrics)


def send_error_notification(bot, error_msg: str, traceback_str: str = ""):
    """Notificação de erro/crash — tolerante a falhas do próprio send."""
    msg = (
        "🚨 ERRO NO BOT\
"
        "------------------------------\
"
        f"❌ {error_msg[:200]}\
"
    )
    if traceback_str:
        msg += f"\
📋 Traceback:\
{traceback_str[:500]}\
"
    msg += f"\
🕐 {datetime.now().strftime('%d/%m %H:%M:%S UTC')}"
    try:
        bot.send(msg)
    except Exception:
        pass
    append_log("error", {"message": error_msg, "traceback": traceback_str})


def _send_confluence_report(bot):
    """Resposta ao comando /confluencia no Telegram."""
    from signals import get_confluence_snapshot
    from ai_validator import load_ai_params
    from utils import get_allowed_symbols

    bot.send("⏳ Calculando confluência...")
    try:
        snapshot        = get_confluence_snapshot()
        ai_params       = load_ai_params()
        min_conf        = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
        live_regime     = ai_params.get("live_regime", "neutral")
        allowed_symbols = get_allowed_symbols(bot.balance)

        lines = [
            f"📊 CONFLUÊNCIA — {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC",
            f"Regime: {live_regime.upper()} | Mínimo: {min_conf} pts",
            "─────────────────────────────────",
        ]

        for item in snapshot:
            score  = item["best_score"]
            total  = item["total"]
            direc  = item["best_dir"]
            sym    = item["symbol"]
            bar    = "🟢" * min(score, 10) + "⚪" * max(0, min(total, 10) - score)
            h4     = "✅" if item["h4_aligned"] else "❌"
            locked = sym not in allowed_symbols

            if locked:
                status = "🔒"
            elif score >= min_conf:
                status = "🔥 SINAL"
            elif score >= min_conf - 2:
                status = "⚡ QUASE"
            elif score >= min_conf - 4:
                status = "👀 WATCH"
            else:
                status = "😴"

            lines.append(
                f"{status} {sym} {direc} {score}/{total}"
                + (" (bloqueado)" if locked else "") + "\
"
                f"  {bar}\
"
                f"  RSI:{item['rsi']} ADX:{item['adx']} H4:{h4}"
            )

        lines.append("─────────────────────────────────")
        lines.append("🔒 = par bloqueado pelo tier de capital atual.")
        lines.append("Use /confluencia para atualizar.")
        bot.send("\
".join(lines))
    except Exception as e:
        bot.send(f"❌ Erro ao calcular confluência: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULER DE TAREFAS ASSÍNCRONAS
# ═══════════════════════════════════════════════════════════════════════════════

def _run_scheduler():
    """Thread que executa tarefas agendadas sem bloquear loop principal."""
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            log(f"[SCHEDULER] Erro: {e}")


def _schedule_weekly_learning(bot):
    """Wrapper assíncrono para aprendizado semanal."""
    def task():
        try:
            from ai_validator import weekly_learning
            result = weekly_learning(bot)
            if result:
                bot.send(
                    "🧠 APRENDIZADO SEMANAL\
"
                    "------------------------------\
"
                    f"{result.get('last_suggestion','')}\
\
"
                    f"Min confluence: {result['min_confluence']} | "
                    f"Min ADX: {result['min_adx']} | "
                    f"Min RR: {result['min_rr']}\
"
                    f"Pares bloqueados: {', '.join(result['blocked_pairs']) or 'nenhum'}"
                )
                log("[LAYER2] Aprendizado concluído")
        except Exception as e:
            log(f"[LAYER2] Erro: {e}")
            append_log("error", {"type": "weekly_learning", "error": str(e)})
    
    return task


def _schedule_monthly_analysis(bot):
    """Wrapper assíncrono para análise mensal."""
    def task():
        try:
            from ai_validator import monthly_deep_analysis
            result = monthly_deep_analysis(bot)
            if result:
                regime_pairs = result.get("regime_pairs", {})
                regime_txt   = " | ".join(f"{k}:{v}" for k, v in list(regime_pairs.items())[:5])
                bot.send(
                    "🔮 ANÁLISE MENSAL (Estratégica)\
"
                    "------------------------------\
"
                    f"{result.get('opus_summary','')}\
\
"
                    f"Regime: {result.get('market_regime','?').upper()} | "
                    f"Viés: {result.get('strategy_bias','?').upper()}\
"
                    f"Sessões favoritas: {', '.join(result.get('favored_sessions',[])) or '—'}\
"
                    f"Horas a evitar (UTC): {result.get('avoid_hours_utc',[]) or 'nenhuma'}\
\
"
                    f"Por par: {regime_txt}"
                )
                log("[LAYER3] Análise mensal concluída")
        except Exception as e:
            log(f"[LAYER3] Erro: {e}")
            append_log("error", {"type": "monthly_analysis", "error": str(e)})
    
    return task


# ═══════════════════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def bot_loop(bot):
    """Loop principal otimizado sem bloqueios de API (agora em scheduler)."""
    last_heartbeat = 0.0
    last_daily_report = None

    while True:
        now = datetime.now(timezone.utc)

        # ── HEARTBEAT ──
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                from ai_validator import check_live_regime, load_ai_params
                regime_info = check_live_regime(bot)
                ai_p        = load_ai_params()
                send_heartbeat(bot, regime_info, ai_p)
                last_heartbeat = time.time()
            except Exception as e:
                log(f"[HEARTBEAT] Erro: {e}")

        # ── RELATÓRIO DIÁRIO ──
        if now.hour == DAILY_REPORT_HOUR and last_daily_report != now.date():
            try:
                send_daily_report(bot)
                last_daily_report = now.date()
            except Exception as e:
                log(f"[DAILY] Erro: {e}")

        # ── SCAN / MONITOR (BLOCKING) ──
        if not bot.is_paused():
            try:
                bot.expire_pending_signals(max_age_seconds=Config.PENDING_EXPIRY_SECONDS)
                scan(bot)
                bot.monitor_trades()

            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                log(f"Erro no loop: {error_msg}")
                send_error_notification(bot, error_msg, tb)
                append_log("loop_error", {"error": error_msg})

        # ── COMANDOS TELEGRAM ──
        try:
            url  = (
                f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                f"/getUpdates?offset={bot.last_id + 1}&timeout=5"
            )
            resp = requests.get(url, timeout=10).json()
            if "result" in resp:
                for u in resp["result"]:
                    if "message" in u and "text" in u["message"]:
                        txt = u["message"]["text"].strip()

                        if txt.startswith("/executar_"):
                            parts = txt.split("_")
                            if len(parts) >= 3:
                                try:
                                    pid    = int(parts[1])
                                    amount = float(parts[2])
                                    ok, msg = bot.execute_pending(pid, amount)
                                    if ok:
                                        bot.send(f"✅ {msg}")
                                    else:
                                        bot.send(f"❌ {msg}")
                                except ValueError:
                                    bot.send("❌ Formato inválido. Use /executar_<id>_<valor>")

                        elif txt in ("/confluencia", "/confluência"):
                            _send_confluence_report(bot)

                        elif txt == "/status":
                            send_heartbeat(bot)

                    bot.last_id = u["update_id"]
        except Exception as e:
            log(f"[TELEGRAM] Erro ao buscar updates: {e}")

        time.sleep(Config.SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Entrypoint com scheduler para tarefas assíncronas."""
    global scheduler_thread
    
    log("Iniciando Sniper Bot v2 (Forex + Gold H1 — modo sinalizador)")
    log(f"Versão Python: {sys.version.split()[0]}")
    
    bot = TradingBot()

    # 1. Carrega estado persistido
    state_loaded = load_state(bot)

    # 2. Refresh inicial de mercado
    try:
        from analysis import force_initial_refresh
        log("Executando refresh inicial de mercado (Twelve Data)...")
        force_initial_refresh(blocking=True)
    except Exception as e:
        log(f"[INIT] Falha no refresh inicial: {e}")

    # 3. Notificação de startup
    if STARTUP_NOTIFICATION:
        try:
            send_startup_notification(bot)
        except Exception as e:
            log(f"[STARTUP] Erro ao enviar notificação: {e}")

    append_log("init", {
        "balance":      bot.balance,
        "state_loaded": state_loaded,
        "leverage":     bot.get_current_leverage(),
        "signal_only":  Config.BOT_IS_SIGNAL_ONLY,
    })

    # 4. Inicia scheduler de tarefas assíncronas
    log("[SCHEDULER] Iniciando agendador de tarefas")
    schedule.every().week.do(_schedule_weekly_learning(bot))
    schedule.every().month.do(_schedule_monthly_analysis(bot))
    
    scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True, name="scheduler")
    scheduler_thread.start()
    log("[SCHEDULER] Thread agendadora iniciada")

    # 5. Inicia loop principal em thread separada
    log("[BOT] Iniciando loop principal")
    threading.Thread(target=bot_loop, args=(bot,), daemon=True, name="bot-loop").start()

    # 6. Sobe API Flask
    app  = create_api(bot)
    port = int(os.environ.get("PORT", 8080))
    log(f"API HTTP escutando em 0.0.0.0:{port}")
    
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        log("Bot interrompido pelo usuário")
    except Exception as e:
        log(f"Erro fatal na API: {e}")
        send_error_notification(bot, f"API crash: {e}", traceback.format_exc())


if __name__ == "__main__":
    # Validação de configuração
    errors = Config.validate()
    if errors:
        print("\n⚠️  PROBLEMAS DE CONFIGURAÇÃO:\n")
        for err in errors:
            print(f"  {err}")
        print("\nDefina as variáveis de ambiente e tente novamente.\n")
        if any("❌" in err for err in errors):
            sys.exit(1)
    
    main()
