"""
ai_validator.py — 3 camadas de inteligência (Google Gemini 2.0 Flash)
======================================================================

CAMADA 1 │ gemini-2.0-flash │ Validação de cada sinal    │ ~1s  │ GRÁTIS
CAMADA 2 │ gemini-2.0-flash │ Aprendizado semanal        │ ~3s  │ GRÁTIS
CAMADA 3 │ gemini-2.0-flash │ Estratégia mensal profunda │ ~8s  │ GRÁTIS

Free tier Google AI Studio: 1.500 req/dia, 15 req/min — mais que suficiente.
Chave grátis em: https://aistudio.google.com/apikey

Para migrar para Claude no futuro: troque _call_gemini por _call_claude
e defina ANTHROPIC_API_KEY no Railway.
"""

import json
import os
import time
import requests
from collections import deque
from datetime import datetime
from utils import log

# ── Modelos ───────────────────────────────────────────────────
_MODEL_FLASH   = "gemini-2.0-flash"
_GEMINI_URL    = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

AI_PARAMS_FILE      = "ai_params.json"
MIN_TRADES_TO_LEARN = 20
MIN_TRADES_FOR_DEEP = 50

# ── Rate limiter global ───────────────────────────────────────
# Free tier: 15 req/min. Mantemos janela deslizante de 60s.
_RATE_LIMIT     = 12          # usa 12 das 15 disponíveis (margem de segurança)
_RATE_WINDOW    = 60          # segundos
_call_times: deque = deque()  # timestamps das últimas chamadas


def _rate_limit_wait():
    """
    Bloqueia até que haja espaço na janela de rate limit.
    Garante que nunca enviamos mais de _RATE_LIMIT req em _RATE_WINDOW segundos.
    """
    now = time.time()
    # Remove chamadas fora da janela
    while _call_times and now - _call_times[0] >= _RATE_WINDOW:
        _call_times.popleft()

    if len(_call_times) >= _RATE_LIMIT:
        wait = _RATE_WINDOW - (now - _call_times[0]) + 1
        if wait > 0:
            log(f"[AI] Rate limit preventivo — aguardando {wait:.0f}s")
            time.sleep(wait)
        # Limpa novamente após espera
        now = time.time()
        while _call_times and now - _call_times[0] >= _RATE_WINDOW:
            _call_times.popleft()

    _call_times.append(time.time())


# ═══════════════════════════════════════════════════════════
# PARÂMETROS APRENDIDOS
# ═══════════════════════════════════════════════════════════

def load_ai_params() -> dict:
    defaults = {
        # Camada 2 — Sonnet/Flash semanal
        "min_confluence":      7,
        "blocked_pairs":       [],
        "session_strictness":  "normal",
        "min_adx":             20,
        "min_rr":              1.5,
        "last_suggestion":     None,
        # Camada 3 — Opus/Flash mensal
        "market_regime":       "neutral",
        "regime_pairs":        {},
        "favored_sessions":    [],
        "avoid_hours_utc":     [],
        "strategy_bias":       "balanced",
        "opus_summary":        None,
        "opus_updated_at":     None,
        # Controle
        "updated_at":          None,
    }
    if not os.path.exists(AI_PARAMS_FILE):
        return defaults
    try:
        with open(AI_PARAMS_FILE) as f:
            stored = json.load(f)
        return {**defaults, **stored}
    except Exception as e:
        log(f"[AI] Erro ao carregar ai_params.json: {e}")
        return defaults


def save_ai_params(params: dict):
    params["updated_at"] = datetime.now().isoformat()
    tmp = AI_PARAMS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    os.replace(tmp, AI_PARAMS_FILE)
    log("[AI] Parâmetros salvos.")


# ── Helper de chamada à API Gemini ───────────────────────────

def _call_gemini(
    system: str,
    user_msg: str,
    max_tokens: int = 500,
    timeout: int = 25,
) -> str | None:
    from config import Config
    api_key = getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        log("[AI] GEMINI_API_KEY não configurada.")
        return None

    url  = _GEMINI_URL.format(model=_MODEL_FLASH)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }

    for attempt in range(2):
        # Espera se necessário antes de cada chamada
        _rate_limit_wait()

        try:
            resp = requests.post(
                url,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        except requests.exceptions.Timeout:
            log(f"[AI] Gemini timeout (tentativa {attempt+1}/2)")
            if attempt == 0:
                time.sleep(5)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status == 429:
                # Rate limit atingido mesmo com controle preventivo
                # Espera 65s para garantir que a janela resetou completamente
                log("[AI] Gemini 429 — aguardando 65s para janela resetar")
                _call_times.clear()  # reseta o tracker local
                time.sleep(65)
                # Tenta uma última vez após espera longa
                if attempt == 0:
                    continue
                return None
            elif status >= 500:
                log(f"[AI] Gemini erro servidor {status} (tentativa {attempt+1}/2)")
                if attempt == 0:
                    time.sleep(5)
            else:
                log(f"[AI] Erro Gemini HTTP {status}")
                return None

        except Exception as e:
            log(f"[AI] Erro Gemini: {e}")
            return None

    log("[AI] Gemini falhou após 2 tentativas — usando fallback")
    return None


def _parse_json(raw: str, context: str = "") -> dict | None:
    """Parse JSON robusto — remove markdown fences se necessário."""
    if raw is None:
        return None
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        log(f"[AI] Erro parse JSON {context}: {e} | raw: {raw[:120]}")
        return None


def _build_pair_stats(history: list) -> tuple[list[str], dict]:
    pair_stats: dict = {}
    for h in history:
        sym = h.get("symbol", "?")
        if sym not in pair_stats:
            pair_stats[sym] = {"wins": 0, "losses": 0, "pnl": 0.0, "adx_vals": [], "hours": []}
        pair_stats[sym]["pnl"] += h.get("pnl", 0)
        pair_stats[sym]["adx_vals"].append(h.get("adx", 0))
        if h.get("opened_at"):
            try:
                pair_stats[sym]["hours"].append(
                    datetime.fromisoformat(h["opened_at"]).hour
                )
            except Exception:
                pass
        if h["result"] == "WIN":
            pair_stats[sym]["wins"] += 1
        else:
            pair_stats[sym]["losses"] += 1

    summary = []
    for sym, s in pair_stats.items():
        total   = s["wins"] + s["losses"]
        wr      = round(s["wins"] / total * 100) if total > 0 else 0
        avg_adx = round(sum(s["adx_vals"]) / len(s["adx_vals"]), 1) if s["adx_vals"] else 0
        summary.append(
            f"{sym}: {s['wins']}W/{s['losses']}L WR={wr}% "
            f"PnL=${round(s['pnl'],2)} ADX_médio={avg_adx}"
        )
    return summary, pair_stats


# ═══════════════════════════════════════════════════════════
# CAMADA 1 — VALIDADOR DE SINAIS
# ═══════════════════════════════════════════════════════════

_VALIDATOR_SYSTEM = """
Você é um validador de sinais forex/ouro especializado em SMC (Smart Money Concepts).

Sua tarefa: avaliar se um sinal técnico deve ser enviado ao trader ou rejeitado.

Rejeite se:
- ADX < 18 (mercado sem direção)
- RSI > 72 em BUY ou RSI < 28 em SELL (zona extrema oposta)
- H4 desalinhado com H1 (sem confluência multi-timeframe)
- Últimos 3 trades no par todos LOSS
- FVG e OB ambos inativos

Aprove com alta confiança (>= 8) se:
- FVG ativo + OB ativo + sweep confirmado + H4 alinhado
- ADX >= 25 e MACD confirmando direção
- WR recente do par >= 55%

Responda SOMENTE com JSON válido, sem texto adicional:
{"approve": true, "confidence": 8, "reason": "motivo curto em português"}
""".strip()


def validate_signal(signal: dict, indicators: dict, bot) -> tuple[bool, str]:
    """
    Camada 1: Gemini Flash valida o sinal antes de enviar ao Telegram.
    Retorna (aprovado, motivo).
    """
    from config import Config
    if not (getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")):
        return True, "IA não configurada — aprovação automática"

    h1        = indicators.get("h1") or indicators
    direction = signal.get("dir", "BUY")
    sym       = signal.get("symbol", "?")
    sweep     = h1.get("sweep", {})

    fvg_active = any(
        f.get("active") for f in
        h1.get("fvg", {}).get("bullish" if direction == "BUY" else "bearish", [])
    )
    ob_active = any(
        o.get("active") for o in
        h1.get("ob", {}).get("bullish" if direction == "BUY" else "bearish", [])
    )

    pair_history = [h for h in (bot.history or []) if h.get("symbol") == sym][-10:]
    pair_wr      = round(sum(1 for h in pair_history if h["result"] == "WIN") / max(len(pair_history), 1) * 100)
    last_results = [h["result"] for h in pair_history[-5:]]

    ai_params   = load_ai_params()
    regime_info = ai_params.get("regime_pairs", {}).get(sym, ai_params.get("market_regime", "neutral"))
    bias        = ai_params.get("strategy_bias", "balanced")

    user_msg = f"""
Par: {sym} | Direção: {direction}
Entrada: {signal.get('entry')} | SL: {signal.get('sl')} | TP: {signal.get('tp')}
RR: {signal.get('rr')} | Score: {signal.get('score')}/{signal.get('max_score')}

Indicadores H1:
- RSI: {h1.get('rsi',50)} | ADX: {h1.get('adx',0)}
- EMA9 {">" if h1.get('ema9',0) > h1.get('ema21',0) else "<"} EMA21
- Preço {">" if h1.get('price',0) > h1.get('ema200',0) else "<"} EMA200
- MACD bull: {h1.get('macd_bull')} | bear: {h1.get('macd_bear')}
- FVG ativo: {fvg_active} | OB ativo: {ob_active}
- Sweep bull: {sweep.get('bullish')} | bear: {sweep.get('bearish')}

H4: alinhado={indicators.get('aligned',False)} | cenário={indicators.get('h4_cenario','NEUTRO')}
Regime do par: {regime_info} | Viés estratégico: {bias}

Histórico par ({len(pair_history)} trades): WR {pair_wr}% | Últimos: {last_results}
WR geral do bot: {round(bot.wins / max(bot.wins + bot.losses, 1) * 100, 1)}%
Trades ativos: {len(bot.active_trades)}
""".strip()

    raw    = _call_gemini(_VALIDATOR_SYSTEM, user_msg, max_tokens=120, timeout=15)
    result = _parse_json(raw, context=f"{sym} {direction}")

    if result is None:
        return True, "Timeout/erro — aprovação automática"

    approve    = bool(result.get("approve", True))
    reason     = result.get("reason", "sem motivo")
    confidence = result.get("confidence", 5)

    log(f"[GEMINI] {sym} {direction} → {'✅' if approve else '❌'} "
        f"confiança {confidence}/10: {reason}")
    return approve, f"IA ({confidence}/10): {reason}"


# ═══════════════════════════════════════════════════════════
# CAMADA 2 — APRENDIZADO SEMANAL
# ═══════════════════════════════════════════════════════════

_LEARNER_SYSTEM = """
Você é um especialista em sistemas de trading algorítmico forex/ouro (SMC).

Analise o histórico do bot e ajuste os parâmetros para maximizar Win Rate.

Regras:
- blocked_pairs: só bloqueie com WR < 35% E mínimo 5 trades. Desbloqueie se melhorou.
- min_confluence: suba 1 se WR < 48%. Desça 1 se WR > 62% e poucos sinais.
- min_adx: suba se maioria das perdas tem ADX < 20.
- Prefira mudanças conservadoras — 1 ponto por vez.
- Se WR >= 60% e P&L positivo, mantenha os parâmetros.

Responda SOMENTE com JSON válido, sem texto adicional:
{
  "min_confluence": 7,
  "blocked_pairs": [],
  "session_strictness": "normal",
  "min_adx": 20,
  "min_rr": 1.5,
  "summary": "análise em até 4 frases em português"
}
""".strip()


def weekly_learning(bot) -> dict | None:
    """
    Camada 2: Gemini Flash analisa histórico e ajusta parâmetros operacionais.
    Chamada 1x por semana. Retorna parâmetros atualizados ou None.
    """
    from config import Config
    if not (getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")):
        log("[AI] GEMINI_API_KEY não configurada — aprendizado semanal ignorado.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_TO_LEARN:
        log(f"[AI] Histórico insuficiente ({len(history)}/{MIN_TRADES_TO_LEARN}) — aguardando.")
        return None

    pair_summary, _ = _build_pair_stats(history)
    total     = bot.wins + bot.losses
    wr        = round(bot.wins / total * 100, 1) if total > 0 else 0
    total_pnl = round(bot.balance - Config.INITIAL_BALANCE, 2)
    recent    = history[-30:]
    recent_wr = round(sum(1 for h in recent if h["result"] == "WIN") / max(len(recent), 1) * 100, 1)
    params    = load_ai_params()

    # ── Feedback loop: WR por faixa de confiança da IA ───────────
    conf_stats: dict = {}
    for h in history:
        c = h.get("ai_confidence", 0)
        if c == 0:
            continue  # trade sem dado de confiança (anterior à feature)
        bucket = f"{(c // 2) * 2}-{(c // 2) * 2 + 1}"  # ex: "8-9", "6-7"
        if bucket not in conf_stats:
            conf_stats[bucket] = {"wins": 0, "total": 0}
        conf_stats[bucket]["total"] += 1
        if h["result"] == "WIN":
            conf_stats[bucket]["wins"] += 1

    conf_summary = []
    for bucket, s in sorted(conf_stats.items()):
        bwr = round(s["wins"] / s["total"] * 100)
        conf_summary.append(f"Confiança {bucket}/10: WR {bwr}% ({s['total']} trades)")

    user_msg = f"""
=== RELATÓRIO SEMANAL ===

Performance: WR {wr}% ({bot.wins}W/{bot.losses}L) | P&L ${total_pnl} | Saldo ${round(bot.balance,2)}
WR últimos 30 trades: {recent_wr}%

Por par:
{chr(10).join(pair_summary)}

WR por confiança da IA (feedback loop):
{chr(10).join(conf_summary) if conf_summary else 'dados insuficientes ainda'}

Parâmetros atuais:
  min_confluence={params['min_confluence']} | min_adx={params['min_adx']}
  min_rr={params['min_rr']} | session_strictness={params['session_strictness']}
  blocked_pairs={params['blocked_pairs']}

Contexto estratégico: {params.get('opus_summary') or 'ainda não disponível'}

Últimos 15 trades:
{[(h['symbol'], h['dir'], h['result'], f"PnL=${h['pnl']}", f"ADX={h.get('adx',0)}", f"conf={h.get('ai_confidence',0)}") for h in history[-15:]]}
""".strip()

    log("[AI] Aprendizado semanal iniciado...")
    raw    = _call_gemini(_LEARNER_SYSTEM, user_msg, max_tokens=600, timeout=40)
    result = _parse_json(raw, context="weekly_learning")

    if result is None:
        return None

    params["min_confluence"]     = max(6, min(9, int(result.get("min_confluence", params["min_confluence"]))))
    params["blocked_pairs"]      = list(result.get("blocked_pairs", []))
    params["session_strictness"] = result.get("session_strictness", "normal")
    params["min_adx"]            = max(15, min(30, int(result.get("min_adx", params["min_adx"]))))
    params["min_rr"]             = max(1.2, min(2.5, float(result.get("min_rr", params["min_rr"]))))
    params["last_suggestion"]    = result.get("summary", "")

    save_ai_params(params)
    log(f"[AI] Aprendizado concluído: {params['last_suggestion']}")
    return params


# ═══════════════════════════════════════════════════════════
# CAMADA 3 — ESTRATÉGIA MENSAL PROFUNDA
# ═══════════════════════════════════════════════════════════

_STRATEGIST_SYSTEM = """
Você é um estrategista quantitativo sênior especializado em forex e ouro algorítmico.

Analise profundamente o histórico do bot e identifique padrões estruturais:
quando e por que o sistema funciona ou falha. Pense como gestor de fundo:
regime de mercado, correlações, viés direcional, horários de alta/baixa performance.

Regras:
- market_regime: avalie o estado geral do mercado forex nas últimas semanas
- regime_pairs: cada par tem seu próprio regime
- favored_sessions: onde o WR é maior (london, new_york, overlap, asia)
- avoid_hours_utc: horas UTC com WR < 40% nos dados
- strategy_bias: "conservative" se drawdown > 15% ou WR < 45%; "aggressive" se WR > 60%
- opus_summary: seja específico — cite pares, números, padrões temporais concretos (5-8 frases)

Responda SOMENTE com JSON válido, sem texto adicional:
{
  "market_regime": "neutral",
  "regime_pairs": {"EURUSD": "trending", "XAUUSD": "volatile"},
  "favored_sessions": ["london", "overlap"],
  "avoid_hours_utc": [2, 3, 22],
  "strategy_bias": "balanced",
  "opus_summary": "análise estratégica em 5-8 frases em português"
}
""".strip()


def monthly_deep_analysis(bot) -> dict | None:
    """
    Camada 3: Gemini Flash analisa padrões estruturais do bot.
    Chamada 1x por mês. Define estratégia macro para as outras camadas.
    """
    from config import Config
    if not (getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")):
        log("[AI] GEMINI_API_KEY não configurada — análise mensal ignorada.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_FOR_DEEP:
        log(f"[AI] Histórico insuficiente ({len(history)}/{MIN_TRADES_FOR_DEEP}) — aguardando.")
        return None

    pair_summary, _ = _build_pair_stats(history)
    total     = bot.wins + bot.losses
    wr        = round(bot.wins / total * 100, 1) if total > 0 else 0
    total_pnl = round(bot.balance - Config.INITIAL_BALANCE, 2)

    buy_trades  = [h for h in history if h.get("dir") == "BUY"]
    sell_trades = [h for h in history if h.get("dir") == "SELL"]
    buy_wr  = round(sum(1 for h in buy_trades  if h["result"] == "WIN") / max(len(buy_trades),  1) * 100, 1)
    sell_wr = round(sum(1 for h in sell_trades if h["result"] == "WIN") / max(len(sell_trades), 1) * 100, 1)

    # WR por hora UTC
    hour_stats: dict = {}
    for h in history:
        if not h.get("opened_at"):
            continue
        try:
            hour = datetime.fromisoformat(h["opened_at"]).hour
            if hour not in hour_stats:
                hour_stats[hour] = {"wins": 0, "total": 0}
            hour_stats[hour]["total"] += 1
            if h["result"] == "WIN":
                hour_stats[hour]["wins"] += 1
        except Exception:
            pass

    hour_summary = [
        f"{hour:02d}h UTC: WR {round(s['wins']/s['total']*100)}% ({s['total']} trades)"
        for hour, s in sorted(hour_stats.items())
    ]

    # Evolução em quartis
    q_size   = max(len(history) // 4, 1)
    quarters = []
    for i in range(4):
        q = history[i * q_size: (i + 1) * q_size]
        if q:
            q_wins = sum(1 for h in q if h["result"] == "WIN")
            quarters.append(f"Q{i+1}: WR {round(q_wins/len(q)*100)}% ({len(q)} trades)")

    params = load_ai_params()

    user_msg = f"""
=== ANÁLISE ESTRATÉGICA MENSAL ===

Geral: {total} trades | WR {wr}% | P&L ${total_pnl} | Saldo ${round(bot.balance,2)}
BUY WR: {buy_wr}% ({len(buy_trades)} trades) | SELL WR: {sell_wr}% ({len(sell_trades)} trades)

Evolução temporal:
{chr(10).join(quarters)}

Por par:
{chr(10).join(pair_summary)}

Por hora UTC:
{chr(10).join(hour_summary) if hour_summary else 'dados insuficientes'}

Parâmetros atuais:
  min_confluence={params['min_confluence']} | min_adx={params['min_adx']}
  strategy_bias={params['strategy_bias']} | blocked_pairs={params['blocked_pairs']}

Análise anterior: {params.get('opus_summary') or 'primeira análise'}

Últimos 50 trades:
{[(h['symbol'], h['dir'], h['result'], f"PnL=${h['pnl']}", f"ADX={h.get('adx',0)}", h.get('opened_at','?')[:16]) for h in history[-50:]]}
""".strip()

    log("[AI] Análise estratégica mensal iniciada...")
    raw    = _call_gemini(_STRATEGIST_SYSTEM, user_msg, max_tokens=1000, timeout=60)
    result = _parse_json(raw, context="monthly_deep_analysis")

    if result is None:
        return None

    params["market_regime"]    = result.get("market_regime", "neutral")
    params["regime_pairs"]     = result.get("regime_pairs", {})
    params["favored_sessions"] = result.get("favored_sessions", [])
    params["avoid_hours_utc"]  = result.get("avoid_hours_utc", [])
    params["strategy_bias"]    = result.get("strategy_bias", "balanced")
    params["opus_summary"]     = result.get("opus_summary", "")
    params["opus_updated_at"]  = datetime.now().isoformat()

    save_ai_params(params)
    log(f"[AI] Análise mensal concluída: regime={params['market_regime']} | bias={params['strategy_bias']}")
    return params


# ═══════════════════════════════════════════════════════════
# ITEM 3 — DETECÇÃO DE REGIME EM TEMPO REAL (sem API)
# ═══════════════════════════════════════════════════════════

# Thresholds de ADX para classificar regime
_ADX_RANGING  = 18   # abaixo = mercado lateral → mais restritivo
_ADX_TRENDING = 25   # acima  = tendência clara → pode relaxar 1 ponto


def check_live_regime(bot) -> dict:
    """
    Roda a cada heartbeat (1h) sem chamar nenhuma API.
    Calcula o ADX médio dos trades ativos + cache de análise recente
    e ajusta min_confluence localmente em ai_params.json.

    Lógica:
      ADX médio < 18  → regime "ranging"   → min_confluence +1 (mais restritivo)
      ADX médio > 25  → regime "trending"  → min_confluence -1 (mais permissivo, mín 6)
      Entre 18-25     → regime "neutral"   → mantém o valor base do Sonnet

    Retorna dict com regime detectado e confluence ajustada.
    """
    from analysis import _cache   # acessa o cache do Twelve Data diretamente

    if not _cache:
        return {"live_regime": "neutral", "confluence_adj": 0}

    # Calcula ADX médio dos últimos candles de todos os pares em cache
    adx_values = []
    for sym, (_, df) in _cache.items():
        try:
            if len(df) < 15:
                continue
            highs  = df["High"]
            lows   = df["Low"]
            closes = df["Close"]
            import pandas as pd
            tr = pd.concat([
                highs - lows,
                (highs - closes.shift()).abs(),
                (lows  - closes.shift()).abs(),
            ], axis=1).max(axis=1)
            up_move  = highs.diff()
            dn_move  = -lows.diff()
            plus_dm  = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
            minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
            atr_s    = tr.ewm(alpha=1/14, adjust=False).mean()
            plus_di  = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_s
            minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_s
            dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
            adx      = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
            if adx > 0:
                adx_values.append(adx)
        except Exception:
            continue

    if not adx_values:
        return {"live_regime": "neutral", "confluence_adj": 0}

    avg_adx = round(sum(adx_values) / len(adx_values), 1)
    params  = load_ai_params()
    base_conf = params.get("min_confluence", 7)

    if avg_adx < _ADX_RANGING:
        live_regime    = "ranging"
        confluence_adj = +1       # mais restritivo em mercado lateral
    elif avg_adx > _ADX_TRENDING:
        live_regime    = "trending"
        confluence_adj = -1       # mais permissivo em tendência clara
    else:
        live_regime    = "neutral"
        confluence_adj = 0

    effective_conf = max(6, min(9, base_conf + confluence_adj))

    # Salva regime live (separado do regime mensal do Opus)
    prev_regime = params.get("live_regime", "neutral")
    params["live_regime"]       = live_regime
    params["live_adx_avg"]      = avg_adx
    params["live_confluence"]   = effective_conf
    save_ai_params(params)

    # Loga só se o regime mudou
    if live_regime != prev_regime:
        log(f"[REGIME] Mudança detectada: {prev_regime} → {live_regime} "
            f"(ADX médio={avg_adx}) | confluence={base_conf} → {effective_conf}")

    return {
        "live_regime":    live_regime,
        "avg_adx":        avg_adx,
        "confluence_adj": confluence_adj,
        "effective_conf": effective_conf,
    }
