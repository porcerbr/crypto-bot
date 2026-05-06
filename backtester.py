"""
backtester.py — motor de backtest robusto e regime-adaptativo.

Objetivos:
- reduzir overfitting
- manter frequência mínima razoável
- avaliar sinais com lógica mais parecida com a operação ao vivo
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from config import Config
from performance import calculate_metrics_from_history
from utils import calc_pnl_usd, is_jpy_pair, log, load_strategy_settings, pip_factor, get_sl_tp_atr


@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass
class BacktestResult:
    metrics: dict
    trades: list[dict]
    equity_curve: list[dict]
    params: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Timeframe / parsing
# ──────────────────────────────────────────────────────────────────────────────

def detect_timeframe(bars: list[Bar]) -> str:
    if len(bars) < 2:
        return "H1"

    deltas = []
    for i in range(1, min(10, len(bars))):
        d = abs((bars[i].timestamp - bars[i - 1].timestamp).total_seconds())
        if d > 0:
            deltas.append(d)

    if not deltas:
        return "H1"

    avg_seconds = sum(deltas) / len(deltas)
    if avg_seconds >= 5 * 24 * 3600:
        return "W1"
    if avg_seconds >= 23 * 3600:
        return "D1"
    if avg_seconds >= 3600:
        return "H1"
    if avg_seconds >= 900:
        return "M15"
    if avg_seconds >= 300:
        return "M5"
    return "M1"


def resample_to_h1(bars: list[Bar]) -> list[Bar]:
    """Agrega candles de timeframe curto (M1/M5/M15) em H1."""
    if not bars:
        return bars
    import pandas as pd

    df = bars_to_dataframe(bars)
    h1 = df.resample("1h").agg({
        "Open":  "first",
        "High":  "max",
        "Low":   "min",
        "Close": "last",
    }).dropna()

    result: list[Bar] = []
    for ts, row in h1.iterrows():
        result.append(Bar(
            timestamp=ts.to_pydatetime(),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
        ))
    return result


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    for fmt in (
        None,
        "%Y%m%d %H%M%S",   # HistData/Dukascopy ASCII: 20230101 170400
        "%Y%m%d %H%M",     # variante sem segundos:     20230101 1704
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%m/%d/%Y",  # formato US do Investing.com inglês
        "%Y-%m-%d",
    ):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(raw)
            else:
                dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def load_bars_from_csv(path: str | Path) -> list[Bar]:
    path = Path(path)

    def _from_rows(rows) -> list[Bar]:
        bars: list[Bar] = []
        for row in rows:
            row = dict(row)
            ts = _parse_dt(
                row.get("timestamp")
                or row.get("time")
                or row.get("date")
                or row.get("datetime")
                or row.get("Data")
                or row.get("Data/Hora")
            )
            if ts is None:
                continue

            def _num(*keys: str) -> float | None:
                for k in keys:
                    v = row.get(k)
                    if v is None:
                        continue
                    try:
                        return float(str(v).replace(",", ".").strip())
                    except Exception:
                        continue
                return None

            o = _num("open", "Open", "abertura")
            h = _num("high", "High", "máxima", "max")
            l = _num("low", "Low", "mínima", "min")
            c = _num("close", "Close", "fechamento")
            if None in (o, h, l, c):
                continue
            bars.append(Bar(timestamp=ts, open=float(o), high=float(h), low=float(l), close=float(c)))
        return sorted(bars, key=lambda b: b.timestamp)

    # Planilha Excel renomeada para .csv (começa com PK)
    try:
        with path.open('rb') as fh:
            sig = fh.read(4)
        if sig.startswith(b'PK'):
            from shutil import copyfile
            from tempfile import NamedTemporaryFile
            from openpyxl import load_workbook

            with NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                copyfile(path, tmp.name)
                tmp_path = Path(tmp.name)
            try:
                wb = load_workbook(tmp_path, read_only=True, data_only=True)
                ws = wb.active
                rows = []
                for vals in ws.iter_rows(values_only=True):
                    if not vals:
                        continue
                    cell = next((v for v in vals if isinstance(v, str) and v.strip()), None)
                    if cell:
                        rows.append(cell.strip())
                parsed = []
                for i, line in enumerate(rows):
                    try:
                        parts = next(csv.reader([line]))
                    except Exception:
                        continue
                    parts = [p.strip() for p in parts if p is not None and str(p).strip()]
                    if not parts:
                        continue
                    if i == 0 and parts[0].lower().startswith('data'):
                        continue
                    # Formato típico: Data,Preço,Abertura,Alta,Baixa,Var%
                    if len(parts) >= 5:
                        date_s = parts[0]
                        close_s = parts[1] if len(parts) > 1 else None
                        open_s = parts[2] if len(parts) > 2 else None
                        high_s = parts[3] if len(parts) > 3 else None
                        low_s = parts[4] if len(parts) > 4 else None
                        row = {
                            'timestamp': date_s,
                            'open': open_s,
                            'high': high_s,
                            'low': low_s,
                            'close': close_s,
                        }
                        parsed.append(row)
                if parsed:
                    return _from_rows(parsed)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass

    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;	|")
    except Exception:
        dialect = csv.get_dialect("excel")

    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return []

    # ── Detecção de formato sem cabeçalho (HistData/Dukascopy ASCII) ──────────
    # Esses arquivos começam com uma linha de dados pura (ex: "20230101 170400;…")
    # em vez de um cabeçalho textual. Se a primeira coluna começar com dígito,
    # tratamos como headerless e mapeamos posicionalmente.
    first_cols = next(csv.reader([lines[0]], dialect=dialect), [])
    first_cell = first_cols[0].strip() if first_cols else ""
    is_headerless = first_cell[:1].isdigit()

    # ── Detecção formato Investing.com (PT/ES) ──────────────────────────────
    # Cabeçalho em português: "Data,Preço,Abertura,Alta,Baixa,Var%"
    # Decimal com vírgula: "1,1792" → 1.1792 | Data: DD/MM/YYYY
    investing_headers_pt = {"data", "preco", "preço", "abertura", "alta", "baixa"}
    investing_headers_en = {"date", "price", "open", "high", "low"}
    first_lower = {c.strip().lower().replace("\u00e7", "c").strip('"') for c in first_cols}
    is_investing = (len(investing_headers_pt & first_lower) >= 3
                    or len(investing_headers_en & first_lower) >= 4)

    if is_investing:
        def _fix_num(s: str) -> str:
            """Normaliza número para float string, suportando formatos PT/BR e EN."""
            s = s.strip().strip('"').replace("%", "").replace(" ", "")
            if not s:
                return "0"
            n_dot   = s.count(".")
            n_comma = s.count(",")
            # Já está em formato EN padrão: "1.1715" ou "1,234.56"
            if n_dot >= 1 and n_comma == 0:
                # ponto é decimal (ex: "1.1715") — não mexe
                return s
            # Formato PT/BR: vírgula decimal sem ponto  "1,1792"
            if n_comma == 1 and n_dot == 0:
                return s.replace(",", ".")
            # Formato PT/BR com milhar: "1.179,20"
            if n_comma == 1 and n_dot >= 1:
                return s.replace(".", "").replace(",", ".")
            # Formato EN com milhar: "1,234.56"
            if n_dot == 1 and n_comma >= 1:
                return s.replace(",", "")
            return s

        reader_inv = csv.DictReader(lines, dialect=dialect)
        col_map = {}  # mapeia header real → chave interna
        header_aliases = {
            "data": "timestamp", "date": "timestamp",
            "preco": "close", "preço": "close", "price": "close", "último": "close", "ultimo": "close",
            "abertura": "open", "open": "open",
            "alta": "high",  "high": "high", "máx": "high", "max": "high",
            "baixa": "low",  "low": "low",  "mín": "low",  "min": "low",
            "vol.": None, "vol": None, "change %": None, "var%": None,  # ignora colunas irrelevantes
        }
        rows_inv: list[dict] = []
        for raw_row in reader_inv:
            row: dict[str, str] = {}
            for raw_col, val in raw_row.items():
                if raw_col is None:
                    continue
                key = header_aliases.get(raw_col.strip().lower().replace("\u00e7", "c").replace("\u00e9", "e").replace("\u00e1", "a").replace("\u00ed", "i"))
                if key == "timestamp":
                    row[key] = val.strip().strip('"').strip()
                elif key in ("open", "high", "low", "close"):
                    cleaned = val.strip().strip('"').strip()
                    row[key] = _fix_num(cleaned)
            # Linha de rodapé do Investing.com começa com "Abertura :"
            if "timestamp" not in row or ":" in row.get("timestamp", ""):
                continue
            if len(row) >= 4:
                rows_inv.append(row)
        return _from_rows(rows_inv)

    if is_headerless:
        # Ordem esperada: DateTime, Open, High, Low, Close[, Volume, ...]
        positional_keys = ["timestamp", "open", "high", "low", "close"]
        rows: list[dict] = []
        for line in lines:
            parts = next(csv.reader([line], dialect=dialect), [])
            if len(parts) < 5:
                continue
            row = {positional_keys[i]: parts[i].strip() for i in range(5)}
            rows.append(row)
        return _from_rows(rows)

    reader = csv.DictReader(lines, dialect=dialect)
    return _from_rows(reader)


def bars_from_dicts(data: list[dict]) -> list[Bar]:
    bars = []
    for d in data:
        try:
            ts = d["timestamp"]
            if not isinstance(ts, datetime):
                ts = _parse_dt(ts) or datetime.fromtimestamp(float(ts), tz=timezone.utc)
            bars.append(Bar(timestamp=ts, open=float(d["open"]), high=float(d["high"]), low=float(d["low"]), close=float(d["close"])))
        except Exception:
            continue
    return sorted(bars, key=lambda b: b.timestamp)


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    idx = pd.to_datetime([b.timestamp for b in bars], utc=True)
    df = pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [0.0 for _ in bars],
        },
        index=idx,
    )
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Session / costs
# ──────────────────────────────────────────────────────────────────────────────

def _in_session(bar: Bar, symbol: str) -> bool:
    h = bar.timestamp.hour
    if symbol == "XAUUSD":
        return 7 <= h < 20
    if is_jpy_pair(symbol):
        return h < 9 or h >= 23
    if "AUD" in symbol or "NZD" in symbol:
        return h < 8 or h >= 22
    return 7 <= h < 17


def _apply_cost(price: float, direction: str, symbol: str) -> float:
    spread_pips = Config.SPREAD_PIPS.get(symbol, 1.0) if getattr(Config, "USE_SPREAD_MODEL", True) else 0.0
    slippage_pips = Config.SLIPPAGE_PIPS.get(symbol, 0.3) if getattr(Config, "USE_SLIPPAGE_MODEL", True) else 0.0
    # custo conservador: metade do spread + slippage médio esperado
    cost = (spread_pips * 0.5 + slippage_pips * 0.5) * pip_factor(symbol)
    if direction == "BUY":
        return round(price + cost, 5)
    return round(price - cost, 5)


# ──────────────────────────────────────────────────────────────────────────────
# Indicators
# ──────────────────────────────────────────────────────────────────────────────

def _indicators(df: pd.DataFrame) -> dict | None:
    n = len(df)
    if n < 40:
        return None

    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    o = df["Open"]

    ema9 = c.ewm(span=9, adjust=False).mean()
    ema21 = c.ewm(span=21, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=min(200, n - 1), adjust=False).mean()

    macd_line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    d = c.diff()
    gain = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)
    atr_safe = atr.replace(0, 1e-10)
    plus_di = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr_safe
    adx = ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100).ewm(span=14, adjust=False).mean()

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std(ddof=0).fillna(0)
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    price = float(c.iloc[-1])
    atr_val = float(atr.iloc[-1]) if not math.isnan(float(atr.iloc[-1])) else 0.0
    e21 = float(ema21.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    e9 = float(ema9.iloc[-1])
    rsi_val = float(rsi.iloc[-1])
    rsi_prev = float(rsi.iloc[-2]) if n >= 2 else rsi_val
    macd_now = float(macd_line.iloc[-1])
    macd_sig = float(macd_signal.iloc[-1])
    macd_prev = float(macd_line.iloc[-2]) if n >= 2 else macd_now
    sig_prev = float(macd_signal.iloc[-2]) if n >= 2 else macd_sig

    return {
        "price": price,
        "ema9": e9,
        "ema21": e21,
        "ema50": e50,
        "ema200": e200,
        "atr": atr_val,
        "adx": float(adx.iloc[-1]),
        "pdi": float(plus_di.iloc[-1]),
        "ndi": float(minus_di.iloc[-1]),
        "rsi": rsi_val,
        "rsi_prev": rsi_prev,
        "macd_above": macd_now > macd_sig,
        "macd_below": macd_now < macd_sig,
        "macd_cross_up": macd_prev <= sig_prev and macd_now > macd_sig,
        "macd_cross_down": macd_prev >= sig_prev and macd_now < macd_sig,
        "dist_e21": (price - e21) / atr_val if atr_val > 0 else 0.0,
        "dist_bb_up": (float(bb_upper.iloc[-1]) - price) / atr_val if atr_val > 0 else 0.0,
        "dist_bb_dn": (price - float(bb_lower.iloc[-1])) / atr_val if atr_val > 0 else 0.0,
        "candle_bull": float(c.iloc[-1]) > float(o.iloc[-1]),
        "candle_bear": float(c.iloc[-1]) < float(o.iloc[-1]),
        "rsi_bounce_up": rsi_prev < 42 and rsi_val >= 42,
        "rsi_bounce_dn": rsi_prev > 58 and rsi_val <= 58,
        "trend_up": price > e200 and e21 > e50,
        "trend_dn": price < e200 and e21 < e50,
        "range_mode": float(adx.iloc[-1]) <= getattr(Config, "REGIME_ADX_RANGING", 18),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Signal logic
# ──────────────────────────────────────────────────────────────────────────────

def _regime(res: dict, tf: str) -> str:
    adx = float(res.get("adx", 0) or 0)
    if adx >= getattr(Config, "REGIME_ADX_TRENDING", 25) and (res["trend_up"] or res["trend_dn"]):
        return "trend"
    if adx <= getattr(Config, "REGIME_ADX_RANGING", 18):
        return "range"
    if tf == "W1" and adx >= getattr(Config, "REGIME_ADX_STRONG", 30):
        return "trend"
    return "transition"


def _signal(
    res: dict,
    tf: str,
    min_confluence: int = 5,
    adx_min: float | None = None,
    pull_range: tuple[float, float] | None = None,
    weekly_trade_target: float = 3.0,
) -> str | None:
    adx_min = float(adx_min if adx_min is not None else (15 if tf == "W1" else 18))
    pull_range = pull_range or ((-1.5, 2.5) if tf == "W1" else (-1.0, 2.0))
    min_confluence = max(1, min(8, int(min_confluence or 5)))

    regime = _regime(res, tf)
    price = res["price"]
    d21 = res["dist_e21"]

    def count(*conds: bool) -> int:
        return sum(1 for c in conds if c)

    def pull_ok(direction: str) -> bool:
        if direction == "BUY":
            return pull_range[0] <= d21 <= pull_range[1]
        return -pull_range[1] <= d21 <= -pull_range[0]

    # Trend-following: pullback + momentum trigger
    if regime in ("trend", "transition"):
        if res["trend_up"]:
            score = count(
                res["trend_up"],
                pull_ok("BUY"),
                res["macd_cross_up"] or res["rsi_bounce_up"],
                res["candle_bull"],
                res["adx"] >= adx_min,
                res["pdi"] >= res["ndi"],
                res["rsi"] >= 40,
                res["rsi"] <= 70,
            )
            if score >= min_confluence and pull_ok("BUY") and (res["macd_cross_up"] or res["rsi_bounce_up"]):
                return "BUY"

        if res["trend_dn"]:
            score = count(
                res["trend_dn"],
                pull_ok("SELL"),
                res["macd_cross_down"] or res["rsi_bounce_dn"],
                res["candle_bear"],
                res["adx"] >= adx_min,
                res["ndi"] >= res["pdi"],
                res["rsi"] <= 60,
                res["rsi"] >= 30,
            )
            if score >= min_confluence and pull_ok("SELL") and (res["macd_cross_down"] or res["rsi_bounce_dn"]):
                return "SELL"

    # Mean reversion in ranges: use extremes + reversals
    if regime == "range":
        buy_score = count(
            res["rsi"] <= 40,
            price <= res["ema21"],
            res["candle_bull"],
            res["dist_bb_dn"] >= 1.0,
            res["rsi_bounce_up"],
            res["macd_cross_up"],
        )
        if buy_score >= max(3, min_confluence - 1):
            return "BUY"

        sell_score = count(
            res["rsi"] >= 60,
            price >= res["ema21"],
            res["candle_bear"],
            res["dist_bb_up"] >= 1.0,
            res["rsi_bounce_dn"],
            res["macd_cross_down"],
        )
        if sell_score >= max(3, min_confluence - 1):
            return "SELL"

    # Light frequency relief: if target trades/week is high, accept slightly weaker transitions
    if weekly_trade_target >= 3.0 and regime == "transition":
        if res["trend_up"] and res["macd_cross_up"] and res["adx"] >= max(14.0, adx_min - 2):
            return "BUY"
        if res["trend_dn"] and res["macd_cross_down"] and res["adx"] >= max(14.0, adx_min - 2):
            return "SELL"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# SL / TP
# ──────────────────────────────────────────────────────────────────────────────

def _sl_tp(entry: float, direction: str, atr: float, atr_sl_mult: float = 1.5, atr_tp_mult: float = 3.0) -> tuple[float, float]:
    atr_sl_mult = max(0.1, float(atr_sl_mult or 1.5))
    atr_tp_mult = max(0.1, float(atr_tp_mult or 3.0))
    return get_sl_tp_atr(entry, atr, direction, atr_sl_mult=atr_sl_mult, atr_tp_mult=atr_tp_mult)[:2]


# ──────────────────────────────────────────────────────────────────────────────
# Backtest engine
# ──────────────────────────────────────────────────────────────────────────────

def run_backtest(
    bars: list[Bar],
    symbol: str,
    initial_balance: float | None = None,
    min_confluence: int = 5,
    adx_min: float | None = None,
    atr_sl_mult: float = 1.5,
    atr_tp_mult: float = 3.0,
    pull_range: tuple[float, float] | None = None,
    risk_pct: float = 2.0,
    warmup_bars: int | None = None,
    weekly_trade_target: float = 3.0,
    max_bars_in_trade: int | None = None,
) -> BacktestResult:
    if not bars:
        return BacktestResult(metrics=calculate_metrics_from_history([], initial_balance=initial_balance), trades=[], equity_curve=[], params={"symbol": symbol})

    # Resample automático: M1/M5/M15 → H1 para performance e compatibilidade da estratégia
    raw_tf = detect_timeframe(bars)
    if raw_tf in ("M1", "M5", "M15"):
        bars = resample_to_h1(bars)

    tf = detect_timeframe(bars)
    initial_balance = float(initial_balance if initial_balance is not None else Config.INITIAL_BALANCE)
    balance = initial_balance

    wb = warmup_bars or (80 if tf == "H1" else 40)
    max_bars = int(max_bars_in_trade or (60 if tf == "H1" else 12))
    cooldown_after_loss = 2 if tf == "H1" else 1

    df_full = bars_to_dataframe(bars)
    trades: list[dict] = []
    active: dict | None = None
    cooldown = 0

    for i in range(wb, len(bars)):
        bar = bars[i]

        if active is not None:
            t = active
            bars_open = i - t["bar_i"]

            # ── Trailing stop: move SL para breakeven após 1× ATR a favor ──
            if not t.get("be_done", False):
                atr_at_entry = t.get("atr_entry", 0)
                if atr_at_entry > 0:
                    if t["dir"] == "BUY" and bar.high >= t["entry"] + atr_at_entry:
                        t["sl"] = max(t["sl"], t["entry"])   # SL → breakeven
                        t["be_done"] = True
                    elif t["dir"] == "SELL" and bar.low <= t["entry"] - atr_at_entry:
                        t["sl"] = min(t["sl"], t["entry"])   # SL → breakeven
                        t["be_done"] = True

            if t["dir"] == "BUY":
                hit_sl = bar.low <= t["sl"]
                hit_tp = bar.high >= t["tp"]
            else:
                hit_sl = bar.high >= t["sl"]
                hit_tp = bar.low <= t["tp"]

            if hit_sl and hit_tp:
                # Conservador: assume SL primeiro quando ambos tocam na mesma vela
                hit_tp = False

            force = bars_open >= max_bars
            if hit_sl or hit_tp or force:
                if force and not hit_sl and not hit_tp:
                    exit_px = bar.close
                    pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], exit_px, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
                    result = "WIN" if pnl > 0 else "LOSS"
                else:
                    exit_px = t["tp"] if hit_tp else t["sl"]
                    pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], exit_px, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
                    result = "WIN" if hit_tp else "LOSS"

                balance = round(balance + t["margin"] + pnl, 2)
                trades.append({
                    "symbol": symbol,
                    "dir": t["dir"],
                    "result": result,
                    "pnl": round(pnl, 2),
                    "entry": t["entry"],
                    "exit": exit_px,
                    "sl": t["sl"],
                    "tp": t["tp"],
                    "lot": t["lot"],
                    "bars_open": bars_open,
                    "opened_at": t["opened_at"].isoformat(),
                    "closed_at": bar.timestamp.isoformat(),
                    "closed_ts": bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "adx": t.get("adx", 0),
                    "timeframe": tf,
                })
                active = None
                if result == "LOSS":
                    cooldown = cooldown_after_loss
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        if tf == "H1" and not _in_session(bar, symbol):
            continue

        window = max(0, i - 260)
        res = _indicators(df_full.iloc[window : i + 1])
        if not res or res["atr"] <= 0:
            continue

        direction = _signal(
            res,
            tf,
            min_confluence=min_confluence,
            adx_min=adx_min,
            pull_range=pull_range,
            weekly_trade_target=weekly_trade_target,
        )
        if not direction:
            continue

        entry = _apply_cost(bar.close, direction, symbol)
        sl, tp = _sl_tp(entry, direction, res["atr"], atr_sl_mult=atr_sl_mult, atr_tp_mult=atr_tp_mult)

        if direction == "BUY" and (sl >= entry or tp <= entry):
            continue
        if direction == "SELL" and (sl <= entry or tp >= entry):
            continue

        cs = 100 if symbol == "XAUUSD" else 100_000
        sl_dist = abs(entry - sl)
        max_risk_usd = balance * max(0.1, float(risk_pct)) / 100.0
        if sl_dist <= 0:
            continue

        lot_by_risk = max_risk_usd / (sl_dist * cs)
        lot = max(Config.MIN_LOT, round(min(lot_by_risk, 50.0), 2))

        margin = round(entry * lot * cs / Config.DEFAULT_LEVERAGE, 2)
        if margin <= 0 or margin > balance * 0.45 or margin > balance:
            continue

        comm = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot
        balance -= margin

        active = {
            "dir": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "lot": lot,
            "margin": margin,
            "comm": comm,
            "bar_i": i,
            "opened_at": bar.timestamp,
            "adx": res["adx"],
            "atr_entry": res["atr"],   # ATR no momento da entrada (para trailing stop)
            "be_done": False,          # flag: breakeven já aplicado?
        }

    if active is not None:
        t = active
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol": symbol,
            "dir": t["dir"],
            "result": "WIN" if pnl > 0 else "LOSS",
            "pnl": round(pnl, 2),
            "entry": t["entry"],
            "exit": bars[-1].close,
            "sl": t["sl"],
            "tp": t["tp"],
            "lot": t["lot"],
            "bars_open": len(bars) - t["bar_i"],
            "opened_at": t["opened_at"].isoformat(),
            "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(),
            "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "adx": t.get("adx", 0),
            "timeframe": tf,
        })

    metrics = calculate_metrics_from_history(trades, initial_balance=initial_balance, current_balance=balance)

    if trades:
        first_ts = trades[0].get("closed_ts") or trades[0].get("opened_at")
        last_ts = trades[-1].get("closed_ts") or trades[-1].get("closed_at")
        try:
            first_dt = datetime.fromisoformat(str(trades[0]["closed_at"]))
            last_dt = datetime.fromisoformat(str(trades[-1]["closed_at"]))
            span_days = max(1.0, (last_dt - first_dt).total_seconds() / 86400.0)
        except Exception:
            span_days = max(1.0, len(bars) / (24.0 if tf == "H1" else 5.0))
        metrics["trade_frequency_per_week"] = round(len(trades) / max(1e-6, span_days / 7.0), 2)
        metrics["avg_bars_per_trade"] = round(sum(t.get("bars_open", 0) for t in trades) / len(trades), 2)
    else:
        metrics["trade_frequency_per_week"] = 0.0
        metrics["avg_bars_per_trade"] = 0.0

    equity_curve = metrics.pop("equity_curve", [])
    return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve, params={"symbol": symbol, "timeframe": tf})


# ──────────────────────────────────────────────────────────────────────────────
# Legacy helpers
# ──────────────────────────────────────────────────────────────────────────────

def backtest_trades(trades: Iterable[dict], initial_balance=None) -> dict:
    return calculate_metrics_from_history(trades, initial_balance=initial_balance)


def backtest_from_strategy(bars, strategy, initial_balance=None) -> dict:
    all_trades = []
    for i in range(1, len(bars)):
        for t in (strategy(bars, i) or []):
            t = dict(t)
            t.setdefault("closed_at", bars[i].timestamp.isoformat())
            all_trades.append(t)
    return calculate_metrics_from_history(all_trades, initial_balance=initial_balance)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    a = p.parse_args()

    bars = load_bars_from_csv(a.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido.")

    tf = detect_timeframe(bars)
    log(f"[BACKTEST] {len(bars)} barras {tf} | {bars[0].timestamp:%d/%m/%Y} → {bars[-1].timestamp:%d/%m/%Y}")
    r = run_backtest(bars, a.symbol, a.balance)
    m = r.metrics

    print()
    print("═" * 52)
    print(f"  {a.symbol} · {tf} · Regime-adaptativo")
    print("═" * 52)
    print(f"  Trades:        {m['total_trades']} ({m['wins']}W / {m['losses']}L)")
    print(f"  Win Rate:      {m['winrate']}%")
    print(f"  Profit Factor: {m['profit_factor']}")
    print(f"  Max Drawdown:  {m['max_drawdown_pct']}%")
    print(f"  Sharpe:        {m.get('sharpe_ratio', 0)}")
    print(f"  Trades/week:   {m.get('trade_frequency_per_week', 0)}")
    print(f"  P&L:           ${m['total_pnl']}")
    print("═" * 52)



if __name__ == "__main__":
    main()
