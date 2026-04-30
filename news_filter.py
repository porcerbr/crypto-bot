from datetime import datetime
from utils import log

"""
Filtro de notícias de alto impacto — heurística conservadora.
Para precisão total, integre com API de calendário econômico
(ForexFactory, Investing.com, TradingEconomics, etc.).
"""

# Janelas fixas semanais (UTC): (dia_semana, start_h, start_m, end_h, end_m, nome)
# 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sab, 6=Dom
HIGH_IMPACT_WINDOWS = [
    {"dow": 4, "sh": 13, "sm": 15, "eh": 14, "em": 30, "name": "NFP"},
    {"dow": 2, "sh": 18, "sm": 45, "eh": 20, "em":  0, "name": "FOMC"},
    {"dow": 3, "sh": 13, "sm":  0, "eh": 14, "em":  0, "name": "ECB"},
    {"dow": 3, "sh": 12, "sm":  0, "eh": 13, "em":  0, "name": "BoE"},
]

def is_high_impact_news_window(minutes_before=15, minutes_after=30):
    """
    Retorna True se estiver dentro de janela de notícia de alto impacto.
    """
    now = datetime.utcnow()
    dow = now.weekday()
    hm = now.hour * 60 + now.minute

    # Janelas semanais fixas
    for w in HIGH_IMPACT_WINDOWS:
        if dow != w["dow"]:
            continue
        start = w["sh"] * 60 + w["sm"] - minutes_before
        end   = w["eh"] * 60 + w["em"] + minutes_after
        if start <= hm <= end:
            log(f"[NEWS] Janela {w['name']} ativa — scan pausado")
            return True

    # US CPI: aproximadamente dias 10–15 do mês, 13:15–14:30 UTC (geralmente Ter–Qui)
    if 10 <= now.day <= 15 and dow in [1, 2, 3]:
        if 13*60+15 <= hm <= 14*60+30:
            log("[NEWS] Janela CPI-US aproximada ativa — scan pausado")
            return True

    return False
