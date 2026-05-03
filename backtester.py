"""
backtester.py — Backtester multi-timeframe (H1 e W1).

Detecta automaticamente o timeframe pelos intervalos entre barras.
Ajusta todos os parâmetros de acordo (sessão, cooldown, ATR, EMA).

Estratégia: Pullback em tendência (EMA-based trend-following).
  - Entry: preço voltou para zona da EMA21 após extensão
  - Trigger: MACD cruzou signal + candle de confirmação
  - SL: 1.5×ATR  |  TP: 2.5×ATR  (RR = 1.67)
  - Filtros: ADX mínimo, sessão (H1 apenas), cooldown pós-loss
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from config import Config
from performance import calculate_metrics_from_history
from utils import calc_pnl_usd, is_jpy_pair, log


# ═══════════════════════════════════════════════════════════════════════════════
# ESTRUTURAS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Bar:
    timestamp: datetime
    open:  float
    high:  float
    low:   float
    close: float


@dataclass
class BacktestResult:
    metrics:      dict
    trades:       list[dict]
    equity_curve: list[dict]
    params:       dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# TIMEFRAME DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_timeframe(bars: list[Bar]) -> str:
    """Detecta o timeframe baseado no intervalo médio entre barras."""
    if len(bars) < 2:
        return "H1"
    deltas = []
    for i in range(1, min(10, len(bars))):
        d = abs((bars[i].timestamp - bars[i-1].timestamp).total_seconds())
        if d > 0:
            deltas.append(d)
    if not deltas:
        return "H1"
    avg_seconds = sum(deltas) / len(deltas)
    if avg_seconds >= 5 * 24 * 3600:   # ≥5 dias
        return "W1"
    if avg_seconds >= 23 * 3600:        # ≥23h
        return "D1"
    return "H1"


# ═══════════════════════════════════════════════════════════════════════════════
# CSV
# ═══════════════════════════════════════════════════════════════════════════════

def load_bars_from_csv(path: str | Path) -> list[Bar]:
    """Carrega barras de CSV padrão (timestamp,open,high,low,close)."""
    path = Path(path)
    bars: list[Bar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("timestamp") or row.get("time") or row.get("date")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                try:
                    ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                    ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
            try:
                bars.append(Bar(
                    timestamp=ts,
                    open= float(row.get("open")  or row.get("Open")),
                    high= float(row.get("high")  or row.get("High")),
                    low=  float(row.get("low")   or row.get("Low")),
                    close=float(row.get("close") or row.get("Close")),
                ))
            except Exception:
                continue
    return sorted(bars, key=lambda b: b.timestamp)


def bars_from_dicts(data: list[dict]) -> list[Bar]:
    """Converte lista de dicts (output do csv_parser) para lista de Bar."""
    bars = []
    for d in data:
        try:
            bars.append(Bar(
                timestamp=d["timestamp"],
                open= float(d["open"]),
                high= float(d["high"]),
                low=  float(d["low"]),
                close=float(d["close"]),
            ))
        except Exception:
            continue
    return sorted(bars, key=lambda b: b.timestamp)


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    records = [{"Open": b.open, "High": b.high, "Low": b.low, "Close": b.close}
               for b in bars]
    df = pd.DataFrame(records,
                      index=pd.to_datetime([b.timestamp for b in bars], utc=True))
    df["Volume"] = 0.0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SESSÃO (apenas H1)
# ═══════════════════════════════════════════════════════════════════════════════

def _in_session(bar: Bar, symbol: str) -> bool:
    h = bar.timestamp.hour
    if symbol == "XAUUSD":
        return 7 <= h < 20
    if is_jpy_pair(symbol):
        return h < 9 or h >= 23
    if "AUD" in symbol or "NZD" in symbol:
        return h < 8 or h >= 22
    return 7 <= h < 17


# ═══════════════════════════════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════════════════════════════

def _indicators(df: pd.DataFrame) -> dict | None:
    n = len(df)
    if n < 30:
        return None

    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    o = df["Open"]

    ema21  = c.ewm(span=21,  adjust=False).mean()
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=min(200, n-1), adjust=False).mean()

    macd_line   = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    d    = c.diff()
    gain = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi  = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    tr  = pd.concat([h - l,
                     (h - c.shift()).abs(),
                     (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    pdm = (h.diff()).clip(lower=0)
    ndm = (-l.diff()).clip(lower=0)
    pdi = 100 * pdm.ewm(span=14).mean() / atr.replace(0, 1e-10)
    ndi = 100 * ndm.ewm(span=14).mean() / atr.replace(0, 1e-10)
    adx = ((abs(pdi - ndi) / (pdi + ndi + 1e-10)) * 100).ewm(span=14).mean()

    price   = float(c.iloc[-1])
    atr_val = float(atr.iloc[-1])
    e21     = float(ema21.iloc[-1])
    e50     = float(ema50.iloc[-1])
    e200    = float(ema200.iloc[-1])
    dist_e21 = (price - e21) / atr_val if atr_val > 0 else 0

    # MACD cruzou nos últimos 3 candles
    ml_now  = float(macd_line.iloc[-1])
    ms_now  = float(macd_signal.iloc[-1])
    macd_above = ml_now > ms_now
    macd_below = ml_now < ms_now

    # Cruzou recentemente (últimas 3 barras)
    crossed_up = crossed_down = False
    for k in range(2, min(4, n)):
        ml_k = float(macd_line.iloc[-k])
        ms_k = float(macd_signal.iloc[-k])
        if macd_above and ml_k <= ms_k:
            crossed_up = True
        if macd_below and ml_k >= ms_k:
            crossed_down = True

    rsi_val  = float(rsi.iloc[-1])
    rsi_prev = float(rsi.iloc[-2]) if n >= 2 else rsi_val

    return {
        "price":          price,
        "ema21":          e21,
        "ema50":          e50,
        "ema200":         e200,
        "atr":            atr_val,
        "adx":            float(adx.iloc[-1]),
        "pdi":            float(pdi.iloc[-1]),
        "ndi":            float(ndi.iloc[-1]),
        "rsi":            rsi_val,
        "macd_above":     macd_above,
        "macd_below":     macd_below,
        "macd_cross_up":  crossed_up,
        "macd_cross_down": crossed_down,
        "dist_e21":       dist_e21,
        "candle_bull":    float(c.iloc[-1]) > float(o.iloc[-1]),
        "candle_bear":    float(c.iloc[-1]) < float(o.iloc[-1]),
        "rsi_bounce_up":  rsi_prev < 42 and rsi_val >= 42,
        "rsi_bounce_dn":  rsi_prev > 58 and rsi_val <= 58,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SINAL: PULLBACK EM TENDÊNCIA
# ═══════════════════════════════════════════════════════════════════════════════

def _signal(res: dict, tf: str) -> str | None:
    """
    Detecta setup de pullback em tendência.
    Parâmetros ligeiramente mais relaxados no W1 (mais barras por período).
    """
    p       = res["price"]
    d21     = res["dist_e21"]
    adx_min = 15 if tf == "W1" else 18

    # Pullback zone: preço na zona da EMA21 (não perseguindo topo/fundo)
    pull_range = (-1.5, 2.5) if tf == "W1" else (-1.0, 2.0)

    # BUY
    trend_up = p > res["ema200"] and res["ema21"] > res["ema50"]
    pull_up  = pull_range[0] <= d21 <= pull_range[1]
    trig_up  = res["macd_cross_up"] or res["rsi_bounce_up"]
    cond_up  = (trend_up and pull_up and trig_up and
                res["candle_bull"] and res["adx"] >= adx_min and
                res["pdi"] > res["ndi"])
    if cond_up:
        return "BUY"

    # SELL
    trend_dn = p < res["ema200"] and res["ema21"] < res["ema50"]
    pull_dn  = -pull_range[1] <= d21 <= -pull_range[0]
    trig_dn  = res["macd_cross_down"] or res["rsi_bounce_dn"]
    cond_dn  = (trend_dn and pull_dn and trig_dn and
                res["candle_bear"] and res["adx"] >= adx_min and
                res["ndi"] > res["pdi"])
    if cond_dn:
        return "SELL"

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SL / TP
# ═══════════════════════════════════════════════════════════════════════════════

def _sl_tp(entry: float, direction: str, atr: float) -> tuple[float, float]:
    """SL=1.5×ATR, TP=2.5×ATR — RR=1.67. Consistente e atingível."""
    if direction == "BUY":
        return round(entry - atr * 1.5, 5), round(entry + atr * 2.5, 5)
    return round(entry + atr * 1.5, 5), round(entry - atr * 2.5, 5)


def _apply_cost(entry: float, direction: str, symbol: str) -> float:
    pf   = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
    cost = Config.SPREAD_PIPS.get(symbol, 1.0) * pf
    cost += random.uniform(0, Config.SLIPPAGE_PIPS.get(symbol, 0.3)) * pf
    return round(entry + cost if direction == "BUY" else entry - cost, 5)


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    bars:            list[Bar],
    symbol:          str,
    initial_balance: float | None = None,
    min_confluence:  int          = 5,   # mantido por compatibilidade
    warmup_bars:     int | None   = None,
) -> BacktestResult:

    tf              = detect_timeframe(bars)
    initial_balance = float(initial_balance or Config.INITIAL_BALANCE)
    balance         = initial_balance

    # Parâmetros por timeframe
    if tf == "W1":
        wb       = warmup_bars or 30
        max_bars = 16    # 4 meses máx em aberto
        cooldown_after_loss = 1
    else:   # H1 / D1
        wb       = warmup_bars or 60
        max_bars = 48
        cooldown_after_loss = 2

    df_full  = bars_to_dataframe(bars)
    trades: list[dict]  = []
    active: dict | None = None
    cooldown            = 0

    for i in range(wb, len(bars)):
        bar = bars[i]

        if cooldown > 0:
            cooldown -= 1

        # ── Gerencia trade ativo ──────────────────────────────────────────────
        if active is not None:
            t         = active
            bars_open = i - t["bar_i"]

            if t["dir"] == "BUY":
                hit_sl = bar.low  <= t["sl"]
                hit_tp = bar.high >= t["tp"]
            else:
                hit_sl = bar.high >= t["sl"]
                hit_tp = bar.low  <= t["tp"]

            # Mesmo candle bate os dois → assume SL (pior caso realista)
            if hit_sl and hit_tp:
                hit_tp = False

            force = bars_open >= max_bars

            if hit_sl or hit_tp or force:
                if force and not hit_sl and not hit_tp:
                    exit_px = bar.close
                    result  = "WIN" if bar.close > t["entry"] and t["dir"] == "BUY" else \
                              "WIN" if bar.close < t["entry"] and t["dir"] == "SELL" else "LOSS"
                else:
                    exit_px = t["tp"] if hit_tp else t["sl"]
                    result  = "WIN" if hit_tp else "LOSS"

                pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], exit_px,
                                   t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
                balance = round(balance + t["margin"] + pnl, 2)
                trades.append({
                    "symbol":        symbol,
                    "dir":           t["dir"],
                    "result":        result,
                    "pnl":           round(pnl, 2),
                    "entry":         t["entry"],
                    "exit":          exit_px,
                    "sl":            t["sl"],
                    "tp":            t["tp"],
                    "lot":           t["lot"],
                    "bars_open":     bars_open,
                    "opened_at":     t["opened_at"].isoformat(),
                    "closed_at":     bar.timestamp.isoformat(),
                    "closed_ts":     bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "adx":           t.get("adx", 0),
                    "timeframe":     tf,
                })
                active = None
                if result == "LOSS":
                    cooldown = cooldown_after_loss
            continue

        # ── Filtros pré-sinal ─────────────────────────────────────────────────
        if cooldown > 0:
            continue

        # Filtro de sessão apenas para H1
        if tf == "H1" and not _in_session(bar, symbol):
            continue

        window = max(0, i - 250)
        res    = _indicators(df_full.iloc[window: i + 1])
        if not res or res["atr"] <= 0:
            continue

        direction = _signal(res, tf)
        if not direction:
            continue

        # ── Abre trade ────────────────────────────────────────────────────────
        entry  = _apply_cost(bar.close, direction, symbol)
        sl, tp = _sl_tp(entry, direction, res["atr"])

        if direction == "BUY"  and (sl >= entry or tp <= entry): continue
        if direction == "SELL" and (sl <= entry or tp >= entry): continue

        try:
            from risk import calc_lot_for_risk
            lot, _, _ = calc_lot_for_risk(symbol, entry, sl, balance)
        except Exception:
            lot = Config.MIN_LOT

        cs     = 100 if symbol == "XAUUSD" else 100_000
        margin = round(entry * lot * cs / Config.DEFAULT_LEVERAGE, 2)
        if margin > balance * 0.4 or margin <= 0:
            continue

        comm    = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot
        balance -= margin

        active = {
            "dir": direction, "entry": entry, "sl": sl, "tp": tp,
            "lot": lot, "margin": margin, "comm": comm,
            "bar_i": i, "opened_at": bar.timestamp, "adx": res["adx"],
        }

    # Trade em aberto no fim dos dados
    if active is not None:
        t   = active
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close,
                            t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol": symbol, "dir": t["dir"],
            "result": "WIN" if pnl > 0 else "LOSS",
            "pnl": round(pnl, 2), "entry": t["entry"],
            "exit": bars[-1].close, "sl": t["sl"], "tp": t["tp"],
            "lot": t["lot"], "bars_open": len(bars) - t["bar_i"],
            "opened_at": t["opened_at"].isoformat(),
            "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(),
            "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "adx": t.get("adx", 0), "timeframe": tf,
        })

    metrics = calculate_metrics_from_history(
        trades, initial_balance=initial_balance, current_balance=balance,
    )
    return BacktestResult(
        metrics=metrics, trades=trades,
        equity_curve=metrics.pop("equity_curve", []),
        params={"symbol": symbol, "timeframe": tf},
    )


# ── Legado ────────────────────────────────────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--symbol",  default="EURUSD")
    p.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    a = p.parse_args()

    bars = load_bars_from_csv(a.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido.")

    tf = detect_timeframe(bars)
    log(f"[BACKTEST] {len(bars)} barras {tf} | {bars[0].timestamp:%d/%m/%Y} → {bars[-1].timestamp:%d/%m/%Y}")
    r = run_backtest(bars, a.symbol, a.balance)
    m = r.metrics

    print(f"\n{'═'*52}")
    print(f"  {a.symbol} · {tf} · Pullback em Tendência")
    print(f"{'═'*52}")
    print(f"  Trades:        {m['total_trades']} ({m['wins']}W / {m['losses']}L)")
    print(f"  Win Rate:      {m['winrate']}%")
    print(f"  Profit Factor: {m['profit_factor']}")
    print(f"  Max Drawdown:  {m['max_drawdown_pct']}%")
    print(f"  Sharpe:        {m.get('sharpe_ratio', 0)}")
    print(f"  P&L:           ${m['total_pnl']}")
    print(f"{'═'*52}\n")


if __name__ == "__main__":
    main()
