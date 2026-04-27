from datetime import datetime
from config import Config

def fmt(value: float) -> str:
    if value is None: return "0"
    if abs(value) >= 10000: return f"{value:,.2f}"
    if abs(value) >= 1000: return f"{value:.2f}"
    if abs(value) >= 10: return f"{value:.4f}"
    if abs(value) >= 1: return f"{value:.5f}"
    return f"{value:.6f}"

def log(msg: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

def asset_name(symbol):
    return Config.FXGOLD_ASSETS.get(symbol, symbol)

def is_jpy_pair(symbol):
    return symbol.endswith("JPY")

def jpy_to_usd(pnl_jpy, usdjpy_price):
    if usdjpy_price and usdjpy_price > 0:
        return pnl_jpy / usdjpy_price
    return 0.0

def max_leverage(symbol, lot=0.01):
    """
    Retorna a alavancagem efetiva.
    Se USE_FIXED_LEVERAGE = True, sempre retorna DEFAULT_LEVERAGE.
    Se False, usa a alavancagem dinâmica da Tickmill.
    """
    if Config.USE_FIXED_LEVERAGE:
        return Config.DEFAULT_LEVERAGE

    # Dinâmica Tickmill (MT5)
    if symbol == "XAUUSD":
        return 1000 if lot <= 1.0 else 500
    return 1000 if lot <= 2.0 else 500

def get_sl_tp_pct(leverage, rr=None):
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, leverage)
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp

def get_sl_tp_atr(entry, atr, direction, atr_sl_mult=1.5, atr_tp_mult=2.5):
    sl_dist = atr * atr_sl_mult
    tp_dist = atr * atr_tp_mult
    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)
    return sl, tp, sl_dist, tp_dist


# ═══════════════════════════════════════════════════════════
# NOVAS FUNÇÕES: SEGURANÇA DINÂMICA
# ═══════════════════════════════════════════════════════════

def get_dynamic_leverage(balance):
    """
    Retorna alavancagem baseada no capital atual.
    Se USE_DYNAMIC_LEVERAGE=False, retorna DEFAULT_LEVERAGE.
    """
    if not Config.USE_DYNAMIC_LEVERAGE:
        return Config.DEFAULT_LEVERAGE

    for threshold, lev in sorted(Config.DYNAMIC_LEVERAGE_TABLE.items()):
        if balance <= threshold:
            return lev
    return Config.DEFAULT_LEVERAGE

def get_dynamic_max_trades(balance):
    """Retorna máximo de trades ativos permitidos para o capital atual."""
    for threshold, max_t in sorted(Config.DYNAMIC_MAX_TRADES.items()):
        if balance <= threshold:
            return max_t
    return Config.MAX_TRADES

def get_allowed_symbols(balance):
    """Retorna lista de símbolos permitidos para o capital atual."""
    allowed = []
    for tier in sorted(Config.ASSET_TIERS.keys()):
        if balance >= Config.ASSET_TIERS[tier]["min_balance"]:
            allowed = Config.ASSET_TIERS[tier]["symbols"]
    return allowed

def get_max_risk_absolute(balance):
    """Retorna risco máximo absoluto (USD) permitido por trade."""
    for threshold, risk in sorted(Config.MAX_RISK_ABSOLUTE_USD.items()):
        if balance <= threshold:
            return risk
    return 100.0

def get_min_free_margin_pct(balance):
    """Retorna % mínima de margem livre obrigatória."""
    for threshold, pct in sorted(Config.MIN_FREE_MARGIN_PCT.items()):
        if balance <= threshold:
            return pct
    return 0.15

def get_dynamic_cooldown(balance):
    """Retorna cooldown em segundos após loss, baseado no capital."""
    for threshold, cd in sorted(Config.DYNAMIC_COOLDOWN.items()):
        if balance <= threshold:
            return cd
    return Config.ASSET_COOLDOWN

def is_weekend_gap_risk():
    """
    Retorna True se estiver em período de alto risco de gap:
    - Sexta após 20h UTC
    - Domingo antes de 22h UTC
    """
    now = datetime.utcnow()
    dow = now.weekday()  # 0=Seg, 4=Sex, 5=Sab, 6=Dom
    hour = now.hour

    if dow == 4 and hour >= Config.FRIDAY_NO_TRADE_AFTER_HOUR:
        return True
    if dow == 5:  # Sábado
        return True
    if dow == 6 and hour < Config.SUNDAY_NO_TRADE_BEFORE_HOUR:
        return True
    return False

def is_symbol_allowed(symbol, balance):
    """Verifica se o símbolo é permitido para o capital atual."""
    allowed = get_allowed_symbols(balance)
    return symbol in allowed


# ═══════════════════════════════════════════════════════════
# FILTRO DE SESSÃO
# ═══════════════════════════════════════════════════════════
# Cada par tem liquidez máxima em janelas específicas.
# Sinais fora da sessão principal têm WR significativamente menor.
#
#   London:      07–16 UTC
#   New York:    12–21 UTC
#   Overlap:     12–16 UTC  (maior volume, melhor para EUR/GBP)
#   Ásia:        00–09 UTC  (melhor para JPY, AUD, NZD)
#
# Formato: lista de (hora_inicio, hora_fim) em UTC.
# Para janelas que cruzam meia-noite, usa dois intervalos.

_SESSION_WINDOWS: dict[str, list[tuple[int, int]]] = {
    "EURUSD": [(7, 20)],          # Londres + NY
    "GBPUSD": [(7, 20)],          # Londres + NY
    "EURGBP": [(7, 18)],          # Principalmente Londres
    "EURJPY": [(7, 20)],          # Londres + NY
    "GBPJPY": [(7, 20)],          # Londres + NY
    "USDJPY": [(0, 9), (12, 16)], # Ásia + overlap London-NY
    "USDCAD": [(12, 21)],         # NY (dados canadenses saem 13-15 UTC)
    "USDCHF": [(7, 20)],          # Londres + NY
    "AUDUSD": [(22, 24), (0, 14)],# Sydney + Ásia + Londres
    "NZDUSD": [(21, 24), (0, 13)],# Sydney + Ásia + início Londres
    "XAUUSD": [(7, 21)],          # Londres + NY (ouro segue ambas)
}


def is_good_session(symbol: str) -> bool:
    """
    Retorna True se o horário atual (UTC) está dentro da janela
    de liquidez principal do par.
    Fora da sessão, a probabilidade de fake breakouts aumenta.
    """
    windows = _SESSION_WINDOWS.get(symbol)
    if not windows:
        return True  # símbolo desconhecido: não bloqueia

    hour = datetime.utcnow().hour
    for start, end in windows:
        if start < end:
            if start <= hour < end:
                return True
        else:
            # intervalo que cruza meia-noite (ex: 22-24 não existe, usamos 22-0)
            if hour >= start or hour < end:
                return True
    return False
