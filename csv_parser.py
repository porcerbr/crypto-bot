"""
csv_parser.py — Parser para CSVs do Investing.com (formato PT-BR).

Suporta:
  - Números brasileiros: "1.234,56" → 1234.56
  - Datas: "25/04/2026" → datetime
  - Colunas: Data, Preço (close), Abertura (open), Alta (high), Baixa (low)
  - Linhas de resumo ao final são ignoradas automaticamente
  - Barras em ordem cronológica (mais antiga primeiro)
"""

from __future__ import annotations
import csv
import io
from datetime import datetime, timezone


def _br_float(s: str) -> float | None:
    """'1.234,56' → 1234.56 | '0,8634' → 0.8634"""
    try:
        return float(s.strip().replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None


def _parse_date(s: str) -> datetime | None:
    """'25/04/2026' → datetime UTC"""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_investing_csv(content: str | bytes) -> list[dict]:
    """
    Parseia conteúdo CSV do Investing.com PT-BR.

    Retorna lista de dicts ordenada do mais antigo para o mais recente:
      [{"timestamp": datetime, "open": float, "high": float,
        "low": float, "close": float}, ...]
    """
    if isinstance(content, bytes):
        # Tenta UTF-8 com BOM, depois latin-1 (comum em CSVs do Windows/Excel)
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                content = content.decode(enc, errors="strict")
                break
            except (UnicodeDecodeError, AttributeError):
                continue
        else:
            content = content.decode("utf-8-sig", errors="replace")

    # Normaliza quebras de linha (Windows \r\n → \n)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Detecta colunas: Data, Preço, Abertura, Alta, Baixa
    COL_MAP = {
        "data":      "date",
        "preço":     "close",
        "preco":     "close",
        "abertura":  "open",
        "alta":      "high",
        "baixa":     "low",
        "fechamento":"close",
    }

    reader = csv.reader(io.StringIO(content, newline=''))
    rows   = list(reader)
    if not rows:
        return []

    # Descobre índice de cada coluna pelo cabeçalho
    header = [h.strip().lower().replace('"', '') for h in rows[0]]
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        key = COL_MAP.get(h)
        if key and key not in idx:
            idx[key] = i

    required = {"date", "close", "open", "high", "low"}
    if not required.issubset(idx):
        # Fallback: assume posição fixa (Data=0, Close=1, Open=2, High=3, Low=4)
        idx = {"date": 0, "close": 1, "open": 2, "high": 3, "low": 4}

    bars: list[dict] = []
    for row in rows[1:]:
        if not row or len(row) < 5:
            continue

        # Ignora linhas de resumo do Investing.com ("Abertura : X")
        raw_date = row[idx["date"]].strip().strip('"')
        if ':' in raw_date or not raw_date:
            continue

        ts    = _parse_date(raw_date)
        close = _br_float(row[idx["close"]])
        open_ = _br_float(row[idx["open"]])
        high  = _br_float(row[idx["high"]])
        low   = _br_float(row[idx["low"]])

        if not all([ts, close, open_, high, low]):
            continue
        if not (low <= close <= high and low <= open_ <= high):
            continue

        bars.append({
            "timestamp": ts,
            "open":      open_,
            "high":      high,
            "low":       low,
            "close":     close,
        })

    # Garante ordem cronológica (Investing.com entrega do mais novo para o mais antigo)
    bars.sort(key=lambda b: b["timestamp"])
    return bars


# Autodetecta símbolo pelo range de preços (heurística)
_PRICE_RANGES = [
    ("EURUSD", 0.90, 1.30),
    ("GBPUSD", 1.10, 1.60),
    ("USDCAD", 1.20, 1.50),
    ("USDCHF", 0.75, 1.10),
    ("EURGBP", 0.78, 0.96),
    ("AUDUSD", 0.55, 0.85),
    ("NZDUSD", 0.50, 0.76),
    ("USDJPY", 95.0, 170.0),
    ("EURJPY", 110.0, 190.0),
    ("GBPJPY", 140.0, 225.0),
    ("XAUUSD", 1200.0, 3800.0),
]

def detect_symbol(bars: list[dict], filename: str = "") -> str | None:
    """
    Tenta identificar o símbolo.
    1. Tenta pelo nome do arquivo (ex: AUDUSD.csv, eurusd_weekly.csv)
    2. Usa o preço mediano de TODAS as barras (não apenas as 10 primeiras)
       para evitar falso positivo em períodos de volatilidade.
    """
    if not bars:
        return None

    # 1. Tenta pelo nome do arquivo
    fname_up = filename.upper()
    for sym, _, _ in _PRICE_RANGES:
        if sym in fname_up:
            return sym

    # 2. Usa mediana de todas as barras (mais robusto que média das 10 primeiras)
    closes = sorted(b["close"] for b in bars)
    median = closes[len(closes) // 2]

    # Prioriza matches mais específicos (ranges menores) primeiro
    sorted_ranges = sorted(_PRICE_RANGES, key=lambda x: x[2] - x[1])
    for sym, lo, hi in sorted_ranges:
        if lo <= median <= hi:
            return sym
    return None
