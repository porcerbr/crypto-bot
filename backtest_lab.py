"""
backtest_lab.py — laboratório de backtest multi-anos e busca de configuração.

Uso:
    python backtest_lab.py dados/EURUSD_M15.csv --symbol EURUSD --balance 1000 --grid quick --top 20 --out reports

Objetivo:
- Rodar várias configurações da estratégia sobre anos de candles OHLC.
- Comparar retorno, drawdown, profit factor, frequência e consistência anual.
- Salvar ranking em CSV/JSON para você escolher configurações menos superajustadas.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from backtester import Bar, BacktestResult, detect_timeframe, load_bars_from_csv, run_backtest
from performance import calculate_metrics_from_history


@dataclass
class LabCandidate:
    rank: int
    score: float
    params: dict
    metrics: dict
    trades: list[dict] = field(default_factory=list)
    valid: bool = False


@dataclass
class LabResult:
    symbol: str
    timeframe: str
    bars: int
    start: str | None
    end: str | None
    tested: int
    ranking: list[LabCandidate]
    yearly_best: list[dict]
    qualified: int = 0

    @property
    def best(self) -> LabCandidate | None:
        return self.ranking[0] if self.ranking else None


def _frange(values: Iterable[float]) -> list[float]:
    return [round(float(v), 4) for v in values]


def generate_param_grid(grid: str = "quick") -> list[dict]:
    """Retorna uma lista de configurações. `quick` é rápida; `deep` busca mais amplo."""
    grid = (grid or "quick").lower().strip()
    if grid not in {"quick", "deep"}:
        raise ValueError("grid deve ser 'quick' ou 'deep'")

    if grid == "quick":
        space = {
            "min_confluence": [6, 7],
            "adx_min": [22, 26],
            "atr_sl_mult": [1.0, 1.25],
            "atr_tp_mult": [2.0, 2.5, 3.0],
            "risk_pct": [0.25, 0.5],
            "rsi_ob": [64, 66],
            "rsi_os": [34, 36],
            "max_bars_in_trade": [12, 20],
        }
    else:
        space = {
            "min_confluence": [6, 7, 8, 9],
            "adx_min": [20, 22, 24, 28],
            "atr_sl_mult": [0.9, 1.0, 1.2, 1.5],
            "atr_tp_mult": [2.0, 2.5, 3.0, 3.5],
            "risk_pct": [0.25, 0.5, 0.75],
            "rsi_ob": [62, 64, 66],
            "rsi_os": [34, 36, 38],
            "max_bars_in_trade": [10, 16, 24, 32],
        }

    keys = list(space.keys())
    combos = []
    for vals in itertools.product(*(space[k] for k in keys)):
        combos.append(dict(zip(keys, vals)))
    return combos


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "inf"):
            return default if value != "inf" else 99.0
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _year_from_trade(trade: dict) -> int | None:
    for key in ("closed_at", "closed_ts_iso", "opened_at"):
        raw = trade.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).year
        except Exception:
            continue
    return None


def yearly_metrics(trades: list[dict], initial_balance: float) -> list[dict]:
    grouped: dict[int, list[dict]] = {}
    for trade in trades:
        year = _year_from_trade(trade)
        if year is None:
            continue
        grouped.setdefault(year, []).append(trade)

    rows: list[dict] = []
    for year in sorted(grouped):
        metrics = calculate_metrics_from_history(grouped[year], initial_balance=initial_balance)
        rows.append({
            "year": year,
            "trades": metrics.get("total_trades", 0),
            "wins": metrics.get("wins", 0),
            "losses": metrics.get("losses", 0),
            "winrate": metrics.get("winrate", 0),
            "total_pnl": metrics.get("total_pnl", 0),
            "return_pct": metrics.get("return_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "profit_factor": metrics.get("profit_factor", 0),
        })
    return rows


def candidate_is_robust(metrics: dict, yearly: list[dict]) -> bool:
    trades = _safe_float(metrics.get("total_trades"))
    wr = _safe_float(metrics.get("winrate"))
    pf = _safe_float(metrics.get("profit_factor"))
    dd = _safe_float(metrics.get("max_drawdown_pct"))
    ret = _safe_float(metrics.get("return_pct"))
    if trades < 25:
        return False
    if wr < 45:
        return False
    if pf < 1.05:
        return False
    if dd > 25:
        return False
    if ret <= 0:
        return False
    losing_years = sum(1 for y in yearly if _safe_float(y.get("total_pnl")) < 0)
    return losing_years <= max(1, len(yearly) // 3)


def score_candidate(metrics: dict, yearly: list[dict]) -> float:
    """
    Score conservador + penalidade forte para estratégias que não passam no filtro.
    """
    ret = _safe_float(metrics.get("return_pct"))
    dd = _safe_float(metrics.get("max_drawdown_pct"))
    pf = min(_safe_float(metrics.get("profit_factor"), 0.0), 5.0)
    trades = _safe_float(metrics.get("total_trades"))
    wr = _safe_float(metrics.get("winrate"))
    freq = _safe_float(metrics.get("trade_frequency_per_week"))

    losing_years = sum(1 for y in yearly if _safe_float(y.get("total_pnl")) < 0)
    active_years = max(1, len(yearly))
    consistency = (active_years - losing_years) / active_years

    trade_penalty = 0.0
    if trades < 20:
        trade_penalty += (20 - trades) * 2.5
    if freq > 12:
        trade_penalty += (freq - 12) * 2.0

    score = (
        ret * 0.55
        + pf * 14.0
        + wr * 0.12
        + consistency * 25.0
        - dd * 1.60
        - losing_years * 10.0
        - trade_penalty
    )

    if not candidate_is_robust(metrics, yearly):
        score -= 150.0

    return round(score, 4)


def run_lab(
    bars: list[Bar],
    symbol: str = "EURUSD",
    balance: float = 1000.0,
    grid: str = "quick",
    top: int = 20,
    configs: list[dict] | None = None,
) -> LabResult:
    if not bars:
        raise ValueError("Nenhum candle válido para backtest.")
    params_list = list(configs) if configs is not None else generate_param_grid(grid)
    if not params_list:
        raise ValueError("Nenhuma configuração para testar.")

    ranking: list[LabCandidate] = []
    qualified = 0
    for params in params_list:
        result: BacktestResult = run_backtest(
            bars,
            symbol=symbol,
            initial_balance=balance,
            min_confluence=int(params.get("min_confluence", 1)),
            adx_min=float(params.get("adx_min", 20)),
            atr_sl_mult=float(params.get("atr_sl_mult", 1.5)),
            atr_tp_mult=float(params.get("atr_tp_mult", 3.0)),
            risk_pct=float(params.get("risk_pct", 1.0)),
            max_bars_in_trade=int(params.get("max_bars_in_trade", 20)),
            rsi_ob=float(params.get("rsi_ob", 68)),
            rsi_os=float(params.get("rsi_os", 32)),
        )
        yearly = yearly_metrics(result.trades, balance)
        valid = candidate_is_robust(result.metrics, yearly)
        qualified += 1 if valid else 0
        score = score_candidate(result.metrics, yearly)
        ranking.append(LabCandidate(rank=0, score=score, params=dict(params), metrics=result.metrics, trades=result.trades, valid=valid))

    ranking.sort(key=lambda c: (c.valid, c.score, _safe_float(c.metrics.get("return_pct")), -_safe_float(c.metrics.get("max_drawdown_pct"))), reverse=True)
    for i, c in enumerate(ranking, start=1):
        c.rank = i

    best = ranking[0] if ranking else None
    yearly_best = yearly_metrics(best.trades, balance) if best else []
    tf = detect_timeframe(bars)
    return LabResult(
        symbol=symbol.upper(),
        timeframe=tf,
        bars=len(bars),
        start=bars[0].timestamp.isoformat() if bars else None,
        end=bars[-1].timestamp.isoformat() if bars else None,
        tested=len(params_list),
        ranking=ranking[: max(1, int(top))],
        yearly_best=yearly_best,
        qualified=qualified,
    )


def _flatten_row(candidate: LabCandidate) -> dict:
    row = {"rank": candidate.rank, "score": candidate.score}
    row.update({f"param_{k}": v for k, v in candidate.params.items()})
    keys = [
        "total_trades", "wins", "losses", "winrate", "profit_factor", "expectancy",
        "total_pnl", "return_pct", "max_drawdown_pct", "sharpe_ratio", "trade_frequency_per_week",
    ]
    for k in keys:
        row[k] = candidate.metrics.get(k, "")
    return row


def save_lab_result(result: LabResult, out_dir: str | Path = "reports") -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = f"{result.symbol}_{result.timeframe}_{stamp}"

    ranking_path = out / f"{base}_ranking.csv"
    top_path = out / f"{base}_top.csv"
    yearly_path = out / f"{base}_yearly_best.csv"
    summary_path = out / f"{base}_summary.json"

    rows = [_flatten_row(c) for c in result.ranking]
    if rows:
        with ranking_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        with top_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows[: min(10, len(rows))])

    if result.yearly_best:
        with yearly_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(result.yearly_best[0].keys()))
            writer.writeheader()
            writer.writerows(result.yearly_best)

    summary = {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "bars": result.bars,
        "start": result.start,
        "end": result.end,
        "tested": result.tested,
        "best": _flatten_row(result.best) if result.best else None,
        "yearly_best": result.yearly_best,
        "qualified": result.qualified,
        "warning": "Backtest não garante lucro futuro; use forward test em conta demo antes de operar real.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    paths = {"summary": str(summary_path)}
    if rows:
        paths.update({"ranking": str(ranking_path), "top": str(top_path)})
    if result.yearly_best:
        paths["yearly_best"] = str(yearly_path)
    return paths


def format_lab_summary(result: LabResult, max_rows: int = 5) -> str:
    best = result.best
    if not best:
        return "Nenhuma configuração testada."
    m = best.metrics
    p = best.params
    lines = [
        f"🧪 BACKTEST LAB — {result.symbol} {result.timeframe}",
        f"Candles: {result.bars} | Período: {str(result.start)[:10]} → {str(result.end)[:10]}",
        f"Configurações testadas: {result.tested} | Robustas: {result.qualified}",
        "—" * 18,
        f"🏆 Melhor score: {best.score}{' (robusta)' if getattr(best, 'valid', False) else ' (não robusta)'}",
        f"Trades: {m.get('total_trades', 0)} | WR: {m.get('winrate', 0)}% | PF: {m.get('profit_factor', 0)}",
        f"Retorno: {m.get('return_pct', 0)}% | DD máx.: {m.get('max_drawdown_pct', 0)}% | P&L: ${m.get('total_pnl', 0)}",
        f"Parâmetros: {json.dumps(p, ensure_ascii=False)}",
        "—" * 18,
        "Consistência anual da melhor configuração:",
    ]
    if result.yearly_best:
        for y in result.yearly_best[:max_rows]:
            lines.append(
                f"{y['year']}: {y['return_pct']}% | DD {y['max_drawdown_pct']}% | "
                f"trades {y['trades']} | PF {y['profit_factor']}"
            )
        if len(result.yearly_best) > max_rows:
            lines.append(f"… +{len(result.yearly_best) - max_rows} ano(s)")
    else:
        lines.append("Sem trades fechados suficientes para separar por ano.")

    if not getattr(best, 'valid', False):
        lines.append("⚠️ Nenhuma configuração passou no filtro de robustez; não usar este setup ao vivo.")
    else:
        lines.append("✅ Configuração passou no filtro de robustez; ainda assim valide em demo/forward test.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Lab multi-anos para Forex/Ouro")
    parser.add_argument("csv", help="Arquivo CSV com candles OHLC")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--balance", type=float, default=1000.0)
    parser.add_argument("--grid", choices=["quick", "deep"], default="quick")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido no CSV.")
    result = run_lab(bars, symbol=args.symbol, balance=args.balance, grid=args.grid, top=args.top)
    paths = save_lab_result(result, args.out)
    print(format_lab_summary(result, max_rows=12))
    print("\nArquivos gerados:")
    for name, path in paths.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
