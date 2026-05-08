import time
import random
from datetime import datetime
from config import Config
from utils import (log, fmt, max_leverage, get_sl_tp_atr, is_jpy_pair,
                   is_good_session, get_kill_zone, is_price_in_ote,
                   get_allowed_symbols, load_strategy_settings)
from analysis import get_multi_timeframe
from risk import calc_margin, contract_size_for, calc_lot_for_risk
from news_filter import is_high_impact_news_window
from cot_filter import get_cot_bias

# Cache do snapshot de confluência
_SNAPSHOT_TTL = 600  # 10 minutos
_snapshot_cache = []
_snapshot_ts = 0.0


def _is_safe_to_trade(bot, symbol):
    """
    Verificações de segurança consolidadas.
    Retorna (True, "") se seguro, ou (False, "motivo") se bloqueado.
    """
    from utils import (
        is_weekend_gap_risk,
        get_allowed_symbols,
        get_dynamic_cooldown,
        is_symbol_allowed,
    )

    # 1. Verifica se o ativo está no universo monitorado
    if not is_symbol_allowed(symbol):
        allowed = get_allowed_symbols()
        return False, f"Ativo fora da lista monitorada. Monitorados: {', '.join(allowed)}"

    # 3. Proteção de fim de semana / gap
    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    # 3. Cooldown dinâmico (fixo no modo signal-only)
    cooldown = get_dynamic_cooldown(None)
    if time.time() - bot.asset_cooldown.get(symbol, 0) < cooldown:
        return False, f"Cooldown ativo ({cooldown//60}min)"

    # 4. Filtro de sessão — só opera na janela de liquidez do par
    if not is_good_session(symbol):
        return False, "Fora da sessão principal"

    # 5. Horas a evitar definidas pelo Opus (aprendizado mensal)
    from ai_validator import load_ai_params
    avoid_hours = load_ai_params().get("avoid_hours_utc", [])
    if avoid_hours and datetime.utcnow().hour in avoid_hours:
        return False, f"Hora bloqueada pelo Opus ({datetime.utcnow().hour}h UTC)"

    return True, ""




def _market_regime(res: dict, mtf: dict | None = None) -> str:
    """Classifica o mercado para adaptar o tipo de setup."""
    h1_adx = float(res.get("adx", 0) or 0)
    aligned = bool(mtf.get("aligned", False)) if mtf else False
    daily_bias = (mtf.get("daily_bias", "NEUTRO") if mtf else "NEUTRO")
    h4 = mtf.get("h4") if mtf else None
    h4_adx = float(h4.get("adx", 0) or 0) if h4 else 0

    if h1_adx >= Config.REGIME_ADX_TRENDING and aligned and daily_bias != "NEUTRO":
        return "trend"
    if h1_adx <= Config.REGIME_ADX_RANGING:
        return "range"
    if 18 < h1_adx < Config.REGIME_ADX_TRENDING:
        return "transition"
    if h4_adx >= Config.REGIME_ADX_STRONG and daily_bias != "NEUTRO":
        return "trend"
    return "neutral"


def _setup_for_regime(regime: str, direction: str) -> str:
    if regime == "trend":
        return "pullback"
    return "wait"


def calc_confluence(res, direction, mtf=None):
    """Confluência enxuta para FX core."""
    price = float(res.get("price", 0) or 0)
    ema200 = float(res.get("ema200", 0) or 0)
    rsi = float(res.get("rsi", 50) or 50)
    macd_bull = bool(res.get("macd_bull", False) or res.get("macd_cross_up", False) or res.get("macd_above", False))
    macd_bear = bool(res.get("macd_bear", False) or res.get("macd_cross_down", False) or res.get("macd_below", False))
    atr = float(res.get("atr", 0) or 0)
    adx = float(res.get("adx", 0) or 0)

    checks = []
    weighted = []
    def add(name: str, ok: bool, weight: int = 1):
        checks.append((name, bool(ok)))
        weighted.append((name, bool(ok), int(weight)))

    regime = "trend" if (price > ema200 and macd_bull) or (price < ema200 and macd_bear) else "transition"
    setup_type = "trend_pullback" if regime == "trend" else "wait"

    if direction == "BUY":
        add("Preço > EMA200", price > ema200, Config.CONFLUENCE_WEIGHTS.get("ema200", 4))
        add("MACD bullish", macd_bull, Config.CONFLUENCE_WEIGHTS.get("macd", 3))
        add("RSI favorável", 50 <= rsi <= 70, Config.CONFLUENCE_WEIGHTS.get("rsi", 2))
    else:
        add("Preço < EMA200", price < ema200, Config.CONFLUENCE_WEIGHTS.get("ema200", 4))
        add("MACD bearish", macd_bear, Config.CONFLUENCE_WEIGHTS.get("macd", 3))
        add("RSI favorável", 30 <= rsi <= 50, Config.CONFLUENCE_WEIGHTS.get("rsi", 2))

    atr_ok = atr > 0
    add("ATR válido", atr_ok, 0)

    score = sum(weight for _, ok, weight in weighted if ok)
    total = sum(weight for _, _, weight in weighted)
    min_score = Config.MIN_CONFLUENCE_WEIGHTED
    passed = score >= min_score and atr_ok
    meta = {"regime": regime, "setup_type": setup_type, "atr": atr, "adx": adx}
    return score, total, checks, passed, min_score, meta


def _recent_pair_wr(bot, symbol: str, direction: str | None = None, lookback: int | None = None):
    """Retorna o win rate recente do par/direção ou None se ainda não houver amostra suficiente."""
    lookback = int(lookback or getattr(Config, "PAIR_PERFORMANCE_LOOKBACK", 12))
    min_sample = max(5, lookback)
    history = list(getattr(bot, "history", []) or [])
    filtered = [h for h in history if h.get("symbol") == symbol and (direction is None or h.get("dir") == direction)]
    if len(filtered) < min_sample:
        return None
    sample = filtered[-lookback:]
    wins = sum(1 for h in sample if h.get("result") == "WIN")
    return wins / max(1, len(sample))

def _get_smc_sl_tp(entry, direction, res, mtf, atr):
    """SL/TP simples baseado só em ATR."""
    if not atr or atr <= 0:
        return None, None, 0.0, "atr", "atr"
    sl, tp, rr = get_sl_tp_atr(entry, atr, direction, Config.ATR_SL_MULT, Config.ATR_TP_MULT)
    return sl, tp, rr, "atr", "atr"


def check_near_signals(bot) -> None:
    """
    Verifica se algum par PERMITIDO está com score próximo do mínimo.
    Só alerta pares que estão próximos do threshold técnico.
    """
    from ai_validator import load_ai_params
    from utils import get_allowed_symbols

    ai_params      = load_ai_params()
    effective_conf = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
    NEAR_THRESHOLD = effective_conf - 2

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    # Universo monitorado
    allowed_symbols = set(get_allowed_symbols())
    now             = time.time()
    snapshot        = get_confluence_snapshot()

    for item in snapshot:
        sym   = item["symbol"]
        score = item["best_score"]
        total = item["total"]
        direction = item.get("best_dir") or item.get("direction") or item.get("dir") or "—"

        if sym not in allowed_symbols:
            continue

        if score < NEAR_THRESHOLD or score >= effective_conf:
            continue

        last_alert = bot._near_signal_cooldown.get(sym, 0)
        if now - last_alert < 7200:
            continue

        checks  = item["buy_checks"] if direction == "BUY" else item["sell_checks"]
        missing = [name for name, ok in checks if not ok][:3]

        bars = "🟢" * score + "⚪" * (total - score)
        msg  = (
            f"📊 QUASE SINAL — {sym}\n"
            f"——————————————\n"
            f"Direção: {direction} | Score: {score}/{total}\n"
            f"{bars}\n"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\n"
            f"H4: {'✅ Alinhado' if item['h4_aligned'] else '❌ Desalinhado'}\n\n"
            f"❌ Falta confirmar:\n" +
            "\n".join(f"  • {m}" for m in missing) +
            f"\n\nFaltam {effective_conf - score} check(s) para virar sinal."
        )
        bot.send(msg)
        bot._near_signal_cooldown[sym] = now
        log(f"[NEAR] {sym} {direction} {score}/{total} — alerta enviado")
