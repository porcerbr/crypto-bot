"""
cot_filter.py — Filtro de bias semanal baseado no Commitment of Traders (COT).

Fonte: CFTC — Traders in Financial Futures (TFF) report
       https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm

Como funciona:
  1. Baixa o relatório TFF semanal da CFTC (CSV público, sem chave API).
  2. Extrai a posição net dos Leveraged Money (hedge funds / CTAs) por par.
  3. Calcula o percentil histórico da posição net sobre as últimas 52 semanas.
  4. Classifica o bias como BULLISH / BEARISH / NEUTRAL.
  5. Cache semanal — o relatório só muda às sextas-feiras 15:30 EST.

Integração em signals.py:
    from cot_filter import get_cot_bias
    bias = get_cot_bias(sym)   # retorna "BULLISH", "BEARISH" ou "NEUTRAL"
    if bias == "BEARISH" and direction == "BUY":
        continue  # descarta sinal contra o fluxo institucional
"""

from __future__ import annotations

import csv
import io
import os
import json
import time
import zipfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal

import requests

from utils import log

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════════════════════

# Fonte primária: arquivo semanal atual (atualiza toda sexta)
_CFTC_WEEKLY_URL  = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"

# Fonte histórica: zip anual (para calcular percentil dos últimos ~3 anos)
_CFTC_HIST_URLS = [
    "https://www.cftc.gov/files/dea/history/fut_fin_txt_2024.zip",
    "https://www.cftc.gov/files/dea/history/fut_fin_txt_2023.zip",
    "https://www.cftc.gov/files/dea/history/fut_fin_txt_2022.zip",
]

# Arquivo de cache local (evita re-download toda vez)
_CACHE_FILE   = "cot_cache.json"
_CACHE_TTL    = 60 * 60 * 24 * 2    # 2 dias (relatório é semanal)

# Percentil para classificar bias
_BULL_THRESHOLD = 65   # net acima do percentil 65 → BULLISH
_BEAR_THRESHOLD = 35   # net abaixo do percentil 35 → BEARISH

# Número de semanas de histórico para calcular o percentil
_HISTORY_WEEKS = 156   # ~3 anos

# ── Mapeamento: símbolo interno → nome no relatório CFTC ─────────────────────
# Fonte: TFF report, coluna "Market_and_Exchange_Names"
_CFTC_MARKET_MAP: dict[str, dict] = {
    "EURUSD": {"name": "EURO FX",           "inverted": False},
    "GBPUSD": {"name": "BRITISH POUND",      "inverted": False},
    "USDJPY": {"name": "JAPANESE YEN",       "inverted": True},   # JPY/USD → inverso
    "USDCAD": {"name": "CANADIAN DOLLAR",    "inverted": True},   # CAD/USD → inverso
    "USDCHF": {"name": "SWISS FRANC",        "inverted": True},   # CHF/USD → inverso
    "AUDUSD": {"name": "AUSTRALIAN DOLLAR",  "inverted": False},
    "NZDUSD": {"name": "NEW ZEALAND DOLLAR", "inverted": False},
    "EURGBP": {"name": None,                 "inverted": False},  # derivado de EUR e GBP
    "EURJPY": {"name": None,                 "inverted": False},  # derivado de EUR e JPY
    "GBPJPY": {"name": None,                 "inverted": False},  # derivado de GBP e JPY
    "XAUUSD": {"name": "GOLD",               "inverted": False},  # COMEX Gold
}

# Pares derivados: calcula bias combinando os dois componentes
_DERIVED_PAIRS: dict[str, tuple[str, str]] = {
    "EURGBP": ("EURUSD", "GBPUSD"),
    "EURJPY": ("EURUSD", "USDJPY"),   # EUR strong + JPY weak = EURGBP bull
    "GBPJPY": ("GBPUSD", "USDJPY"),
}

CotBias = Literal["BULLISH", "BEARISH", "NEUTRAL"]

# ═══════════════════════════════════════════════════════════════════════════════
# ESTADO INTERNO
# ═══════════════════════════════════════════════════════════════════════════════

_lock        = threading.Lock()
_bias_cache:  dict[str, CotBias]   = {}  # sym → bias atual
_history:     dict[str, list[float]] = {}  # sym → lista de net positions (histórico)
_last_update: float = 0.0
_initialized: bool  = False

# ═══════════════════════════════════════════════════════════════════════════════
# DOWNLOAD E PARSE DO RELATÓRIO CFTC
# ═══════════════════════════════════════════════════════════════════════════════

def _cftc_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; SniperBot/2.0; +https://github.com)",
        "Accept": "text/plain,text/csv,*/*",
    }


def _download_text(url: str, timeout: int = 20) -> str | None:
    """Baixa um arquivo de texto da CFTC com retry simples."""
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_cftc_headers(), timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                log(f"[COT] Falha ao baixar {url}: {e}")
    return None


def _download_zip_csv(url: str, timeout: int = 30) -> str | None:
    """Baixa um zip da CFTC e extrai o primeiro arquivo de texto."""
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=_cftc_headers(), timeout=timeout)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith((".txt", ".csv")):
                        return zf.read(name).decode("latin-1", errors="replace")
        except Exception as e:
            if attempt == 0:
                time.sleep(5)
            else:
                log(f"[COT] Falha ao baixar zip {url}: {e}")
    return None


def _parse_tff_csv(text: str) -> dict[str, list[tuple[str, float]]]:
    """
    Parseia o CSV do relatório TFF da CFTC.

    Retorna:
        dict[market_name → list[(date_str, net_lev_money)]]
        net_lev_money = Leveraged Money Long - Short (posição net dos hedge funds)
    """
    result: dict[str, list[tuple[str, float]]] = {}

    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            market = str(row.get("Market_and_Exchange_Names", "")).strip().upper()
            date   = str(row.get("Report_Date_as_MM_DD_YYYY", "")
                         or row.get("Report_Date_as_YYYY-MM-DD", "")).strip()
            if not market or not date:
                continue

            try:
                lev_long  = float(str(row.get("Lev_Money_Positions_Long_All",  "0") or "0").replace(",", ""))
                lev_short = float(str(row.get("Lev_Money_Positions_Short_All", "0") or "0").replace(",", ""))
            except (ValueError, TypeError):
                continue

            net = lev_long - lev_short

            # Normaliza o nome do mercado (remove exchange suffix)
            # Ex: "EURO FX - CHICAGO MERCANTILE EXCHANGE" → "EURO FX"
            market_clean = market.split(" - ")[0].strip()

            if market_clean not in result:
                result[market_clean] = []
            result[market_clean].append((date, net))
    except Exception as e:
        log(f"[COT] Erro no parse CSV: {e}")

    # Ordena por data (mais recente primeiro)
    for key in result:
        try:
            result[key].sort(key=lambda x: x[0], reverse=True)
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DO BIAS
# ═══════════════════════════════════════════════════════════════════════════════

def _percentile_rank(value: float, series: list[float]) -> float:
    """
    Calcula o percentil da posição net atual em relação ao histórico.
    Retorna valor entre 0.0 e 100.0.
    """
    if not series:
        return 50.0
    below = sum(1 for v in series if v < value)
    return round((below / len(series)) * 100, 1)


def _net_to_bias(net: float, history: list[float], inverted: bool) -> CotBias:
    """Converte posição net + histórico → bias direcional."""
    if len(history) < 10:
        return "NEUTRAL"

    pct = _percentile_rank(net, history[-_HISTORY_WEEKS:])

    if inverted:
        # Para pares invertidos (USDJPY): se JPY está bullish (pct alto),
        # o dólar está fraco → USDJPY é BEARISH
        if pct >= _BULL_THRESHOLD:
            return "BEARISH"
        elif pct <= _BEAR_THRESHOLD:
            return "BULLISH"
    else:
        if pct >= _BULL_THRESHOLD:
            return "BULLISH"
        elif pct <= _BEAR_THRESHOLD:
            return "BEARISH"

    return "NEUTRAL"


def _derive_cross_bias(base_sym: str, quote_sym: str) -> CotBias:
    """
    Calcula o bias de um par cruzado (ex: EURGBP) combinando os dois componentes.
    EURGBP = EURUSD / GBPUSD
    Se EUR é BULLISH e GBP é NEUTRAL → EURGBP é BULLISH
    Se EUR é NEUTRAL e GBP é BULLISH → EURGBP é BEARISH
    """
    base_bias  = _bias_cache.get(base_sym,  "NEUTRAL")
    quote_bias = _bias_cache.get(quote_sym, "NEUTRAL")

    score = 0
    if base_bias  == "BULLISH": score += 1
    if base_bias  == "BEARISH": score -= 1
    if quote_bias == "BULLISH": score -= 1   # quote forte = par fraco
    if quote_bias == "BEARISH": score += 1

    if score >= 1:
        return "BULLISH"
    elif score <= -1:
        return "BEARISH"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE LOCAL (JSON)
# ═══════════════════════════════════════════════════════════════════════════════

def _save_cache(parsed: dict[str, list[tuple[str, float]]]) -> None:
    try:
        data = {
            "updated_at": time.time(),
            "data": {k: v for k, v in parsed.items()},
        }
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        log(f"[COT] Erro ao salvar cache: {e}")


def _load_cache() -> dict[str, list[tuple[str, float]]] | None:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - float(data.get("updated_at", 0))
        if age > _CACHE_TTL:
            return None
        return data.get("data", {})
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ATUALIZAÇÃO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def _update_cot_data(force: bool = False) -> bool:
    """
    Baixa e processa o relatório COT. Atualiza _bias_cache e _history.
    Retorna True se bem-sucedido.
    """
    global _last_update, _initialized

    # Tenta cache local primeiro
    cached = _load_cache()
    if cached and not force:
        log("[COT] Usando cache local (dados recentes)")
        _process_parsed_data(cached)
        _last_update = time.time()
        _initialized = True
        return True

    log("[COT] Baixando relatório CFTC — Traders in Financial Futures...")

    # ── 1. Dados semanais atuais ─────────────────────────────────────────────
    weekly_text = _download_text(_CFTC_WEEKLY_URL)
    if not weekly_text:
        log("[COT] ⚠️  Falha no download semanal — tentando Yahoo Finance fallback")
        return _fallback_no_data()

    parsed_weekly = _parse_tff_csv(weekly_text)

    # ── 2. Histórico anual (para percentil robusto) ──────────────────────────
    parsed_all = dict(parsed_weekly)  # copia
    for url in _CFTC_HIST_URLS:
        zip_text = _download_zip_csv(url)
        if not zip_text:
            continue
        parsed_hist = _parse_tff_csv(zip_text)
        for market, entries in parsed_hist.items():
            if market not in parsed_all:
                parsed_all[market] = []
            parsed_all[market].extend(entries)

    # Deduplica e ordena
    for market in parsed_all:
        seen = set()
        deduped = []
        for entry in parsed_all[market]:
            if entry[0] not in seen:
                seen.add(entry[0])
                deduped.append(entry)
        parsed_all[market] = sorted(deduped, key=lambda x: x[0], reverse=True)

    _save_cache(parsed_all)
    _process_parsed_data(parsed_all)
    _last_update = time.time()
    _initialized = True

    n_markets = len([s for s in _CFTC_MARKET_MAP
                     if _bias_cache.get(s, "NEUTRAL") != "NEUTRAL" or s in _DERIVED_PAIRS])
    log(f"[COT] ✅ Atualizado — {len(parsed_all)} mercados | Bias: "
        + " | ".join(f"{s}={_bias_cache.get(s,'?')}" for s in _CFTC_MARKET_MAP if s in _bias_cache))
    return True


def _process_parsed_data(parsed: dict[str, list[tuple[str, float]]]) -> None:
    """Calcula bias para cada símbolo a partir dos dados parseados."""
    global _bias_cache, _history

    # Monta índice inverso: nome CFTC → lista de nets históricos
    market_nets: dict[str, list[float]] = {}
    for market, entries in parsed.items():
        nets = [e[1] for e in entries]
        market_nets[market] = nets

    # Calcula bias para pares diretos
    for sym, cfg in _CFTC_MARKET_MAP.items():
        cftc_name = cfg["name"]
        if cftc_name is None:
            continue  # par derivado, calculado depois

        # Busca flexível: "EURO FX" pode aparecer como "EURO FX - CME"
        nets = None
        for market, n in market_nets.items():
            if cftc_name in market:
                nets = n
                break

        if not nets:
            _bias_cache[sym] = "NEUTRAL"
            _history[sym]    = []
            continue

        current_net = nets[0] if nets else 0.0
        _history[sym]    = nets
        _bias_cache[sym] = _net_to_bias(current_net, nets, cfg["inverted"])

    # Calcula bias para pares cruzados (derivados)
    for cross, (base, quote) in _DERIVED_PAIRS.items():
        _bias_cache[cross] = _derive_cross_bias(base, quote)


def _fallback_no_data() -> bool:
    """Quando não há dados, todos os pares ficam NEUTRAL (sem filtro)."""
    for sym in _CFTC_MARKET_MAP:
        _bias_cache[sym] = "NEUTRAL"
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# API PÚBLICA
# ═══════════════════════════════════════════════════════════════════════════════

def get_cot_bias(symbol: str) -> CotBias:
    """
    Retorna o bias COT semanal para o símbolo informado.

    Args:
        symbol: símbolo interno do bot (ex: "EURUSD", "GBPUSD", "XAUUSD")

    Returns:
        "BULLISH"  — institucionais net long (favorece BUY)
        "BEARISH"  — institucionais net short (favorece SELL)
        "NEUTRAL"  — posicionamento sem viés claro (sem filtro)
    """
    with _lock:
        _ensure_initialized()
        return _bias_cache.get(symbol.upper(), "NEUTRAL")


def get_cot_summary() -> dict[str, dict]:
    """
    Retorna um resumo completo do COT para todos os pares monitorados.
    Útil para o relatório do Telegram.

    Returns:
        {
            "EURUSD": {
                "bias": "BULLISH",
                "net": 125000.0,
                "percentile": 72.5,
                "history_weeks": 156,
                "updated_at": "06/05/2026 15:30",
            },
            ...
        }
    """
    with _lock:
        _ensure_initialized()
        summary = {}
        for sym, cfg in _CFTC_MARKET_MAP.items():
            nets = _history.get(sym, [])
            current_net = nets[0] if nets else 0.0
            pct = _percentile_rank(current_net, nets[-_HISTORY_WEEKS:]) if len(nets) >= 10 else 50.0
            summary[sym] = {
                "bias":          _bias_cache.get(sym, "NEUTRAL"),
                "net":           round(current_net),
                "percentile":    pct,
                "history_weeks": min(len(nets), _HISTORY_WEEKS),
                "updated_at":    datetime.fromtimestamp(_last_update).strftime("%d/%m/%Y %H:%M") if _last_update else "—",
            }
        return summary


def refresh_cot(force: bool = False) -> bool:
    """
    Força atualização dos dados COT (chamar no startup e toda sexta-feira).
    Thread-safe.
    """
    with _lock:
        now = time.time()
        # Só baixa novamente se passou mais de 12h desde última atualização
        if not force and _initialized and (now - _last_update) < 12 * 3600:
            return True
        return _update_cot_data(force=force)


def _ensure_initialized() -> None:
    """Garante inicialização lazy (chamado na primeira consulta)."""
    global _initialized
    if not _initialized:
        _update_cot_data()


# ═══════════════════════════════════════════════════════════════════════════════
# AGENDAMENTO SEMANAL (chamado pelo scheduler do main.py)
# ═══════════════════════════════════════════════════════════════════════════════

def is_cot_update_day() -> bool:
    """Retorna True se hoje é sexta-feira após 15:30 EST (hora do relatório)."""
    now_utc = datetime.now(timezone.utc)
    # Sexta = weekday 4; 15:30 EST = 20:30 UTC
    return now_utc.weekday() == 4 and now_utc.hour >= 20


def format_cot_telegram() -> str:
    """Formata o resumo COT para mensagem Telegram."""
    summary = get_cot_summary()
    if not summary:
        return "📊 <b>COT</b>: dados não disponíveis"

    bias_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⬜"}
    lines = [
        "📊 <b>COMMITMENT OF TRADERS — BIAS SEMANAL</b>",
        f"<i>Fonte: CFTC | Leveraged Money (hedge funds)</i>",
        "—" * 20,
    ]
    for sym, d in summary.items():
        if d["history_weeks"] < 5:
            continue
        emoji = bias_emoji.get(d["bias"], "⬜")
        pct_bar = "█" * int(d["percentile"] / 10) + "░" * (10 - int(d["percentile"] / 10))
        lines.append(
            f"{emoji} <b>{sym}</b>  {d['bias']:<8}  "
            f"Net: {d['net']:+,.0f}  "
            f"Pct: {d['percentile']:.0f}%  {pct_bar}"
        )

    updated = next((d["updated_at"] for d in summary.values()), "—")
    lines += ["—" * 20, f"<i>Atualizado: {updated}</i>"]
    return "\n".join(lines)
