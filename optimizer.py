"""
optimizer.py — Grid search de parâmetros com indicadores pré-computados.

Uso:
    python optimizer.py                        # gera dados sintéticos
    python optimizer.py caminho/para/dados.csv # usa CSV real
"""

from __future__ import annotations
import sys, time, math, itertools
import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

# ── Importa estruturas do bot ──────────────────────────────────────────────────
sys.path.insert(0, ".")
from backtester import (
    Bar, load_bars_from_csv, bars_to_dataframe,
    detect_timeframe, resample_to_h1,
    _apply_cost, _sl_tp, _in_session,
    calc_pnl_usd,
)
from performance import calculate_metrics_from_history
from config import Config


# ══════════════════════════════════════════════════════════════════════════════
# 1. Pré-computação vetorial de todos os indicadores
# ══════════════════════════════════════════════════════════════════════════════

def precompute_all(bars: list[Bar]) -> dict[str, np.ndarray]:
    """
    Calcula TODOS os indicadores uma única vez sobre o DataFrame completo.
    Retorna arrays numpy indexados por posição de barra.
    ~50x mais rápido do que recalcular por barra.
    """
    df = bars_to_dataframe(bars)
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    o = df["Open"]
    n = len(df)

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

    tr      = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr     = tr.ewm(span=14, adjust=False).mean()
    atr_s   = atr.replace(0, 1e-10)

    up_move   = h.diff()
    down_move = -l.diff()
    plus_dm   = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm  = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)
    plus_di   = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr_s
    minus_di  = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr_s
    adx_raw   = ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100)
    adx       = adx_raw.ewm(span=14, adjust=False).mean()

    bb_mid   = c.rolling(20).mean()
    bb_std   = c.rolling(20).std(ddof=0).fillna(0)
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    REGIME_ADX_RANGING  = getattr(Config, "REGIME_ADX_RANGING",  18)
    REGIME_ADX_TRENDING = getattr(Config, "REGIME_ADX_TRENDING", 25)

    c_arr   = c.to_numpy(dtype=float)
    o_arr   = o.to_numpy(dtype=float)
    e9_arr  = ema9.to_numpy(dtype=float)
    e21_arr = ema21.to_numpy(dtype=float)
    e50_arr = ema50.to_numpy(dtype=float)
    e200_arr= ema200.to_numpy(dtype=float)
    atr_arr = atr.to_numpy(dtype=float)
    adx_arr = adx.to_numpy(dtype=float)
    pdi_arr = plus_di.to_numpy(dtype=float)
    ndi_arr = minus_di.to_numpy(dtype=float)
    rsi_arr = rsi.to_numpy(dtype=float)
    ml_arr  = macd_line.to_numpy(dtype=float)
    ms_arr  = macd_signal.to_numpy(dtype=float)
    bbu_arr = bb_upper.to_numpy(dtype=float)
    bbl_arr = bb_lower.to_numpy(dtype=float)
    bbm_arr = bb_mid.to_numpy(dtype=float)

    # Campos derivados (todos vetorizados)
    trend_up = (c_arr > e200_arr) & (e21_arr > e50_arr)
    trend_dn = (c_arr < e200_arr) & (e21_arr < e50_arr)
    rsi_prev = np.roll(rsi_arr, 1); rsi_prev[0] = rsi_arr[0]
    ml_prev  = np.roll(ml_arr,  1); ml_prev[0]  = ml_arr[0]
    ms_prev  = np.roll(ms_arr,  1); ms_prev[0]  = ms_arr[0]

    dist_e21    = np.where(atr_arr > 0, (c_arr - e21_arr) / atr_arr, 0.0)
    dist_bb_up  = np.where(atr_arr > 0, (bbu_arr - c_arr) / atr_arr, 0.0)
    dist_bb_dn  = np.where(atr_arr > 0, (c_arr - bbl_arr) / atr_arr, 0.0)
    candle_bull = c_arr > o_arr
    candle_bear = c_arr < o_arr
    macd_above  = ml_arr > ms_arr
    macd_below  = ml_arr < ms_arr
    macd_xup    = (ml_prev <= ms_prev) & (ml_arr > ms_arr)
    macd_xdn    = (ml_prev >= ms_prev) & (ml_arr < ms_arr)
    rsi_bup     = (rsi_prev < 42) & (rsi_arr >= 42)
    rsi_bdn     = (rsi_prev > 58) & (rsi_arr <= 58)
    range_mode  = adx_arr <= REGIME_ADX_RANGING
    trend_mode  = adx_arr >= REGIME_ADX_TRENDING

    return {
        "price":      c_arr,
        "open":       o_arr,
        "atr":        atr_arr,
        "adx":        adx_arr,
        "pdi":        pdi_arr,
        "ndi":        ndi_arr,
        "rsi":        rsi_arr,
        "trend_up":   trend_up,
        "trend_dn":   trend_dn,
        "dist_e21":   dist_e21,
        "dist_bb_up": dist_bb_up,
        "dist_bb_dn": dist_bb_dn,
        "candle_bull":candle_bull,
        "candle_bear":candle_bear,
        "macd_xup":   macd_xup,
        "macd_xdn":   macd_xdn,
        "rsi_bup":    rsi_bup,
        "rsi_bdn":    rsi_bdn,
        "range_mode": range_mode,
        "trend_mode": trend_mode,
        "macd_above": macd_above,
        "macd_below": macd_below,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. Backtest rápido usando arrays pré-computados
# ══════════════════════════════════════════════════════════════════════════════

def _score_combo(
    bars: list[Bar],
    pre: dict[str, np.ndarray],
    symbol: str,
    initial_balance: float,
    min_confluence: int,
    adx_min: float,
    atr_sl_mult: float,
    atr_tp_mult: float,
    risk_pct: float,
    weekly_trade_target: float,
    max_bars_in_trade: int,
    warmup: int = 80,
) -> dict:
    """Backtest sobre arrays pré-computados — sem recalcular indicadores."""

    REGIME_ADX_RANGING  = getattr(Config, "REGIME_ADX_RANGING",  18)
    REGIME_ADX_TRENDING = getattr(Config, "REGIME_ADX_TRENDING", 25)
    pull_lo, pull_hi = -1.0, 2.0  # pull-range H1 padrão

    balance = initial_balance
    active  = None
    cooldown = 0
    trades: list[dict] = []

    n = len(bars)
    p  = pre

    for i in range(warmup, n):
        bar = bars[i]
        atr_val = float(p["atr"][i])
        adx_val = float(p["adx"][i])

        # ── Gerencia trade aberto ─────────────────────────────────────────────
        if active is not None:
            t = active
            bars_open = i - t["bar_i"]
            hit_sl = (bar.low  <= t["sl"]) if t["dir"] == "BUY" else (bar.high >= t["sl"])
            hit_tp = (bar.high >= t["tp"]) if t["dir"] == "BUY" else (bar.low  <= t["tp"])
            if hit_sl and hit_tp:
                hit_tp = False

            force = bars_open >= max_bars_in_trade
            if hit_sl or hit_tp or force:
                exit_px = bar.close if force and not hit_sl and not hit_tp else (t["tp"] if hit_tp else t["sl"])
                pnl     = calc_pnl_usd(symbol, t["dir"], t["entry"], exit_px, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
                result  = "WIN" if (hit_tp or (force and pnl > 0)) else "LOSS"
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
                    "adx": adx_val, "timeframe": "H1",
                })
                active = None
                if result == "LOSS":
                    cooldown = 2
            continue

        if cooldown > 0:
            cooldown -= 1
            continue

        if not _in_session(bar, symbol):
            continue

        if atr_val <= 0:
            continue

        # ── Regime ───────────────────────────────────────────────────────────
        trend_up = bool(p["trend_up"][i])
        trend_dn = bool(p["trend_dn"][i])

        if adx_val >= REGIME_ADX_TRENDING and (trend_up or trend_dn):
            regime = "trend"
        elif adx_val <= REGIME_ADX_RANGING:
            regime = "range"
        else:
            regime = "transition"

        # ── Sinal ─────────────────────────────────────────────────────────────
        d21      = float(p["dist_e21"][i])
        rsi_v    = float(p["rsi"][i])
        adx_ok   = adx_val >= adx_min

        def pull_ok_buy():  return pull_lo <= d21 <= pull_hi
        def pull_ok_sell(): return -pull_hi <= d21 <= -pull_lo

        macd_xup = bool(p["macd_xup"][i])
        macd_xdn = bool(p["macd_xdn"][i])
        rsi_bup  = bool(p["rsi_bup"][i])
        rsi_bdn  = bool(p["rsi_bdn"][i])
        cbull    = bool(p["candle_bull"][i])
        cbear    = bool(p["candle_bear"][i])
        pdi_gt   = float(p["pdi"][i]) >= float(p["ndi"][i])

        direction: str | None = None

        if regime in ("trend", "transition"):
            if trend_up:
                trigger = macd_xup or rsi_bup
                score = sum([trend_up, pull_ok_buy(), trigger, cbull, adx_ok, pdi_gt, rsi_v >= 40, rsi_v <= 70])
                if score >= min_confluence and pull_ok_buy() and trigger:
                    direction = "BUY"
            if trend_dn and direction is None:
                trigger = macd_xdn or rsi_bdn
                score = sum([trend_dn, pull_ok_sell(), trigger, cbear, adx_ok, not pdi_gt, rsi_v <= 60, rsi_v >= 30])
                if score >= min_confluence and pull_ok_sell() and trigger:
                    direction = "SELL"

        if direction is None and regime in ("range",):
            dist_bu = float(p["dist_bb_up"][i])
            dist_bd = float(p["dist_bb_dn"][i])
            if dist_bu > 0.3 and cbull and (macd_xup or rsi_bup) and rsi_v < 65:
                score = sum([dist_bu > 0.3, cbull, macd_xup or rsi_bup, rsi_v < 65])
                if score >= min(min_confluence, 3):
                    direction = "BUY"
            if direction is None and dist_bd > 0.3 and cbear and (macd_xdn or rsi_bdn) and rsi_v > 35:
                score = sum([dist_bd > 0.3, cbear, macd_xdn or rsi_bdn, rsi_v > 35])
                if score >= min(min_confluence, 3):
                    direction = "SELL"

        # Light frequency: regime=transition, target alto
        if direction is None and weekly_trade_target >= 3.0 and regime == "transition":
            if trend_up and macd_xup and adx_val >= max(14.0, adx_min - 2):
                direction = "BUY"
            elif trend_dn and macd_xdn and adx_val >= max(14.0, adx_min - 2):
                direction = "SELL"

        if direction is None:
            continue

        # ── Entrada ───────────────────────────────────────────────────────────
        entry  = _apply_cost(bar.close, direction, symbol)
        sl, tp = _sl_tp(entry, direction, atr_val, atr_sl_mult=atr_sl_mult, atr_tp_mult=atr_tp_mult)

        if direction == "BUY"  and (sl >= entry or tp <= entry): continue
        if direction == "SELL" and (sl <= entry or tp >= entry): continue

        cs         = 100 if symbol == "XAUUSD" else 100_000
        sl_dist    = abs(entry - sl)
        max_risk   = balance * max(0.1, risk_pct) / 100.0
        if sl_dist <= 0: continue

        lot    = max(Config.MIN_LOT, round(min(max_risk / (sl_dist * cs), 50.0), 2))
        margin = round(entry * lot * cs / Config.DEFAULT_LEVERAGE, 2)
        if margin <= 0 or margin > balance * 0.45 or margin > balance: continue

        comm    = Config.COMMISSION_PER_LOT.get("FOREX", 6.0) * lot
        balance -= margin

        active = {
            "dir": direction, "entry": entry, "sl": sl, "tp": tp,
            "lot": lot, "margin": margin, "comm": comm,
            "bar_i": i, "opened_at": bar.timestamp, "adx": adx_val,
        }

    # Fecha trade aberto no fim
    if active is not None:
        t = active
        pnl = calc_pnl_usd(symbol, t["dir"], t["entry"], bars[-1].close, t["lot"], usdjpy_price=150.0) - t.get("comm", 0)
        balance = round(balance + t["margin"] + pnl, 2)
        trades.append({
            "symbol": symbol, "dir": t["dir"],
            "result": "WIN" if pnl > 0 else "LOSS",
            "pnl": round(pnl, 2), "entry": t["entry"], "exit": bars[-1].close,
            "sl": t["sl"], "tp": t["tp"], "lot": t["lot"],
            "bars_open": n - t["bar_i"],
            "opened_at": t["opened_at"].isoformat(),
            "closed_at": bars[-1].timestamp.isoformat(),
            "closed_ts": bars[-1].timestamp.timestamp(),
            "closed_ts_iso": bars[-1].timestamp.isoformat(),
            "adx": 0.0, "timeframe": "H1",
        })

    m = calculate_metrics_from_history(trades, initial_balance=initial_balance, current_balance=balance)
    pnl_total  = balance - initial_balance
    pf         = float(m.get("profit_factor", 0) or 0)
    wr         = float(m.get("win_rate", 0) or 0)
    dd         = float(m.get("max_drawdown_pct", 0) or 0)
    sharpe     = float(m.get("sharpe_ratio", 0) or 0)
    n_trades   = len(trades)

    # Score composto: prioriza profit factor e drawdown controlado
    if n_trades >= 10 and dd < 50:
        score = pf * (wr / 100) * (1 - dd / 100) * min(sharpe, 3.0) if sharpe > 0 else pf * (wr / 100) * (1 - dd / 100)
    else:
        score = 0.0

    return {
        "min_confluence":    min_confluence,
        "adx_min":           adx_min,
        "atr_sl_mult":       atr_sl_mult,
        "atr_tp_mult":       atr_tp_mult,
        "risk_pct":          risk_pct,
        "weekly_trade_target": weekly_trade_target,
        "n_trades":          n_trades,
        "win_rate":          wr,
        "profit_factor":     round(pf, 2),
        "max_drawdown":      round(dd, 1),
        "sharpe":            round(sharpe, 2),
        "pnl":               round(pnl_total, 2),
        "score":             round(score, 4),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. Grid search
# ══════════════════════════════════════════════════════════════════════════════

GRID = {
    "min_confluence":      [3, 4, 5, 6],
    "adx_min":             [15.0, 18.0, 22.0, 26.0],
    "atr_sl_mult":         [1.0, 1.5, 2.0, 2.5],
    "atr_tp_mult":         [2.0, 3.0, 4.0, 5.0],
    "risk_pct":            [1.0, 2.0, 3.0],
    "weekly_trade_target": [2.0, 3.0, 5.0],
}

def run_grid(
    bars: list[Bar],
    symbol: str = "EURUSD",
    initial_balance: float = 150.0,
    top_n: int = 10,
) -> list[dict]:

    tf = detect_timeframe(bars)
    if tf in ("M1", "M5", "M15"):
        print(f"  Resampleando {len(bars)} candles {tf} → H1...")
        bars = resample_to_h1(bars)

    print(f"  Pré-computando indicadores sobre {len(bars)} candles H1...")
    t0 = time.time()
    pre = precompute_all(bars)
    print(f"  Indicadores prontos em {time.time()-t0:.1f}s")

    combos = list(itertools.product(*GRID.values()))
    keys   = list(GRID.keys())
    total  = len(combos)
    print(f"  Testando {total} combinações...\n")

    results = []
    t_start = time.time()
    for idx, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        r = _score_combo(
            bars, pre, symbol, initial_balance,
            min_confluence     = params["min_confluence"],
            adx_min            = params["adx_min"],
            atr_sl_mult        = params["atr_sl_mult"],
            atr_tp_mult        = params["atr_tp_mult"],
            risk_pct           = params["risk_pct"],
            weekly_trade_target= params["weekly_trade_target"],
            max_bars_in_trade  = 60,
        )
        results.append(r)

        if idx % 100 == 0 or idx == total:
            elapsed  = time.time() - t_start
            eta      = elapsed / idx * (total - idx)
            best_pf  = max((x["profit_factor"] for x in results if x["n_trades"] >= 10), default=0)
            print(f"  [{idx}/{total}] {elapsed:.0f}s decorridos | ETA ~{eta:.0f}s | melhor PF até agora: {best_pf:.2f}")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Relatório
# ══════════════════════════════════════════════════════════════════════════════

def print_report(top: list[dict], symbol: str, initial_balance: float) -> None:
    sep = "═" * 72

    print(f"\n{sep}")
    print(f"  🏆  TOP {len(top)} CONFIGURAÇÕES — {symbol}  (saldo inicial: ${initial_balance:.2f})")
    print(sep)
    header = f"{'#':>2}  {'Conf':>4}  {'ADX':>4}  {'SL×':>4}  {'TP×':>4}  {'Risk':>4}  {'Wkly':>4}  {'Trd':>4}  {'WR%':>5}  {'PF':>5}  {'DD%':>5}  {'Sharpe':>6}  {'P&L':>7}  Score"
    print(header)
    print("─" * 72)
    for rank, r in enumerate(top, 1):
        wr_icon = "✅" if r["win_rate"] >= 50 else "⚠️ "
        pf_icon = "✅" if r["profit_factor"] >= 1.5 else "⚠️ "
        print(
            f"{rank:>2}  "
            f"{r['min_confluence']:>4}  "
            f"{r['adx_min']:>4.0f}  "
            f"{r['atr_sl_mult']:>4.1f}  "
            f"{r['atr_tp_mult']:>4.1f}  "
            f"{r['risk_pct']:>4.0f}%  "
            f"{r['weekly_trade_target']:>4.0f}  "
            f"{r['n_trades']:>4}  "
            f"{r['win_rate']:>5.1f}  "
            f"{r['profit_factor']:>5.2f}  "
            f"{r['max_drawdown']:>5.1f}  "
            f"{r['sharpe']:>6.2f}  "
            f"${r['pnl']:>+7.2f}  "
            f"{r['score']:.4f}"
        )
    print(f"\n{sep}")
    best = top[0]
    print("  🥇  MELHOR CONFIGURAÇÃO:")
    print(f"      min_confluence      = {best['min_confluence']}")
    print(f"      adx_min             = {best['adx_min']:.0f}")
    print(f"      atr_sl_mult         = {best['atr_sl_mult']}")
    print(f"      atr_tp_mult         = {best['atr_tp_mult']}")
    print(f"      risk_pct            = {best['risk_pct']:.0f}%")
    print(f"      weekly_trade_target = {best['weekly_trade_target']:.0f}")
    print(f"\n      Resultado: {best['n_trades']} trades  |  WR {best['win_rate']:.1f}%  |  PF {best['profit_factor']:.2f}  |  DD {best['max_drawdown']:.1f}%  |  P&L ${best['pnl']:+.2f}")
    print(sep)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Gerador de dados sintéticos (para testes sem CSV)
# ══════════════════════════════════════════════════════════════════════════════

def _synthetic_bars(n: int = 322638, seed: int = 42) -> list[Bar]:
    """Gera candles M1 sintéticos com tendências e reversões realistas."""
    import random
    random.seed(seed)
    price = 1.07
    bars  = []
    ts    = datetime(2023, 1, 1, tzinfo=timezone.utc)
    drift = 0.0
    for i in range(n):
        if i % 5000 == 0:
            drift = random.uniform(-0.0002, 0.0002)
        o = price
        h = o + random.uniform(0, 0.0010)
        l = o - random.uniform(0, 0.0010)
        c = random.uniform(l, h) + drift
        c = max(l, min(h, c))
        bars.append(Bar(timestamp=ts, open=o, high=h, low=l, close=c))
        price = c
        ts   += timedelta(minutes=1)
    return bars


# ══════════════════════════════════════════════════════════════════════════════
# 6. Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    SYMBOL          = "EURUSD"
    INITIAL_BALANCE = 150.0

    csv_path = sys.argv[1] if len(sys.argv) > 1 else None

    print("\n" + "═" * 60)
    print("  OTIMIZADOR DE PARÂMETROS — EURUSD")
    print("═" * 60)

    if csv_path:
        print(f"\n  Carregando {csv_path}...")
        bars = load_bars_from_csv(csv_path)
        print(f"  {len(bars)} candles carregados  (TF={detect_timeframe(bars)})")
    else:
        print("\n  [Modo demo] Gerando dados sintéticos M1 (322 638 candles)...")
        bars = _synthetic_bars()
        print(f"  {len(bars)} candles gerados")

    t0  = time.time()
    top = run_grid(bars, symbol=SYMBOL, initial_balance=INITIAL_BALANCE)
    print(f"\n  Grid concluído em {time.time()-t0:.1f}s")
    print_report(top, SYMBOL, INITIAL_BALANCE)
