
"""
ai_validator.py \u2014 3 camadas de intelig\u00eancia (Google Gemini 2.0 Flash)
======================================================================

CAMADA 1 \u2502 gemini-2.0-flash \u2502 Valida\u00e7\u00e3o de cada sinal    \u2502 ~1s  \u2502 GR\u00c1TIS
CAMADA 2 \u2502 gemini-2.0-flash \u2502 Aprendizado semanal        \u2502 ~3s  \u2502 GR\u00c1TIS
CAMADA 3 \u2502 gemini-2.0-flash \u2502 Estrat\u00e9gia mensal profunda \u2502 ~8s  \u2502 GR\u00c1TIS

Free tier Google AI Studio: 1.500 req/dia, 15 req/min.
Chave gr\u00e1tis em: https://aistudio.google.com/apikey
"""

import json
import os
import time
import requests
from collections import deque
from datetime import datetime, timezone
from utils import log

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Configura\u00e7\u00e3o do modelo
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
_MODEL_FLASH = "gemini-2.0-flash"
_GEMINI_URL  = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

AI_PARAMS_FILE      = "ai_params.json"
MIN_TRADES_TO_LEARN = 20
MIN_TRADES_FOR_DEEP = 50

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Rate limiter (15 req/min free tier, usamos 12 com margem)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
_RATE_LIMIT  = 12
_RATE_WINDOW = 60
_call_times: deque = deque()


def _rate_limit_wait():
    """Bloqueia at\u00e9 haver espa\u00e7o na janela deslizante de 60s."""
    now = time.time()
    while _call_times and now - _call_times[0] >= _RATE_WINDOW:
        _call_times.popleft()

    if len(_call_times) >= _RATE_LIMIT:
        wait = _RATE_WINDOW - (now - _call_times[0]) + 1
        if wait > 0:
            log(f"[AI] Rate limit preventivo \u2014 aguardando {wait:.0f}s")
            time.sleep(wait)
        now = time.time()
        while _call_times and now - _call_times[0] >= _RATE_WINDOW:
            _call_times.popleft()

    _call_times.append(time.time())


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# PAR\u00c2METROS APRENDIDOS
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def load_ai_params() -> dict:
    defaults = {
        # Camada 2 \u2014 Aprendizado semanal
        "min_confluence":      7,
        "blocked_pairs":       [],
        "session_strictness":  "normal",
        "min_adx":             20,
        "min_rr":              1.5,
        "last_suggestion":     None,
        # Camada 3 \u2014 An\u00e1lise mensal
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
    params["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = AI_PARAMS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    os.replace(tmp, AI_PARAMS_FILE)


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# HELPER: chamada ao Gemini com retry e rate limit
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def _get_api_key() -> str:
    from config import Config
    return getattr(Config, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")


def _call_gemini(
    system: str,
    user_msg: str,
    max_tokens: int = 500,
    timeout: int = 25,
) -> str | None:
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
            log(f"[AI] Gemini conex\u00e3o falhou (tentativa {attempt + 1}/2): {str(e)[:80]}")
            if attempt == 0:
                time.sleep(10)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 429:
                log("[AI] Gemini 429 \u2014 aguardando 65s")
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

    log("[AI] Gemini falhou ap\u00f3s 2 tentativas")
    return None


def _parse_json(raw: str, context: str = "") -> dict | None:
    """Parse JSON robusto \u2014 remove markdown fences se necess\u00e1rio."""
    if raw is None:
        return None
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        log(f"[AI] Erro parse JSON {context}: {e} | raw: {raw[:120]}")
        return None


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# HELPER: estat\u00edsticas por par
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def _parse_history_hour(h: dict) -> int | None:
    """
    Extrai a hora UTC de um trade do hist\u00f3rico.
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
            f"PnL=${round(s['pnl'], 2)} ADX_m\u00e9dio={avg_adx}"
        )
    return summary, pair_stats


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CAMADA 1 \u2014 VALIDADOR DE SINAIS
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

_VALIDATOR_SYSTEM = """
Voc\u00ea \u00e9 um validador de sinais forex/ouro especializado em SMC (Smart Money Concepts).

Sua tarefa: avaliar se um sinal t\u00e9cnico deve ser enviado ao trader ou rejeitado.

Rejeite se:
- ADX < 18 (mercado sem dire\u00e7\u00e3o)
- RSI > 72 em BUY ou RSI < 28 em SELL (zona extrema oposta)
- H4 desalinhado com H1 (sem conflu\u00eancia multi-timeframe)
- \u00daltimos 3 trades no par todos LOSS
- FVG e OB ambos inativos

Aprove com alta confian\u00e7a (>= 8) se:
- FVG ativo + OB ativo + sweep confirmado + H4 alinhado
- ADX >= 25 e MACD confirmando dire\u00e7\u00e3o
- WR recente do par >= 55%

Responda SOMENTE com JSON v\u00e1lido, sem texto adicional:
{"approve": true, "confidence": 8, "reason": "motivo curto em portugu\u00eas"}
""".strip()


def validate_signal(signal: dict, indicators: dict, bot) -> tuple[bool, str]:
    """
    Camada 1: Gemini valida o sinal antes de enviar ao Telegram.
    Retorna (aprovado, motivo).

    IMPORTANTE: se IA n\u00e3o est\u00e1 configurada ou falha, seguimos uma
    pol\u00edtica conservadora baseada no saldo:
    - Banca <= $500: REJEITA em caso de falha (prote\u00e7\u00e3o m\u00e1xima)
    - Banca > $500:  APROVA em caso de falha (business continuity)
    """
    from config import Config

    if not _get_api_key():
        # Sem IA: aprova mas deixa expl\u00edcito
        return True, "IA n\u00e3o configurada \u2014 aprova\u00e7\u00e3o autom\u00e1tica (0/10)"

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
    )
    last_results = [h["result"] for h in pair_history[-5:]]

    ai_params   = load_ai_params()
    regime_info = ai_params.get("regime_pairs", {}).get(sym, ai_params.get("market_regime", "neutral"))
    bias        = ai_params.get("strategy_bias", "balanced")

    user_msg = f"""
Par: {sym} | Dire\u00e7\u00e3o: {direction}
Entrada: {signal.get('entry')} | SL: {signal.get('sl')} | TP: {signal.get('tp')}
RR: {signal.get('rr')} | Score: {signal.get('score')}/{signal.get('max_score')}

Indicadores H1:
- RSI: {h1.get('rsi',50)} | ADX: {h1.get('adx',0)}
- EMA9 {">" if h1.get('ema9',0) > h1.get('ema21',0) else "<"} EMA21
- Pre\u00e7o {">" if h1.get('price',0) > h1.get('ema200',0) else "<"} EMA200
- MACD bull: {h1.get('macd_bull')} | bear: {h1.get('macd_bear')}
- FVG ativo: {fvg_active} | OB ativo: {ob_active}
- Sweep bull: {sweep.get('bullish')} | bear: {sweep.get('bearish')}

H4: alinhado={indicators.get('aligned',False)} | cen\u00e1rio={indicators.get('h4_cenario','NEUTRO')}
Regime do par: {regime_info} | Vi\u00e9s estrat\u00e9gico: {bias}

Hist\u00f3rico par ({len(pair_history)} trades): WR {pair_wr}% | \u00daltimos: {last_results}
WR geral do bot: {round(bot.wins / max(bot.wins + bot.losses, 1) * 100, 1)}%
Trades ativos: {len(bot.active_trades)}
""".strip()

    raw    = _call_gemini(_VALIDATOR_SYSTEM, user_msg, max_tokens=120, timeout=15)
    result = _parse_json(raw, context=f"{sym} {direction}")

    if result is None:
        # Pol\u00edtica de fallback baseada no saldo
        if bot.balance <= 500:
            return False, "IA indispon\u00edvel \u2014 rejeitado (prote\u00e7\u00e3o banca pequena)"
        return True, "IA indispon\u00edvel \u2014 aprova\u00e7\u00e3o autom\u00e1tica (5/10)"

    approve    = bool(result.get("approve", True))
    reason     = result.get("reason", "sem motivo")
    confidence = int(result.get("confidence", 5))

    approve_emoji = "✅" if approve else "❌"
    log(f"[GEMINI] {sym} {direction} → {approve_emoji} "
        f"confiança {confidence}/10: {reason}")


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CAMADA 2 \u2014 APRENDIZADO SEMANAL
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

_LEARNER_SYSTEM = """
Voc\u00ea \u00e9 um especialista em sistemas de trading algor\u00edtmico forex/ouro (SMC).

Analise o hist\u00f3rico do bot e ajuste os par\u00e2metros para maximizar Win Rate.

Regras:
- blocked_pairs: s\u00f3 bloqueie com WR < 35% E m\u00ednimo 5 trades. Desbloqueie se melhorou.
- min_confluence: suba 1 se WR < 48%. Des\u00e7a 1 se WR > 62% e poucos sinais.
- min_adx: suba se maioria das perdas tem ADX < 20.
- Prefira mudan\u00e7as conservadoras \u2014 1 ponto por vez.
- Se WR >= 60% e P&L positivo, mantenha os par\u00e2metros.

Responda SOMENTE com JSON v\u00e1lido, sem texto adicional:
{
  "min_confluence": 7,
  "blocked_pairs": [],
  "session_strictness": "normal",
  "min_adx": 20,
  "min_rr": 1.5,
  "summary": "an\u00e1lise em at\u00e9 4 frases em portugu\u00eas"
}
""".strip()


def weekly_learning(bot) -> dict | None:
    """Camada 2: analisa hist\u00f3rico e ajusta par\u00e2metros operacionais."""
    from config import Config

    if not _get_api_key():
        log("[AI] GEMINI_API_KEY n\u00e3o configurada \u2014 aprendizado semanal ignorado.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_TO_LEARN:
        log(f"[AI] Hist\u00f3rico insuficiente ({len(history)}/{MIN_TRADES_TO_LEARN})")
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

    # Feedback loop: WR por faixa de confian\u00e7a da IA
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
        f"Confian\u00e7a {bucket}/10: WR {round(s['wins']/s['total']*100)}% ({s['total']} trades)"
        for bucket, s in sorted(conf_stats.items())
    ]

    user_msg = f"""
=== RELAT\u00d3RIO SEMANAL ===

Performance: WR {wr}% ({bot.wins}W/{bot.losses}L) | P&L ${total_pnl} | Saldo ${round(bot.balance, 2)}
WR \u00faltimos 30 trades: {recent_wr}%

Por par:
{chr(10).join(pair_summary)}

WR por confian\u00e7a da IA (feedback loop):
{chr(10).join(conf_summary) if conf_summary else 'dados insuficientes ainda'}

Par\u00e2metros atuais:
  min_confluence={params['min_confluence']} | min_adx={params['min_adx']}
  min_rr={params['min_rr']} | session_strictness={params['session_strictness']}
  blocked_pairs={params['blocked_pairs']}

Contexto estrat\u00e9gico: {params.get('opus_summary') or 'ainda n\u00e3o dispon\u00edvel'}

\u00daltimos 15 trades:
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
    log(f"[AI] Aprendizado conclu\u00eddo: {params['last_suggestion']}")
    return params


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CAMADA 3 \u2014 ESTRAT\u00c9GIA MENSAL PROFUNDA
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

_STRATEGIST_SYSTEM = """
Voc\u00ea \u00e9 um estrategista quantitativo s\u00eanior especializado em forex e ouro algor\u00edtmico.

Analise profundamente o hist\u00f3rico do bot e identifique padr\u00f5es estruturais:
quando e por que o sistema funciona ou falha. Pense como gestor de fundo:
regime de mercado, correla\u00e7\u00f5es, vi\u00e9s direcional, hor\u00e1rios de alta/baixa performance.

Regras:
- market_regime: avalie o estado geral do mercado forex nas \u00faltimas semanas
- regime_pairs: cada par tem seu pr\u00f3prio regime (trending/ranging/volatile)
- favored_sessions: onde o WR \u00e9 maior (london, new_york, overlap, asia)
- avoid_hours_utc: horas UTC com WR < 40% nos dados
- strategy_bias: "conservative" se drawdown > 15% ou WR < 45%; "aggressive" se WR > 60%
- opus_summary: seja espec\u00edfico \u2014 cite pares, n\u00fameros, padr\u00f5es temporais (5-8 frases)

Responda SOMENTE com JSON v\u00e1lido:
{
  "market_regime": "neutral",
  "regime_pairs": {"EURUSD": "trending", "XAUUSD": "volatile"},
  "favored_sessions": ["london", "overlap"],
  "avoid_hours_utc": [2, 3, 22],
  "strategy_bias": "balanced",
  "opus_summary": "an\u00e1lise estrat\u00e9gica em 5-8 frases em portugu\u00eas"
}
""".strip()


def monthly_deep_analysis(bot) -> dict | None:
    """Camada 3: an\u00e1lise estrutural mensal."""
    from config import Config

    if not _get_api_key():
        log("[AI] GEMINI_API_KEY n\u00e3o configurada \u2014 an\u00e1lise mensal ignorada.")
        return None

    history = bot.history or []
    if len(history) < MIN_TRADES_FOR_DEEP:
        log(f"[AI] Hist\u00f3rico insuficiente ({len(history)}/{MIN_TRADES_FOR_DEEP})")
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

    # Evolu\u00e7\u00e3o em quartis
    q_size   = max(len(history) // 4, 1)
    quarters = []
    for i in range(4):
        q = history[i * q_size: (i + 1) * q_size]
        if q:
            q_wins = sum(1 for h in q if h["result"] == "WIN")
            quarters.append(f"Q{i+1}: WR {round(q_wins/len(q)*100)}% ({len(q)} trades)")

    params = load_ai_params()

    user_msg = f"""
=== AN\u00c1LISE ESTRAT\u00c9GICA MENSAL ===

Geral: {total} trades | WR {wr}% | P&L ${total_pnl} | Saldo ${round(bot.balance, 2)}
BUY WR: {buy_wr}% ({len(buy_trades)} trades) | SELL WR: {sell_wr}% ({len(sell_trades)} trades)

Evolu\u00e7\u00e3o temporal:
{chr(10).join(quarters)}

Por par:
{chr(10).join(pair_summary)}

Por hora UTC:
{chr(10).join(hour_summary) if hour_summary else 'dados insuficientes'}

Par\u00e2metros atuais:
  min_confluence={params['min_confluence']} | min_adx={params['min_adx']}
  strategy_bias={params['strategy_bias']} | blocked_pairs={params['blocked_pairs']}

An\u00e1lise anterior: {params.get('opus_summary') or 'primeira an\u00e1lise'}
""".strip()

    log("[AI] An\u00e1lise estrat\u00e9gica mensal iniciada...")
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
    log(f"[AI] An\u00e1lise mensal conclu\u00edda: regime={params['market_regime']} | bias={params['strategy_bias']}")
    return params


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# DETEC\u00c7\u00c3O DE REGIME EM TEMPO REAL (sem API)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

_ADX_RANGING  = 18
_ADX_TRENDING = 25


def check_live_regime(bot) -> dict:
    """
    Roda a cada heartbeat (1h) sem chamar API.
    Usa os valores de ADX do cache para classificar regime.
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
            df_tail = df.tail(50)  # evita recurs\u00e3o profunda em s\u00e9ries longas
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
            if adx_val > 0 and not pd.isna(adx_val):
                adx_values.append(adx_val)
        except Exception:
            continue

    params    = load_ai_params()
    base_conf = params.get("min_confluence", 7)

    if not adx_values:
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
    elif avg_adx > _ADX_TRENDING:
        live_regime    = "trending"
        confluence_adj = -1
    else:
        live_regime    = "neutral"
        confluence_adj = 0

    effective_conf = max(6, min(9, base_conf + confluence_adj))

    prev_regime = params.get("live_regime", "neutral")
    params["live_regime"]      = live_regime
    params["live_adx_avg"]     = avg_adx
    params["live_confluence"]  = effective_conf
    save_ai_params(params)

    if live_regime != prev_regime:
        log(f"[REGIME] {prev_regime} \u2192 {live_regime} (ADX m\u00e9dio={avg_adx}) | confluence={effective_conf}")

    return {
        "live_regime":    live_regime,
        "avg_adx":        avg_adx,
        "confluence_adj": confluence_adj,
        "effective_conf": effective_conf,
    }
