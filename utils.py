from datetime import datetime
import json
import logging
import logging.handlers
import os
from config import Config

# ── Logger com rotação ────────────────────────────────────────────────────────
_logger = logging.getLogger("sniperbot")
_logger.setLevel(logging.INFO)

# Console handler
_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
_logger.addHandler(_ch)

# Rotating file handler — 10 MB × 5 arquivos = 50 MB máximo
_rfh = logging.handlers.RotatingFileHandler(
    "bot_app.log",
    maxBytes=Config.LOG_MAX_BYTES,
    backupCount=Config.LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_rfh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
_logger.addHandler(_rfh)

# Evita propagação para o root logger do Flask
_logger.propagate = False


def fmt(value: float) -> str:
    if value is None: return "0"
    if abs(value) >= 10000: return f"{value:,.2f}"
    if abs(value) >= 1000: return f"{value:.2f}"
    if abs(value) >= 10: return f"{value:.4f}"
    if abs(value) >= 1: return f"{value:.5f}"
    return f"{value:.6f}"


def log(msg: str):
    _logger.info(msg)

def asset_name(symbol):
    return Config.FXGOLD_ASSETS.get(symbol, symbol)

ASSET_SETTINGS_FILE = "asset_settings.json"


def _default_selected_symbols() -> list[str]:
    return list(Config.FXGOLD_ASSETS.keys())


def load_asset_settings() -> dict:
    defaults = {
        "selected_symbols": _default_selected_symbols(),
        "updated_at": None,
    }
    if not os.path.exists(ASSET_SETTINGS_FILE):
        return defaults
    try:
        with open(ASSET_SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        selected = stored.get("selected_symbols")
        if not isinstance(selected, list) or not selected:
            selected = _default_selected_symbols()
        cleaned = [s for s in selected if s in Config.FXGOLD_ASSETS]
        if not cleaned:
            cleaned = _default_selected_symbols()
        return {**defaults, **stored, "selected_symbols": cleaned}
    except Exception as e:
        log(f"[ASSETS] Erro ao carregar asset_settings.json: {e}")
        return defaults


def save_asset_settings(selected_symbols: list[str]) -> dict:
    cleaned = [s for s in selected_symbols if s in Config.FXGOLD_ASSETS]
    if not cleaned:
        cleaned = _default_selected_symbols()
    data = {
        "selected_symbols": cleaned,
        "updated_at": datetime.utcnow().isoformat(),
    }
    tmp = ASSET_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ASSET_SETTINGS_FILE)
    return data


def get_selected_symbols() -> list[str]:
    return load_asset_settings()["selected_symbols"]

TRADE_SETTINGS_FILE = "trade_settings.json"
MAX_MANUAL_ACTIVE_TRADES = 10


def load_trade_settings() -> dict:
    defaults = {
        "max_active_trades": None,  # None = modo Auto
        "updated_at": None,
    }
    if not os.path.exists(TRADE_SETTINGS_FILE):
        return defaults
    try:
        with open(TRADE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        raw = stored.get("max_active_trades")
        if raw in (None, "", "auto", "AUTO"):
            max_active = None
        else:
            try:
                max_active = int(raw)
            except (TypeError, ValueError):
                max_active = None
        if max_active is not None:
            max_active = max(1, min(max_active, MAX_MANUAL_ACTIVE_TRADES))
        return {**defaults, **stored, "max_active_trades": max_active}
    except Exception as e:
        log(f"[TRADES] Erro ao carregar trade_settings.json: {e}")
        return defaults


def save_trade_settings(max_active_trades) -> dict:
    if max_active_trades in (None, "", "auto", "AUTO"):
        cleaned = None
    else:
        try:
            cleaned = int(max_active_trades)
        except (TypeError, ValueError):
            cleaned = None

    if cleaned is not None:
        cleaned = max(1, min(cleaned, MAX_MANUAL_ACTIVE_TRADES))

    data = {
        "max_active_trades": cleaned,
        "updated_at": datetime.utcnow().isoformat(),
    }
    tmp = TRADE_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, TRADE_SETTINGS_FILE)
    return data


def get_trade_limit_override():
    return load_trade_settings()["max_active_trades"]



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
    override = get_trade_limit_override()
    if override is not None:
        return override

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

    selected = set(get_selected_symbols())
    if selected:
        allowed = [sym for sym in allowed if sym in selected]
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
            if hour >= start or hour < end:
                return True
    return False


# ═══════════════════════════════════════════════════════════
# KILL ZONES — janelas institucionais precisas (ICT)
# ═══════════════════════════════════════════════════════════
# Traders profissionais focam nestas janelas onde o volume
# institucional é máximo e os movimentos mais limpos.
#
#   London Open:  07:00–09:00 UTC  (maior liquidez europeia)
#   NY Open:      13:00–15:00 UTC  (overlap + dados EUA)
#   London Close: 15:00–16:00 UTC  (reversões frequentes)
#   Asia Session: 00:00–03:00 UTC  (pares JPY e AUD/NZD)

_KILL_ZONES = [
    (7,  9,  "London Open"),
    (13, 15, "NY Open"),
    (15, 16, "London Close"),
    (0,  3,  "Asia Session"),
]

# Score bônus por Kill Zone (adicionado ao check de confluência)
_KILL_ZONE_PAIRS = {
    "London Open":   ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "GBPJPY", "XAUUSD"],
    "NY Open":       ["EURUSD", "GBPUSD", "USDCAD", "USDCHF", "XAUUSD", "USDJPY"],
    "London Close":  ["EURUSD", "GBPUSD", "EURGBP"],
    "Asia Session":  ["USDJPY", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY"],
}


def get_kill_zone(symbol: str) -> str | None:
    """
    Retorna o nome da Kill Zone ativa para o par, ou None se fora dela.
    Fora de Kill Zone, o sinal é aceito mas sem bônus de score.
    """
    hour = datetime.utcnow().hour
    for start, end, name in _KILL_ZONES:
        in_window = (start <= hour < end) if start < end else (hour >= start or hour < end)
        if in_window and symbol in _KILL_ZONE_PAIRS.get(name, []):
            return name
    return None


def is_in_kill_zone(symbol: str) -> bool:
    """Retorna True se o par está numa Kill Zone agora."""
    return get_kill_zone(symbol) is not None


# ═══════════════════════════════════════════════════════════
# OTE — OPTIMAL TRADE ENTRY (Fibonacci 62-79%)
# ═══════════════════════════════════════════════════════════
# Conceito ICT: após um impulso direcional, o preço retorna
# para a zona de 62-79% de Fibonacci antes de continuar.
# Entrar nessa zona melhora o RR e reduz stops prematuros.

def calc_ote_zone(swing_high: float, swing_low: float, direction: str) -> dict:
    """
    Calcula a zona OTE (Optimal Trade Entry) para um impulso.

    BUY:  swing_low = início do impulso, swing_high = topo
          OTE = retrace de 62-79% para cima (zona de compra)

    SELL: swing_high = início do impulso, swing_low = fundo
          OTE = retrace de 62-79% para baixo (zona de venda)

    Retorna: {"low": ..., "high": ..., "mid": ..., "valid": bool}
    """
    rng = swing_high - swing_low
    if rng <= 0:
        return {"low": 0, "high": 0, "mid": 0, "valid": False}

    if direction == "BUY":
        # Retrace de alta: zona entre 62% e 79% do impulso de baixo para cima
        ote_low  = swing_high - rng * 0.79   # 79% de retrace
        ote_high = swing_high - rng * 0.62   # 62% de retrace
    else:
        # Retrace de baixa: zona entre 62% e 79% do impulso de cima para baixo
        ote_low  = swing_low + rng * 0.62    # 62% de retrace
        ote_high = swing_low + rng * 0.79    # 79% de retrace

    ote_mid = (ote_low + ote_high) / 2
    return {
        "low":   round(ote_low,  5),
        "high":  round(ote_high, 5),
        "mid":   round(ote_mid,  5),
        "valid": True,
    }


def is_price_in_ote(price: float, swing_high: float, swing_low: float,
                    direction: str) -> bool:
    """
    Verifica se o preço atual está na zona OTE.
    Retorna True se o preço está no retrace de 62-79%.
    """
    zone = calc_ote_zone(swing_high, swing_low, direction)
    if not zone["valid"]:
        return False
    return zone["low"] <= price <= zone["high"]


# ── P&L helpers ──────────────────────────────────────────────────────────────

def pip_factor(symbol: str) -> float:
    """
    Retorna o valor de 1 pip para o símbolo.
    Pares JPY e XAUUSD usam 0.01; demais pares forex usam 0.0001.
    """
    if is_jpy_pair(symbol) or symbol == "XAUUSD":
        return 0.01
    return 0.0001


def calc_pnl_pips(symbol: str, direction: str, entry: float,
                  exit_price: float) -> float:
    """
    Calcula o P&L em pips (positivo = lucro).
    """
    pf = pip_factor(symbol)
    if direction == "BUY":
        return round((exit_price - entry) / pf, 1)
    return round((entry - exit_price) / pf, 1)


def calc_pnl_usd(symbol: str, direction: str, entry: float,
                 exit_price: float, lot: float,
                 usdjpy_price: float = 0.0) -> float:
    """
    Calcula o P&L em USD, replicando a lógica usada em bot.close_trade.

    Para pares JPY o lucro bruto está em JPY e é convertido para USD via
    jpy_to_usd(). Para todos os outros pares o resultado já está em USD.
    """
    from risk import contract_size_for
    cs = contract_size_for(symbol)

    if direction == "BUY":
        profit_raw = (exit_price - entry) * cs * lot
    else:
        profit_raw = (entry - exit_price) * cs * lot

    if is_jpy_pair(symbol):
        if usdjpy_price and usdjpy_price > 0:
            return round(jpy_to_usd(profit_raw, usdjpy_price), 2)
        # fallback: retorna o valor bruto em JPY (melhor que zero)
        return round(profit_raw, 2)

    return round(profit_raw, 2)
