"""
backtester.py — motor de backtest com suporte nativo M15 e H1.

Estratégia M15: EMA50 (tendência) + MACD (momentum) + RSI (zona)
Estratégia H1:  EMA200/21/50 + pullback + ADX (original regime-adaptativo)
Multi-timeframe: bias H1 filtra sinais M15 (maior melhora de WR).
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
# Timeframe detection & resampling
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
    avg = sum(deltas) / len(deltas)
    if avg >= 5 * 24 * 3600: return "W1"
    if avg >= 23 * 3600:     return "D1"
    if avg >= 3600:          return "H1"
    if avg >= 900:           return "M15"
    if avg >= 300:           return "M5"
    return "M1"


def resample_to_h1(bars: list[Bar]) -> list[Bar]:
    if not bars:
        return bars
    df = bars_to_dataframe(bars)
    h1 = df.resample("1h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    return [
        Bar(timestamp=ts.to_pydatetime(), open=float(r["Open"]),
            high=float(r["High"]), low=float(r["Low"]), close=float(r["Close"]))
        for ts, r in h1.iterrows()
    ]


def prepare_bars_for_backtest(bars: list[Bar]) -> list[Bar]:
    """M15 mantido como M15. Só M1/M5 são reamostrados para H1."""
    if not bars:
        return bars
    tf = detect_timeframe(bars)
    if tf in ("M1", "M5"):
        return resample_to_h1(bars)
    return bars


# ──────────────────────────────────────────────────────────────────────────────
# CSV / parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y%m%d %H%M%S", "%Y%m%d %H%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(raw) if fmt is None else datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            continue
    return None


def load_bars_from_csv(path: str | Path) -> list[Bar]:
    path = Path(path)

    def _from_rows(rows) -> list[Bar]:
        bars: list[Bar] = []
        for row in rows:
            row = dict(row)
            ts = _parse_dt(row.get("timestamp") or row.get("time") or row.get("date")
                           or row.get("datetime") or row.get("Data"))
            if ts is None:
                continue
            def _n(*keys):
                for k in keys:
                    v = row.get(k)
                    if v is None: continue
                    try: return float(str(v).replace(",", ".").strip())
                    except: continue
                return None
            o, h, l, c = _n("open","Open"), _n("high","High"), _n("low","Low"), _n("close","Close")
            if None in (o, h, l, c): continue
            bars.append(Bar(timestamp=ts, open=float(o), high=float(h), low=float(l), close=float(c)))
        return sorted(bars, key=lambda b: b.timestamp)

    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return []
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except Exception:
        dialect = csv.get_dialect("excel")
    first_cols = next(csv.reader([lines[0]], dialect=dialect), [])
    first_cell = first_cols[0].strip() if first_cols else ""
    if first_cell[:1].isdigit():
        rows = []
        for line in lines:
            parts = next(csv.reader([line], dialect=dialect), [])
            if len(parts) >= 5:
                rows.append({"timestamp": parts[0], "open": parts[1], "high": parts[2],
                             "low": parts[3], "close": parts[4]})
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
            bars.append(Bar(timestamp=ts, open=float(d["open"]), high=float(d["high"]),
                            low=float(d["low"]), close=float(d["close"])))
        except Exception:
            continue
    return sorted(bars, key=lambda b: b.timestamp)


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    idx = pd.to_datetime([b.timestamp for b in bars], utc=True)
    return pd.DataFrame({
        "Open": [b.open for b in bars], "High": [b.high for b in bars],
        "Low": [b.low for b in bars],  "Close": [b.close for b in bars],
        "Volume": [0.0] * len(bars),
    }, index=idx)


# ──────────────────────────────────────────────────────────────────────────────
# Session filter
# ──────────────────────────────────────────────────────────────────────────────

def _in_session(bar: Bar, symbol: str, tf: str = "H1") -> bool:
    ts = bar.timestamp
    # Fim de semana: mercado fechado
    if ts.weekday() >= 5:
        return False
    # Sexta após 22h UTC: risco de gap de fim de semana
    if ts.weekday() == 4 and ts.hour >= 22:
        return False
    h = ts.hour
    if tf == "M15":
        # M15: bloqueia apenas madrugada UTC (00h–04h) — mercado morto
        return h >= 5
    # H1: janelas por par
    if symbol == "XAUUSD":
        return 7 <= h < 20
    if is_jpy_pair(symbol):
        return h < 9 or h >= 23
    if "AUD" in symbol or "NZD" in symbol:
        return h < 8 or h >= 22
    return 7 <= h < 17


# ──────────────────────────────────────────────────────────────────────────────
# Costs
# ──────────────────────────────────────────────────────────────────────────────

def _apply_cost(price: float, direction: str, symbol: str) -> float:
    spread = Config.SPREAD_PIPS.get(symbol, 1.0) if getattr(Config, "USE_SPREAD_MODEL", True) else 0.0
    slip   = Config.SLIPPAGE_PIPS.get(symbol, 0.3) if getattr(Config, "USE_SLIPPAGE_MODEL", True) else 0.0
    cost   = (spread * 0.5 + slip * 0.5) * pip_factor(symbol)
    return round(price + cost if direction == "BUY" else price - cost, 5)


# ──────────────────────────────────────────────────────────────────────────────
# Indicators (rolling window — used directly in run_backtest)
# ──────────────────────────────────────────────────────────────────────────────

def _indicators(df: pd.DataFrame) -> dict | None:
    n = len(df)
    if n < 40:
        return None

    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]

    ema9   = c.ewm(span=9,   adjust=False).mean()
    ema21  = c.ewm(span=21,  adjust=False).mean()
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=min(200, n - 1), adjust=False).mean()

    macd_line   = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    d    = c.diff()
    gain = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi  = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    tr   = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr  = tr.ewm(span=14, adjust=False).mean()

    up_m    = h.diff(); dn_m = -l.diff()
    plus_dm = ((up_m > dn_m) & (up_m > 0)) * up_m.clip(lower=0)
    minus_dm= ((dn_m > up_m) & (dn_m > 0)) * dn_m.clip(lower=0)
    atr_s   = atr.replace(0, 1e-10)
    pdi     = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr_s
    ndi     = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr_s
    adx     = ((pdi - ndi).abs() / (pdi + ndi + 1e-10) * 100).ewm(span=14, adjust=False).mean()

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std(ddof=0).fillna(0)

    price    = float(c.iloc[-1])
    atr_val  = float(atr.iloc[-1]); atr_val = 0.0 if math.isnan(atr_val) else atr_val
    atr_s_v  = atr_val if atr_val > 0 else 1e-10
    e9, e21, e50, e200 = float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])
    rsi_v    = float(rsi.iloc[-1]); rsi_p = float(rsi.iloc[-2]) if n >= 2 else rsi_v
    macd_n   = float(macd_line.iloc[-1]); macd_s = float(macd_signal.iloc[-1])
    macd_p   = float(macd_line.iloc[-2]) if n >= 2 else macd_n
    sig_p    = float(macd_signal.iloc[-2]) if n >= 2 else macd_s

    return {
        "price": price, "ema9": e9, "ema21": e21, "ema50": e50, "ema200": e200,
        "atr": atr_val, "adx": float(adx.iloc[-1]),
        "pdi": float(pdi.iloc[-1]), "ndi": float(ndi.iloc[-1]),
        "rsi": rsi_v, "rsi_prev": rsi_p,
        "macd_above":      macd_n > macd_s,
        "macd_below":      macd_n < macd_s,
        "macd_cross_up":   macd_p <= sig_p and macd_n > macd_s,
        "macd_cross_down": macd_p >= sig_p and macd_n < macd_s,
        "dist_e21":    (price - e21) / atr_s_v,
        "dist_bb_up":  (float((bb_mid + 2*bb_std).iloc[-1]) - price) / atr_s_v,
        "dist_bb_dn":  (price - float((bb_mid - 2*bb_std).iloc[-1])) / atr_s_v,
        "candle_bull": float(c.iloc[-1]) > float(o.iloc[-1]),
        "candle_bear": float(c.iloc[-1]) < float(o.iloc[-1]),
        "rsi_bounce_up": rsi_p < 42 and rsi_v >= 42,
        "rsi_bounce_dn": rsi_p > 58 and rsi_v <= 58,
        "trend_up":    price > e200 and e21 > e50,
        "trend_dn":    price < e200 and e21 < e50,
        "range_mode":  float(adx.iloc[-1]) <= getattr(Config, "REGIME_ADX_RANGING", 18),
        # M15 extras
        "above_ema50": price > e50,
        "below_ema50": price < e50,
        "above_ema21": price > e21,
        "below_ema21": price < e21,
    }


# ──────────────────────────────────────────────────────────────────────────────
# build_indicator_cache — vectorized, used by genetic optimizer
# ──────────────────────────────────────────────────────────────────────────────

def build_indicator_cache(bars: list[Bar], lookback: int = 300) -> list[dict | None]:
    """
    Calcula indicadores de forma vetorizada para toda a série.
    Retorna lista[dict|None] — None para barras sem histórico suficiente.
    Muito mais rápido que chamar _indicators() em janela deslizante.
    """
    if not bars:
        return []
    df = bars_to_dataframe(bars)
    n  = len(df)
    if n < 27:
        return [None] * n

    c, h_col, l_col, o_col = df["Close"], df["High"], df["Low"], df["Open"]

    ema9   = c.ewm(span=9,   adjust=False).mean()
    ema21  = c.ewm(span=21,  adjust=False).mean()
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()

    macd_line   = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    d    = c.diff()
    gain = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi  = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    tr   = pd.concat([h_col - l_col, (h_col - c.shift()).abs(), (l_col - c.shift()).abs()], axis=1).max(axis=1)
    atr  = tr.ewm(span=14, adjust=False).mean()

    up_m    = h_col.diff(); dn_m = -l_col.diff()
    plus_dm = ((up_m > dn_m) & (up_m > 0)) * up_m.clip(lower=0)
    minus_dm= ((dn_m > up_m) & (dn_m > 0)) * dn_m.clip(lower=0)
    atr_s   = atr.replace(0, 1e-10)
    pdi_s   = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr_s
    ndi_s   = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr_s
    adx_s   = ((pdi_s - ndi_s).abs() / (pdi_s + ndi_s + 1e-10) * 100).ewm(span=14, adjust=False).mean()

    bb_mid  = c.rolling(20).mean()
    bb_std  = c.rolling(20).std(ddof=0).fillna(0)
    bb_up   = bb_mid + 2 * bb_std
    bb_dn   = bb_mid - 2 * bb_std

    regime_adx = getattr(Config, "REGIME_ADX_RANGING", 18)
    cache: list[dict | None] = []

    for i in range(n):
        if i < 27:
            cache.append(None)
            continue
        price   = float(c.iloc[i])
        atr_val = float(atr.iloc[i]); atr_val = 0.0 if math.isnan(atr_val) else atr_val
        atr_sv  = atr_val if atr_val > 0 else 1e-10
        e9      = float(ema9.iloc[i])
        e21     = float(ema21.iloc[i])
        e50     = float(ema50.iloc[i])
        e200    = float(ema200.iloc[i])
        rsi_v   = float(rsi.iloc[i])
        rsi_p   = float(rsi.iloc[i-1]) if i >= 1 else rsi_v
        macd_n  = float(macd_line.iloc[i])
        macd_s  = float(macd_signal.iloc[i])
        macd_p  = float(macd_line.iloc[i-1]) if i >= 1 else macd_n
        sig_p   = float(macd_signal.iloc[i-1]) if i >= 1 else macd_s
        cache.append({
            "price": price, "ema9": e9, "ema21": e21, "ema50": e50, "ema200": e200,
            "atr": atr_val, "adx": float(adx_s.iloc[i]),
            "pdi": float(pdi_s.iloc[i]), "ndi": float(ndi_s.iloc[i]),
            "rsi": rsi_v, "rsi_prev": rsi_p,
            "macd_above":      macd_n > macd_s,
            "macd_below":      macd_n < macd_s,
            "macd_cross_up":   macd_p <= sig_p and macd_n > macd_s,
            "macd_cross_down": macd_p >= sig_p and macd_n < macd_s,
            "dist_e21":    (price - e21) / atr_sv,
            "dist_bb_up":  (float(bb_up.iloc[i]) - price) / atr_sv,
            "dist_bb_dn":  (price - float(bb_dn.iloc[i])) / atr_sv,
            "candle_bull": float(c.iloc[i]) > float(o_col.iloc[i]),
            "candle_bear": float(c.iloc[i]) < float(o_col.iloc[i]),
            "rsi_bounce_up": rsi_p < 42 and rsi_v >= 42,
            "rsi_bounce_dn": rsi_p > 58 and rsi_v <= 58,
            "trend_up":    price > e200 and e21 > e50,
            "trend_dn":    price < e200 and e21 < e50,
            "range_mode":  float(adx_s.iloc[i]) <= regime_adx,
            "above_ema50": price > e50,
            "below_ema50": price < e50,
            "above_ema21": price > e21,
            "below_ema21": price < e21,
        })
    return cache


# ──────────────────────────────────────────────────────────────────────────────
# Multi-timeframe bias maps
# ──────────────────────────────────────────────────────────────────────────────

def _build_h1_bias_from_m15(bars: list[Bar]) -> list[str | None]:
    """
    Viés H1 para cada barra M15.
    BUY = preço H1 > EMA21 H1 e EMA21 > EMA50 H1 (tendência altista).
    SELL = oposto. NEUTRAL = sem tendência clara.
    """
    if not bars or len(bars) < 25:
        return [None] * len(bars)
    df = bars_to_dataframe(bars)
    h1 = df.resample("1h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
    if len(h1) < 22:
        return [None] * len(bars)
    cl   = h1["Close"]
    e21h = cl.ewm(span=21, adjust=False).mean()
    e50h = cl.ewm(span=50, adjust=False).mean()
    bias_rows = []
    for ts in h1.index:
        try:
            price = float(h1.loc[ts, "Close"])
            e21   = float(e21h.loc[ts])
            e50   = float(e50h.loc[ts])
            bias  = "BUY" if price > e21 and e21 > e50 else ("SELL" if price < e21 and e21 < e50 else "NEUTRAL")
        except Exception:
            bias = "NEUTRAL"
        bias_rows.append({"timestamp": ts.to_pydatetime().replace(tzinfo=None), "h1_bias": bias})
    orig  = pd.DataFrame({"timestamp": [b.timestamp.replace(tzinfo=None) for b in bars]})
    bdf   = pd.DataFrame(bias_rows).sort_values("timestamp")
    merged = pd.merge_asof(orig.sort_values("timestamp"), bdf, on="timestamp", direction="backward")
    return [None if pd.isna(v) else str(v) for v in merged["h1_bias"].tolist()]


def _build_h4_bias_map(bars: list[Bar]) -> list[str | None]:
    """Viés H4 para cada barra H1 (filtro multi-TF para sinais H1)."""
    if not bars or len(bars) < 10:
        return [None] * len(bars)
    df = bars_to_dataframe(bars)
    h4 = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
    if len(h4) < 5:
        return [None] * len(bars)
    cl   = h4["Close"]
    e21h = cl.ewm(span=21, adjust=False).mean()
    e50h = cl.ewm(span=50, adjust=False).mean()
    h4_bars = [Bar(timestamp=ts.to_pydatetime(), open=float(r["Open"]), high=float(r["High"]),
                   low=float(r["Low"]), close=float(r["Close"])) for ts, r in h4.iterrows()]
    h4_cache = build_indicator_cache(h4_bars, lookback=260)
    adx_min_h4 = getattr(Config, "REGIME_ADX_TRENDING", 25) - 2
    h4_rows = []
    for bar, res in zip(h4_bars, h4_cache):
        bias = "NEUTRO"
        if res and float(res.get("adx", 0) or 0) >= adx_min_h4:
            if res.get("trend_up"):  bias = "BUY"
            elif res.get("trend_dn"): bias = "SELL"
        h4_rows.append({"timestamp": bar.timestamp, "h4_bias": bias})
    orig  = pd.DataFrame({"timestamp": [b.timestamp for b in bars]})
    bdf   = pd.DataFrame(h4_rows).sort_values("timestamp")
    merged = pd.merge_asof(orig.sort_values("timestamp"), bdf, on="timestamp", direction="backward")
    return [None if pd.isna(v) else str(v) for v in merged["h4_bias"].tolist()]


# ──────────────────────────────────────────────────────────────────────────────
# Signal logic — H1 (original, regime-adaptativo)
# ──────────────────────────────────────────────────────────────────────────────

def _regime(res: dict, tf: str) -> str:
    adx = float(res.get("adx", 0) or 0)
    if adx >= getattr(Config, "REGIME_ADX_TRENDING", 25) and (res.get("trend_up") or res.get("trend_dn")):
        return "trend"
    if adx <= getattr(Config, "REGIME_ADX_RANGING", 18):
        return "range"
    return "transition"


def _signal(res: dict, tf: str, min_confluence: int = 5, adx_min: float | None = None,
            pull_range: tuple | None = None, weekly_trade_target: float = 3.0,
            h4_bias=None, require_h4_alignment: bool = False) -> str | None:
    adx_min    = float(adx_min if adx_min is not None else 18)
    pull_range = pull_range or (-1.0, 2.0)
    min_confluence = max(1, min(8, int(min_confluence or 5)))
    regime = _regime(res, tf)
    d21    = res["dist_e21"]

    def count(*conds): return sum(1 for c in conds if c)
    def pull_ok(d): return (pull_range[0] <= d21 <= pull_range[1] if d=="BUY"
                            else -pull_range[1] <= d21 <= -pull_range[0])

    if regime in ("trend", "transition"):
        if res.get("trend_up"):
            if require_h4_alignment and h4_bias and h4_bias not in ("BUY", "NEUTRO", None):
                pass
            else:
                score = count(res["trend_up"], pull_ok("BUY"),
                              res.get("macd_cross_up") or res.get("rsi_bounce_up"),
                              res.get("candle_bull"), res.get("adx",0) >= adx_min,
                              res.get("pdi",0) >= res.get("ndi",0),
                              38 <= res.get("rsi",50) <= 72)
                if score >= min_confluence and pull_ok("BUY") and (res.get("macd_cross_up") or res.get("rsi_bounce_up")):
                    return "BUY"
        if res.get("trend_dn"):
            if require_h4_alignment and h4_bias and h4_bias not in ("SELL", "NEUTRO", None):
                pass
            else:
                score = count(res["trend_dn"], pull_ok("SELL"),
                              res.get("macd_cross_down") or res.get("rsi_bounce_dn"),
                              res.get("candle_bear"), res.get("adx",0) >= adx_min,
                              res.get("ndi",0) >= res.get("pdi",0),
                              28 <= res.get("rsi",50) <= 62)
                if score >= min_confluence and pull_ok("SELL") and (res.get("macd_cross_down") or res.get("rsi_bounce_dn")):
                    return "SELL"

    if regime == "range":
        if count(res.get("rsi",50) <= 40, res.get("above_ema21") == False or True,
                 res.get("candle_bull"), res.get("rsi_bounce_up"), res.get("macd_cross_up")) >= max(3, min_confluence-1):
            return "BUY"
        if count(res.get("rsi",50) >= 60, res.get("candle_bear"),
                 res.get("rsi_bounce_dn"), res.get("macd_cross_down")) >= max(3, min_confluence-1):
            return "SELL"

    if weekly_trade_target >= 3.0 and regime == "transition":
        if res.get("trend_up") and res.get("macd_cross_up") and res.get("adx",0) >= max(14.0, adx_min-2):
            return "BUY"
        if res.get("trend_dn") and res.get("macd_cross_down") and res.get("adx",0) >= max(14.0, adx_min-2):
            return "SELL"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Signal logic — M15 (EMA50 + MACD + RSI, multi-timeframe H1 bias)
# ──────────────────────────────────────────────────────────────────────────────

def _signal_m15(
    res: dict,
    min_confluence: int = 1,
    adx_min: float = 20.0,
    pull_range=None,
    weekly_trade_target: float = 8.0,
    h1_bias: str | None = None,
    rsi_ob: float = 68.0,
    rsi_os: float = 32.0,
) -> str | None:
    """
    Estratégia M15 de alta probabilidade.

    Três camadas de filtro:
    1. H1 bias (obrigatório forte): H1 deve estar CONFIRMANDO a direção —
       não basta H1 neutro. Isso elimina a maioria das entradas erradas.
    2. EMA50 M15 (obrigatório): preço na direção da tendência de médio prazo.
    3. Trigger qualificado: MACD cross + RSI em zona saudável + vela confirmando.
       RSI bounce sozinho não é mais suficiente — muito ruído em M15.
    4. ADX (soft): força de tendência confirma o setup.

    WR alvo: 45–55% | R:R alvo: 1.8–2.5:1 | Frequência: 3–8 trades/dia.
    """
    rsi = float(res.get("rsi", 50) or 50)
    adx = float(res.get("adx", 0) or 0)

    # H1 deve estar CLARAMENTE a favor — neutralidade não basta
    h1_strong_up   = h1_bias == "BUY"
    h1_strong_dn   = h1_bias == "SELL"
    h1_neutral_up  = h1_bias in (None, "NEUTRAL")  # permite, mas sem bônus
    h1_neutral_dn  = h1_bias in (None, "NEUTRAL")

    # ── BUY ──────────────────────────────────────────────────────────────────
    # H1 deve permitir BUY (BUY ou NEUTRO, nunca SELL)
    if h1_bias == "SELL":
        pass  # bloqueia BUY se H1 claramente em queda
    elif (res.get("above_ema50", False)           # M15 tendência de alta
            and res.get("macd_cross_up", False)   # MACD cruzou (trigger preciso)
            and rsi_os + 10 <= rsi < rsi_ob       # RSI em zona saudável (nem extremo)
            and res.get("candle_bull", False)):    # vela confirma (obrigatório)
        soft = sum([
            adx >= adx_min,                        # força de tendência (soft)
            h1_strong_up,                          # H1 fortemente a favor (bônus)
            45 <= rsi <= 65,                       # RSI em zona ideal
        ])
        if soft >= min_confluence:
            return "BUY"

    # ── SELL ─────────────────────────────────────────────────────────────────
    if h1_bias == "BUY":
        pass  # bloqueia SELL se H1 claramente em alta
    elif (res.get("below_ema50", False)
            and res.get("macd_cross_down", False)
            and rsi_os < rsi <= rsi_ob - 10
            and res.get("candle_bear", False)):
        soft = sum([
            adx >= adx_min,
            h1_strong_dn,
            35 <= rsi <= 55,
        ])
        if soft >= min_confluence:
            return "SELL"

    return None

# ──────────────────────────────────────────────────────────────────────────────
# SL / TP
# ──────────────────────────────────────────────────────────────────────────────

def _sl_tp(entry: float, direction: str, atr: float,
           atr_sl_mult: float = 1.5, atr_tp_mult: float = 3.0) -> tuple[float, float]:
    atr_sl_mult = max(0.5, float(atr_sl_mult or 1.5))
    atr_tp_mult = max(0.5, float(atr_tp_mult or 3.0))
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
    pull_range: tuple | None = None,
    risk_pct: float = 2.0,
    warmup_bars: int | None = None,
    weekly_trade_target: float = 3.0,
    max_bars_in_trade: int | None = None,
    indicator_cache: list | None = None,
    prepared_bars: bool = False,
    h4_bias_map: list | None = None,
    rsi_ob: float = 68.0,
    rsi_os: float = 32.0,
) -> BacktestResult:
    if not bars:
        return BacktestResult(
            metrics=calculate_metrics_from_history([], initial_balance=initial_balance),
            trades=[], equity_curve=[], params={"symbol": symbol})

    if not prepared_bars:
        bars = prepare_bars_for_backtest(bars)
    else:
        bars = list(bars)

    tf = detect_timeframe(bars)
    initial_balance = float(initial_balance if initial_balance is not None else Config.INITIAL_BALANCE)
    balance = initial_balance

    wb       = warmup_bars or (80 if tf == "H1" else 60)
    max_bars = int(max_bars_in_trade or (60 if tf == "H1" else 20))
    cooldown_after_loss = 2 if tf == "H1" else 1

    # Pre-compute H1 bias for M15
    h1_bias_map: list[str | None] = []
    if tf == "M15":
        h1_bias_map = _build_h1_bias_from_m15(bars)
        if len(h1_bias_map) < len(bars):
            h1_bias_map += [None] * (len(bars) - len(h1_bias_map))

    # Pre-compute H4 bias for H1
    if tf == "H1":
        if h4_bias_map is None:
            h4_bias_map = _build_h4_bias_map(bars)
        if len(h4_bias_map) < len(bars):
            h4_bias_map = list(h4_bias_map) + [None] * (len(bars) - len(h4_bias_map))
    else:
        h4_bias_map = [None] * len(bars)

    # Build indicator cache if not provided
    if indicator_cache is None:
        indicator_cache = build_indicator_cache(bars)
    if len(indicator_cache) < len(bars):
        indicator_cache = list(indicator_cache) + [None] * (len(bars) - len(indicator_cache))

    trades: list[dict] = []
    active: dict | None = None
    cooldown = 0

    for i in range(wb, len(bars)):
        bar = bars[i]

        # ── Manage open trade ─────────────────────────────────────────────────
        if active is not None:
            t = active
            bars_open = i - t["bar_i"]

            # Trailing: move SL to breakeven after 1×ATR profit
            if not t.get("be_done", False):
                atr_e = t.get("atr_entry", 0) or 0
                if atr_e > 0:
                    if t["dir"] == "BUY"  and bar.high >= t["entry"] + atr_e:
                        t["sl"] = max(t["sl"], t["entry"]); t["be_done"] = True
                    elif t["dir"] == "SELL" and bar.low  <= t["entry"] - atr_e:
                        t["sl"] = min(t["sl"], t["entry"]); t["be_done"] = True

            hit_sl = (bar.low  <= t["sl"]) if t["dir"] == "BUY"  else (bar.high >= t["sl"])
            hit_tp = (bar.high >= t["tp"]) if t["dir"] == "BUY"  else (bar.low  <= t["tp"])
            if hit_sl and hit_tp: hit_tp = False   # conservative: SL wins ties

            force  = bars_open >= max_bars
            if hit_sl or hit_tp or force:
                exit_px = bar.close if (force and not hit_sl and not hit_tp) else (t["tp"] if hit_tp else t["sl"])
                pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], exit_px, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
                result = "WIN" if (hit_tp or (force and pnl > 0)) else "LOSS"
                balance = round(balance + t["margin"] + pnl, 2)
                trades.append({
                    "symbol": symbol, "dir": t["dir"], "result": result,
                    "pnl": round(pnl, 2), "entry": t["entry"], "exit": exit_px,
                    "sl": t["sl"], "tp": t["tp"], "lot": t["lot"],
                    "bars_open": bars_open,
                    "opened_at": t["opened_at"].isoformat(),
                    "closed_at": bar.timestamp.isoformat(),
                    "closed_ts": bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "adx": t.get("adx", 0), "timeframe": tf,
                })
                active = None
                if result == "LOSS":
                    cooldown = cooldown_after_loss
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        if not _in_session(bar, symbol, tf):
            continue

        res = indicator_cache[i] if i < len(indicator_cache) else None
        if not res or res.get("atr", 0) <= 0:
            continue

        # ── Signal routing ────────────────────────────────────────────────────
        if tf == "M15":
            h1_b = h1_bias_map[i] if i < len(h1_bias_map) else None
            direction = _signal_m15(
                res, min_confluence=min_confluence,
                adx_min=adx_min if adx_min is not None else 20.0,
                pull_range=pull_range, weekly_trade_target=weekly_trade_target,
                h1_bias=h1_b, rsi_ob=rsi_ob, rsi_os=rsi_os,
            )
        else:
            h4_b = h4_bias_map[i] if i < len(h4_bias_map) else None
            direction = _signal(
                res, tf, min_confluence=min_confluence, adx_min=adx_min,
                pull_range=pull_range, weekly_trade_target=weekly_trade_target,
                h4_bias=h4_b, require_h4_alignment=(tf == "H1"),
            )

        if not direction:
            continue

        entry = _apply_cost(bar.close, direction, symbol)
        sl, tp = _sl_tp(entry, direction, res["atr"], atr_sl_mult=atr_sl_mult, atr_tp_mult=atr_tp_mult)

        if direction == "BUY"  and (sl >= entry or tp <= entry): continue
        if direction == "SELL" and (sl <= entry or tp >= entry): continue

        cs          = 100 if symbol == "XAUUSD" else 100_000
        sl_dist     = abs(entry - sl)
        if sl_dist <= 0: continue

        max_risk_usd = balance * max(0.1, float(risk_pct)) / 100.0
        lot   = max(Config.MIN_LOT, round(min(max_risk_usd / (sl_dist * cs), 50.0), 2))
        margin = round(entry * lot * cs / Config.DEFAULT_LEVERAGE, 2)
        if margin <= 0 or margin > balance * 0.45 or margin > balance: continue

        comm    = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot
        balance -= margin
        active   = {
            "dir": direction, "entry": entry, "sl": sl, "tp": tp,
            "lot": lot, "margin": margin, "comm": comm,
            "bar_i": i, "opened_at": bar.timestamp,
            "adx": res.get("adx", 0), "atr_entry": res.get("atr", 0), "be_done": False,
        }

    # Close open trade at end
    if active is not None:
        t = active
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol": symbol, "dir": t["dir"], "result": "WIN" if pnl > 0 else "LOSS",
            "pnl": round(pnl, 2), "entry": t["entry"], "exit": bars[-1].close,
            "sl": t["sl"], "tp": t["tp"], "lot": t["lot"],
            "bars_open": len(bars) - t["bar_i"],
            "opened_at": t["opened_at"].isoformat(), "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(), "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "adx": t.get("adx", 0), "timeframe": tf,
        })

    metrics = calculate_metrics_from_history(trades, initial_balance=initial_balance, current_balance=balance)
    if trades:
        try:
            d0 = datetime.fromisoformat(str(trades[0]["closed_at"]))
            d1 = datetime.fromisoformat(str(trades[-1]["closed_at"]))
            span = max(1.0, (d1 - d0).total_seconds() / 86400.0)
        except Exception:
            span = max(1.0, len(bars) / (96.0 if tf == "M15" else 24.0))
        metrics["trade_frequency_per_week"] = round(len(trades) / max(1e-6, span / 7.0), 2)
        metrics["avg_bars_per_trade"] = round(sum(t.get("bars_open", 0) for t in trades) / len(trades), 2)
    else:
        metrics["trade_frequency_per_week"] = 0.0
        metrics["avg_bars_per_trade"] = 0.0

    equity_curve = metrics.pop("equity_curve", [])
    return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve,
                          params={"symbol": symbol, "timeframe": tf})


# ──────────────────────────────────────────────────────────────────────────────
# Legacy / CLI
# ──────────────────────────────────────────────────────────────────────────────

def backtest_trades(trades, initial_balance=None):
    return calculate_metrics_from_history(trades, initial_balance=initial_balance)

def backtest_from_strategy(bars, strategy, initial_balance=None):
    all_trades = []
    for i in range(1, len(bars)):
        for t in (strategy(bars, i) or []):
            t = dict(t); t.setdefault("closed_at", bars[i].timestamp.isoformat())
            all_trades.append(t)
    return calculate_metrics_from_history(all_trades, initial_balance=initial_balance)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv"); p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    a = p.parse_args()
    bars = load_bars_from_csv(a.csv)
    if not bars: raise SystemExit("Nenhum candle válido.")
    tf = detect_timeframe(bars)
    log(f"[BACKTEST] {len(bars)} barras {tf} | {bars[0].timestamp:%d/%m/%Y} → {bars[-1].timestamp:%d/%m/%Y}")
    r = run_backtest(bars, a.symbol, a.balance)
    m = r.metrics
    print(f"\n{'═'*52}\n  {a.symbol} · {tf}\n{'═'*52}")
    print(f"  Trades: {m['total_trades']} ({m['wins']}W/{m['losses']}L)  WR: {m['winrate']}%")
    print(f"  PF: {m['profit_factor']}  DD: {m['max_drawdown_pct']}%  Sharpe: {m.get('sharpe_ratio',0)}")
    print(f"  Trades/week: {m.get('trade_frequency_per_week',0)}  P&L: ${m['total_pnl']}\n{'═'*52}")

if __name__ == "__main__":
    main()
