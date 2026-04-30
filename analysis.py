import time
import requests
import pandas as pd
from datetime import datetime, timezone
from config import Config
from utils import log, asset_name

# ── Mapeamento interno → Twelve Data ────────────────────────
TD_SYMBOLS = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
    "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
    "GBPJPY": "GBP/JPY", "XAUUSD": "XAU/USD",
}

# Cooldown de log para candle inválido — evita spam a cada minuto
_invalid_candle_logged: dict = {}
_INVALID_LOG_COOLDOWN = 10 * 60  # loga no máximo 1x a cada 10 min por símbolo


def _log_invalid_candle(symbol: str):
    now = time.time()
    if now - _invalid_candle_logged.get(symbol, 0) >= _INVALID_LOG_COOLDOWN:
        _log_invalid_candle(symbol)
        _invalid_candle_logged[symbol] = now
_cache: dict = {}
_CACHE_TTL = 20 * 60   # 20 min → máx ~72 refreshes/dia (< 800 créditos free tier)
_last_refresh: float = 0.0


def _refresh_cache():
    """
    Busca todos os 11 pares em UMA chamada batch.
    Custo: 11 créditos por refresh.
    Com TTL de 20 min: ~72 refreshes/dia, dentro do free tier de 800/dia.
    """
    global _last_refresh

    if not Config.TWELVE_DATA_API_KEY:
        log("[TWELVEDATA] TWELVE_DATA_API_KEY não configurada no Railway.")
        return

    # Free tier: 8 créditos/minuto, 1 crédito por símbolo.
    # 11 símbolos em 1 chamada = 11 créditos → excede o limite.
    # Solução: 2 batches (8 + 3) com 61s de intervalo.
    items    = list(TD_SYMBOLS.items())
    batches  = [items[:8], items[8:]]   # [8 pares, 3 pares]
    now      = time.time()
    ok_count = 0
    merged   = {}

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            log("[TWELVEDATA] Aguardando 61s entre batches (limite free tier)...")
            time.sleep(61)

        symbols_str = ",".join(sym_td for _, sym_td in batch)
        params = {
            "symbol":     symbols_str,
            "interval":   "1h",
            "outputsize": 800,
            "apikey":     Config.TWELVE_DATA_API_KEY,
            "format":     "JSON",
            "timezone":   "UTC",
        }

        try:
            resp = requests.get(
                "https://api.twelvedata.com/time_series",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            merged.update(data)
            log(f"[TWELVEDATA] Batch {batch_idx+1}/2 recebido ({len(batch)} pares)")
        except Exception as e:
            log(f"[TWELVEDATA] Erro no batch {batch_idx+1}: {e}")
            continue

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

            _cache[sym_internal] = (now, df)
            ok_count += 1

        except Exception as e:
            log(f"[TWELVEDATA] Erro ao processar {sym_td}: {e}")

    _last_refresh = now
    log(f"[TWELVEDATA] Cache atualizado — {ok_count}/{len(TD_SYMBOLS)} pares OK")


def force_initial_refresh(blocking: bool = True):
    """
    Força um refresh imediato do cache de análise no startup.

    Quando blocking=True (padrão) a chamada é síncrona — o bot só
    continua após o cache estar populado.  Se blocking=False o refresh
    é disparado em uma thread separada para não travar o startup.
    """
    if blocking:
        _refresh_cache()
    else:
        import threading
        threading.Thread(target=_refresh_cache, daemon=True).start()


def _get_df(symbol: str):
    """
    Retorna o DataFrame do cache para o símbolo.
    Dispara refresh batch se o cache estiver vencido.
    Se o refresh falhar, usa cache antigo como fallback.
    """
    now = time.time()
    if (now - _last_refresh) >= _CACHE_TTL:
        _refresh_cache()

    if symbol not in _cache:
        return None

    _, df = _cache[symbol]
    return df.copy()


# ── Helpers internos ─────────────────────────────────────────

def _resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample("4h").agg({
        "Open": "first", "High": "max",
        "Low":  "min",   "Close": "last", "Volume": "sum",
    }).dropna()


def _strip_open_candle(df: pd.DataFrame) -> pd.DataFrame:
    """Remove o último candle se ainda não fechou (candle H1 fecha a cada hora)."""
    if df.empty:
        return df
    last_time = df.index[-1]
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    if last_time + pd.Timedelta(hours=1) > datetime.now(timezone.utc):
        df = df.iloc[:-1]
    return df


def _validate_last_candle(df: pd.DataFrame) -> bool:
    """Rejeita candles anômalos ou de indecisão. Retorna True se válido."""
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
        return False   # candle anômalo
    if atr_temp > 0 and last_body < 0.1 * atr_temp:
        return False   # candle de indecisão
    return True


def _detect_fvg(df: pd.DataFrame, lookback: int = 20) -> dict:
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    fvg_bull, fvg_bear = [], []
    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    opens  = df["Open"].values
    times  = df.index

    for i in range(max(3, len(df) - lookback), len(df)):
        # Bullish FVG: gap entre high[i-2] (fundo) e low[i] (topo)
        if lows[i] > highs[i - 2]:
            body_i1  = abs(closes[i-1] - opens[i-1])
            range_i1 = highs[i-1] - lows[i-1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bull.append({
                    "top": float(lows[i]), "bottom": float(highs[i - 2]),
                    "time": times[i],
                    # Ativo = preço retornou ao interior do gap
                    "active": float(highs[i-2]) <= closes[-1] <= float(lows[i]),
                })

        # Bearish FVG: gap entre high[i] (fundo) e low[i-2] (topo)
        if highs[i] < lows[i - 2]:
            body_i1  = abs(closes[i-1] - opens[i-1])
            range_i1 = highs[i-1] - lows[i-1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bear.append({
                    "top": float(lows[i - 2]), "bottom": float(highs[i]),
                    "time": times[i],
                    # Ativo = preço retornou ao interior do gap
                    "active": float(highs[i]) <= closes[-1] <= float(lows[i-2]),
                })

    return {"bullish": fvg_bull, "bearish": fvg_bear}


def _detect_order_blocks(df: pd.DataFrame, lookback: int = 15) -> dict:
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    obs_bull, obs_bear = [], []
    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    opens  = df["Open"].values
    times  = df.index

    for i in range(2, len(df)):
        if closes[i-2] < opens[i-2]:   # candle bearish → potencial bullish OB
            body    = closes[i-1] - opens[i-1]
            range_c = highs[i-1] - lows[i-1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5 and closes[i] > closes[i-1]:
                obs_bull.append({
                    "high": float(highs[i-2]), "low": float(lows[i-2]),
                    "time": times[i-2],
                    "active": float(lows[i-2]) <= closes[-1] <= float(highs[i-2]),
                })

        if closes[i-2] > opens[i-2]:   # candle bullish → potencial bearish OB
            body    = opens[i-1] - closes[i-1]
            range_c = highs[i-1] - lows[i-1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5 and closes[i] < closes[i-1]:
                obs_bear.append({
                    "high": float(highs[i-2]), "low": float(lows[i-2]),
                    "time": times[i-2],
                    "active": float(lows[i-2]) <= closes[-1] <= float(highs[i-2]),
                })

    cutoff   = times[-1] - pd.Timedelta(hours=lookback)
    obs_bull = [ob for ob in obs_bull if ob["time"] >= cutoff][-3:]
    obs_bear = [ob for ob in obs_bear if ob["time"] >= cutoff][-3:]
    return {"bullish": obs_bull, "bearish": obs_bear}


def _detect_liquidity_sweeps(df: pd.DataFrame, swing_lookback: int = 10) -> dict:
    if len(df) < swing_lookback + 3:
        return {"bullish": False, "bearish": False, "swing_high": None, "swing_low": None}

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values

    recent_high = float(max(highs[-swing_lookback-2:-2]))
    recent_low  = float(min(lows[-swing_lookback-2:-2]))

    return {
        "bullish":    float(lows[-1])  < recent_low  and float(closes[-1]) > recent_low,
        "bearish":    float(highs[-1]) > recent_high and float(closes[-1]) < recent_high,
        "swing_high": recent_high,
        "swing_low":  recent_low,
    }


def _calc_indicators(df: pd.DataFrame) -> dict:
    closes = df["Close"]
    highs  = df["High"]
    lows   = df["Low"]
    opens  = df["Open"]

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
    rsi_val  = round(100 - (100 / (1 + float(gain.iloc[-1]) / loss_val)), 1) if loss_val != 0 else 50.0

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
    chg   = float((closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100) if len(closes) >= 10 else 0.0

    cen = "NEUTRO"
    if price > float(ema200) and float(ema9) > float(ema21):
        cen = "ALTA"
    elif price < float(ema200) and float(ema9) < float(ema21):
        cen = "BAIXA"

    # Candle de força real: body >= 50% do range do candle
    last_body  = abs(float(closes.iloc[-1]) - float(opens.iloc[-1]))
    last_range = float(highs.iloc[-1]) - float(lows.iloc[-1])
    body_ratio = (last_body / last_range) if last_range > 0 else 0
    candle_bull = float(closes.iloc[-1]) > float(opens.iloc[-1]) and body_ratio >= 0.5
    candle_bear = float(closes.iloc[-1]) < float(opens.iloc[-1]) and body_ratio >= 0.5

    return {
        "price": price,
        "ema9": float(ema9), "ema21": float(ema21), "ema200": float(ema200),
        "upper": float(sma20 + 2 * std20), "lower": float(sma20 - 2 * std20),
        "rsi": rsi_val, "atr": round(atr, 5), "adx": round(adx, 1),
        "macd_bull": bool(macd_line.iloc[-1] > sig_line.iloc[-1]),
        "macd_bear": bool(macd_line.iloc[-1] < sig_line.iloc[-1]),
        "macd_hist": float(macd_line.iloc[-1] - sig_line.iloc[-1]),
        "change_pct": round(chg, 2),
        "candle_bull": candle_bull, "candle_bear": candle_bear,
        "t_buy":  float(highs.tail(5).max()),
        "t_sell": float(lows.tail(5).min()),
        "cenario": cen,
    }


# ── API pública ──────────────────────────────────────────────

def get_analysis(symbol: str, timeframe: str = None) -> dict | None:
    """Retorna indicadores H1 para o símbolo (usa cache interno)."""
    df = _get_df(symbol)
    if df is None or len(df) < 50:
        log(f"[ANÁLISE] {symbol}: sem dados no cache")
        return None

    df = _strip_open_candle(df)
    if not _validate_last_candle(df):
        log(f"[ANÁLISE] {symbol}: candle inválido, ignorando")
        return None

    ind = _calc_indicators(df)
    ind["fvg"]    = _detect_fvg(df, Config.FVG_LOOKBACK)
    ind["ob"]     = _detect_order_blocks(df, Config.OB_LOOKBACK)
    ind["sweep"]  = _detect_liquidity_sweeps(df, Config.LIQUIDITY_SWING_LOOKBACK)
    ind["symbol"] = symbol
    ind["name"]   = asset_name(symbol)
    return ind


def get_multi_timeframe(symbol: str) -> dict:
    """Retorna análise H1 + H4 + D1 (todos resampleados do H1 em cache)."""
    mtf = {
        "h1": None, "h4": None, "d1": None,
        "aligned": False, "h4_cenario": "NEUTRO",
        "d1_cenario": "NEUTRO", "daily_bias": "NEUTRO",
    }

    df = _get_df(symbol)
    if df is None or len(df) < 50:
        return mtf

    df = _strip_open_candle(df)

    # ── H1 ───────────────────────────────────────────────────
    if not _validate_last_candle(df):
        _log_invalid_candle(symbol)
        return mtf

    h1 = _calc_indicators(df)
    h1["fvg"]   = _detect_fvg(df, Config.FVG_LOOKBACK)
    h1["ob"]    = _detect_order_blocks(df, Config.OB_LOOKBACK)
    h1["sweep"] = _detect_liquidity_sweeps(df, Config.LIQUIDITY_SWING_LOOKBACK)
    mtf["h1"]   = h1

    # ── H4 (resampleado) ─────────────────────────────────────
    df_4h = _resample_to_4h(df)
    if len(df_4h) >= 30:
        h4 = _calc_indicators(df_4h)
        h4["fvg"]   = _detect_fvg(df_4h, Config.FVG_LOOKBACK)
        h4["ob"]    = _detect_order_blocks(df_4h, Config.OB_LOOKBACK)
        h4["sweep"] = _detect_liquidity_sweeps(df_4h, Config.LIQUIDITY_SWING_LOOKBACK)
        mtf["h4"]         = h4
        mtf["aligned"]    = h1["cenario"] == h4["cenario"] and h1["cenario"] != "NEUTRO"
        mtf["h4_cenario"] = h4["cenario"]
    else:
        log(f"[MTF] {symbol}: dados H4 insuficientes ({len(df_4h)} candles)")

    # ── D1 (Daily bias) ───────────────────────────────────────
    # Resampla H1 → D1 para capturar a tendência macro
    # Profissionais usam D1 como filtro primário de direção
    try:
        df_d1 = df.resample("1D").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

        if len(df_d1) >= 20:
            d1 = _calc_indicators(df_d1)
            mtf["d1"]          = d1
            mtf["d1_cenario"]  = d1["cenario"]

            # Daily bias: direção que os profissionais operam hoje
            # Alta: preço D1 > EMA200 D1 E EMA9 > EMA21 no Daily
            # Baixa: o oposto
            # Neutro: sem consenso claro
            if d1["price"] > d1["ema200"] and d1["ema9"] > d1["ema21"]:
                mtf["daily_bias"] = "ALTA"
            elif d1["price"] < d1["ema200"] and d1["ema9"] < d1["ema21"]:
                mtf["daily_bias"] = "BAIXA"
            else:
                mtf["daily_bias"] = "NEUTRO"
    except Exception as e:
        log(f"[MTF] {symbol}: erro no D1: {e}")

    return mtf
