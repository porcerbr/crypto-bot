from datetime import datetime, timezone
from utils import log

"""
Filtro de notícias de alto impacto — heurística conservadora, porém menos agressiva.

Correção principal:
- antes: bloqueava TODAS as quartas/quinta/sextas do mês
- agora: bloqueia apenas a ocorrência aproximada correta do evento no mês
  (ex.: 1ª sexta para NFP, 1ª quinta para ECB/BoE, etc.)

Se quiser precisão total, o próximo passo é integrar um calendário econômico real.
"""

# Cada item representa UMA janela aproximada por mês, não toda semana.
# 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sab, 6=Dom
HIGH_IMPACT_EVENTS = [
    # NFP: normalmente 1ª sexta-feira do mês, 13:30 UTC
    {"name": "NFP", "weekday": 4, "nth": 1, "start_h": 13, "start_m": 15, "end_h": 14, "end_m": 30},

    # CPI-US: normalmente 2ª quarta-feira do mês (aproximação conservadora), 13:30 UTC
    {"name": "CPI-US", "weekday": 2, "nth": 2, "start_h": 13, "start_m": 15, "end_h": 14, "end_m": 30},

    # FOMC: aproximação conservadora para 4ª quarta-feira do mês
    {"name": "FOMC", "weekday": 2, "nth": 4, "start_h": 18, "start_m": 45, "end_h": 20, "end_m": 0},

    # ECB: normalmente 1ª quinta-feira do mês
    {"name": "ECB", "weekday": 3, "nth": 1, "start_h": 13, "start_m": 0, "end_h": 14, "end_m": 0},

    # BoE: normalmente 1ª quinta-feira do mês
    {"name": "BoE", "weekday": 3, "nth": 1, "start_h": 12, "start_m": 0, "end_h": 13, "end_m": 0},
]


def _to_utc_now(now=None) -> datetime:
    """
    Normaliza para UTC.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return now


def _nth_weekday_of_month(dt: datetime) -> int:
    """
    Retorna a ocorrência do weekday dentro do mês.
    Ex.: 1 = 1ª sexta do mês, 2 = 2ª sexta do mês, etc.
    """
    return ((dt.day - 1) // 7) + 1


def is_high_impact_news_window(minutes_before=15, minutes_after=30, now=None):
    """
    Retorna True se estiver dentro de uma janela aproximada de notícia de alto impacto.

    A correção importante aqui é que o bot NÃO bloqueia mais toda semana inteira
    para eventos mensais. Ele bloqueia apenas a ocorrência aproximada do evento
    naquela semana/mês.
    """
    now = _to_utc_now(now)
    weekday = now.weekday()
    nth = _nth_weekday_of_month(now)
    hm = now.hour * 60 + now.minute

    for ev in HIGH_IMPACT_EVENTS:
        if weekday != ev["weekday"]:
            continue
        if nth != ev["nth"]:
            continue

        start = ev["start_h"] * 60 + ev["start_m"] - minutes_before
        end = ev["end_h"] * 60 + ev["end_m"] + minutes_after

        if start <= hm <= end:
            log(f"[NEWS] Janela {ev['name']} ativa — scan pausado")
            return True

    return False
