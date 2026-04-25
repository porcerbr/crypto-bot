# news_filter.py
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from config import Config
from utils import log

_cached_events = []
_cache_ts = 0

def fetch_calendar():
    """Baixa e parseia o calendário semanal do ForexFactory."""
    global _cached_events, _cache_ts
    now = time.time()
    if now - _cache_ts < 3600:  # cache de 1 hora
        return _cached_events
    try:
        resp = requests.get(Config.FOREX_FACTORY_CALENDAR_URL, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        events = []
        for event in root.findall("event"):
            title = event.findtext("title", "")
            country = event.findtext("country", "")
            impact = event.findtext("impact", "")
            date_str = event.findtext("date", "")
            time_str = event.findtext("time", "00:00")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %H:%M")
                dt = dt.replace(tzinfo=timezone.utc)
            except:
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M")
                    dt = dt.replace(tzinfo=timezone.utc)
                except:
                    continue
            events.append({
                "title": title,
                "country": country,
                "impact": impact,
                "datetime": dt,
            })
        _cached_events = events
        _cache_ts = now
        log(f"[NEWS] {len(events)} eventos carregados do calendário")
    except Exception as e:
        log(f"[NEWS] Erro ao carregar calendário: {e}")
    return _cached_events

def is_high_impact_news_near():
    """Retorna True se há evento High impact dentro da janela NEWS_BLOCK_MINUTES."""
    if not Config.NEWS_FILTER_ENABLED:
        return False
    events = fetch_calendar()
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=Config.NEWS_BLOCK_MINUTES)
    for ev in events:
        if ev["impact"] not in ("High", "high", "HIGH", "3"):
            continue
        if abs(ev["datetime"] - now) <= window:
            return True
    return False
