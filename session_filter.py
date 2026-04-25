# session_filter.py
from datetime import datetime, timezone
from config import Config

def count_open_sessions():
    """Retorna quantas sessões principais estão abertas agora (UTC)."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=seg, 6=dom
    # Fim de semana não conta
    if weekday >= 5:
        return 0
    h = now.hour + now.minute / 60
    count = 0
    for name, (start, end) in Config.SESSIONS.items():
        if start <= h < end:
            count += 1
    return count

def is_trading_session_open():
    """True se o número de sessões abertas >= Config.MIN_SESSIONS_OVERLAP."""
    if not Config.SESSION_FILTER_ENABLED:
        return True
    return count_open_sessions() >= Config.MIN_SESSIONS_OVERLAP
