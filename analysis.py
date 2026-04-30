
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
from config import Config
from utils import log, asset_name

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# Mapeamento interno \u2192 Twelve Data
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
TD_SYMBOLS = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
    "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
    "GBPJPY": "GBP/JPY", "XAUUSD": "XAU/USD",
}

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CACHE E SINCRONIZA\u00c7\u00c3O
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# O refresh pode demorar ~65s (sleep entre batches do free tier),
# ent\u00e3o roda numa thread separada. O loop principal l\u00ea o cache
# sem bloquear, e recebe None se o cache ainda estiver vazio.
_cache: dict = {}
_cache_lock = threading.RLock()
_CACHE_TTL = 20 * 60          # 20 min
_last_refresh: float = 0.0
_refresh_thread: threading.Thread = None
_refresh_in_progress = threading.Event()

# Cooldown de log para candle inv\u00e1lido
_invalid_candle_logged: dict = {}
_INVALID_LOG_COOLDOWN = 10 * 60


def _log_invalid_candle(symbol: str):
    now = time.time()
    if now - _invalid_candle_logged.get(symbol, 0) >= _INVALID_LOG_COOLDOWN:
        log(f"[AN\u00c1LISE] {symbol}: candle inv\u00e1lido ou incompleto, ignorando...")
        _invalid_candle_logged[symbol] = now


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# REFRESH DE CACHE (thread separada)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def _fetch_batch(symbols_td: list[str]) -> dict:
    """Faz UMA chamada batch ao Twelve Data e retorna o JSON."""
    if not Config.TWELVE_DATA_API_KEY:
        return {}
    try:
        resp = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":     ",".join(symbols_td),
                "interval":   "1h",
                "outputsize": 800,
                "apikey":     Config.TWELVE_DATA_API_KEY,
                "format":     "JSON",
                "timezone":   "UTC",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log(f"[TWELVEDATA] Erro no batch: {type(e).__name__}: {str(e)[:100]}")
        return {}


def _refresh_cache_worker():
    """Executa o refresh em thread separada para n\u00e3o bloquear o loop principal."""
    global _last_refresh

    if not Config.TWELVE_DATA_API_KEY:
        log("[TWELVEDATA] TWELVE_DATA_API_KEY n\u00e3o configurada.")
        _refresh_in_progress.
        return

    try:
        items = list(TD_SYMBOLS.items())
        # Free tier: 8 cr\u00e9ditos/minuto. 11 s\u00edmbolos = 2 batches de 8+3
        batches = [items[:8], items[8:]]
        merged = {}

        for batch_idx, batch in enumerate(batches):
            if batch_idx > 0:
                log("[TWELVEDATA] Aguardando 61s entre batches (free tier)...")
                time.sleep(61)

            symbols_td = [sym_td for _, sym_td in batch]
            data = _fetch_batch(symbols_td)
            if data:
                merged.update(data)
                log(f"[TWELVEDATA] Batch {batch_idx + 1}/2 OK ({len(batch)} pares)")

        ok_count = 0
        new_data = {}
        now = time.time()

        for sym_internal, sym_td in TD_SYMBOLS.items():
            sym_data = merged.get(sym_td, {})

            if sym_data.get("status") == "error":
                log(f"[TWELVEDATA] {sym_td}: {sym_data.get('message', 'erro')}")
                continue

            values = sym_data.get("values", [])
            if not values or len(values) < 50:
                log(f"[TWELVEDATA] {sym_td}: dados insuficientes ({len(values)} candles)")
                continue

            try:
                df = pd.DataFrame(values)
                df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
                df = df.set_index("datetime").sort_index()
                df = df.rename(columns={
                    "open": "Open", "high": "High",
                    "low":  "Low",  "close": "Close",
                })
                for col in ["Open", "High", "Low", "Close"]:
                    df[col] = df[col].astype(float)
                df["Volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0

                new_data[sym_internal] = (now, df)
                ok_count += 1
            except Exception as e:
                log(f"[TWELVEDATA] Erro ao processar {sym_td}: {e}")

        # Commita tudo de uma vez no cache (mant\u00e9m dados antigos dos pares que falharam)
        with _cache_lock:
            _cache.update(new_data)
            _last_refresh = now

        log(f"[TWELVEDATA] Cache atualizado \u2014 {ok_count}/{len(TD_SYMBOLS)} pares OK")

    finally:
        _refresh_in_progress.clear()


def _trigger_refresh_if_needed():
    """Dispara refresh em thread separada se o cache estiver vencido."""
    global _refresh_thread

    now = time.time()
    if now - _last_refresh < _CACHE_TTL:
        return  # cache ainda válido

    # Se já tem refresh rolando, não dispara outro
    if _refresh_in_progress.is_set():
        return

    _refresh_in_progress.set()
    try:
        _refresh_thread = threading.Thread(
            target=_refresh_cache_worker,
            daemon=True,
            name="td-refresh",
        )
        _refresh_thread.start()
    except Exception as e:
        log(f"[TWELVEDATA] Erro ao iniciar refresh: {e}")
        _refresh_in_progress.clear()

def force_initial_refresh(blocking: bool = True):
    """
    Chamado no startup do bot. Se blocking=True, aguarda o primeiro fetch
    completar antes de retornar (evita sinais com cache vazio).
    """
    _trigger_refresh_if_needed()
    if blocking and _refresh_thread is not None:
        _refresh_thread.join(timeout=180)


def _get_df(symbol: str):
    """Retorna o DataFrame do cache. None se n\u00e3o dispon\u00edvel ainda."""
    _trigger_refresh_if_needed()
    with _cache_lock:
        if symbol not in _cache:
            return None
        _, df = _cache[symbol]
        return df.copy()


def get_cached_price(symbol: str):
    """\u00daltimo pre\u00e7o de fechamento do cache (sem trigger de refresh)."""
    with _cache_lock:
        if symbol not in _cache:
            return None
        _, df = _cache[symbol]
        if df is None or len(df) == 0:
            return None
        return float(df["Close"].iloc[-1])


def get_cache_age_seconds() -> float:
    """Idade do \u00faltimo refresh (para exibir no dashboard)."""
    if _last_refresh == 0:
        return float("inf")
    return time.time() - _last_refresh


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# HELPERS DE C\u00c1LCULO
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def _resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample("4h").agg({
        "Open":  "first", "High":   "max",
        "Low":   "min",   "Close":  "last", "Volume": "sum",
    }).dropna()


def _strip_open_candle(df: pd.DataFrame) -> pd.DataFrame:
    """Remove o \u00faltimo candle se ainda n\u00e3o fechou."""
    if df.empty:
        return df
    last_time = df.index[-1]
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    if last_time + pd.Timedelta(hours=1) > datetime.now(timezone.utc):
        df = df.iloc[:-1]
    return df


def _validate_last_candle(df: pd.DataFrame) -> bool:
    """Rejeita candles an\u00f4malos ou de indecis\u00e3o."""
    if len(df) < 15:
        return False
    tr_temp = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"]  - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_temp   = tr_temp.rolling(14).mean().iloc[-1]
    last_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
    last_body  = abs(df["Close"].iloc[-1] - df["Open"].iloc[-1])
    atr_mult   = getattr(Config, "ATR_ANOMALY_MULT", 2.5)
    if atr_temp > 0 and last_range > atr_mult * atr_temp:
        return False   # candle an\u00f4malo
    if atr_temp > 0 and last_body < 0.1 * atr_temp:
        return False   # candle de indecis\u00e3o
    return True


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SMC: FVG, ORDER BLOCKS, LIQUIDITY SWEEPS
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def _detect_fvg(df: pd.DataFrame, lookback: int = 20) -> dict:
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    fvg_bull, fvg_bear = [], []
    highs, lows, closes, opens = (
        df["High"].values, df["Low"].values,
        df["Close"].values, df["Open"].values,
    )
    times = df.index

    for i in range(max(3, len(df) - lookback), len(df)):
        # Bullish FVG: low[i] > high[i-2]
        if lows[i] > highs[i - 2]:
            body_i1  = abs(closes[i - 1] - opens[i - 1])
            range_i1 = highs[i - 1] - lows[i - 1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bull.append({
                    "top": float(lows[i]), "bottom": float(highs[i - 2]),
                    "time": times[i],
                    "active": float(highs[i - 2]) <= closes[-1] <= float(lows[i]),
                })

        # Bearish FVG: high[i] < low[i-2]
        if highs[i] < lows[i - 2]:
            body_i1  = abs(closes[i - 1] - opens[i - 1])
            range_i1 = highs[i - 1] - lows[i - 1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bear.append({
                    "top": float(lows[i - 2]), "bottom": float(highs[i]),
                    "time": times[i],
                    "active": float(highs[i]) <= closes[-1] <= float(lows[i - 2]),
                })

    return {"bullish": fvg_bull, "bearish": fvg_bear}


def _detect_order_blocks(df: pd.DataFrame, lookback: int = 15) -> dict:
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    obs_bull, obs_bear = [], []
    highs, lows, closes, opens = (
        df["High"].values, df["Low"].values,
        df["Close"].values, df["Open"].values,
    )
    times = df.index

    for i in range(2, len(df)):
        # Candle bearish \u2192 potencial bullish OB
        if closes[i - 2] < opens[i - 2]:
            body    = closes[i - 1] - opens[i - 1]
            range_c = highs[i - 1] - lows[i - 1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5 and closes[i] > closes[i - 1]:
                obs_bull.append({
                    "high": float(highs[i - 2]), "low": float(lows[i - 2]),
                    "time": times[i - 2],
                    "active": float(lows[i - 2]) <= closes[-1] <= float(highs[i - 2]),
                })

        # Candle bullish \u2192 potencial bearish OB
        if closes[i - 2] > opens[i - 2]:
            body    = opens[i - 1] - closes[i - 1]
            range_c = highs[i - 1] - lows[i - 1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5 and closes[i] < closes[i - 1]:
                obs_bear.append({
                    "high": float(highs[i - 2]), "low": float(lows[i - 2]),
                    "time": times[i - 2],
                    "active": float(lows[i - 2]) <= closes[-1] <= float(highs[i - 2]),
                })

    cutoff   = times[-1] - pd.Timedelta(hours=lookback)
    obs_bull = [ob for ob in obs_bull if ob["time"] >= cutoff][-3:]
    obs_bear = [ob for ob in obs_bear if ob["time"] >= cutoff][-3:]
    return {"bullish": obs_bull, "bearish": obs_bear}


def _detect_liquidity_sweeps(df: pd.DataFrame, swing_lookback: int = 10) -> dict:
    if len(df) < swing_lookback + 3:
        return {"bullish": False, "bearish": False, "swing_high": None, "swing_low": None}

    highs, lows, closes = df["High"].values, df["Low"].values, df["Close"].values
    recent_high = float(max(highs[-swing_lookback - 2:-2]))
    recent_low  = float(min(lows[-swing_lookback - 2:-2]))

    return {
        "bullish":    float(lows[-1])  < recent_low  and float(closes[-1]) > recent_low,
        "bearish":    float(highs[-1]) > recent_high and float(closes[-1]) < recent_high,
        "swing_high": recent_high,
        "swing_low":  recent_low,
    }


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# INDICADORES CL\u00c1SSICOS
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def _calc_indicators(df: pd.DataFrame) -> dict:
    closes = df["Close"]
    highs, lows, opens = df["High"], df["Low"], df["Open"]

    ema9   = closes.ewm(span=9,   adjust=False).mean().iloc[-1]
    ema21  = closes.ewm(span=21,  adjust=False).mean().iloc[-1]
    ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]

    w     = min(20, len(closes) - 1)
    sma20 = closes.rolling(w).mean().iloc[-1]
    std20 = closes.rolling(w).std().iloc[-1]

    delta = closes.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    loss_val = float(loss.iloc[-1])
    rsi_val  = (
        round(100 - (100 / (1 + float(gain.iloc[-1]) / loss_val)), 1)
        if loss_val != 0 else 50.0
    )

    ema12     = closes.ewm(span=12, adjust=False).mean()
    ema26     = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    sig_line  = macd_line.ewm(span=9, adjust=False).mean()

    tr = pd.concat([
        highs - lows,
        (highs - closes.shift()).abs(),
        (lows  - closes.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    up_move  = highs.diff()
    dn_move  = -lows.diff()
    plus_dm  = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
    minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
    atr_s    = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_s
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx      = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])

    price = float(closes.iloc[-1])
    chg   = (
        float((closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100)
        if len(closes) >= 10 else 0.0
    )

    cen = "NEUTRO"
    if price > float(ema200) and float(ema9) > float(ema21):
        cen = "ALTA"
    elif price < float(ema200) and float(ema9) < float(ema21):
        cen = "BAIXA"

    # Candle de for\u00e7a real: body >= 50% do range
    last_body  = abs(float(closes.iloc[-1]) - float(opens.iloc[-1]))
    last_range = float(highs.iloc[-1]) - float(lows.iloc[-1])
    body_ratio = (last_body / last_range) if last_range > 0 else 0
    candle_bull = float(closes.iloc[-1]) > float(opens.iloc[-1]) and body_ratio >= 0.5
    candle_bear = float(closes.iloc[-1]) < float(opens.iloc[-1]) and body_ratio >= 0.5

    return {
        "price":       price,
        "ema9":        float(ema9),
        "ema21":       float(ema21),
        "ema200":      float(ema200),
        "upper":       float(sma20 + 2 * std20),
        "lower":       float(sma20 - 2 * std20),
        "rsi":         rsi_val,
        "atr":         round(atr, 5) if not pd.isna(atr) else 0.0,
        "adx":         round(adx, 1) if not pd.isna(adx) else 0.0,
        "macd_bull":   bool(macd_line.iloc[-1] > sig_line.iloc[-1]),
        "macd_bear":   bool(macd_line.iloc[-1] < sig_line.iloc[-1]),
        "macd_hist":   float(macd_line.iloc[-1] - sig_line.iloc[-1]),
        "change_pct":  round(chg, 2),
        "candle_bull": candle_bull,
        "candle_bear": candle_bear,
        "t_buy":       float(highs.tail(5).max()),
        "t_sell":      float(lows.tail(5).min()),
        "cenario":     cen,
    }


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# API P\u00daBLICA
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def get_analysis(symbol: str, timeframe: str = None) -> dict | None:
    """Retorna indicadores H1 para o s\u00edmbolo (usa cache interno)."""
    df = _get_df(symbol)
    if df is None or len(df) < 50:
        log(f"[AN\u00c1LISE] {symbol}: sem dados no cache")
        return None

    df = _strip_open_candle(df)
    if not _validate_last_candle(df):
        _log_invalid_candle(symbol)
        return None

    ind = _calc_indicators(df)
    ind["fvg"]    = _detect_fvg(df, Config.FVG_LOOKBACK)
    ind["ob"]     = _detect_order_blocks(df, Config.OB_LOOKBACK)
    ind["sweep"]  = _detect_liquidity_sweeps(df, Config.LIQUIDITY_SWING_LOOKBACK)
    ind["symbol"] = symbol
    ind["name"]   = asset_name(symbol)
    return ind


def get_multi_timeframe(symbol: str) -> dict:
    """Retorna an\u00e1lise H1 + H4 (H4 resampleado do H1 em cache)."""
    mtf = {"h1": None, "h4": None, "aligned": False, "h4_cenario": "NEUTRO"}

    df = _get_df(symbol)
    if df is None or len(df) < 50:
        return mtf

    df = _strip_open_candle(df)

    if not _validate_last_candle(df):
        _log_invalid_candle(symbol)
        return mtf

    h1 = _calc_indicators(df)
    h1["fvg"]   = _detect_fvg(df, Config.FVG_LOOKBACK)
    h1["ob"]    = _detect_order_blocks(df, Config.OB_LOOKBACK)
    h1["sweep"] = _detect_liquidity_sweeps(df, Config.LIQUIDITY_SWING_LOOKBACK)
    mtf["h1"]   = h1

    df_4h = _resample_to_4h(df)
    if len(df_4h) >= 30:
        h4 = _calc_indicators(df_4h)
        h4["fvg"]   = _detect_fvg(df_4h, Config.FVG_LOOKBACK)
        h4["ob"]    = _detect_order_blocks(df_4h, Config.OB_LOOKBACK)
        h4["sweep"] = _detect_liquidity_sweeps(df_4h, Config.LIQUIDITY_SWING_LOOKBACK)
        mtf["h4"]         = h4
        mtf["aligned"]    = (
            h1["cenario"] == h4["cenario"] and h1["cenario"] != "NEUTRO"
        )
        mtf["h4_cenario"] = h4["cenario"]
    else:
        log(f"[MTF] {symbol}: dados H4 insuficientes ({len(df_4h)} candles)")

    return mtf
