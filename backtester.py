"""
backtester.py — Backtester integrado com a estratégia real do bot.

Melhorias v2:
  - Filtro de sessão (07h-17h UTC — Londres + Nova York)
  - SL atrás de swing high/low real (não só ATR)
  - FVG detection simplificado
  - Filtro de tendência D1 (EMA200 diária via H1)
  - Confluence melhorado com FVG e estrutura
  - Sem re-entrada na mesma barra que fechou trade
  - Cooldown de 3 barras após loss (evita revenge trading)

Uso:
    python backtester.py EURUSD.csv --symbol EURUSD --balance 500
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dt_time
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
# CARREGAMENTO DE DADOS
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
    idx = pd.to_datetime([b.timestamp for b in bars], utc=True)
    df  = pd.DataFrame(records, index=idx)
    df["Volume"] = 0.0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# FILTRO DE SESSÃO
# ═══════════════════════════════════════════════════════════════════════════════

# Sessões de melhor liquidez por tipo de par
_SESSION_RULES = {
    "JPY":  (0,  9),   # Tokyo + London open
    "AUD":  (22, 10),  # Sydney + Tokyo
    "NZD":  (21, 9),
    "XAU":  (7,  20),  # Ouro: London + NY completo
    "DEFAULT": (7, 17), # Londres + NY overlap
}

def _in_session(bar: Bar, symbol: str) -> bool:
    """Retorna True se a barra está dentro da sessão de maior liquidez."""
    hour = bar.timestamp.hour
    if is_jpy_pair(symbol):
        start, end = _SESSION_RULES["JPY"]
    elif "AUD" in symbol or "NZD" in symbol:
        start, end = _SESSION_RULES.get("AUD" if "AUD" in symbol else "NZD", (21,10))
    elif symbol == "XAUUSD":
        start, end = _SESSION_RULES["XAU"]
    else:
        start, end = _SESSION_RULES["DEFAULT"]

    if start < end:
        return start <= hour < end
    else:  # overnight (ex: 22-10)
        return hour >= start or hour < end


# ═══════════════════════════════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_indicators(df: pd.DataFrame) -> dict | None:
    if len(df) < 60:
        return None

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]

    ema9   = close.ewm(span=9,   adjust=False).mean()
    ema21  = close.ewm(span=21,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    # Tendência D1 aproximada: EMA das últimas 24 barras H1
    ema_d1 = close.ewm(span=min(24 * 20, len(df)), adjust=False).mean()

    # MACD
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi   = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    # ATR
    tr  = pd.concat([high - low,
                     (high - close.shift()).abs(),
                     (low  - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    # ADX
    plus_dm  = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_di  = 100 * (plus_dm.ewm(span=14).mean() / atr.replace(0, 1e-10))
    minus_di = 100 * (minus_dm.ewm(span=14).mean() / atr.replace(0, 1e-10))
    dx       = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
    adx      = dx.ewm(span=14, adjust=False).mean()

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_width = (bb_upper - bb_lower) / sma20.replace(0, 1e-10)

    # FVG detection (Fair Value Gap)
    # Bullish FVG: candle[i-2].high < candle[i].low (gap de alta)
    # Bearish FVG: candle[i-2].low  > candle[i].high (gap de baixa)
    fvg_bull = bool(high.iloc[-3] < low.iloc[-1])  if len(df) >= 3 else False
    fvg_bear = bool(low.iloc[-3]  > high.iloc[-1]) if len(df) >= 3 else False

    # Swing High/Low (últimas 10 barras)
    lookback = min(10, len(df) - 1)
    swing_high = float(high.iloc[-lookback:].max())
    swing_low  = float(low.iloc[-lookback:].min())

    # Momentum: candle atual forte
    last = -1
    price     = float(close.iloc[last])
    candle_body = abs(price - float(open_.iloc[last]))
    candle_range = float(high.iloc[last]) - float(low.iloc[last])
    candle_momentum = candle_body / candle_range if candle_range > 0 else 0

    return {
        "price":        price,
        "ema9":         float(ema9.iloc[last]),
        "ema21":        float(ema21.iloc[last]),
        "ema50":        float(ema50.iloc[last]),
        "ema200":       float(ema200.iloc[last]),
        "ema_d1":       float(ema_d1.iloc[last]),
        "macd":         float(macd.iloc[last]),
        "macd_signal":  float(macd_signal.iloc[last]),
        "macd_bull":    float(macd.iloc[last]) > float(macd_signal.iloc[last]),
        "macd_bear":    float(macd.iloc[last]) < float(macd_signal.iloc[last]),
        "rsi":          float(rsi.iloc[last]),
        "adx":          float(adx.iloc[last]),
        "atr":          float(atr.iloc[last]),
        "bb_upper":     float(bb_upper.iloc[last]),
        "bb_lower":     float(bb_lower.iloc[last]),
        "bb_width":     float(bb_width.iloc[last]),
        "fvg_bull":     fvg_bull,
        "fvg_bear":     fvg_bear,
        "swing_high":   swing_high,
        "swing_low":    swing_low,
        "candle_bull":  price > float(open_.iloc[last]),
        "candle_bear":  price < float(open_.iloc[last]),
        "candle_momentum": candle_momentum,
        "plus_di":      float(plus_di.iloc[last]),
        "minus_di":     float(minus_di.iloc[last]),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE MELHORADO
# ═══════════════════════════════════════════════════════════════════════════════

def _confluence(res: dict, direction: str) -> tuple[int, int]:
    """
    Confluence com 10 critérios, pesos até 14 pontos.
    Inclui: tendência D1, FVG, MACD cruzamento, RSI zona, ADX, momentum de candle.
    """
    score = 0
    price = res["price"]

    if direction == "BUY":
        # Tendência macro (D1 aproximado) — peso 2
        if price > res["ema_d1"]:       score += 2

        # Tendência H1 (EMA200) — peso 2
        if price > res["ema200"]:       score += 2

        # Alinhamento EMA curto/médio — peso 1
        if res["ema9"] > res["ema21"] > res["ema50"]: score += 1

        # MACD acima da signal line (momentum) — peso 1
        if res["macd_bull"]:            score += 1

        # MACD positivo (tendência) — peso 1
        if res["macd"] > 0:             score += 1

        # RSI em zona saudável de alta (não sobrecomprado) — peso 1
        if 45 < res["rsi"] < 65:        score += 1

        # ADX mostra tendência — peso 2
        if res["adx"] >= Config.REGIME_ADX_TRENDING:
            score += 2
        elif res["adx"] >= Config.REGIME_ADX_RANGING:
            score += 1

        # +DI > -DI (direcionalidade bullish) — peso 1
        if res["plus_di"] > res["minus_di"]: score += 1

        # FVG bullish presente — peso 2
        if res["fvg_bull"]:             score += 2

        # Candle de alta com momentum — peso 1
        if res["candle_bull"] and res["candle_momentum"] > 0.5: score += 1

    else:  # SELL
        if price < res["ema_d1"]:       score += 2
        if price < res["ema200"]:       score += 2
        if res["ema9"] < res["ema21"] < res["ema50"]: score += 1
        if res["macd_bear"]:            score += 1
        if res["macd"] < 0:             score += 1
        if 35 < res["rsi"] < 55:        score += 1
        if res["adx"] >= Config.REGIME_ADX_TRENDING:
            score += 2
        elif res["adx"] >= Config.REGIME_ADX_RANGING:
            score += 1
        if res["minus_di"] > res["plus_di"]: score += 1
        if res["fvg_bear"]:             score += 2
        if res["candle_bear"] and res["candle_momentum"] > 0.5: score += 1

    return score, 15


# ═══════════════════════════════════════════════════════════════════════════════
# SL/TP BASEADO EM ESTRUTURA + ATR
# ═══════════════════════════════════════════════════════════════════════════════

def _structure_sl_tp(entry: float, direction: str, res: dict, atr: float
                     ) -> tuple[float, float]:
    """
    SL atrás do swing high/low real (+ buffer de 0.3 ATR).
    TP com RR mínimo de 1.8 a partir do SL real.
    """
    buffer = atr * 0.3
    min_rr = 1.8

    if direction == "BUY":
        sl = round(res["swing_low"] - buffer, 5)
        # Garante SL mínimo de 1 ATR abaixo da entrada
        if entry - sl < atr:
            sl = round(entry - atr, 5)
        dist = entry - sl
        tp   = round(entry + dist * min_rr, 5)
    else:
        sl = round(res["swing_high"] + buffer, 5)
        if sl - entry < atr:
            sl = round(entry + atr, 5)
        dist = sl - entry
        tp   = round(entry - dist * min_rr, 5)

    return sl, tp


# ═══════════════════════════════════════════════════════════════════════════════
# SPREAD / SLIPPAGE
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_spread_slippage(entry: float, direction: str, symbol: str) -> float:
    if not (Config.USE_SPREAD_MODEL or Config.USE_SLIPPAGE_MODEL):
        return entry
    pf   = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
    cost = 0.0
    if Config.USE_SPREAD_MODEL:
        cost += Config.SPREAD_PIPS.get(symbol, 1.0) * pf
    if Config.USE_SLIPPAGE_MODEL:
        cost += random.uniform(0, Config.SLIPPAGE_PIPS.get(symbol, 0.3)) * pf
    return round(entry + cost if direction == "BUY" else entry - cost, 5)


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest(
    bars:            list[Bar],
    symbol:          str,
    initial_balance: float | None = None,
    min_confluence:  int          = 7,
    warmup_bars:     int          = 60,
) -> BacktestResult:
    """
    Executa backtest sobre barras históricas com todos os filtros de qualidade.
    """
    initial_balance = float(initial_balance or Config.INITIAL_BALANCE)
    balance      = initial_balance
    trades:      list[dict]  = []
    active_trade: dict | None = None
    df_full      = bars_to_dataframe(bars)
    cooldown     = 0          # barras de cooldown após loss
    MAX_BARS_OPEN = 72        # força fechamento após 3 dias (evita trades eternos)

    for i in range(warmup_bars, len(bars)):
        bar   = bars[i]
        price = bar.close

        if cooldown > 0:
            cooldown -= 1

        # ── Gerencia trade ativo ──────────────────────────────────────────────
        if active_trade is not None:
            t         = active_trade
            bars_open = i - t["bar_open"]

            if t["dir"] == "BUY":
                hit_sl = bar.low  <= t["sl"]
                hit_tp = bar.high >= t["tp"]
            else:
                hit_sl = bar.high >= t["sl"]
                hit_tp = bar.low  <= t["tp"]

            # Força fechamento após MAX_BARS_OPEN
            if bars_open >= MAX_BARS_OPEN and not hit_tp:
                hit_sl = True

            if hit_sl or hit_tp:
                exit_price = t["tp"] if hit_tp else t["sl"]
                result     = "WIN" if hit_tp else "LOSS"
                pnl = calc_pnl_usd(
                    symbol, t["dir"], t["entry"], exit_price,
                    t["lot"], usdjpy_price=150.0
                ) - t.get("commission", 0)
                balance = round(balance + t["margin"] + pnl, 2)
                trades.append({
                    "symbol":       symbol,
                    "dir":          t["dir"],
                    "result":       result,
                    "pnl":          round(pnl, 2),
                    "entry":        t["entry"],
                    "exit":         exit_price,
                    "sl":           t["sl"],
                    "tp":           t["tp"],
                    "lot":          t["lot"],
                    "bars_open":    bars_open,
                    "opened_at":    t["opened_at"].isoformat(),
                    "closed_at":    bar.timestamp.isoformat(),
                    "closed_ts":    bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "score":        t["score"],
                })
                active_trade = None
                if result == "LOSS":
                    cooldown = 3   # pausa 3 barras após loss
            continue   # uma barra de cada vez — não reabre no mesmo candle

        # ── Filtros de qualidade ──────────────────────────────────────────────

        # 1. Sessão de maior liquidez
        if not _in_session(bar, symbol):
            continue

        # 2. Cooldown pós-loss
        if cooldown > 0:
            continue

        # 3. Calcula indicadores (janela deslizante de 250 barras)
        df_win = df_full.iloc[max(0, i - 250): i + 1]
        res    = _compute_indicators(df_win)
        if not res:
            continue

        atr = res["atr"]
        if atr <= 0:
            continue

        # 4. Mercado não pode estar em consolidação muito estreita
        if res["bb_width"] < 0.001:
            continue

        # ── Geração de sinal ──────────────────────────────────────────────────
        for direction in ("BUY", "SELL"):
            score, max_score = _confluence(res, direction)
            if score < min_confluence:
                continue

            entry        = _apply_spread_slippage(price, direction, symbol)
            sl, tp       = _structure_sl_tp(entry, direction, res, atr)

            # Valida SL/TP
            if direction == "BUY"  and (sl >= entry or tp <= entry): continue
            if direction == "SELL" and (sl <= entry or tp >= entry): continue

            dist = abs(entry - sl)
            if dist <= 0: continue

            rr = abs(tp - entry) / dist
            if rr < 1.5:   # RR mínimo absoluto
                continue

            # Position sizing
            try:
                from risk import calc_lot_for_risk
                lot, risk_usd, _ = calc_lot_for_risk(symbol, entry, sl, balance)
            except Exception:
                lot = Config.MIN_LOT

            cs     = Config.CONTRACT_SIZES.get("XAUUSD" if symbol == "XAUUSD" else "FOREX", 100000)
            margin = round(entry * lot * cs / Config.DEFAULT_LEVERAGE, 2)

            if margin > balance * 0.5 or margin <= 0:
                continue

            commission = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot

            balance -= margin
            active_trade = {
                "dir":        direction,
                "entry":      entry,
                "sl":         sl,
                "tp":         tp,
                "lot":        lot,
                "margin":     margin,
                "commission": commission,
                "bar_open":   i,
                "opened_at":  bar.timestamp,
                "score":      score,
            }
            break

    # Fecha trade ainda aberto ao fim dos dados (sem contabilizar como win/loss)
    if active_trade is not None:
        t   = active_trade
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close,
                            t["lot"], usdjpy_price=150.0) - t.get("commission", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol":    symbol, "dir": t["dir"], "result": "OPEN",
            "pnl":       round(pnl, 2), "entry": t["entry"],
            "exit":      bars[-1].close, "sl": t["sl"], "tp": t["tp"],
            "lot":       t["lot"], "bars_open": len(bars) - t["bar_open"],
            "opened_at": t["opened_at"].isoformat(),
            "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(),
            "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "score":     t["score"],
        })

    metrics = calculate_metrics_from_history(
        trades, initial_balance=initial_balance, current_balance=balance,
    )
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=metrics.pop("equity_curve", []),
        params={"symbol": symbol, "min_confluence": min_confluence},
    )


# ── Compatibilidade legado ────────────────────────────────────────────────────

def backtest_trades(trades: Iterable[dict], initial_balance: float | None = None) -> dict:
    return calculate_metrics_from_history(trades, initial_balance=initial_balance)


def backtest_from_strategy(
    bars:            list[Bar],
    strategy:        Callable[[list[Bar], int], list[dict]],
    initial_balance: float | None = None,
) -> dict:
    all_trades: list[dict] = []
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
    parser = argparse.ArgumentParser(description="Backtester Sniper Bot v2")
    parser.add_argument("csv",               help="CSV com OHLC histórico")
    parser.add_argument("--symbol",          default="EURUSD")
    parser.add_argument("--balance",         type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--min-confluence",  type=int,   default=7)
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido no CSV.")

    log(f"[BACKTEST] {len(bars)} barras | {bars[0].timestamp} → {bars[-1].timestamp}")
    result = run_backtest(bars, args.symbol, args.balance, args.min_confluence)
    m = result.metrics

    print("\n" + "═" * 50)
    print(f"  {args.symbol} · confluence≥{args.min_confluence}")
    print("═" * 50)
    print(f"  Trades:        {m['total_trades']} ({m['wins']}W / {m['losses']}L)")
    print(f"  Win Rate:      {m['winrate']}%")
    print(f"  Profit Factor: {m['profit_factor']}")
    print(f"  Max Drawdown:  {m['max_drawdown_pct']}%")
    print(f"  Sharpe:        {m.get('sharpe_ratio', 0)}")
    print(f"  P&L:           ${m['total_pnl']}")
    print("═" * 50 + "\n")


if __name__ == "__main__":
    main()
