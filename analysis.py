
from __future__ import annotations

import os
import time
import json
import random
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import requests

from config import Config
from utils import log, asset_name

# ============================================================================
# PROFESSIONAL MARKET DATA PROVIDER
# ============================================================================
#
# Goals:
# - normalize broker symbols to Twelve Data format
# - retry with exponential backoff
# - validate payloads before accepting them
# - persist last good candles to disk
# - warm start from disk cache so the bot does not begin empty
# - keep the public cache contract used by the rest of the bot
# ============================================================================

TD_SYMBOLS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
    "USDCHF": "USD/CHF",
    "NZDUSD": "NZD/USD",
    "EURGBP": "EUR/GBP",
    "EURJPY": "EUR/JPY",
    "GBPJPY": "GBP/JPY",
    "XAUUSD": "XAU/USD",
}

_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_cache_lock = threading.RLock()
# Free tier suporta FX/crypto com histórico limitado; um refresh por hora evita gastar créditos à toa.
_CACHE_TTL = int(os.getenv("MARKET_DATA_CACHE_TTL", str(60 * 60)))
_last_refresh: float = 0.0
_refresh_thread: threading.Thread | None = None
_refresh_in_progress = threading.Event()
_invalid_candle_logged: dict[str, float] = {}
_INVALID_LOG_COOLDOWN = int(os.getenv("MARKET_DATA_INVALID_LOG_COOLDOWN", str(10 * 60)))

_DATA_DIR = Path(os.getenv("MARKET_DATA_DIR", ".market_cache"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)

_TD_TIMEOUT = float(os.getenv("TWELVE_DATA_TIMEOUT", "20"))
_TD_RETRIES = max(1, int(os.getenv("TWELVE_DATA_RETRIES", "2")))
_TD_BATCH_SIZE = max(1, int(os.getenv("TWELVE_DATA_BATCH_SIZE", "8")))
_TD_BATCH_PAUSE = max(0, int(os.getenv("TWELVE_DATA_BATCH_PAUSE", "61")))
_TD_DEFAULT_INTERVAL = os.getenv("TWELVE_DATA_INTERVAL", "1h")
_TD_OUTPUTSIZE = max(50, int(os.getenv("TWELVE_DATA_OUTPUTSIZE", "250")))
_TD_USE_DISK_FALLBACK = os.getenv("MARKET_DATA_DISK_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}
_TD_ALLOW_DEMO_FALLBACK = os.getenv("TWELVE_DATA_DEMO_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}
_YAHOO_FALLBACK_ENABLED = os.getenv("MARKET_DATA_YAHOO_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}



def _chunked(items: list[tuple[str, str]], size: int) -> Iterable[list[tuple[str, str]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _symbol_to_api(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    if "/" in sym or ":" in sym:
        return sym
    # EURUSD -> EUR/USD, XAUUSD -> XAU/USD
    if len(sym) == 6:
        return f"{sym[:3]}/{sym[3:]}"
    return sym


def _symbol_to_file(symbol: str) -> str:
    return (symbol or "UNKNOWN").replace("/", "_").replace(":", "_")


def _interval_to_yahoo(interval: str) -> tuple[str, str]:
    """Mapeia intervalos do bot para o endpoint chart do Yahoo Finance."""
    normalized = (interval or "1h").strip().lower()
    if normalized in {"1h", "60min", "1hour"}:
        return "1h", "60d"
    if normalized in {"4h", "240min", "4hour"}:
        return "1h", "60d"
    if normalized in {"1day", "1d", "day"}:
        return "1d", "1y"
    return "1h", "60d"


def _fetch_yahoo_symbol(symbol_internal: str, interval: str = None, outputsize: int = None) -> tuple[pd.DataFrame | None, dict | None]:
    if not _YAHOO_FALLBACK_ENABLED:
        return None, None

    ticker = Config.YAHOO_SYMBOLS.get(symbol_internal)
    if not ticker:
        return None, None

    yahoo_interval, yahoo_range = _interval_to_yahoo(interval or _TD_DEFAULT_INTERVAL)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "interval": yahoo_interval,
        "range": yahoo_range,
        "includePrePost": "false",
        "events": "div,splits",
    }

    try:
        resp = requests.get(url, params=params, timeout=_TD_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
        chart = (raw or {}).get("chart", {})
        result = (chart.get("result") or [None])[0]
        if not result:
            return None, raw if isinstance(raw, dict) else None

        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows = []
        for i, ts in enumerate(timestamps):
            try:
                dt = pd.to_datetime(int(ts), unit="s", utc=True)
            except Exception:
                continue
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            if o is None or h is None or l is None or c is None:
                continue
            rows.append({
                "datetime": dt,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0,
            })

        if not rows:
            return None, raw if isinstance(raw, dict) else None

        df = pd.DataFrame(rows).set_index("datetime").sort_index()
        return _response_to_frame({"values": df.reset_index().rename(columns={"datetime": "datetime", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}).to_dict(orient="records")}, symbol_internal), raw if isinstance(raw, dict) else None
    except Exception as exc:
        log(f"[YAHOO] {symbol_internal}: falha no fallback ({type(exc).__name__}: {str(exc)[:120]})")
        return None, None


def _disk_path(symbol: str) -> Path:
    return _DATA_DIR / f"{_symbol_to_file(symbol)}.csv"


def _save_disk_cache(symbol: str, df: pd.DataFrame) -> None:
    try:
        if df is None or df.empty:
            return
        path = _disk_path(symbol)
        out = df.copy()
        if out.index.name != "datetime":
            out.index.name = "datetime"
        out.reset_index().to_csv(path, index=False)
    except Exception as exc:
        log(f"[TWELVEDATA] Falha ao salvar cache em disco para {symbol}: {type(exc).__name__}: {str(exc)[:80]}")


def _load_disk_cache(symbol: str) -> pd.DataFrame | None:
    if not _TD_USE_DISK_FALLBACK:
        return None
    path = _disk_path(symbol)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or "datetime" not in df.columns:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
        df = df.dropna(subset=["datetime"])
        df = df.set_index("datetime").sort_index()
        required = ["Open", "High", "Low", "Close"]
        for col in required:
            if col not in df.columns:
                return None
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "Volume" not in df.columns:
            df["Volume"] = 0.0
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if len(df) == 0:
            return None
        return df
    except Exception as exc:
        log(f"[TWELVEDATA] Falha ao ler cache em disco para {symbol}: {type(exc).__name__}: {str(exc)[:80]}")
        return None


def _response_to_frame(raw: dict, api_symbol: str) -> pd.DataFrame | None:
    if not isinstance(raw, dict):
        return None

    if raw.get("status") == "error":
        message = raw.get("message", "erro desconhecido")
        raise RuntimeError(message)

    values = raw.get("values")
    if not values and api_symbol in raw and isinstance(raw[api_symbol], dict):
        values = raw[api_symbol].get("values")
    if not values:
        return None

    df = pd.DataFrame(values)
    if df.empty or "datetime" not in df.columns:
        return None

    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df.dropna(subset=["datetime"])
    if df.empty:
        return None

    df = df.set_index("datetime").sort_index()
    rename_map = {"open": "Open", "high": "High", "low": "Low", "close": "Close"}
    df = df.rename(columns=rename_map)

    for col in ["Open", "High", "Low", "Close"]:
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if not df.empty else None


def _fetch_symbol(symbol_internal: str, interval: str = None, outputsize: int = None) -> tuple[pd.DataFrame | None, dict | None]:
    if not Config.TWELVE_DATA_API_KEY and symbol_internal != "XAUUSD":
        return None, None

    api_symbol = _symbol_to_api(symbol_internal)
    if not api_symbol and symbol_internal != "XAUUSD":
        return None, None

    interval = interval or _TD_DEFAULT_INTERVAL
    outputsize = int(outputsize or _TD_OUTPUTSIZE)
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": api_symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": Config.TWELVE_DATA_API_KEY,
        "format": "JSON",
        "timezone": "UTC",
    }

    def _call_twelvedata(request_params: dict) -> tuple[pd.DataFrame | None, dict | None, Exception | None]:
        last_error = None
        for attempt in range(1, _TD_RETRIES + 1):
            try:
                resp = requests.get(url, params=request_params, timeout=_TD_TIMEOUT)
                resp.raise_for_status()
                raw = resp.json()
                df = _response_to_frame(raw, api_symbol)
                if df is not None and len(df) >= 20:
                    return df, raw if isinstance(raw, dict) else None, None
                if isinstance(raw, dict) and raw.get("status") == "error":
                    return None, raw, RuntimeError(raw.get("message", "erro desconhecido"))
                last_error = RuntimeError(f"{api_symbol}: payload vazio ou insuficiente")
            except Exception as exc:
                last_error = exc

            if attempt < _TD_RETRIES:
                sleep_for = min(8.0, 0.9 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.25)
                time.sleep(sleep_for)
        return None, None, last_error

    # 1) Twelve Data normal
    df, raw, err = _call_twelvedata(params)
    if df is not None:
        return df, raw

    # 2) Interval aliases quando a free tier é mais sensível a parâmetros
    if interval == "1h":
        for alt_interval in ("60min", "1hour"):
            alt_params = dict(params)
            alt_params["interval"] = alt_interval
            alt_df, alt_raw, alt_err = _call_twelvedata(alt_params)
            if alt_df is not None:
                return alt_df, alt_raw
            if alt_err is not None:
                err = alt_err

    # 3) Fallback demo para símbolos trial/forex quando a conta free está apertando o limite
    if _TD_ALLOW_DEMO_FALLBACK and symbol_internal != "XAUUSD":
        demo_params = dict(params)
        demo_params["apikey"] = "demo"
        demo_df, demo_raw, demo_err = _call_twelvedata(demo_params)
        if demo_df is not None:
            log(f"[TWELVEDATA] {api_symbol}: usando fallback demo")
            return demo_df, demo_raw
        if demo_err is not None:
            err = demo_err

    # 4) Gold/commodities: Twelve Data free não cobre commodities; usa Yahoo como fallback só para XAUUSD
    if symbol_internal == "XAUUSD":
        yahoo_df, yahoo_raw = _fetch_yahoo_symbol(symbol_internal, interval=interval, outputsize=outputsize)
        if yahoo_df is not None:
            log("[MARKET DATA] XAUUSD obtido via fallback Yahoo Finance")
            return yahoo_df, yahoo_raw

    log(f"[TWELVEDATA] {api_symbol}: falha ao obter candles ({type(err).__name__ if err else 'erro'})")
    return None, None


def _normalize_cache_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out


def _warm_start_from_disk() -> int:
    loaded = 0
    with _cache_lock:
        for symbol in TD_SYMBOLS:
            df = _load_disk_cache(symbol)
            if df is None:
                continue
            _cache[symbol] = (time.time(), _normalize_cache_df(df))
            loaded += 1
    if loaded:
        log(f"[TWELVEDATA] Warm start carregou {loaded}/{len(TD_SYMBOLS)} pares do cache local")
    return loaded


_warm_start_from_disk()


def _log_invalid_candle(symbol: str):
    now = time.time()
    if now - _invalid_candle_logged.get(symbol, 0) >= _INVALID_LOG_COOLDOWN:
        log(f"[ANÁLISE] {symbol}: candle inválido ou incompleto, ignorando...")
        _invalid_candle_logged[symbol] = now


def _strip_open_candle(df: pd.DataFrame) -> pd.DataFrame:
    """Remove o último candle se ainda não fechou."""
    if df.empty:
        return df
    last_time = df.index[-1]
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    # assume H1 base data; safer to remove the current candle if it may still be forming
    if last_time + pd.Timedelta(hours=1) > datetime.now(timezone.utc):
        df = df.iloc[:-1]
    return df


def _validate_last_candle(df: pd.DataFrame) -> bool:
    """Rejeita candles anômalos ou de indecisão."""
    if len(df) < 15:
        return False
    tr_temp = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"]  - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_temp = tr_temp.rolling(14).mean().iloc[-1]
    last_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
    last_body = abs(df["Close"].iloc[-1] - df["Open"].iloc[-1])
    atr_mult = getattr(Config, "ATR_ANOMALY_MULT", 2.5)
    if atr_temp > 0 and last_range > atr_mult * atr_temp:
        return False
    if atr_temp > 0 and last_body < 0.1 * atr_temp:
        return False
    return True


def _trigger_refresh_if_needed():
    global _refresh_thread
    now = time.time()
    if now - _last_refresh < _CACHE_TTL:
        return
    if _refresh_in_progress.is_set():
        return
    _refresh_in_progress.set()
    _refresh_thread = threading.Thread(target=_refresh_cache_worker, daemon=True, name="td-refresh")
    _refresh_thread.start()


def force_initial_refresh(blocking: bool = True):
    """
    Chamado no startup do bot. Se blocking=True, aguarda o primeiro fetch
    completar antes de retornar (evita sinais com cache vazio).
    """
    _trigger_refresh_if_needed()
    if blocking and _refresh_thread is not None:
        _refresh_thread.join(timeout=180)


def _get_df(symbol: str):
    """Retorna o DataFrame do cache. None se não disponível ainda."""
    _trigger_refresh_if_needed()
    with _cache_lock:
        if symbol not in _cache:
            return None
        _, df = _cache[symbol]
        if df is None:
            return None
        return df.copy()


def get_cached_price(symbol: str):
    """Último preço de fechamento do cache."""
    with _cache_lock:
        if symbol not in _cache:
            return None
        _, df = _cache[symbol]
        if df is None or len(df) == 0:
            return None
        return float(df["Close"].iloc[-1])


def get_cache_age_seconds() -> float:
    """Idade do último refresh (para exibir no dashboard)."""
    if _last_refresh == 0:
        return float("inf")
    return time.time() - _last_refresh


def _refresh_cache_worker():
    """Refresh profissional com retry, fallback e persistência local."""
    global _last_refresh

    if not Config.TWELVE_DATA_API_KEY:
        log("[TWELVEDATA] TWELVE_DATA_API_KEY não configurada.")
        _refresh_in_progress.clear()
        return

    started = time.time()
    now = time.time()
    success_count = 0
    disk_fallback_count = 0
    updated: dict[str, tuple[float, pd.DataFrame]] = {}
    stale_before = 0

    try:
        items = list(TD_SYMBOLS.items())
        batches = list(_chunked(items, _TD_BATCH_SIZE))

        with _cache_lock:
            stale_before = len(_cache)

        for batch_idx, batch in enumerate(batches):
            if batch_idx > 0 and _TD_BATCH_PAUSE > 0:
                log(f"[TWELVEDATA] Aguardando {_TD_BATCH_PAUSE}s entre lotes (rate limit)...")
                time.sleep(_TD_BATCH_PAUSE)

            for sym_internal, sym_td in batch:
                df, raw = _fetch_symbol(sym_internal)
                if df is None:
                    disk_df = _load_disk_cache(sym_internal)
                    if disk_df is not None and len(disk_df) >= 50:
                        disk_df = _normalize_cache_df(disk_df)
                        updated[sym_internal] = (now, disk_df)
                        disk_fallback_count += 1
                        continue

                    # Preserve old cache if we already had valid data before.
                    with _cache_lock:
                        if sym_internal in _cache:
                            updated[sym_internal] = _cache[sym_internal]
                            log(f"[TWELVEDATA] {sym_td}: usando cache antigo")
                            continue

                    # XAUUSD não pertence ao plano free da Twelve Data; o fallback pode falhar sem afetar o restante.
                    if sym_internal == "XAUUSD":
                        log(f"[TWELVEDATA] {sym_td}: indisponível na Twelve Data free; usando fallback quando possível")
                    else:
                        log(f"[TWELVEDATA] {sym_td}: dados insuficientes ou indisponíveis")
                    continue

                df = _normalize_cache_df(df)
                if len(df) < 50:
                    log(f"[TWELVEDATA] {sym_td}: dados insuficientes ({len(df)} candles)")
                    continue

                updated[sym_internal] = (now, df)
                _save_disk_cache(sym_internal, df)
                success_count += 1

            log(f"[TWELVEDATA] Lote {batch_idx + 1}/{len(batches)} processado ({len(batch)} pares)")

        if updated:
            with _cache_lock:
                _cache.update(updated)
                _last_refresh = now

        total_ok = success_count + disk_fallback_count
        elapsed = round(time.time() - started, 1)
        log(f"[TWELVEDATA] Cache atualizado — {total_ok}/{len(TD_SYMBOLS)} pares prontos em {elapsed}s")

    except Exception as exc:
        log(f"[TWELVEDATA] Erro inesperado no refresh: {type(exc).__name__}: {str(exc)[:180]}")
    finally:
        _refresh_in_progress.clear()


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
    closes = df["Close"].astype(float)
    highs = df["High"].astype(float)
    lows = df["Low"].astype(float)
    opens = df["Open"].astype(float)

    ema9 = closes.ewm(span=9, adjust=False, min_periods=1).mean().iloc[-1]
    ema21 = closes.ewm(span=21, adjust=False, min_periods=1).mean().iloc[-1]
    ema200 = closes.ewm(span=200, adjust=False, min_periods=1).mean().iloc[-1]

    w = min(20, max(len(closes) - 1, 2))
    sma20 = closes.rolling(w, min_periods=2).mean().iloc[-1]
    std20 = closes.rolling(w, min_periods=2).std(ddof=0).iloc[-1]

    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=1).mean()
    avg_gain = float(gain.iloc[-1]) if len(gain) else 0.0
    avg_loss = float(loss.iloc[-1]) if len(loss) else 0.0
    if avg_loss <= 1e-12:
        rsi_val = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi_val = 100 - (100 / (1 + rs))
    rsi_val = round(float(max(0, min(100, rsi_val))), 1)

    ema12 = closes.ewm(span=12, adjust=False, min_periods=1).mean()
    ema26 = closes.ewm(span=26, adjust=False, min_periods=1).mean()
    macd_line = ema12 - ema26
    sig_line = macd_line.ewm(span=9, adjust=False, min_periods=1).mean()

    tr = pd.concat([
        highs - lows,
        (highs - closes.shift()).abs(),
        (lows - closes.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.rolling(14, min_periods=1).mean()
    atr = float(atr_series.iloc[-1]) if len(atr_series) else 0.0

    up_move = highs.diff()
    dn_move = -lows.diff()
    plus_dm = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
    minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
    atr_s = tr.ewm(alpha=1/14, adjust=False, min_periods=1).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False, min_periods=1).mean() / (atr_s + 1e-10)
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False, min_periods=1).mean() / (atr_s + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = float(dx.ewm(alpha=1/14, adjust=False, min_periods=1).mean().iloc[-1])

    price = float(closes.iloc[-1])
    chg = float((closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100) if len(closes) >= 10 else 0.0

    cen = "NEUTRO"
    if price > float(ema200) and float(ema9) > float(ema21):
        cen = "ALTA"
    elif price < float(ema200) and float(ema9) < float(ema21):
        cen = "BAIXA"

    last_body = abs(float(closes.iloc[-1]) - float(opens.iloc[-1]))
    last_range = float(highs.iloc[-1]) - float(lows.iloc[-1])
    body_ratio = (last_body / last_range) if last_range > 0 else 0.0
    candle_bull = float(closes.iloc[-1]) > float(opens.iloc[-1]) and body_ratio >= 0.5
    candle_bear = float(closes.iloc[-1]) < float(opens.iloc[-1]) and body_ratio >= 0.5

    atr_pct = round((atr / price) * 100, 3) if price > 0 else 0.0
    if atr_pct >= 1.5:
        volatility_regime = "extreme"
    elif atr_pct >= 0.8:
        volatility_regime = "high"
    elif atr_pct <= 0.15:
        volatility_regime = "low"
    else:
        volatility_regime = "normal"

    return {
        "price":       price,
        "ema9":        float(ema9),
        "ema21":       float(ema21),
        "ema200":      float(ema200),
        "upper":       float(sma20 + 2 * std20) if pd.notna(sma20) and pd.notna(std20) else price,
        "lower":       float(sma20 - 2 * std20) if pd.notna(sma20) and pd.notna(std20) else price,
        "rsi":         rsi_val,
        "adx":         round(adx, 1) if pd.notna(adx) else 0.0,
        "atr":         round(atr, 6) if pd.notna(atr) else 0.0,
        "atr_pct":     atr_pct,
        "volatility":  volatility_regime,
        "macd_bull":   bool(macd_line.iloc[-1] > sig_line.iloc[-1]),
        "macd_bear":   bool(macd_line.iloc[-1] < sig_line.iloc[-1]),
        "candle_bull": candle_bull,
        "candle_bear": candle_bear,
        "delta_pct":   round(chg, 2),
        "cenario":     cen,
    }

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
