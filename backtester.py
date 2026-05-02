"""
backtester.py — Backtester integrado com a estratégia real do bot.

Uso rápido (CSV com OHLC):
    python backtester.py EURUSD.csv --symbol EURUSD --balance 500

O backtester replica a lógica de calc_confluence + _get_smc_sl_tp do signals.py,
aplicando os mesmos filtros de confluência usados em produção.

Formato do CSV esperado:
    timestamp,open,high,low,close
    2024-01-02 00:00:00,1.09123,1.09200,...
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
# ESTRUTURAS DE DADOS
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
    """Carrega barras OHLC de um CSV. Aceita colunas em minúsculo ou maiúsculo."""
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
    """Converte lista de Bar para DataFrame no formato esperado por analysis.py."""
    records = [
        {
            "Open":  b.open,
            "High":  b.high,
            "Low":   b.low,
            "Close": b.close,
        }
        for b in bars
    ]
    idx = pd.to_datetime([b.timestamp for b in bars], utc=True)
    df  = pd.DataFrame(records, index=idx)
    df["Volume"] = 0.0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# INDICADORES TÉCNICOS (subset de analysis.py — sem chamada HTTP)
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_indicators(df: pd.DataFrame) -> dict | None:
    """Calcula indicadores técnicos em cima de um DataFrame de barras históricas."""
    if len(df) < 60:
        return None
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    ema9   = close.ewm(span=9,   adjust=False).mean()
    ema21  = close.ewm(span=21,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi   = 100 - 100 / (1 + gain / loss.replace(0, 1e-10))

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    # ADX
    plus_dm  = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_di  = 100 * (plus_dm.ewm(span=14).mean()  / atr.replace(0, 1e-10))
    minus_di = 100 * (minus_dm.ewm(span=14).mean() / atr.replace(0, 1e-10))
    dx       = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
    adx      = dx.ewm(span=14, adjust=False).mean()

    # Bollinger Bands (20,2)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20

    last = -1
    price = float(close.iloc[last])

    return {
        "price":     price,
        "ema9":      float(ema9.iloc[last]),
        "ema21":     float(ema21.iloc[last]),
        "ema200":    float(ema200.iloc[last]),
        "macd_bull": float(macd.iloc[last]) > 0,
        "macd_bear": float(macd.iloc[last]) < 0,
        "rsi":       float(rsi.iloc[last]),
        "adx":       float(adx.iloc[last]),
        "atr":       float(atr.iloc[last]),
        "upper":     float(upper.iloc[last]),
        "lower":     float(lower.iloc[last]),
        "candle_bull": (price - float(df["Open"].iloc[last])) > 0,
        "candle_bear": (price - float(df["Open"].iloc[last])) < 0,
        # Sem FVG/OB/sweep no backtester simplificado (dados OHLC apenas)
        "fvg":   {"bullish": [], "bearish": []},
        "ob":    {"bullish": [], "bearish": []},
        "sweep": {"bullish": False, "bearish": False,
                  "swing_high": float(high.rolling(10).max().iloc[last]),
                  "swing_low":  float(low.rolling(10).min().iloc[last])},
        "symbol": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ESTRATÉGIA REAL — REPLICA signals.calc_confluence
# ═══════════════════════════════════════════════════════════════════════════════

def _simple_confluence(res: dict, direction: str) -> tuple[int, int]:
    """
    Versão simplificada do calc_confluence (sem dados SMC que dependem de OHLC completo).
    Retorna (score, max_score).
    """
    score = 0
    price = res["price"]

    if direction == "BUY":
        if price > res["ema200"]:   score += 2
        if res["ema9"] > res["ema21"]: score += 1
        if res["macd_bull"]:        score += 1
        if 40 < res["rsi"] < 68:   score += 1
        if res["adx"] >= Config.REGIME_ADX_TRENDING: score += 2
        if price < res["lower"] * 1.01: score += 1
        if res["candle_bull"]:      score += 1
    else:
        if price < res["ema200"]:   score += 2
        if res["ema9"] < res["ema21"]: score += 1
        if res["macd_bear"]:        score += 1
        if 32 < res["rsi"] < 60:   score += 1
        if res["adx"] >= Config.REGIME_ADX_TRENDING: score += 2
        if price > res["upper"] * 0.99: score += 1
        if res["candle_bear"]:      score += 1

    return score, 11


def _atr_sl_tp(entry: float, direction: str, atr: float) -> tuple[float, float]:
    """SL/TP baseado em ATR (fallback simples)."""
    mult_sl = Config.ATR_SL_MULT
    mult_tp = Config.ATR_TP_MULT
    if direction == "BUY":
        return round(entry - atr * mult_sl, 5), round(entry + atr * mult_tp, 5)
    return round(entry + atr * mult_sl, 5), round(entry - atr * mult_tp, 5)


def _lot_for_risk(entry: float, sl: float, balance: float, symbol: str) -> float:
    """Calcula lote para 2% de risco (Turtle sizing simplificado)."""
    from risk import calc_lot_for_risk
    lot, _, _ = calc_lot_for_risk(symbol, entry, sl, balance)
    return lot


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR DE BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_spread_slippage(entry: float, direction: str, symbol: str) -> float:
    """Aplica spread + slippage simulado na entrada (mesma lógica do bot.py)."""
    if not (Config.USE_SPREAD_MODEL or Config.USE_SLIPPAGE_MODEL):
        return entry
    pf = 0.01 if (is_jpy_pair(symbol) or symbol == "XAUUSD") else 0.0001
    cost = 0.0
    if Config.USE_SPREAD_MODEL:
        cost += Config.SPREAD_PIPS.get(symbol, 1.0) * pf
    if Config.USE_SLIPPAGE_MODEL:
        cost += random.uniform(0, Config.SLIPPAGE_PIPS.get(symbol, 0.3)) * pf
    return round(entry + cost if direction == "BUY" else entry - cost, 5)


def run_backtest(
    bars:            list[Bar],
    symbol:          str,
    initial_balance: float | None = None,
    min_confluence:  int          = 6,
    warmup_bars:     int          = 60,
) -> BacktestResult:
    """
    Executa backtest da estratégia real sobre barras históricas.

    Para cada barra, reconstrói o DataFrame de janela deslizante,
    calcula indicadores e aplica as mesmas regras de confluência do signals.py.
    """
    initial_balance = float(initial_balance or Config.INITIAL_BALANCE)
    balance = initial_balance
    trades:        list[dict] = []
    active_trade:  dict | None = None
    df_full = bars_to_dataframe(bars)

    for i in range(warmup_bars, len(bars)):
        bar     = bars[i]
        df_win  = df_full.iloc[max(0, i - 300): i + 1]
        res     = _compute_indicators(df_win)
        if not res:
            continue

        price = res["price"]
        atr   = res["atr"]

        # ── Gerenciamento do trade ativo ──────────────────────────────────────
        if active_trade is not None:
            t = active_trade
            if t["dir"] == "BUY":
                hit_sl = price <= t["sl"]
                hit_tp = price >= t["tp"]
            else:
                hit_sl = price >= t["sl"]
                hit_tp = price <= t["tp"]

            if hit_sl or hit_tp:
                result = "WIN" if hit_tp else "LOSS"
                pnl    = calc_pnl_usd(
                    symbol, t["dir"], t["entry"], price,
                    t["lot"], usdjpy_price=150.0
                ) - t.get("commission", 0)
                balance = round(balance + t["margin"] + pnl, 2)
                trades.append({
                    "symbol":    symbol,
                    "dir":       t["dir"],
                    "result":    result,
                    "pnl":       round(pnl, 2),
                    "entry":     t["entry"],
                    "exit":      price,
                    "sl":        t["sl"],
                    "tp":        t["tp"],
                    "lot":       t["lot"],
                    "opened_at": t["opened_at"].isoformat(),
                    "closed_at": bar.timestamp.isoformat(),
                    "closed_ts": bar.timestamp.timestamp(),
                    "closed_ts_iso": bar.timestamp.isoformat(),
                    "adx":       res["adx"],
                    "atr":       atr,
                })
                active_trade = None
            continue  # não abre novo trade enquanto há um ativo

        # ── Geração de sinal ──────────────────────────────────────────────────
        for direction in ("BUY", "SELL"):
            score, max_score = _simple_confluence(res, direction)
            if score < min_confluence:
                continue

            entry = _apply_spread_slippage(price, direction, symbol)
            sl, tp = _atr_sl_tp(entry, direction, atr)
            rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
            if rr < Config.REGIME_MIN_RR.get("neutral", 1.8):
                continue

            lot     = _lot_for_risk(entry, sl, balance, symbol)
            margin  = round(entry * lot * Config.CONTRACT_SIZES.get("FOREX", 100000)
                            / Config.DEFAULT_LEVERAGE, 2)
            commission = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot

            if margin > balance * 0.8:
                continue

            balance -= margin
            active_trade = {
                "dir":       direction,
                "entry":     entry,
                "sl":        sl,
                "tp":        tp,
                "lot":       lot,
                "margin":    margin,
                "commission": commission,
                "opened_at": bar.timestamp,
                "score":     score,
            }
            break  # só um sinal por barra

    metrics = calculate_metrics_from_history(
        trades,
        initial_balance=initial_balance,
        current_balance=balance,
    )
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=metrics.pop("equity_curve", []),
        params={"symbol": symbol, "min_confluence": min_confluence},
    )


# ── Compatibilidade com código legado ─────────────────────────────────────────

def backtest_trades(trades: Iterable[dict], initial_balance: float | None = None) -> dict:
    return calculate_metrics_from_history(trades, initial_balance=initial_balance)


def backtest_from_strategy(
    bars:            list[Bar],
    strategy:        Callable[[list[Bar], int], list[dict]],
    initial_balance: float | None = None,
) -> dict:
    """
    Estratégia recebe (bars, index_atual) e retorna lista de trades fechados.
    Cada trade deve ter ao menos: result, pnl, symbol, dir, closed_at.
    """
    all_trades: list[dict] = []
    for i in range(1, len(bars)):
        generated = strategy(bars, i) or []
        for trade in generated:
            trade = dict(trade)
            trade.setdefault("closed_at", bars[i].timestamp.isoformat())
            all_trades.append(trade)
    return calculate_metrics_from_history(all_trades, initial_balance=initial_balance)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Backtester integrado do Sniper Bot")
    parser.add_argument("csv",       help="Arquivo CSV com OHLC (timestamp,open,high,low,close)")
    parser.add_argument("--symbol",  default="EURUSD", help="Símbolo (ex: EURUSD, XAUUSD)")
    parser.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE,
                        help="Saldo inicial para simulação")
    parser.add_argument("--min-confluence", type=int, default=6,
                        help="Score mínimo de confluência para abrir trade")
    args = parser.parse_args()

    log(f"[BACKTEST] Carregando {args.csv}...")
    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("[BACKTEST] Nenhum candle válido encontrado no CSV.")

    log(f"[BACKTEST] {len(bars)} barras | {bars[0].timestamp} → {bars[-1].timestamp}")
    log(f"[BACKTEST] Símbolo: {args.symbol} | Saldo: ${args.balance} | Min confluence: {args.min_confluence}")

    result = run_backtest(
        bars,
        symbol=args.symbol,
        initial_balance=args.balance,
        min_confluence=args.min_confluence,
    )

    m = result.metrics
    print("\n" + "═" * 50)
    print(f"  RESULTADO DO BACKTEST — {args.symbol}")
    print("═" * 50)
    print(f"  Trades:          {m['total_trades']} ({m['wins']}W / {m['losses']}L)")
    print(f"  Win Rate:        {m['winrate']}%")
    print(f"  Profit Factor:   {m['profit_factor']}")
    print(f"  Expectancy:      ${m['expectancy']}")
    print(f"  Max Drawdown:    {m['max_drawdown_pct']}%")
    print(f"  Sharpe Ratio:    {m['sharpe_ratio']}")
    print(f"  Saldo inicial:   ${m['initial_balance']}")
    print(f"  Saldo final:     ${m['current_balance']}")
    print(f"  P&L total:       ${m['total_pnl']}")
    print("═" * 50 + "\n")


if __name__ == "__main__":
    main()
