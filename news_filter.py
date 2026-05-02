"""
news_filter.py — Filtro de notícias de alto impacto.

Estratégia em duas camadas:
  1. Primária: busca calendário econômico via ForexFactory JSON público (dados reais).
  2. Fallback: janelas fixas de eventos recorrentes (NFP, FOMC, ECB, BoE, RBA, CPI)
     para quando a busca remota falhar ou estiver em backoff.

Cache TTL: 30 minutos (renovado sob demanda).
"""

import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from utils import log

# ── Fallback: janelas fixas de eventos de alto impacto (hora UTC) ──────────────
HIGH_IMPACT_WINDOWS = [
    {"dow": 4, "sh": 13, "sm": 15, "eh": 14, "em": 30, "name": "NFP",    "currencies": {"USD"}},
    {"dow": 2, "sh": 18, "sm": 45, "eh": 20, "em":  0, "name": "FOMC",   "currencies": {"USD"}},
    {"dow": 3, "sh": 13, "sm":  0, "eh": 14, "em":  0, "name": "ECB",    "currencies": {"EUR"}},
    {"dow": 3, "sh": 12, "sm":  0, "eh": 13, "em":  0, "name": "BoE",    "currencies": {"GBP"}},
    {"dow": 0, "sh": 22, "sm":  0, "eh": 23, "em": 30, "name": "RBA",    "currencies": {"AUD"}},
    {"dow": 2, "sh": 14, "sm": 30, "eh": 15, "em": 30, "name": "CPI-US", "currencies": {"USD"}},
]

# Pares sensíveis por moeda de impacto
_CURRENCY_PAIRS: dict[str, set[str]] = {
    "USD": {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "USDCHF", "XAUUSD"},
    "EUR": {"EURUSD", "EURGBP", "EURJPY"},
    "GBP": {"GBPUSD", "EURGBP", "GBPJPY"},
    "AUD": {"AUDUSD"},
    "JPY": {"USDJPY", "EURJPY", "GBPJPY"},
    "CAD": {"USDCAD"},
    "CHF": {"USDCHF"},
    "NZD": {"NZDUSD"},
}

# ── Cache de eventos reais (ForexFactory JSON) ─────────────────────────────────
_ff_events: list[dict] = []
_ff_last_fetch: float  = 0.0
_ff_lock = threading.Lock()
_FF_TTL           = 30 * 60   # renova a cada 30 min
_FF_ERROR_BACKOFF = 10 * 60   # aguarda 10 min após erro antes de tentar de novo
_FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def _fetch_ff_calendar() -> list[dict]:
    """Busca calendário econômico semanal da ForexFactory (formato JSON público)."""
    try:
        resp = requests.get(_FF_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        events = []
        for item in data:
            if item.get("impact", "").lower() != "high":
                continue
            try:
                dt_str = item.get("date", "")
                dt = datetime.fromisoformat(dt_str).astimezone(timezone.utc)
                events.append({
                    "dt":       dt,
                    "name":     item.get("title", ""),
                    "currency": item.get("country", "").upper(),
                })
            except Exception:
                continue
        log(f"[NEWS] ForexFactory: {len(events)} eventos de alto impacto esta semana")
        return events
    except Exception as e:
        log(f"[NEWS] Falha ao buscar ForexFactory: {e} — usando fallback estático")
        return []


def _ensure_ff_cache():
    """Garante que o cache FF está atualizado (thread-safe)."""
    global _ff_events, _ff_last_fetch
    now = time.time()
    with _ff_lock:
        if now - _ff_last_fetch >= _FF_TTL:
            fetched = _fetch_ff_calendar()
            if fetched:
                _ff_events = fetched
                _ff_last_fetch = now
            elif _ff_last_fetch == 0.0:
                # Primeira tentativa falhou: reentrar daqui a 10 min
                _ff_last_fetch = now - _FF_TTL + _FF_ERROR_BACKOFF


def _in_ff_window(
    symbol: str | None,
    minutes_before: int,
    minutes_after: int,
) -> tuple[bool, str]:
    """Verifica se há evento real de alto impacto na janela para o símbolo dado."""
    _ensure_ff_cache()
    now = datetime.now(timezone.utc)
    for ev in _ff_events:
        dt: datetime = ev["dt"]
        if now < dt - timedelta(minutes=minutes_before):
            continue
        if now > dt + timedelta(minutes=minutes_after):
            continue
        currency = ev["currency"]
        if symbol is None or symbol in _CURRENCY_PAIRS.get(currency, set()):
            return True, ev["name"]
    return False, ""


def _in_static_window(
    symbol: str | None,
    minutes_before: int,
    minutes_after: int,
) -> tuple[bool, str]:
    """Fallback: janelas fixas hardcoded por dia da semana e hora UTC."""
    now = datetime.now(timezone.utc)
    dow = now.weekday()
    hm  = now.hour * 60 + now.minute
    for w in HIGH_IMPACT_WINDOWS:
        if dow != w["dow"]:
            continue
        start = w["sh"] * 60 + w["sm"] - minutes_before
        end   = w["eh"] * 60 + w["em"] + minutes_after
        if not (start <= hm <= end):
            continue
        if symbol is not None:
            affected = any(
                symbol in _CURRENCY_PAIRS.get(c, set())
                for c in w["currencies"]
            )
            if not affected:
                continue
        return True, w["name"]
    return False, ""


_LAST_NEWS_LOG: dict[str, float] = {}


def is_high_impact_news_window(
    minutes_before: int = 15,
    minutes_after:  int = 30,
    symbol: str | None = None,
) -> bool:
    """
    Retorna True se há evento de alto impacto ativo na janela especificada.
    Tenta dados reais do ForexFactory primeiro; fallback para janelas estáticas.
    """
    in_window, event_name = _in_ff_window(symbol, minutes_before, minutes_after)

    if not in_window:
        in_window, event_name = _in_static_window(symbol, minutes_before, minutes_after)

    if in_window:
        key = f"{event_name}|{symbol}"
        if time.time() - _LAST_NEWS_LOG.get(key, 0.0) > 900:
            log(f"[NEWS] {event_name} ativo — setup suspenso para {symbol or 'todos'}")
            _LAST_NEWS_LOG[key] = time.time()

    return in_window
