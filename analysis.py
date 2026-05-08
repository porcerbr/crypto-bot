import time
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except Exception:  # fallback mínimo para ambientes sem a dependência
    def retry(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

    def retry_if_exception_type(*args, **kwargs):
        return None
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
        log(f"[ANÁLISE] {symbol}: candle inválido, ignorando")
        _invalid_candle_logged[symbol] = now

_cache: dict = {}
_cache_lock = threading.Lock()
_cache_meta: dict = {}
_CACHE_TTL = 45 * 60   # 45 min → máx ~32 refreshes/dia × 11 pares = ~352 créditos/dia (free tier ok)
_last_refresh: float = 0.0
_refresh_lock = threading.Lock()
_refresh_in_progress = threading.Event()
_feed_worker_started = False
_feed_worker_lock = threading.Lock()
_BACKGROUND_REFRESH_GRACE = 90  # segundos após TTL antes de bloquear o uso do cache
_BATCH_SIZE = 6                 # mais conservador que o máximo para reduzir falhas

# ── Yahoo Finance fallback ────────────────────────────────────
_yahoo_cache: dict = {}
_yahoo_cache_lock = threading.Lock()
_yahoo_last_error: float = 0.0
_YAHOO_ERROR_BACKOFF = 300  # 5 min sem tentar Yahoo após erro


@retry(
    stop=stop_after_attempt(Config.API_RETRY_ATTEMPTS),
    wait=wait_exponential(min=Config.API_RETRY_MIN_WAIT, max=Config.API_RETRY_MAX_WAIT),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError)),
    reraise=True,
)
def _fetch_twelvedata_batch(symbols_str: str, params: dict) -> dict:
    """Busca um batch do Twelve Data com retry automático (tenacity)."""
    resp = requests.get(
        "https://api.twelvedata.com/time_series",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _normalize_td_symbol(symbol: str) -> str:
    """Normaliza símbolo para uso no Twelve Data e no cache interno."""
    return symbol.replace(" ", "").upper().strip()


def _build_df_from_values(values: list[dict]) -> pd.DataFrame | None:
    """Cria um DataFrame OHLC robusto a partir do payload do Twelve Data."""
    if not values:
        return None

    df = pd.DataFrame(values)
    if df.empty:
        return None

    dt_col = None
    for candidate in ("datetime", "timestamp", "date", "time"):
        if candidate in df.columns:
            dt_col = candidate
            break
    if dt_col is None:
        return None

    df[dt_col] = pd.to_datetime(df[dt_col], utc=True, errors="coerce")
    df = df.dropna(subset=[dt_col])
    if df.empty:
        return None
    df = df.set_index(dt_col).sort_index()

    rename_map = {}
    for c in df.columns:
        lc = str(c).lower()
        if lc == "open": rename_map[c] = "Open"
        elif lc == "high": rename_map[c] = "High"
        elif lc == "low": rename_map[c] = "Low"
        elif lc == "close": rename_map[c] = "Close"
        elif lc == "volume": rename_map[c] = "Volume"
    if rename_map:
        df = df.rename(columns=rename_map)

    required = ["Open", "High", "Low", "Close"]
    if not all(col in df.columns for col in required):
        return None

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
    else:
        df["Volume"] = 0.0

    df = df.dropna(subset=required)
    if len(df) < 15:
        return None
    return df


def _extract_symbol_payload(payload: dict, symbol_td: str) -> dict | None:
    """Extrai a sub-resposta de um símbolo em respostas batch ou single."""
    if not isinstance(payload, dict):
        return None

    if payload.get("status") == "error":
        return payload

    # Resposta single-symbol: contém values/meta diretamente
    if isinstance(payload.get("values"), list):
        return payload

    # Resposta batch: chave é o próprio símbolo (ou versão sem barra)
    for key in (symbol_td, symbol_td.replace("/", ""), symbol_td.replace("/", "_") ):
        sub = payload.get(key)
        if isinstance(sub, dict):
            return sub

    # Fallback: pega o primeiro subobjeto que pareça time-series
    for sub in payload.values():
        if isinstance(sub, dict) and ("values" in sub or "meta" in sub):
            return sub

    return None


def _upsert_cache(symbol_internal: str, df: pd.DataFrame, source: str, now: float | None = None):
    now = now or time.time()
    with _cache_lock:
        _cache[symbol_internal] = (now, df)
        _cache_meta[symbol_internal] = {
            "source": source,
            "last_ok": now,
            "rows": len(df),
        }


def _single_symbol_refresh(symbol_internal: str, symbol_td: str, now: float) -> bool:
    """Fallback em símbolo único quando o batch vem vazio ou incompleto."""
    params = {
        "symbol": symbol_td,
        "interval": "1h",
        "outputsize": 200,
        "apikey": Config.TWELVE_DATA_API_KEY,
        "format": "JSON",
        "timezone": "UTC",
    }
    try:
        data = _fetch_twelvedata_batch(symbol_td, params)
        sym_data = _extract_symbol_payload(data, symbol_td)
        if not sym_data or sym_data.get("status") == "error":
            msg = sym_data.get("message", "sem payload") if isinstance(sym_data, dict) else "sem payload"
            log(f"[TWELVEDATA] {symbol_td}: fallback individual falhou ({msg})")
            # Se créditos esgotados, não tenta mais Twelve Data
            if "run out of API credits" in msg or "credits" in msg.lower():
                log(f"[TWELVEDATA] Créditos esgotados — pulando para Yahoo Finance")
            return False
        values = sym_data.get("values", [])
        df = _build_df_from_values(values)
        if df is None:
            log(f"[TWELVEDATA] {symbol_td}: fallback individual sem candles válidos")
            return False
        _upsert_cache(symbol_internal, df, "twelvedata-single", now)
        log(f"[TWELVEDATA] {symbol_td}: recuperado via fallback individual ({len(df)} candles)")
        return True
    except Exception as e:
        log(f"[TWELVEDATA] {symbol_td}: erro no fallback individual — {e}")
        return False


def _normalize_td_symbol(symbol: str) -> str:
    """Normaliza o símbolo interno para uso consistente no feed."""
    return symbol.replace(" ", "").upper().strip()


def _build_df_from_values(values: list[dict]) -> pd.DataFrame | None:
    """Cria um DataFrame OHLC robusto a partir do payload do Twelve Data."""
    if not values:
        return None

    df = pd.DataFrame(values)
    if df.empty:
        return None

    dt_col = next((c for c in ("datetime", "timestamp", "date", "time") if c in df.columns), None)
    if dt_col is None:
        return None

    df[dt_col] = pd.to_datetime(df[dt_col], utc=True, errors="coerce")
    df = df.dropna(subset=[dt_col])
    if df.empty:
        return None

    df = df.set_index(dt_col).sort_index()

    rename_map = {}
    for c in df.columns:
        lc = str(c).lower()
        if lc == "open":
            rename_map[c] = "Open"
        elif lc == "high":
            rename_map[c] = "High"
        elif lc == "low":
            rename_map[c] = "Low"
        elif lc == "close":
            rename_map[c] = "Close"
        elif lc == "volume":
            rename_map[c] = "Volume"
    if rename_map:
        df = df.rename(columns=rename_map)

    required = ["Open", "High", "Low", "Close"]
    if not all(col in df.columns for col in required):
        return None

    for col in required:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0) if "Volume" in df.columns else 0.0
    df = df.dropna(subset=required)
    if len(df) < 15:
        return None
    return df


def _extract_symbol_payload(payload: dict, symbol_td: str) -> dict | None:
    """Extrai a sub-resposta de um símbolo em respostas batch ou single."""
    if not isinstance(payload, dict):
        return None

    if payload.get("status") == "error":
        return payload

    if isinstance(payload.get("values"), list):
        return payload

    candidates = (symbol_td, symbol_td.replace("/", ""), symbol_td.replace("/", "_"))
    for key in candidates:
        sub = payload.get(key)
        if isinstance(sub, dict):
            return sub

    for sub in payload.values():
        if isinstance(sub, dict) and ("values" in sub or "meta" in sub):
            return sub

    return None


def _upsert_cache(symbol_internal: str, df: pd.DataFrame, source: str, now: float | None = None):
    now = now or time.time()
    with _cache_lock:
        _cache[symbol_internal] = (now, df)
        _cache_meta[symbol_internal] = {
            "source": source,
            "last_ok": now,
            "rows": len(df),
        }


def _single_symbol_refresh(symbol_internal: str, symbol_td: str, now: float) -> bool:
    """Fallback em símbolo único quando o batch vem vazio ou incompleto."""
    params = {
        "symbol": symbol_td,
        "interval": "1h",
        "outputsize": 200,
        "apikey": Config.TWELVE_DATA_API_KEY,
        "format": "JSON",
        "timezone": "UTC",
    }
    try:
        data = _fetch_twelvedata_batch(symbol_td, params)
        sym_data = _extract_symbol_payload(data, symbol_td)
        values = (sym_data or {}).get("values", []) if isinstance(sym_data, dict) else []
        df = _build_df_from_values(values)
        if df is None:
            msg = sym_data.get("message", "sem candles válidos") if isinstance(sym_data, dict) else "sem payload"
            log(f"[TWELVEDATA] {symbol_td}: fallback individual falhou ({msg})")
            return False
        _upsert_cache(symbol_internal, df, "twelvedata-single", now)
        log(f"[TWELVEDATA] {symbol_td}: recuperado via fallback individual ({len(df)} candles)")
        return True
    except Exception as e:
        log(f"[TWELVEDATA] {symbol_td}: erro no fallback individual — {e}")
        return False


def _refresh_cache_from_yahoo(symbols: list[str]) -> int:
    """
    Fallback: busca dados do Yahoo Finance para os símbolos listados.
    Retorna o número de pares atualizados com sucesso.
    """
    global _yahoo_last_error
    if not Config.USE_YAHOO_FALLBACK:
        return 0
    if time.time() - _yahoo_last_error < _YAHOO_ERROR_BACKOFF:
        return 0

    try:
        import yfinance as yf
    except ImportError:
        log("[YAHOO] yfinance não instalado — instale com pip install yfinance")
        return 0

    ok = 0
    now = time.time()
    for sym in symbols:
        yf_sym = Config.YAHOO_SYMBOLS.get(sym)
        if not yf_sym:
            continue
        try:
            df = yf.download(yf_sym, period="60d", interval="1h", progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                continue
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close"})
            for col in ["Open", "High", "Low", "Close"]:
                df[col] = df[col].astype(float)
            df["Volume"] = df.get("Volume", 0).astype(float)

            _upsert_cache(sym, df, "yahoo", now)
            ok += 1
        except Exception as e:
            log(f"[YAHOO] Erro ao buscar {sym}: {e}")
            _yahoo_last_error = time.time()
    if ok:
        log(f"[YAHOO] Fallback OK — {ok}/{len(symbols)} pares atualizados")
    return ok


def _refresh_cache():
    """
    Refresh profissional do feed:
      1) tenta Twelve Data em batch conservador
      2) faz fallback individual nos símbolos que vierem vazios
      3) mantém cache antigo se a fonte falhar
      4) usa Yahoo apenas como última camada de segurança
    """
    global _last_refresh

    if not Config.TWELVE_DATA_API_KEY:
        log("[TWELVEDATA] TWELVE_DATA_API_KEY não configurada — usando Yahoo fallback.")
        _refresh_cache_from_yahoo(list(TD_SYMBOLS.keys()))
        _last_refresh = time.time()
        return

    now = time.time()
    items = list(TD_SYMBOLS.items())
    batches = [items[i:i + _BATCH_SIZE] for i in range(0, len(items), _BATCH_SIZE)]
    ok_count = 0
    failed_symbols: list[str] = []
    source_stats = {"batch": 0, "single": 0, "yahoo": 0, "stale": 0}

    log(f"[FEED] Refresh profissional iniciado ({len(items)} símbolos | batch={_BATCH_SIZE})")

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            log("[TWELVEDATA] Aguardando 61s entre batches (limite free tier)...")
            time.sleep(61)

        symbols_str = ",".join(sym_td for _, sym_td in batch)
        params = {
            "symbol": symbols_str,
            "interval": "1h",
            "outputsize": 200,
            "apikey": Config.TWELVE_DATA_API_KEY,
            "format": "JSON",
            "timezone": "UTC",
        }

        try:
            payload = _fetch_twelvedata_batch(symbols_str, params)
            log(f"[TWELVEDATA] Batch {batch_idx + 1}/{len(batches)} recebido ({len(batch)} pares)")

            # ── Detecta crédito esgotado dentro do payload ───────────────────
            # Quando o free tier está esgotado, o batch retorna com status de erro
            # em cada símbolo individualmente — detectamos e acionamos Yahoo direto.
            if isinstance(payload, dict):
                first_val = next(iter(payload.values()), {}) if payload else {}
                err_msg = ""
                if isinstance(first_val, dict):
                    err_msg = str(first_val.get("message", "") or first_val.get("status", ""))
                if not err_msg and "message" in payload:
                    err_msg = str(payload.get("message", ""))
                if "run out of API credits" in err_msg or "credits" in err_msg.lower():
                    log(f"[TWELVEDATA] ⚠️  Créditos esgotados — ativando Yahoo Finance para todos os pares")
                    failed_symbols.extend(sym_internal for sym_internal, _ in batch)
                    # adiciona todos os batches restantes direto como falhos
                    for future_batch in batches[batch_idx + 1:]:
                        failed_symbols.extend(sym_internal for sym_internal, _ in future_batch)
                    break  # sai do loop de batches e vai direto para Yahoo
        except Exception as e:
            log(f"[TWELVEDATA] Erro no batch {batch_idx + 1}: {e}")
            failed_symbols.extend(sym_internal for sym_internal, _ in batch)
            continue

        for sym_internal, sym_td in batch:
            sym_data = _extract_symbol_payload(payload, sym_td)
            values = (sym_data or {}).get("values", []) if isinstance(sym_data, dict) else []
            df = _build_df_from_values(values)
            if df is not None and len(df) >= 50:
                _upsert_cache(sym_internal, df, "twelvedata-batch", now)
                ok_count += 1
                source_stats["batch"] += 1
                continue

            if _single_symbol_refresh(sym_internal, sym_td, now):
                ok_count += 1
                source_stats["single"] += 1
            else:
                failed_symbols.append(sym_internal)

    if failed_symbols:
        yahoo_ok = _refresh_cache_from_yahoo(failed_symbols)
        source_stats["yahoo"] += yahoo_ok
        # Símbolos que ainda falharam após Yahoo
        still_failed = [s for s in failed_symbols
                        if s not in _cache or source_stats["yahoo"] == 0]
    else:
        still_failed = []

    # ── Stale-safe: usa cache expirado quando todas as fontes falharam ───────
    # Para análise H1, dados de até 4h atrás são aceitáveis.
    # Isso cobre o período de créditos esgotados até meia-noite UTC.
    _STALE_MAX_AGE = 4 * 3600   # 4 horas
    for sym in list(still_failed):
        cached_entry = _cache.get(sym)
        if cached_entry is not None:
            # _cache guarda (timestamp, dataframe)
            cache_ts  = cached_entry[0] if isinstance(cached_entry, tuple) else cached_entry.get("ts", 0)
            cache_age = now - cache_ts
            if cache_age <= _STALE_MAX_AGE:
                source_stats["stale"] += 1
                still_failed.remove(sym)
                log(f"[FEED] {sym}: cache stale OK ({int(cache_age/60)}min atrás)")
            else:
                log(f"[FEED] {sym}: cache muito antigo ({int(cache_age/3600)}h) — sem dados")
        else:
            log(f"[FEED] {sym}: sem dados em nenhuma fonte e sem cache")

    _last_refresh = now
    log(
        f"[FEED] Cache atualizado — {ok_count}/{len(TD_SYMBOLS)} símbolos válidos | "
        f"batch={source_stats['batch']} | single={source_stats['single']} | yahoo={source_stats['yahoo']} | stale={source_stats['stale']}"
    )


def _refresh_cache_async():
    try:
        _refresh_cache()
    finally:
        _refresh_in_progress.clear()


def _ensure_background_refresh(force: bool = False):
    age = time.time() - _last_refresh
    if not force and age < _CACHE_TTL and _cache:
        return False
    if _refresh_in_progress.is_set():
        return False
    _refresh_in_progress.set()
    threading.Thread(target=_refresh_cache_async, daemon=True, name="market-feed-refresh").start()
    return True


def _start_feed_worker():
    """Worker em background que renova o cache sem travar o loop principal."""
    while True:
        try:
            age = time.time() - _last_refresh
            if age >= _CACHE_TTL:
                _ensure_background_refresh(force=True)
                time.sleep(5)
            else:
                time.sleep(max(10, min(60, _CACHE_TTL - age)))
        except Exception as e:
            log(f"[FEED] Worker background erro: {e}")
            time.sleep(10)


def start_professional_feed():
    """Inicializa o worker de refresh apenas uma vez."""
    global _feed_worker_started
    with _feed_worker_lock:
        if _feed_worker_started:
            return
        _feed_worker_started = True
    threading.Thread(target=_start_feed_worker, daemon=True, name="market-feed-worker").start()
    log("[FEED] Worker profissional iniciado")


def force_initial_refresh(blocking: bool = True):
    """
    Força um refresh imediato do cache de análise no startup.
    """
    if blocking:
        _refresh_cache()
    else:
        _ensure_background_refresh(force=True)


def _get_df(symbol: str):
    """
    Retorna o DataFrame do cache para o símbolo.
    - Não bloqueia o loop principal quando o cache vencer.
    - Dispara refresh em background e entrega o último cache bom.
    """
    now = time.time()
    age = now - _last_refresh

    if age >= _CACHE_TTL:
        _ensure_background_refresh()

    if symbol not in _cache:
        return None

    _, df = _cache[symbol]
    if df is None or df.empty:
        return None

    if age >= (_CACHE_TTL + _BACKGROUND_REFRESH_GRACE):
        meta = _cache_meta.get(symbol, {})
        log(f"[FEED] {symbol}: cache stale-safe ({int(age)}s | source={meta.get('source', 'unknown')})")

    return df.copy()

# ── Helpers internos ─────────────────────────────────────────
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
