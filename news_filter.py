from datetime import datetime, timezone
from utils import log

"""
Filtro de notícias de alto impacto — versão mais conservadora e menos "travada".
Sem calendário econômico em tempo real, usamos janelas fixas e curtas.
"""

HIGH_IMPACT_WINDOWS = [
    {"dow": 4, "sh": 13, "sm": 15, "eh": 14, "em": 30, "name": "NFP"},
    {"dow": 2, "sh": 18, "sm": 45, "eh": 20, "em":  0, "name": "FOMC"},
    {"dow": 3, "sh": 13, "sm":  0, "eh": 14, "em":  0, "name": "ECB"},
    {"dow": 3, "sh": 12, "sm":  0, "eh": 13, "em":  0, "name": "BoE"},
]

USD_SENSITIVE = {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD", "USDCHF", "XAUUSD"}


def is_high_impact_news_window(minutes_before: int = 15, minutes_after: int = 30, symbol: str | None = None) -> bool:
    """
    Retorna True apenas durante uma janela curta de evento de alto impacto.
    Sem "bloqueio por vários dias": a proteção é pontual.
    """
    now = datetime.now(timezone.utc)
    dow = now.weekday()
    hm = now.hour * 60 + now.minute

    for w in HIGH_IMPACT_WINDOWS:
        if dow != w["dow"]:
            continue
        start = w["sh"] * 60 + w["sm"] - minutes_before
        end   = w["eh"] * 60 + w["em"] + minutes_after
        if start <= hm <= end:
            if symbol is None or symbol in USD_SENSITIVE:
                log(f"[NEWS] Janela {w['name']} ativa — setup reduzido")
                return True

    return False
