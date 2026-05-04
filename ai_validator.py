"""
ai_validator.py — 3 camadas de inteligência (Google Gemini)
============================================================

CAMADA 1 │ gemini-2.0-flash │ Pontuação de cada sinal      │ ~1s  │ INFO ONLY
CAMADA 2 │ gemini-2.0-flash │ Aprendizado semanal           │ ~3s  │ AJUSTA PARAMS
CAMADA 3 │ gemini-2.0-flash │ Estratégia mensal profunda    │ ~8s  │ ANÁLISE GERAL

MUDANÇA PRINCIPAL:
  A Camada 1 NÃO mais bloqueia sinais — ela pontua de 1 a 10 para
  análise e aprendizado. Todos os sinais que passam nos filtros técnicos
  são enviados. O histórico de WIN/LOSS alimenta as camadas 2 e 3.

Free tier Google AI Studio: 1.500 req/dia, 15 req/min.
Chave grátis em: https://aistudio.google.com/apikey
"""

import json
import os
import time
import requests
import math
from collections import deque
from datetime import datetime, timezone
from utils import log

# ═══════════════════════════════════════════════════════════════════════════════
# Configuração
# ═══════════════════════════════════════════════════════════════════════════════
_MODEL_FLASH        = "gemini-2.0-flash"
_GEMINI_URL         = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

AI_PARAMS_FILE      = "ai_params.json"
MIN_TRADES_TO_LEARN = 20
MIN_TRADES_FOR_DEEP = 50

# Rate limiter (15 req/min free tier — usamos 12 com margem)
_RATE_LIMIT  = 12
_RATE_WINDOW = 60
_call_times: deque = deque()

_AI_DISABLED_UNTIL = 0.0
_SIGNAL_CACHE: dict[str, tuple[float, tuple[bool, str]]] = {}
_SIGNAL_CACHE_TTL = 900  # 15 min
_SIGNAL_COOLDOWN: dict[str, float] = {}
_SIGNAL_COOLDOWN_TTL = 1800  # 30 min por par/direção


def _rate_limit_wait():
    """Bloqueia até haver espaço na janela deslizante de 60s."""
    now = time.time()
    while _call_times and now - _call_times[0] >= _RATE_WINDOW:
        _call_times.popleft()

    if len(_call_times) >= _RATE_LIMIT:
        wait = _RATE_WINDOW - (now - _call_times[0]) + 1
        if wait > 0:
            log(f"[AI] Rate limit — aguardando {wait:.0f}s")
            time.sleep(wait)
        now = time.time()
        while _call_times and now - _call_times[0] >= _RATE_WINDOW:
            _call_times.popleft()

    _call_times.append(time.time())


def _fallback_ai_response(h1: dict, direction: str) -> tuple[int, str]:
    score, reason = _get_technical_score(h1, direction)
    return score, f"Técnico {score}/10: {reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# PARÂMETROS APRENDIDOS
# ═══════════════════════════════════════════════════════════════════════════════

def load_ai_params() -> dict:
    defaults = {
        "min_confluence":     7,
        "blocked_pairs":      [],
        "session_strictness": "normal",
        "min_adx":            20,
        "min_rr":             1.5,
        "last_suggestion":    None,
        "market_regime":      "neutral",
        "regime_pairs":       {},
        "favored_sessions":   [],
        "avoid_hours_utc":    [],
        "strategy_bias":      "balanced",
        "opus_summary":       None,
        "opus_updated_at":    None,
        "live_regime":        "neutral",
        "live_adx_avg":       0,
        "live_confluence":    7,
        "updated_at":         None,
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
    params["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = AI_PARAMS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    os.replace(tmp, AI_PARAMS_FILE)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: chamada ao Gemini com retry e rate limit
# ═══════════════════════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    from config import Config
    return getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def _call_gemini(system: str, user_msg: str, max_tokens: int = 500, timeout: int = 25) -> str | None:
    """
    Chamada ao Gemini com retry automático e rate limiting.
    Retorna string com a resposta, ou None se falhar após retries.
    """
    global _AI_DISABLED_UNTIL
    api_key = _get_api_key()
    if not api_key or time.time() < _AI_DISABLED_UNTIL:
        return None

    url  = _GEMINI_URL.format(model=_MODEL_FLASH)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.1,   # Mais determinístico
            "topP": 0.9,
        },
    }

    for attempt in range(3):  # 3 tentativas
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
            data = resp.json()
            # Valida estrutura da resposta
            candidates = data.get("candidates", [])
            if not candidates:
                log(f"[AI] Gemini retornou 0 candidatos (tentativa {attempt+1}/3)")
                continue
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            if text:
                _AI_DISABLED_UNTIL = 0.0
                return text
            log(f"[AI] Gemini retornou texto vazio (tentativa {attempt+1}/3)")

        except requests.exceptions.Timeout:
            log(f"[AI] Gemini timeout (tentativa {attempt+1}/3)")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

        except requests.exceptions.ConnectionError as e:
            log(f"[AI] Conexao falhou (tentativa {attempt+1}/3): {str(e)[:80]}")
            if attempt < 2:
                time.sleep(10)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 429:
                # Evita bloquear o loop principal: entra em cooldown e sai.
                wait = 3600 + (attempt * 300)
                log(f"[AI] Gemini 429 — entrando em cooldown por {wait//60} min")
                _call_times.clear()
                _AI_DISABLED_UNTIL = time.time() + wait
                return None
            elif status >= 500:
                log(f"[AI] Gemini erro servidor {status} (tentativa {attempt+1}/3)")
                if attempt < 2:
                    time.sleep(10)
            else:
                log(f"[AI] Gemini HTTP {status}: {str(e)[:80]}")
                return None  # Não tenta de novo em erros 4xx (exceto 429)

        except Exception as e:
            log(f"[AI] Erro inesperado: {type(e).__name__}: {str(e)[:80]}")
            if attempt < 2:
                time.sleep(5)

    log("[AI] Gemini falhou apos 3 tentativas")
    return None


def _parse_json(raw: str, context: str = "") -> dict | None:
    """Parse JSON robusto — remove markdown fences se necessário."""
    if raw is None:
        return None
    try:
        # Remove blocos de código markdown
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        clean = clean.strip()
        return json.loads(clean)
    except Exception as e:
        # Tenta extrair JSON com regex como fallback
        import re
        match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        log(f"[AI] Erro parse JSON {context}: {e} | raw: {raw[:150]}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: estatísticas por par
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_history_hour(h: dict) -> int | None:
    iso = h.get("opened_ts_iso")
    if iso:
        try:
            return datetime.fromisoformat(iso).astimezone(timezone.utc).hour
        except Exception:
            pass
    opened = h.get("opened_at", "")
    if opened and " " in opened:
        try:
            return int(opened.split(" ")[1].split(":")[0])
        except Exception:
            pass
    return None


def _build_pair_stats(history: list) -> tuple[list[str], dict]:
    pair_stats: dict = {}
    for h in history:
        sym = h.get("symbol", "?")
        if sym not in pair_stats:
            pair_stats[sym] = {"wins": 0, "losses": 0, "pnl": 0.0, "adx_vals": [], "hours": []}
        pair_stats[sym]["pnl"] += h.get("pnl", 0)
        pair_stats[sym]["adx_vals"].append(h.get("adx", 0))
        hour = _parse_history_hour(h)
        if hour is not None:
            pair_stats[sym]["hours"].append(hour)
        if h.get("result") == "WIN":
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
            f"PnL=${round(s['pnl'], 2)} ADX_medio={avg_adx}"
        )
    return summary, pair_stats


# ═══════════════════════════════════════════════════════════════════════════════
# PONTUAÇÃO TÉCNICA (fallback sem IA)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_technical_score(h1: dict, direction: str) -> tuple[int, str]:
    """Pontua o sinal tecnicamente quando a IA está indisponível. Score 0–10."""
    price  = h1.get("price", 0)
    score  = 0
    reasons = []

    # Tendência (3 pts)
    if direction == "BUY":
        if price > h1.get("ema200", 0):
            score += 2; reasons.append("P>EMA200")
        if h1.get("ema9", 0) > h1.get("ema21", 0):
            score += 1; reasons.append("EMA9>21")
    else:
        if price < h1.get("ema200", float("inf")):
            score += 2; reasons.append("P<EMA200")
        if h1.get("ema9", 0) < h1.get("ema21", 0):
            score += 1; reasons.append("EMA9<21")

    # Momentum (2 pts)
    if h1.get("macd_bull") and direction == "BUY":
        score += 1; reasons.append("MACD↑")
    elif h1.get("macd_bear") and direction == "SELL":
        score += 1; reasons.append("MACD↓")

    # Força (3 pts)
    adx = h1.get("adx", 0)
    if adx > 25:
        score += 3; reasons.append(f"ADX{adx:.0f}")
    elif adx > 20:
        score += 2; reasons.append(f"ADX{adx:.0f}")
    elif adx > 15:
        score += 1; reasons.append(f"ADX{adx:.0f}")

    # Candle (1 pt)
    if direction == "BUY" and h1.get("candle_bull"):
        score += 1; reasons.append("Candle↑")
    elif direction == "SELL" and h1.get("candle_bear"):
        score += 1; reasons.append("Candle↓")

    # Garante máximo 10
    score = min(score, 10)
    reason = " | ".join(reasons) if reasons else "Sem confirmação técnica"
    return score, reason


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 1 — PONTUADOR DE SINAIS (NÃO BLOQUEIA, APENAS PONTUA)
# ═══════════════════════════════════════════════════════════════════════════════

_SCORER_SYSTEM = """
Você é um analista técnico especializado em SMC (Smart Money Concepts) para forex e ouro.

Sua tarefa: pontuar a QUALIDADE de um sinal de 1 a 10, com base nos dados fornecidos.

IMPORTANTE: Você NÃO aprova nem rejeita. Apenas pontua e explica.

Critérios de pontuação:
- Score 9-10: Setup premium — FVG ou OB ativo + H4 alinhado + sweep confirmado + ADX > 25 + Daily Bias a favor
- Score 7-8: Setup bom — maioria dos critérios SMC presentes, H4 alinhado
- Score 5-6: Setup mediano — critérios técnicos ok mas falta algum elemento SMC
- Score 3-4: Setup fraco — poucos critérios confirmados
- Score 1-2: Setup muito fraco — maioria dos critérios ausentes

Seja objetivo e cite os 2-3 fatores mais relevantes.
Responda SOMENTE com JSON válido, sem texto adicional:
{"confidence": 7, "reason": "motivo curto em português (máx 70 chars)"}
""".strip()


def validate_signal(signal: dict, indicators: dict, bot) -> tuple[bool, str]:
    """
    Camada 1: Pontua o sinal com IA e retorna sempre aprovado=True.
    O score de confiança é informativo — usado no aprendizado semanal/mensal.

    NÃO BLOQUEIA SINAIS. Todos os sinais que passam nos filtros técnicos são enviados.
    """
    api_key   = _get_api_key()
    h1        = indicators.get("h1") or indicators
    direction = signal.get("dir") or signal.get("direction") or "BUY"
    sym       = signal.get("symbol", "?")
    score_key = f"{sym}|{direction}|{signal.get('setup_type','n/a')}|{signal.get('market_regime','n/a')}|{signal.get('rr','n/a')}"
    cooldown_key = f"{sym}|{direction}"

    cached = _SIGNAL_CACHE.get(score_key)
    if cached and (time.time() - cached[0]) < _SIGNAL_CACHE_TTL:
        return cached[1]

    ai_params = load_ai_params()
    live_min_conf = int(ai_params.get("live_confluence", 7))
    score_floor = max(7, live_min_conf + 1)
    api_disabled = time.time() < _AI_DISABLED_UNTIL
    last_call_ts = _SIGNAL_COOLDOWN.get(cooldown_key, 0.0)
    in_symbol_cooldown = (time.time() - last_call_ts) < _SIGNAL_COOLDOWN_TTL

    use_ai = bool(api_key and not api_disabled and not in_symbol_cooldown and int(signal.get("score", 0) or 0) >= score_floor)

    if not use_ai:
        tech_score, tech_reason = _fallback_ai_response(h1, direction)
        result = (True, tech_reason)
        _SIGNAL_CACHE[score_key] = (time.time(), result)
        if api_disabled:
            log(f"[AI] {sym} {direction} → fallback técnico ({tech_reason})")
        elif in_symbol_cooldown:
            log(f"[AI] {sym} {direction} → cooldown ativo, usando heurística")
        else:
            log(f"[AI] {sym} {direction} → score técnico {tech_score}/10 (heurística)")
        return result

    sweep     = h1.get("sweep", {}) or {}
    fvg_active = any(
        f.get("active") for f in
        (h1.get("fvg", {}) or {}).get("bullish" if direction == "BUY" else "bearish", [])
    )
    ob_active = any(
        o.get("active") for o in
        (h1.get("ob", {}) or {}).get("bullish" if direction == "BUY" else "bearish", [])
    )

    pair_history = [h for h in (bot.history or []) if h.get("symbol") == sym][-10:]
    pair_wr      = (
        round(sum(1 for h in pair_history if h["result"] == "WIN") / max(len(pair_history), 1) * 100)
        if pair_history else 0
    )
    last_results = [h["result"] for h in pair_history[-5:]]

    regime_info = ai_params.get("regime_pairs", {}).get(sym, ai_params.get("market_regime", "neutral"))
    bias        = ai_params.get("strategy_bias", "balanced")

    user_msg = f"""
Par: {sym} | Direção: {direction}
Entrada: {signal.get('entry')} | SL: {signal.get('sl')} | TP: {signal.get('tp')}
RR: {signal.get('rr')} | Score técnico: {signal.get('score')}/{signal.get('max_score')}
Regime do setup: {signal.get('market_regime', 'n/a')} | Setup: {signal.get('setup_type', 'n/a')}

Indicadores H1:
- RSI: {h1.get('rsi', 50)} | ADX: {h1.get('adx', 0)}
- EMA9 {">" if h1.get('ema9', 0) > h1.get('ema21', 0) else "<"} EMA21
- Preço {">" if h1.get('price', 0) > h1.get('ema200', 0) else "<"} EMA200
- MACD bull: {h1.get('macd_bull')} | bear: {h1.get('macd_bear')}
- FVG ativo: {fvg_active} | OB ativo: {ob_active}
- Sweep bull: {sweep.get('bullish')} | bear: {sweep.get('bearish')}

Multi-timeframe:
- H4 alinhado: {indicators.get('aligned', False)} | cenário H4: {indicators.get('h4_cenario', 'NEUTRO')}
- Daily Bias: {indicators.get('daily_bias', 'NEUTRO')}

Contexto:
- Regime do par: {regime_info} | Viés estratégico: {bias}
- Kill Zone ativa: {signal.get('kill_zone') is not None}
- OTE (62-79%): {signal.get('ote_active', False)}

Histórico recente do par ({len(pair_history)} trades):
- WR: {pair_wr}% | Últimos 5: {last_results}
- WR geral do bot: {round(bot.wins / max(bot.wins + bot.losses, 1) * 100, 1)}%
""".strip()

    raw    = _call_gemini(_SCORER_SYSTEM, user_msg, max_tokens=100, timeout=15)
    result = _parse_json(raw, context=f"{sym} {direction}")

    if result is None:
        tech_score, tech_reason = _fallback_ai_response(h1, direction)
        result_tuple = (True, f"Técnico {tech_score}/10: {tech_reason}")
        _SIGNAL_CACHE[score_key] = (time.time(), result_tuple)
        log(f"[AI] {sym} {direction} → fallback técnico {tech_score}/10 (Gemini indisponível)")
        return result_tuple

    confidence = max(1, min(10, int(result.get("confidence", 5))))
    reason     = result.get("reason", "sem análise")
    final = (True, f"{reason}")
    _SIGNAL_CACHE[score_key] = (time.time(), final)
    _SIGNAL_COOLDOWN[cooldown_key] = time.time()

    log(f"[AI] {sym} {direction} → confiança {confidence}/10: {reason}")
    return final


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 2 — APRENDIZADO SEMANAL
# ═══════════════════════════════════════════════════════════════════════════════

_LEARNER_SYSTEM = """
Você é um especialista em sistemas de trading algorítmico forex/ouro (SMC).

Analise o histórico REAL de WIN/LOSS do bot e ajuste os parâmetros para maximizar resultados.

Regras de ajuste:
- blocked_pairs: só bloqueie com WR < 35% E mínimo 5 trades. Desbloqueie automaticamente se WR melhorou.
- min_confluence: suba 1 ponto se WR geral < 48%. Desça 1 se WR > 62% e trades são escassos.
- min_adx: suba se a maioria das perdas ocorreu com ADX < 20. Desça se perdas ocorreram com ADX alto.
- min_rr: ajuste conforme o RR médio dos trades vencedores.
- Mudanças conservadoras: no máximo ±1 por ciclo.
- Se WR >= 60% e P&L positivo: mantenha os parâmetros atuais.

Analise o feedback loop de confiança da IA:
- Se scores altos (8-10) têm WR baixo, a IA está sendo otimista demais.
- Se scores baixos (1-4) têm WR alto, a IA está sendo pessimista demais.

Responda SOMENTE com JSON válido, sem texto adicional:
{
  "min_confluence": 7,
  "blocked_pairs": [],
  "session_strictness": "normal",
  "min_adx": 20,
  "min_rr": 1.5,
  "summary": "análise em até 4 frases em português com foco em ações concretas"
}
""".strip()


def weekly_learning(bot) -> dict | None:
    """
    Camada 2: analisa histórico de WIN/LOSS e ajusta parâmetros operacionais.
    Retorna dicionário com novos parâmetros, ou None se falhar.
    """
    from config import Config

    if not _get_api_key():
        log("[AI] GEMINI_API_KEY não configurada — aprendizado semanal ignorado.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_TO_LEARN:
        log(f"[AI] Histórico insuficiente ({len(history)}/{MIN_TRADES_TO_LEARN})")
        return None

    pair_summary, _ = _build_pair_stats(history)
    total     = bot.wins + bot.losses
    wr        = round(bot.wins / total * 100, 1) if total > 0 else 0
    total_pnl = round(bot.balance - Config.INITIAL_BALANCE, 2)
    recent    = history[-30:]
    recent_wr = round(sum(1 for h in recent if h["result"] == "WIN") / max(len(recent), 1) * 100, 1)
    params    = load_ai_params()

    # Feedback loop: WR por faixa de confiança da IA
    conf_stats: dict = {}
    for h in history:
        c = h.get("ai_confidence", 0)
        if c == 0:
            continue
        bucket = f"{(c // 2) * 2}-{(c // 2) * 2 + 1}"
        if bucket not in conf_stats:
            conf_stats[bucket] = {"wins": 0, "total": 0}
        conf_stats[bucket]["total"] += 1
        if h["result"] == "WIN":
            conf_stats[bucket]["wins"] += 1

    conf_summary = [
        f"Confiança {bucket}/10: WR {round(s['wins']/s['total']*100)}% ({s['total']} trades)"
        for bucket, s in sorted(conf_stats.items())
    ]

    user_msg = f"""
=== RELATÓRIO SEMANAL ===

Performance geral: WR {wr}% ({bot.wins}W/{bot.losses}L) | P&L ${total_pnl} | Saldo ${round(bot.balance, 2)}
WR últimos 30 trades: {recent_wr}%

Por par:
{chr(10).join(pair_summary)}

Feedback loop IA (confiança x resultado):
{chr(10).join(conf_summary) if conf_summary else 'dados insuficientes ainda'}

Parâmetros atuais:
  min_confluence={params['min_confluence']} | min_adx={params['min_adx']}
  min_rr={params['min_rr']} | session_strictness={params['session_strictness']}
  blocked_pairs={params['blocked_pairs']}

Análise estratégica vigente: {params.get('opus_summary') or 'ainda não disponível'}

Últimos 15 trades (para contexto):
{[(h['symbol'], h['dir'], h['result'], f"PnL=${h['pnl']}", f"ADX={h.get('adx', 0)}", f"conf={h.get('ai_confidence', 0)}") for h in history[-15:]]}
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


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 3 — ESTRATÉGIA MENSAL PROFUNDA
# ═══════════════════════════════════════════════════════════════════════════════

_STRATEGIST_SYSTEM = """
Você é um estrategista quantitativo sênior especializado em forex e ouro algorítmico.

Analise profundamente o histórico do bot e identifique padrões estruturais.
Pense como gestor de fundo: regime de mercado, correlações, viés direcional, horários.

Regras:
- market_regime: estado geral do mercado forex nas últimas semanas
- regime_pairs: cada par tem seu próprio regime (trending/ranging/volatile)
- favored_sessions: sessões com WR maior (london, new_york, overlap, asia)
- avoid_hours_utc: horas UTC com WR < 40% nos dados
- strategy_bias: "conservative" se drawdown > 15% ou WR < 45%; "aggressive" se WR > 62%; senão "balanced"
- opus_summary: seja específico — cite pares, números, padrões temporais concretos (5-8 frases)

Responda SOMENTE com JSON válido:
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
    Camada 3: análise estrutural mensal.
    Retorna dicionário com análise profunda, ou None se falhar.
    """
    from config import Config

    if not _get_api_key():
        log("[AI] GEMINI_API_KEY não configurada — análise mensal ignorada.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_FOR_DEEP:
        log(f"[AI] Histórico insuficiente ({len(history)}/{MIN_TRADES_FOR_DEEP})")
        return None

    pair_summary, _ = _build_pair_stats(history)
    total     = bot.wins + bot.losses
    wr        = round(bot.wins / total * 100, 1) if total > 0 else 0
    total_pnl = round(bot.balance - Config.INITIAL_BALANCE, 2)

    buy_trades  = [h for h in history if h.get("dir") == "BUY"]
    sell_trades = [h for h in history if h.get("dir") == "SELL"]
    buy_wr  = round(sum(1 for h in buy_trades  if h["result"] == "WIN") / max(len(buy_trades),  1) * 100, 1)
    sell_wr = round(sum(1 for h in sell_trades if h["result"] == "WIN") / max(len(sell_trades), 1) * 100, 1)

    hour_stats: dict = {}
    for h in history:
        hour = _parse_history_hour(h)
        if hour is None:
            continue
        if hour not in hour_stats:
            hour_stats[hour] = {"wins": 0, "total": 0}
        hour_stats[hour]["total"] += 1
        if h["result"] == "WIN":
            hour_stats[hour]["wins"] += 1

    hour_summary = [
        f"{hour:02d}h UTC: WR {round(s['wins']/s['total']*100)}% ({s['total']} trades)"
        for hour, s in sorted(hour_stats.items())
    ]

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

Geral: {total} trades | WR {wr}% | P&L ${total_pnl} | Saldo ${round(bot.balance, 2)}
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
    params["opus_updated_at"]  = datetime.now(timezone.utc).isoformat()

    save_ai_params(params)
    log(f"[AI] Análise mensal concluída: regime={params['market_regime']} | bias={params['strategy_bias']}")
    return params


# ═══════════════════════════════════════════════════════════════════════════════
# DETECÇÃO DE REGIME EM TEMPO REAL (sem API)
# ═══════════════════════════════════════════════════════════════════════════════

_ADX_RANGING  = 18
_ADX_TRENDING = 25


def check_live_regime(bot) -> dict:
    """
    Roda a cada heartbeat (1h) sem chamar API.
    Usa ADX do cache para classificar regime de mercado.
    """
    try:
        from analysis import _cache, _cache_lock
        import pandas as pd
    except ImportError:
        return {"live_regime": "neutral", "confluence_adj": 0, "avg_adx": 0, "effective_conf": 7}

    adx_values = []
    with _cache_lock:
        cache_items = list(_cache.items())

    for sym, (_, df) in cache_items:
        try:
            if len(df) < 28:
                continue
            df_tail = df.tail(50)
            highs, lows, closes = df_tail["High"], df_tail["Low"], df_tail["Close"]

            tr = pd.concat([
                highs - lows,
                (highs - closes.shift()).abs(),
                (lows  - closes.shift()).abs(),
            ], axis=1).max(axis=1)

            up_move  = highs.diff()
            dn_move  = -lows.diff()
            plus_dm  = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
            minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
            atr_s    = tr.rolling(14).mean()
            plus_di  = 100 * plus_dm.rolling(14).mean() / (atr_s + 1e-10)
            minus_di = 100 * minus_dm.rolling(14).mean() / (atr_s + 1e-10)
            dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
            adx_val  = float(dx.rolling(14).mean().iloc[-1])

            if adx_val > 0 and adx_val <= 100 and not pd.isna(adx_val):
                adx_values.append(adx_val)
        except Exception as e:
            log(f"[REGIME] Erro ao calcular ADX para {sym}: {e}")
            continue

    params    = load_ai_params()
    base_conf = params.get("min_confluence", 7)

    if len(adx_values) < 3:
        log(f"[REGIME] Dados insuficientes ({len(adx_values)}/3 pares) — mantendo regime anterior")
        return {
            "live_regime":    params.get("live_regime", "neutral"),
            "avg_adx":        0,
            "confluence_adj": 0,
            "effective_conf": base_conf,
        }

    avg_adx = round(sum(adx_values) / len(adx_values), 1)

    if avg_adx < _ADX_RANGING:
        live_regime    = "ranging"
        confluence_adj = +1
        log(f"[REGIME] Mercado em RANGING (ADX={avg_adx})")
    elif avg_adx > _ADX_TRENDING:
        live_regime    = "trending"
        confluence_adj = -1
        log(f"[REGIME] Mercado em TRENDING (ADX={avg_adx})")
    else:
        live_regime    = "neutral"
        confluence_adj = 0
        log(f"[REGIME] Mercado NEUTRO (ADX={avg_adx})")

    effective_conf = max(6, min(9, base_conf + confluence_adj))

    prev_regime = params.get("live_regime", "neutral")
    params["live_regime"]     = live_regime
    params["live_adx_avg"]    = avg_adx
    params["live_confluence"] = effective_conf
    save_ai_params(params)

    if live_regime != prev_regime:
        log(f"[REGIME] Mudança: {prev_regime} → {live_regime} | confluence={effective_conf}")

    return {
        "live_regime":    live_regime,
        "avg_adx":        avg_adx,
        "confluence_adj": confluence_adj,
        "effective_conf": effective_conf,
    }
