"""
ai_validator.py — 3 camadas de inteligência (Google Gemini 2.0 Flash)
======================================================================

CAMADA 1 │ gemini-2.0-flash │ Validação de cada sinal    │ ~1s  │ GRÁTIS
CAMADA 2 │ gemini-2.0-flash │ Aprendizado semanal        │ ~3s  │ GRÁTIS
CAMADA 3 │ gemini-2.0-flash │ Estratégia mensal profunda │ ~8s  │ GRÁTIS

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
# Configuração do modelo
# ═══════════════════════════════════════════════════════════════════════════════
_MODEL_FLASH = "gemini-2.0-flash"
_GEMINI_URL  = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

AI_PARAMS_FILE      = "ai_params.json"
MIN_TRADES_TO_LEARN = 20
MIN_TRADES_FOR_DEEP = 50

# ═════════════���═════════════════════════════════════════════════════════════════
# Rate limiter (15 req/min free tier, usamos 12 com margem)
# ═══════════════════════════════════════════════════════════════════════════════
_RATE_LIMIT  = 12
_RATE_WINDOW = 60
_call_times: deque = deque()


def _rate_limit_wait():
    """Bloqueia até haver espaço na janela deslizante de 60s."""
    now = time.time()
    while _call_times and now - _call_times[0] >= _RATE_WINDOW:
        _call_times.popleft()

    if len(_call_times) >= _RATE_LIMIT:
        wait = _RATE_WINDOW - (now - _call_times[0]) + 1
        if wait > 0:
            log(f"[AI] Rate limit preventivo — aguardando {wait:.0f}s")
            time.sleep(wait)
        now = time.time()
        while _call_times and now - _call_times[0] >= _RATE_WINDOW:
            _call_times.popleft()

    _call_times.append(time.time())


# ═══════════════════════════════════════════════════════════════════════════════
# PARÂMETROS APRENDIDOS
# ═══════════════════════════════════════════════════════════════════════════════

def load_ai_params() -> dict:
    """Carrega parâmetros aprendidos de ai_params.json."""
    defaults = {
        # Camada 2 — Aprendizado semanal
        "min_confluence":      7,
        "blocked_pairs":       [],
        "session_strictness":  "normal",
        "min_adx":             20,
        "min_rr":              1.5,
        "last_suggestion":     None,
        # Camada 3 — Análise mensal
        "market_regime":       "neutral",
        "regime_pairs":        {},
        "favored_sessions":    [],
        "avoid_hours_utc":     [],
        "strategy_bias":       "balanced",
        "opus_summary":        None,
        "opus_updated_at":     None,
        # Regime em tempo real
        "live_regime":         "neutral",
        "live_adx_avg":        0,
        "live_confluence":     7,
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
    """Salva parâmetros aprendidos em ai_params.json."""
    params["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = AI_PARAMS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    os.replace(tmp, AI_PARAMS_FILE)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: chamada ao Gemini com retry e rate limit
# ═══════════════════════════════════════════════════════════════════════════════

def _get_api_key() -> str:
    """Retorna a chave da API Gemini."""
    from config import Config
    return getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def _call_gemini(
    system: str,
    user_msg: str,
    max_tokens: int = 500,
    timeout: int = 25,
) -> str | None:
    """
    Chamada ao Gemini com retry automático e rate limiting.
    
    Parâmetros:
    - system: System prompt (instruções para a IA)
    - user_msg: Mensagem do usuário
    - max_tokens: Máximo de tokens na resposta
    - timeout: Timeout em segundos
    
    Retorna:
    - String com a resposta, ou None se falhar após retries
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    url  = _GEMINI_URL.format(model=_MODEL_FLASH)
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }

    for attempt in range(2):
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
            log(f"[AI] Gemini timeout (tentativa {attempt + 1}/2)")
            if attempt == 0:
                time.sleep(5)

        except requests.exceptions.ConnectionError as e:
            log(f"[AI] Gemini conexão falhou (tentativa {attempt + 1}/2): {str(e)[:80]}")
            if attempt == 0:
                time.sleep(10)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 429:
                log("[AI] Gemini 429 — aguardando 65s")
                _call_times.clear()
                time.sleep(65)
                if attempt == 0:
                    continue
                return None
            elif status >= 500:
                log(f"[AI] Gemini erro servidor {status}")
                if attempt == 0:
                    time.sleep(5)
            else:
                log(f"[AI] Gemini HTTP {status}: {str(e)[:80]}")
                return None

        except Exception as e:
            log(f"[AI] Gemini erro inesperado: {type(e).__name__}: {str(e)[:80]}")
            return None

    log("[AI] Gemini falhou após 2 tentativas")
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


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: estatísticas por par
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_history_hour(h: dict) -> int | None:
    """
    Extrai a hora UTC de um trade do histórico.
    Tenta ISO primeiro (novo formato), depois "dd/mm HH:MM" (legado).
    """
    iso = h.get("opened_ts_iso")
    if iso:
        try:
            return datetime.fromisoformat(iso).astimezone(timezone.utc).hour
        except Exception:
            pass
    # Legado
    opened = h.get("opened_at", "")
    if opened and " " in opened:
        try:
            return int(opened.split(" ")[1].split(":")[0])
        except Exception:
            pass
    return None


def _build_pair_stats(history: list) -> tuple[list[str], dict]:
    """Calcula estatísticas por par (WR, PnL, ADX)."""
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
            f"PnL=${round(s['pnl'], 2)} ADX_médio={avg_adx}"
        )
    return summary, pair_stats


# ════════���══════════════════════════════════════════════════════════════════════
# FALLBACK TÉCNICO - Sem IA
# ═══════════════════════════════════════════════════════════════════════════════

def _get_technical_fallback_score(h1: dict, direction: str) -> tuple[int, str]:
    """
    Fallback 100% técnico quando IA cai.
    Retorna (score, motivo).
    
    Score máximo sem IA: 9 pontos
    """
    price = h1.get("price", 0)
    
    score = 0
    reasons = []
    
    # ── Trend (4 pontos) ──
    if direction == "BUY":
        if price > h1.get("ema200", 0):
            score += 2
            reasons.append("Preço > EMA200")
        if h1.get("ema9", 0) > h1.get("ema21", 0):
            score += 1
            reasons.append("EMA9 > EMA21")
    else:
        if price < h1.get("ema200", float('inf')):
            score += 2
            reasons.append("Preço < EMA200")
        if h1.get("ema9", 0) < h1.get("ema21", 0):
            score += 1
            reasons.append("EMA9 < EMA21")
    
    # ── Momentum (1 ponto) ──
    if h1.get("macd_bull") and direction == "BUY":
        score += 1
        reasons.append("MACD bullish")
    elif h1.get("macd_bear") and direction == "SELL":
        score += 1
        reasons.append("MACD bearish")
    
    # ── Force (3 pontos) ──
    if h1.get("adx", 0) > 25:
        score += 3
        reasons.append("ADX > 25")
    elif h1.get("adx", 0) > 20:
        score += 2
        reasons.append("ADX > 20")
    elif h1.get("adx", 0) > 15:
        score += 1
        reasons.append("ADX > 15")
    
    # ── Candle (1 ponto) ──
    if direction == "BUY" and h1.get("candle_bull"):
        score += 1
        reasons.append("Candle bullish")
    elif direction == "SELL" and h1.get("candle_bear"):
        score += 1
        reasons.append("Candle bearish")
    
    reason = " | ".join(reasons) if reasons else "Nenhuma confirmação técnica"
    return score, reason


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 1 — VALIDADOR DE SINAIS
# ═══════════════════════════════════════════════════════════════════════════════

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
    Camada 1: Gemini valida o sinal antes de enviar ao Telegram.
    Retorna (aprovado, motivo).

    COM FALLBACK TÉCNICO SE IA CAIR.
    
    Política:
    - Sem API Key: usa fallback técnico
    - IA cai: usa fallback técnico com score mínimo ajustado por banca
    """
    from config import Config

    api_key = _get_api_key()

    h1        = indicators.get("h1") or indicators
    direction = signal.get("dir", "BUY")
    sym       = signal.get("symbol", "?")
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

    ai_params   = load_ai_params()
    regime_info = ai_params.get("regime_pairs", {}).get(sym, ai_params.get("market_regime", "neutral"))
    bias        = ai_params.get("strategy_bias", "balanced")

    # ── FALLBACK: Se IA não está configurada ──
    if not api_key:
        tech_score, tech_reason = _get_technical_fallback_score(h1, direction)
        approved = tech_score >= 5  # Score mínimo técnico
        reason = f"[FALLBACK TÉCNICO] {tech_score}/9: {tech_reason}"
        log(f"[GEMINI] {sym} {direction} → {'✅' if approved else '❌'} {reason}")
        return approved, reason

    # ── GEMINI NORMAL ──
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

    # ── FALLBACK: Se Gemini falhou ──
    if result is None:
        tech_score, tech_reason = _get_technical_fallback_score(h1, direction)
        
        # Banca pequena: conservador
        if bot.balance <= 500:
            approved = tech_score >= 6  # Score mais alto
            reason = f"[IA INDISPONÍVEL] Fallback técnico: {tech_score}/9: {tech_reason}"
        # Banca grande: permite
        else:
            approved = tech_score >= 5
            reason = f"[IA INDISPONÍVEL] Fallback técnico: {tech_score}/9: {tech_reason}"
        
        log(f"[GEMINI] {sym} {direction} → {'✅' if approved else '❌'} {reason}")
        return approved, reason

    approve    = bool(result.get("approve", True))
    reason     = result.get("reason", "sem motivo")
    confidence = int(result.get("confidence", 5))

    log(f"[GEMINI] {sym} {direction} → {'✅' if approve else '❌'} "
        f"confiança {confidence}/10: {reason}")
    return approve, f"IA ({confidence}/10): {reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 2 — APRENDIZADO SEMANAL
# ═══════════════════════════════════════════════════════════════════════════════

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
    Camada 2: analisa histórico e ajusta parâmetros operacionais.
    
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
    recent_wr = (
        round(sum(1 for h in recent if h["result"] == "WIN") / max(len(recent), 1) * 100, 1)
    )
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

Performance: WR {wr}% ({bot.wins}W/{bot.losses}L) | P&L ${total_pnl} | Saldo ${round(bot.balance, 2)}
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
{[(h['symbol'], h['dir'], h['result'], 'PnL=$' + str(h['pnl']), 'ADX=' + str(h.get('adx', 0)), 'conf=' + str(h.get('ai_confidence', 0))) for h in history[-15:]]}
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

Analise profundamente o histórico do bot e identifique padrões estruturais:
quando e por que o sistema funciona ou falha. Pense como gestor de fundo:
regime de mercado, correlações, viés direcional, horários de alta/baixa performance.

Regras:
- market_regime: avalie o estado geral do mercado forex nas últimas semanas
- regime_pairs: cada par tem seu próprio regime (trending/ranging/volatile)
- favored_sessions: onde o WR é maior (london, new_york, overlap, asia)
- avoid_hours_utc: horas UTC com WR < 40% nos dados
- strategy_bias: "conservative" se drawdown > 15% ou WR < 45%; "aggressive" se WR > 60%
- opus_summary: seja específico — cite pares, números, padrões temporais (5-8 frases)

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

    # WR por hora UTC (corrigido: usa _parse_history_hour)
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
    Usa os valores de ADX do cache para classificar regime.
    COM VALIDAÇÃO DE DADOS SUFICIENTES.
    
    Retorna dicionário com:
    - live_regime: "ranging", "trending", "neutral", "volatile"
    - avg_adx: ADX médio calculado
    - confluence_adj: ajuste de confluência baseado no regime
    - effective_conf: confluência efetiva após ajuste
    """
    try:
        from analysis import _cache, _cache_lock
        import pandas as pd
    except ImportError:
        return {
            "live_regime": "neutral",
            "confluence_adj": 0,
            "avg_adx": 0,
            "effective_conf": 7
        }

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
            
            # Validação: ADX deve estar entre 0 e 100
            if adx_val > 0 and adx_val <= 100 and not pd.isna(adx_val):
                adx_values.append(adx_val)
        except Exception as e:
            log(f"[REGIME] Erro ao calcular ADX para {sym}: {e}")
            continue

    params    = load_ai_params()
    base_conf = params.get("min_confluence", 7)

    # ── VALIDAÇÃO: Mínimo 3 pares com dados válidos ──
    if len(adx_values) < 3:
        log(f"[REGIME] Dados insuficientes ({len(adx_values)}/3 pares) — mantendo regime anterior")
        return {
            "live_regime":    params.get("live_regime", "neutral"),
            "avg_adx":        0,
            "confluence_adj": 0,
            "effective_conf": base_conf,
        }

    avg_adx = round(sum(adx_values) / len(adx_values), 1)

    # ── Classificação ──
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
    params["live_regime"]      = live_regime
    params["live_adx_avg"]     = avg_adx
    params["live_confluence"]  = effective_conf
    save_ai_params(params)

    if live_regime != prev_regime:
        log(f"[REGIME] Mudança detectada: {prev_regime} → {live_regime} | confluence={effective_conf}")

    return {
        "live_regime":    live_regime,
        "avg_adx":        avg_adx,
        "confluence_adj": confluence_adj,
        "effective_conf": effective_conf,
    }
