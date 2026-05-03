"""
backtester.py — Backtester com estratégia de pullback em tendência.

Lógica baseada em evidências:
  - Trend-following com pullback (maior edge comprovado em H1)
  - SL fixo em 1.5×ATR (consistente, sem distorção por swing)
  - TP em 2.5×ATR → RR = 1.67 (atingível no H1)
  - Filtro de sessão, ADX mínimo e cooldown
  - Sem confluência excessiva que filtra tudo

Por que pullback funciona: você entra quando o preço retorna à média
após excesso, com o vento da tendência a favor. É o setup com maior
win rate comprovado em forex H1.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
# CSV
# ═══════════════════════════════════════════════════════════════════════════════

def load_bars_from_csv(path: str | Path) -> list[Bar]:
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


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    records = [{"Open": b.open, "High": b.high, "Low": b.low, "Close": b.close}
               for b in bars]
    df = pd.DataFrame(records,
                      index=pd.to_datetime([b.timestamp for b in bars], utc=True))
    df["Volume"] = 0.0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# SESSÃO
# ═══════════════════════════════════════════════════════════════════════════════

def _in_session(bar: Bar, symbol: str) -> bool:
    """Retorna True se estamos dentro da janela de liquidez do par."""
    h = bar.timestamp.hour
    if symbol == "XAUUSD":
        return 7 <= h < 20        # London + NY completo
    if is_jpy_pair(symbol):
        return h < 9 or h >= 23  # Tokyo
    if "AUD" in symbol or "NZD" in symbol:
        return h < 8 or h >= 22  # Sydney + Tokyo
    return 7 <= h < 17            # London + NY overlap (EUR/GBP/CHF/CAD)


# ═══════════════════════════════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════════════════════════════

def _indicators(df: pd.DataFrame) -> dict | None:
    n = len(df)
    if n < 50:
        return None

    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    o = df["Open"]

    # Tendência
    ema21  = c.ewm(span=21,  adjust=False).mean()
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()

    # Momentum
    macd_line   = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()

    # RSI
    d    = c.diff()
    gain = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi  = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    # ATR
    tr  = pd.concat([h - l,
                     (h - c.shift()).abs(),
                     (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    # ADX
    pdm = (h.diff()).clip(lower=0)
    ndm = (-l.diff()).clip(lower=0)
    pdi = 100 * pdm.ewm(span=14).mean() / atr.replace(0, 1e-10)
    ndi = 100 * ndm.ewm(span=14).mean() / atr.replace(0, 1e-10)
    adx = ((abs(pdi - ndi) / (pdi + ndi + 1e-10)) * 100).ewm(span=14).mean()

    # Pullback: distância do preço à EMA21 em múltiplos de ATR
    price   = float(c.iloc[-1])
    e21     = float(ema21.iloc[-1])
    e50     = float(ema50.iloc[-1])
    e200    = float(ema200.iloc[-1])
    atr_val = float(atr.iloc[-1])
    dist_e21 = (price - e21) / atr_val if atr_val > 0 else 0

    # MACD cruzou a signal line neste candle?
    macd_cross_up   = (float(macd_line.iloc[-1]) > float(macd_signal.iloc[-1]) and
                       float(macd_line.iloc[-2]) <= float(macd_signal.iloc[-2]))
    macd_cross_down = (float(macd_line.iloc[-1]) < float(macd_signal.iloc[-1]) and
                       float(macd_line.iloc[-2]) >= float(macd_signal.iloc[-2]))

    # Candle de confirmação
    candle_bull = float(c.iloc[-1]) > float(o.iloc[-1])
    candle_bear = float(c.iloc[-1]) < float(o.iloc[-1])

    # RSI saindo de zona de sobrevenda/sobrecompra
    rsi_val       = float(rsi.iloc[-1])
    rsi_prev      = float(rsi.iloc[-2]) if n >= 2 else rsi_val
    rsi_bounce_up = rsi_prev < 40 and rsi_val >= 40   # saiu de sobrevenda
    rsi_bounce_dn = rsi_prev > 60 and rsi_val <= 60   # saiu de sobrecompra

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
        "macd":           float(macd_line.iloc[-1]),
        "macd_signal":    float(macd_signal.iloc[-1]),
        "macd_cross_up":  macd_cross_up,
        "macd_cross_down": macd_cross_down,
        "dist_e21":       dist_e21,       # >0 = acima, <0 = abaixo
        "candle_bull":    candle_bull,
        "candle_bear":    candle_bear,
        "rsi_bounce_up":  rsi_bounce_up,
        "rsi_bounce_dn":  rsi_bounce_dn,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ESTRATÉGIA: PULLBACK EM TENDÊNCIA
# ═══════════════════════════════════════════════════════════════════════════════

def _check_signal(res: dict) -> str | None:
    """
    Retorna 'BUY', 'SELL' ou None.

    Critérios BUY (todos necessários):
      1. Preço acima da EMA200 (tendência de alta)
      2. EMA21 acima da EMA50 (estrutura de alta)
      3. Preço puxou de volta: entre -0.5 e +1.5 ATR da EMA21 (pullback zone)
      4. MACD cruzou a signal OU RSI saiu de sobrevenda
      5. Candle de confirmação bullish
      6. ADX >= 18 (mercado direcional, não ranging)
      7. +DI > -DI (força direcional confirmada)

    Critérios SELL: espelho.
    """
    p      = res["price"]
    d21    = res["dist_e21"]   # distância em ATRs da EMA21
    adx    = res["adx"]

    # BUY
    trend_up    = p > res["ema200"] and res["ema21"] > res["ema50"]
    pullback_ok = -0.5 <= d21 <= 1.5   # preço próximo ou ligeiramente acima da EMA21
    trigger_up  = res["macd_cross_up"] or res["rsi_bounce_up"]
    confirm_up  = res["candle_bull"]
    direction_up = res["pdi"] > res["ndi"]

    if (trend_up and pullback_ok and trigger_up and
            confirm_up and adx >= 18 and direction_up):
        return "BUY"

    # SELL
    trend_dn     = p < res["ema200"] and res["ema21"] < res["ema50"]
    pullback_dn  = -1.5 <= d21 <= 0.5
    trigger_dn   = res["macd_cross_down"] or res["rsi_bounce_dn"]
    confirm_dn   = res["candle_bear"]
    direction_dn = res["ndi"] > res["pdi"]

    if (trend_dn and pullback_dn and trigger_dn and
            confirm_dn and adx >= 18 and direction_dn):
        return "SELL"

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SL / TP
# ═══════════════════════════════════════════════════════════════════════════════

def _sl_tp(entry: float, direction: str, atr: float) -> tuple[float, float]:
    """SL = 1.5×ATR, TP = 2.5×ATR → RR 1.67 (atingível em H1)."""
    sl_dist = atr * 1.5
    tp_dist = atr * 2.5
    if direction == "BUY":
        return round(entry - sl_dist, 5), round(entry + tp_dist, 5)
    return round(entry + sl_dist, 5), round(entry - tp_dist, 5)


def _spread(entry: float, direction: str, symbol: str) -> float:
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
    min_confluence:  int          = 5,    # não usado nessa estratégia, mantido por compat
    warmup_bars:     int          = 60,
) -> BacktestResult:

    initial_balance = float(initial_balance or Config.INITIAL_BALANCE)
    balance         = initial_balance
    trades:         list[dict]  = []
    active:         dict | None = None
    df_full         = bars_to_dataframe(bars)
    cooldown        = 0
    MAX_BARS        = 48         # fecha trade após 2 dias sem hit

    for i in range(warmup_bars, len(bars)):
        bar   = bars[i]

        if cooldown > 0:
            cooldown -= 1

        # ── Gerencia trade ativo ──────────────────────────────────────────────
        if active is not None:
            t    = active
            open_bars = i - t["bar_i"]

            if t["dir"] == "BUY":
                hit_sl = bar.low  <= t["sl"]
                hit_tp = bar.high >= t["tp"]
            else:
                hit_sl = bar.high >= t["sl"]
                hit_tp = bar.low  <= t["tp"]

            # Se os dois são atingidos na mesma barra → assume SL (pior caso)
            if hit_sl and hit_tp:
                hit_tp = False

            force_close = open_bars >= MAX_BARS

            if hit_sl or hit_tp or force_close:
                exit_px = t["tp"] if hit_tp else t["sl"]
                if force_close and not hit_sl and not hit_tp:
                    exit_px = bar.close

                result = "WIN" if hit_tp else ("LOSS" if hit_sl else "OPEN")
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
                    "opened_at":     t["opened_at"].isoformat(),
                    "closed_at":     bar.timestamp.isoformat(),
                    "closed_ts":     bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "adx":           t.get("adx", 0),
                })
                active = None
                if result == "LOSS":
                    cooldown = 2
            continue

        # ── Filtros pré-sinal ─────────────────────────────────────────────────
        if cooldown > 0 or not _in_session(bar, symbol):
            continue

        df_win = df_full.iloc[max(0, i - 250): i + 1]
        res    = _indicators(df_win)
        if not res or res["atr"] <= 0:
            continue

        direction = _check_signal(res)
        if not direction:
            continue

        # ── Abre trade ────────────────────────────────────────────────────────
        entry    = _spread(bar.close, direction, symbol)
        sl, tp   = _sl_tp(entry, direction, res["atr"])

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

        comm   = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot
        balance -= margin

        active = {
            "dir":       direction,
            "entry":     entry,
            "sl":        sl,
            "tp":        tp,
            "lot":       lot,
            "margin":    margin,
            "comm":      comm,
            "bar_i":     i,
            "opened_at": bar.timestamp,
            "adx":       res["adx"],
        }

    # Trade ainda aberto no fim dos dados
    if active is not None:
        t   = active
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close,
                            t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol": symbol, "dir": t["dir"], "result": "OPEN",
            "pnl": round(pnl, 2), "entry": t["entry"], "exit": bars[-1].close,
            "sl": t["sl"], "tp": t["tp"], "lot": t["lot"],
            "opened_at": t["opened_at"].isoformat(),
            "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(),
            "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "adx": t.get("adx", 0),
        })

    metrics = calculate_metrics_from_history(
        trades, initial_balance=initial_balance, current_balance=balance,
    )
    return BacktestResult(
        metrics=metrics, trades=trades,
        equity_curve=metrics.pop("equity_curve", []),
        params={"symbol": symbol, "strategy": "pullback_trend"},
    )


# ── Legado ────────────────────────────────────────────────────────────────────

def backtest_trades(trades: Iterable[dict], initial_balance: float | None = None) -> dict:
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

    log(f"[BACKTEST] {len(bars)} barras | {bars[0].timestamp:%d/%m/%Y} → {bars[-1].timestamp:%d/%m/%Y}")
    r = run_backtest(bars, a.symbol, a.balance)
    m = r.metrics

    print(f"\n{'═'*50}")
    print(f"  {a.symbol} · Pullback em Tendência H1")
    print(f"{'═'*50}")
    print(f"  Trades:        {m['total_trades']} ({m['wins']}W / {m['losses']}L)")
    print(f"  Win Rate:      {m['winrate']}%")
    print(f"  Profit Factor: {m['profit_factor']}")
    print(f"  Max Drawdown:  {m['max_drawdown_pct']}%")
    print(f"  Sharpe:        {m.get('sharpe_ratio', 0)}")
    print(f"  P&L:           ${m['total_pnl']}")
    print(f"{'═'*50}\n")


if __name__ == "__main__":
    main()
