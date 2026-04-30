from datetime import datetime, timezone
from config import Config
import pandas as pd
import math


# ══════════════════════════════════════════════════════════════════════════════
# FORMATAÇÃO E LOG
# ══════════════════════════════════════════════════════════════════════════════

def fmt(value: float) -> str:
    if value is None:
        return "0"
    if abs(value) >= 10000:
        return f"{value:,.2f}"
    if abs(value) >= 1000:
        return f"{value:.2f}"
    if abs(value) >= 10:
        return f"{value:.4f}"
    if abs(value) >= 1:
        return f"{value:.5f}"
    return f"{value:.6f}"


def log(msg: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def asset_name(symbol: str) -> str:
    return Config.FXGOLD_ASSETS.get(symbol, symbol)


def is_jpy_pair(symbol: str) -> bool:
    return symbol.endswith("JPY")


def jpy_to_usd(pnl_jpy: float, usdjpy_price: float) -> float:
    """
    Converte P&L em JPY para USD com validação de sanidade.
    USDJPY normalmente oscila entre 100 e 160.
    """
    # Validação: USDJPY deve estar em range razoável
    if usdjpy_price and 100 <= usdjpy_price <= 160:
        return round(pnl_jpy / usdjpy_price, 2)
    
    # Fallback seguro
    if usdjpy_price and usdjpy_price > 0:
        log(f"[USDJPY] Cotação suspeita: {usdjpy_price}, usando fallback 150.0")
    return round(pnl_jpy / 150.0, 2)


# ══════════════════════════════════════════════════════════════════════════════
# PIP FACTOR E P&L UNIFICADO (usado em bot.py E api.py)
# ══════════════════════════════════════════════════════════════════════════════

def pip_factor(symbol: str) -> float:
    """Retorna o tamanho de 1 pip em unidades de preço."""
    if is_jpy_pair(symbol) or symbol == "XAUUSD":
        return 0.01
    return 0.0001


def contract_size(symbol: str) -> int:
    """Tamanho do contrato por lote padrão (evita import circular com risk.py)."""
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    if symbol == "XAUUSD":
        return Config.CONTRACT_SIZES["COMMODITIES"]
    return Config.CONTRACT_SIZES.get("FOREX", 100000)


def calc_pnl_usd(
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float,
    lot: float,
    usdjpy_price: float = 150.0,
    commission: float = 0.0,
) -> float:
    """
    Cálculo UNIFICADO de P&L em USD com validação.
    Usar tanto em bot.close_trade quanto em api.status (P&L flutuante).
    
    Parâmetros:
    - symbol: Símbolo do ativo (EURUSD, USDJPY, etc)
    - direction: BUY ou SELL
    - entry: Preço de entrada
    - exit_price: Preço de saída
    - lot: Tamanho do lote em padrão (0.01 = 1000 unidades em forex)
    - usdjpy_price: Cotação USDJPY para conversão de pares JPY
    - commission: Comissão em USD
    
    Retorna:
    - P&L em USD (positivo = lucro, negativo = perda)
    """
    # ── Validação de inputs ──
    if entry is None or exit_price is None or lot is None:
        log(f"[P&L] Valores None detectados: entry={entry}, exit={exit_price}, lot={lot}")
        return 0.0
    
    try:
        entry = float(entry)
        exit_price = float(exit_price)
        lot = float(lot)
        commission = float(commission)
    except (TypeError, ValueError):
        log(f"[P&L] Conversão falhou: entry={entry}, exit={exit_price}, lot={lot}")
        return 0.0
    
    # Validação: valores devem ser positivos e válidos
    if entry <= 0 or exit_price <= 0 or lot <= 0:
        log(f"[P&L] Valores inválidos: entry={entry}, exit={exit_price}, lot={lot}")
        return 0.0
    
    # Verificar NaN ou infinito
    if math.isnan(entry) or math.isinf(entry):
        log(f"[P&L] Entry inválido (NaN/inf): {entry}")
        return 0.0
    if math.isnan(exit_price) or math.isinf(exit_price):
        log(f"[P&L] Exit inválido (NaN/inf): {exit_price}")
        return 0.0
    
    cs = contract_size(symbol)
    
    # Calcula P&L bruto
    if direction == "BUY":
        raw = (exit_price - entry) * cs * lot
    else:
        raw = (entry - exit_price) * cs * lot

    # Subtrai comissão
    raw -= commission

    # Converte JPY para USD se necessário
    if is_jpy_pair(symbol):
        return jpy_to_usd(raw, usdjpy_price)
    
    return round(raw, 2)


def calc_pnl_pips(symbol: str, direction: str, entry: float, exit_price: float) -> float:
    """
    Distância em pips entre entry e exit, com sinal (positivo = favor do trade).
    """
    pf = pip_factor(symbol)
    if direction == "BUY":
        return round((exit_price - entry) / pf, 1)
    return round((entry - exit_price) / pf, 1)


# ══════════════════════════════════════════════════════════════════════════════
# ALAVANCAGEM
# ══════════════════════════════════════════════════════════════════════════════

def max_leverage(symbol: str, lot: float = 0.01) -> int:
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


def get_sl_tp_pct(leverage: int, rr: float = None) -> tuple[float, float]:
    """
    Calcula SL e TP em percentagem baseado na alavancagem.
    Retorna (sl_pct, tp_pct).
    """
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, leverage)
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp


def get_sl_tp_atr(
    entry: float,
    atr: float,
    direction: str,
    atr_sl_mult: float = 1.5,
    atr_tp_mult: float = 2.5,
) -> tuple[float, float, float, float]:
    """
    Calcula SL e TP baseado em ATR.
    Retorna (sl, tp, sl_dist, tp_dist).
    """
    if not atr or atr <= 0:
        # Fallback: usa 0.5% como distância mínima
        sl_dist = entry * 0.005
        tp_dist = sl_dist * (atr_tp_mult / atr_sl_mult)
    else:
        sl_dist = atr * atr_sl_mult
        tp_dist = atr * atr_tp_mult

    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)
    
    return sl, tp, sl_dist, tp_dist


# ══════════════════════════════════════════════════════════════════════════════
# SEGURANÇA DINÂMICA POR FAIXA DE SALDO
# ══════════════════════════════════════════════════════════════════════════════

def _lookup_by_threshold(balance: float, table: dict, default):
    """Helper: retorna o valor da primeira threshold >= balance."""
    for threshold, value in sorted(table.items()):
        if balance <= threshold:
            return value
    return default


def get_dynamic_leverage(balance: float) -> int:
    """Alavancagem baseada no capital atual."""
    if not Config.USE_DYNAMIC_LEVERAGE:
        return Config.DEFAULT_LEVERAGE
    return _lookup_by_threshold(balance, Config.DYNAMIC_LEVERAGE_TABLE, Config.DEFAULT_LEVERAGE)


def get_dynamic_max_trades(balance: float) -> int:
    """Máximo de trades ativos permitidos para o capital atual."""
    return _lookup_by_threshold(balance, Config.DYNAMIC_MAX_TRADES, Config.MAX_TRADES)


def get_allowed_symbols(balance: float) -> list:
    """Lista de símbolos permitidos para o capital atual."""
    allowed = []
    for tier in sorted(Config.ASSET_TIERS.keys()):
        if balance >= Config.ASSET_TIERS[tier]["min_balance"]:
            allowed = Config.ASSET_TIERS[tier]["symbols"]
    return allowed


def get_max_risk_absolute(balance: float) -> float:
    """Risco máximo absoluto (USD) permitido por trade."""
    return _lookup_by_threshold(balance, Config.MAX_RISK_ABSOLUTE_USD, 100.0)


def get_min_free_margin_pct(balance: float) -> float:
    """% mínima de margem livre obrigatória."""
    return _lookup_by_threshold(balance, Config.MIN_FREE_MARGIN_PCT, 0.15)


def get_dynamic_cooldown(balance: float) -> int:
    """Cooldown em segundos após loss, baseado no capital."""
    return _lookup_by_threshold(balance, Config.DYNAMIC_COOLDOWN, Config.ASSET_COOLDOWN)


def is_symbol_allowed(symbol: str, balance: float) -> bool:
    """True se o símbolo é permitido para o capital atual."""
    return symbol in get_allowed_symbols(balance)


def is_weekend_gap_risk() -> bool:
    """
    True se estiver em período de alto risco de gap:
    - Sexta após FRIDAY_NO_TRADE_AFTER_HOUR UTC
    - Sábado inteiro
    - Domingo antes de SUNDAY_NO_TRADE_BEFORE_HOUR UTC
    """
    now = datetime.now(timezone.utc)
    dow = now.weekday()  # 0=Seg, 4=Sex, 5=Sab, 6=Dom
    hour = now.hour

    if dow == 4 and hour >= Config.FRIDAY_NO_TRADE_AFTER_HOUR:
        return True
    if dow == 5:  # Sábado
        return True
    if dow == 6 and hour < Config.SUNDAY_NO_TRADE_BEFORE_HOUR:
        return True
    return False


def is_weekend() -> bool:
    """True durante sábado inteiro ou domingo antes da abertura."""
    return is_weekend_gap_risk() and datetime.now(timezone.utc).weekday() >= 5


# ══════════════════════════════════════════════════════════════════════════════
# FILTRO DE SESSÃO POR PAR
# ══════════════════════════════════════════════════════════════════════════════
# Cada par tem liquidez máxima em janelas específicas.
# Sinais fora da sessão principal têm WR significativamente menor.
#
#   London:      07–16 UTC
#   New York:    12–21 UTC
#   Overlap:     12–16 UTC  (maior volume, melhor para EUR/GBP)
#   Ásia:        00–09 UTC  (melhor para JPY, AUD, NZD)

_SESSION_WINDOWS: dict[str, list[tuple[int, int]]] = {
    "EURUSD": [(7, 20)],
    "GBPUSD": [(7, 20)],
    "EURGBP": [(7, 18)],
    "EURJPY": [(7, 20)],
    "GBPJPY": [(7, 20)],
    "USDJPY": [(0, 9), (12, 16)],
    "USDCAD": [(12, 21)],
    "USDCHF": [(7, 20)],
    "AUDUSD": [(22, 24), (0, 14)],
    "NZDUSD": [(21, 24), (0, 13)],
    "XAUUSD": [(7, 21)],
}


def is_good_session(symbol: str) -> bool:
    """
    True se o horário atual (UTC) está dentro da janela
    de liquidez principal do par.
    """
    windows = _SESSION_WINDOWS.get(symbol)
    if not windows:
        return True  # símbolo desconhecido: não bloqueia

    hour = datetime.now(timezone.utc).hour
    for start, end in windows:
        if start < end:
            if start <= hour < end:
                return True
        else:
            # intervalo que cruza meia-noite (ex: 22-2 = das 22 às 02)
            if hour >= start or hour < end:
                return True
    return False
