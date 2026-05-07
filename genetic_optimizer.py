"""
genetic_optimizer.py — otimizador robusto com validação walk-forward.

Objetivo:
- evitar overfitting
- buscar consistência em teste fora da amostra
- favorecer frequência próxima da meta semanal
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backtester import load_bars_from_csv, run_backtest, build_indicator_cache, prepare_bars_for_backtest
from config import Config
from utils import log, save_strategy_settings


GENOME_KEYS = [
    "MIN_CONFLUENCE",
    "ADX_MIN",
    "ATR_MULT_SL",
    "ATR_MULT_TP",
    "PULL_MIN",
    "PULL_MAX",
    "RISK_PCT",
    "WEEKLY_TARGET",
    "MIN_RR",
    "WARMUP_BARS",
    "MAX_BARS_IN_TRADE",
]

RANGES: dict[str, tuple[float, float]] = {
    "MIN_CONFLUENCE": (3, 8),
    "ADX_MIN": (14, 30),
    "ATR_MULT_SL": (1.0, 2.2),
    "ATR_MULT_TP": (2.0, 4.8),
    "PULL_MIN": (-2.2, -0.4),
    "PULL_MAX": (0.8, 3.0),
    "RISK_PCT": (0.5, 2.5),
    "WEEKLY_TARGET": (1.5, 5.0),
    "MIN_RR": (1.2, 3.5),
    "WARMUP_BARS": (40, 160),
    "MAX_BARS_IN_TRADE": (8, 120),
}

# Universo padrão para robustez multi-pair quando houver dados via API.
SYMBOL_PEERS: dict[str, list[str]] = {
    "EURUSD": ["GBPUSD", "USDJPY"],
    "GBPUSD": ["EURUSD", "USDJPY"],
    "USDJPY": ["EURUSD", "GBPUSD"],
    "EURJPY": ["EURUSD", "GBPJPY"],
    "GBPJPY": ["GBPUSD", "EURJPY"],
    "AUDUSD": ["NZDUSD"],
    "NZDUSD": ["AUDUSD"],
    "USDCAD": ["USDCHF"],
    "USDCHF": ["USDCAD"],
    "XAUUSD": ["EURUSD", "USDJPY"],
}

POPULATION_SIZE = 16
ELITE_COUNT = 4
MUTATION_RATE = 0.22
TOURNAMENT_SIZE = 4
MIN_TRADES = 16
TARGET_TRADES_WEEK = 3.0
MAX_WALK_FORWARD_FOLDS = 3

Genome = dict[str, Any]


def _rand_gene(key: str) -> float | int:
    lo, hi = RANGES[key]
    if float(lo).is_integer() and float(hi).is_integer():
        return random.randint(int(lo), int(hi))
    return round(random.uniform(lo, hi), 2)


def random_genome() -> Genome:
    g = {k: _rand_gene(k) for k in GENOME_KEYS}
    if g["PULL_MIN"] > g["PULL_MAX"]:
        g["PULL_MIN"], g["PULL_MAX"] = g["PULL_MAX"], g["PULL_MIN"]
    return g


def crossover(g1: Genome, g2: Genome) -> Genome:
    child: Genome = {}
    for k in GENOME_KEYS:
        child[k] = g1[k] if random.random() < 0.5 else g2[k]
    for k in GENOME_KEYS:
        if random.random() < MUTATION_RATE:
            child[k] = _rand_gene(k)
    for k in GENOME_KEYS:
        lo, hi = RANGES[k]
        child[k] = max(lo, min(hi, child[k]))
    if child["PULL_MIN"] > child["PULL_MAX"]:
        child["PULL_MIN"], child["PULL_MAX"] = child["PULL_MAX"], child["PULL_MIN"]
    return child


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and value.lower() == "inf":
            return 999.0
        return float(value)
    except Exception:
        return default


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _make_walk_forward_slices(total_len: int, train_ratio: float = 0.60, test_ratio: float = 0.20, max_folds: int = MAX_WALK_FORWARD_FOLDS) -> list[tuple[slice, slice]]:
    """Gera janelas cronológicas rolantes para walk-forward."""
    if total_len < 400:
        return []

    train_len = max(220, int(total_len * train_ratio))
    test_len = max(120, int(total_len * test_ratio))
    if train_len + test_len > total_len:
        train_len = max(220, total_len - test_len)
    if train_len + test_len > total_len:
        return []

    step = max(60, test_len)
    folds: list[tuple[slice, slice]] = []
    start = 0
    while start + train_len + test_len <= total_len and len(folds) < max_folds:
        train_slice = slice(start, start + train_len)
        test_slice = slice(start + train_len, start + train_len + test_len)
        folds.append((train_slice, test_slice))
        start += step
    return folds


def _evaluate_genome_on_dataset(
    genome: Genome,
    symbol: str,
    prepared: list,
    full_cache: list[dict | None],
    folds: list[tuple[slice, slice]],
    balance: float,
) -> dict[str, Any]:
    """Avalia um genoma em walk-forward cronológico dentro de um único par."""
    if len(prepared) < 400 or not folds:
        return {
            "fitness": -5.0,
            "primary_train": {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0},
            "primary_test": {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0},
            "folds": 0,
            "avg_test_trades": 0.0,
            "avg_train_trades": 0.0,
        }

    fold_scores: list[float] = []
    primary_train = None
    primary_test = None
    primary_test_score = None
    train_trades_total = 0
    test_trades_total = 0
    penalty_total = 0.0

    for fold_idx, (train_slice, test_slice) in enumerate(folds):
        train_bars = prepared[train_slice]
        test_bars = prepared[test_slice]
        train_cache = full_cache[train_slice]
        test_cache = full_cache[test_slice]

        try:
            train_bt = _run_segment(train_bars, symbol, balance, genome, train_cache)
            test_bt = _run_segment(test_bars, symbol, balance, genome, test_cache)
            train_m = train_bt.metrics
            test_m = test_bt.metrics
        except Exception:
            train_m = {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
            test_m = train_m.copy()

        train_trades = int(train_m.get("total_trades", 0) or 0)
        test_trades = int(test_m.get("total_trades", 0) or 0)
        train_trades_total += train_trades
        test_trades_total += test_trades

        if primary_train is None:
            primary_train = train_m
            primary_test = test_m

        local_score = fitness(genome, train_m, test_m)
        fold_scores.append(local_score)

        # Penaliza genomas que só funcionam em poucos trades ou que somem com qualquer ruído.
        if train_trades < MIN_TRADES or test_trades < max(10, MIN_TRADES // 2):
            penalty_total += 0.6
        elif test_trades < MIN_TRADES:
            penalty_total += 0.25

        pf_gap = abs(_safe_float(train_m.get("profit_factor", 0.0), 0.0) - _safe_float(test_m.get("profit_factor", 0.0), 0.0))
        if pf_gap > 1.25:
            penalty_total += min(0.25, (pf_gap - 1.25) / 8.0)

        if fold_idx == 0:
            primary_test_score = local_score

    avg_score = sum(fold_scores) / max(1, len(fold_scores))
    avg_train_trades = train_trades_total / max(1, len(folds))
    avg_test_trades = test_trades_total / max(1, len(folds))
    robustness_bonus = max(0.0, 1.0 - min(1.0, penalty_total))
    final_fitness = avg_score * 0.82 + robustness_bonus * 0.18

    return {
        "fitness": final_fitness,
        "primary_train": primary_train or {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0},
        "primary_test": primary_test or {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0},
        "folds": len(folds),
        "avg_test_trades": avg_test_trades,
        "avg_train_trades": avg_train_trades,
        "primary_fold_score": primary_test_score if primary_test_score is not None else avg_score,
    }


def _metric_score(metrics: dict, target_trades_week: float) -> float:
    total = int(metrics.get("total_trades", 0) or 0)
    if total <= 0:
        return -1.0

    pf = _safe_float(metrics.get("profit_factor", 0.0), 0.0)
    wr = _safe_float(metrics.get("winrate", 0.0), 0.0) / 100.0
    dd = _safe_float(metrics.get("max_drawdown_pct", 100.0), 100.0) / 100.0
    exp = _safe_float(metrics.get("expectancy", 0.0), 0.0)
    pnl = _safe_float(metrics.get("total_pnl", 0.0), 0.0)
    initial_balance = max(1.0, _safe_float(metrics.get("initial_balance", Config.INITIAL_BALANCE), Config.INITIAL_BALANCE))
    freq = _safe_float(metrics.get("trade_frequency_per_week", 0.0), 0.0)

    pf_score = min(max(pf, 0.0), 3.0) / 3.0
    dd_score = max(0.0, 1.0 - min(dd, 0.35) / 0.35)
    pnl_score = max(-1.0, min(1.0, pnl / (initial_balance * 0.25)))
    exp_score = max(-1.0, min(1.0, exp / max(1.0, initial_balance * 0.01)))
    freq_score = max(0.0, 1.0 - abs(freq - target_trades_week) / max(1.0, target_trades_week))

    return (
        0.28 * pf_score +
        0.18 * wr +
        0.18 * dd_score +
        0.16 * freq_score +
        0.10 * (exp_score + 1) / 2 +
        0.10 * (pnl_score + 1) / 2
    )


def fitness(genome: Genome, train_metrics: dict, test_metrics: dict) -> float:
    train_trades = int(train_metrics.get("total_trades", 0) or 0)
    test_trades = int(test_metrics.get("total_trades", 0) or 0)
    if train_trades < MIN_TRADES or test_trades < max(8, MIN_TRADES // 2):
        return -5.0

    target_week = float(genome.get("WEEKLY_TARGET", TARGET_TRADES_WEEK) or TARGET_TRADES_WEEK)
    train_score = _metric_score(train_metrics, target_week)
    test_score = _metric_score(test_metrics, target_week)

    train_pf = _safe_float(train_metrics.get("profit_factor", 0.0), 0.0)
    test_pf = _safe_float(test_metrics.get("profit_factor", 0.0), 0.0)
    train_dd = _safe_float(train_metrics.get("max_drawdown_pct", 100.0), 100.0)
    test_dd = _safe_float(test_metrics.get("max_drawdown_pct", 100.0), 100.0)

    robustness = 1.0 - min(1.0, abs(train_score - test_score))
    pf_gap_penalty = min(1.0, abs(train_pf - test_pf) / 2.0)
    dd_penalty = min(1.0, max(train_dd, test_dd) / 35.0)

    return (
        0.58 * test_score +
        0.22 * train_score +
        0.12 * robustness +
        0.08 * (1.0 - pf_gap_penalty) -
        0.10 * dd_penalty
    )


@dataclass
class GenerationResult:
    generation: int
    best_genome: Genome
    best_fitness: float
    best_train_metrics: dict
    best_test_metrics: dict
    population: list[Genome] = field(default_factory=list)


def _tournament(population: list[Genome], scores: list[float]) -> Genome:
    idxs = random.sample(range(len(population)), k=min(TOURNAMENT_SIZE, len(population)))
    best = max(idxs, key=lambda i: scores[i])
    return population[best]


def evolve(population: list[Genome], fitness_scores: list[float]) -> list[Genome]:
    if not population:
        return [random_genome() for _ in range(POPULATION_SIZE)]

    paired = sorted(zip(population, fitness_scores), key=lambda x: x[1], reverse=True)
    elites = [copy.deepcopy(g) for g, _ in paired[:ELITE_COUNT]]
    new_pop = elites[:]
    while len(new_pop) < POPULATION_SIZE:
        p1 = _tournament(population, fitness_scores)
        p2 = _tournament(population, fitness_scores)
        child = crossover(p1, p2)
        new_pop.append(child)
    return new_pop[:POPULATION_SIZE]


def _split_bars(bars: list, split_ratio: float = 0.7) -> tuple[list, list]:
    split = max(120, int(len(bars) * split_ratio))
    split = min(split, len(bars) - 80)
    return bars[:split], bars[max(0, split - 180):]


def _run_segment(bars, symbol: str, balance: float, genome: Genome, indicator_cache: list[dict | None] | None = None):
    return run_backtest(
        bars,
        symbol=symbol,
        initial_balance=balance,
        min_confluence=int(genome["MIN_CONFLUENCE"]),
        adx_min=float(genome["ADX_MIN"]),
        atr_sl_mult=float(genome["ATR_MULT_SL"]),
        atr_tp_mult=float(genome["ATR_MULT_TP"]),
        pull_range=(float(genome["PULL_MIN"]), float(genome["PULL_MAX"])),
        risk_pct=float(genome["RISK_PCT"]),
        warmup_bars=int(genome["WARMUP_BARS"]),
        weekly_trade_target=float(genome["WEEKLY_TARGET"]),
        max_bars_in_trade=int(genome["MAX_BARS_IN_TRADE"]),
        indicator_cache=indicator_cache,
    )


def run_evolution(
    bars: list | dict[str, list],
    symbol: str,
    balance: float,
    generations: int = 20,
    extra_datasets: dict[str, list] | None = None,
) -> list[GenerationResult]:
    """Executa a evolução genética em walk-forward, podendo validar vários pares."""
    datasets: dict[str, list]
    if isinstance(bars, dict):
        datasets = {str(k).upper(): list(v) for k, v in bars.items() if v}
    else:
        datasets = {symbol.upper(): list(bars)}

    if extra_datasets:
        for k, v in extra_datasets.items():
            if v:
                datasets[str(k).upper()] = list(v)

    if symbol.upper() not in datasets and datasets:
        symbol = next(iter(datasets.keys()))

    # Sempre valida o par principal primeiro e, quando possível, adiciona pares correlatos.
    primary = symbol.upper()
    universe = _unique_preserve_order([primary] + [s.upper() for s in SYMBOL_PEERS.get(primary, [])])
    datasets = {k: datasets[k] for k in universe if k in datasets}
    if primary not in datasets and datasets:
        primary = next(iter(datasets.keys()))

    if primary not in datasets:
        raise ValueError("Nenhum histórico válido para o símbolo principal")

    prepared_map: dict[str, list] = {}
    cache_map: dict[str, list[dict | None]] = {}
    fold_map: dict[str, list[tuple[slice, slice]]] = {}

    for sym, data in datasets.items():
        prepared = prepare_bars_for_backtest(data)
        if len(prepared) < 400:
            continue
        prepared_map[sym] = prepared
        cache_map[sym] = build_indicator_cache(prepared)
        fold_map[sym] = _make_walk_forward_slices(len(prepared), max_folds=MAX_WALK_FORWARD_FOLDS)

    if primary not in prepared_map:
        raise ValueError("Histórico insuficiente para otimização robusta")

    if primary not in fold_map or not fold_map[primary]:
        raise ValueError("Histórico insuficiente para gerar walk-forward")

    log("[GENETIC] Pré-calculando indicadores e janelas walk-forward...")
    population: list[Genome] = [random_genome() for _ in range(POPULATION_SIZE)]
    results: list[GenerationResult] = []

    for gen in range(1, generations + 1):
        log(f"[GENETIC] Geração {gen}/{generations} — avaliando {len(population)} genomas em {len(prepared_map)} par(es)...")
        fitness_scores: list[float] = []
        train_metrics_list: list[dict] = []
        test_metrics_list: list[dict] = []

        for i, genome in enumerate(population):
            symbol_scores: list[float] = []
            primary_train = None
            primary_test = None
            primary_fitness = None
            symbol_trade_penalty = 0.0

            for sym, prepared in prepared_map.items():
                evaluation = _evaluate_genome_on_dataset(genome, sym, prepared_map[sym], cache_map[sym], fold_map[sym], balance)
                symbol_scores.append(float(evaluation["fitness"]))
                symbol_trade_penalty += max(0.0, 1.0 - min(1.0, float(evaluation["avg_test_trades"]) / float(MIN_TRADES)))
                if sym == primary:
                    primary_train = evaluation["primary_train"]
                    primary_test = evaluation["primary_test"]
                    primary_fitness = evaluation["fitness"]

            if not symbol_scores:
                train_m = {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
                test_m = train_m.copy()
                f = -5.0
            else:
                avg_fitness = sum(symbol_scores) / len(symbol_scores)
                # Penaliza genomas que só funcionam num único par ou que geram poucos trades no universo.
                universe_penalty = min(0.45, symbol_trade_penalty / max(1, len(symbol_scores)))
                f = avg_fitness - universe_penalty
                train_m = primary_train or {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
                test_m = primary_test or train_m.copy()
                if primary_fitness is not None:
                    f = (f * 0.8) + (float(primary_fitness) * 0.2)

            fitness_scores.append(f)
            train_metrics_list.append(train_m)
            test_metrics_list.append(test_m)

        best_idx = fitness_scores.index(max(fitness_scores))
        best_g = population[best_idx]
        best_f = fitness_scores[best_idx]
        best_train = train_metrics_list[best_idx]
        best_test = test_metrics_list[best_idx]

        log(
            f"[GENETIC] Gen {gen}: fitness={best_f:.3f} | "
            f"WR(t)={best_test.get('winrate', 0)}% | PF(t)={best_test.get('profit_factor', 0)} | "
            f"DD(t)={best_test.get('max_drawdown_pct', 0)}% | Trades(t)={best_test.get('total_trades', 0)} | "
            f"Trades/wk={best_test.get('trade_frequency_per_week', 0)}"
        )

        results.append(GenerationResult(
            generation=gen,
            best_genome=copy.deepcopy(best_g),
            best_fitness=best_f,
            best_train_metrics=best_train,
            best_test_metrics=best_test,
            population=list(population),
        ))

        population = evolve(population, fitness_scores)

    return results


def save_best_genome(result: GenerationResult, path: str = "best_genome.json"):
    data = {
        "generation": result.generation,
        "fitness": round(result.best_fitness, 4),
        "genome": result.best_genome,
        "train_metrics": result.best_train_metrics,
        "test_metrics": result.best_test_metrics,
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    log(f"[GENETIC] Melhor genoma salvo em {path}")


def main():
    parser = argparse.ArgumentParser(description="Otimizador robusto do Sniper Bot")
    parser.add_argument("csv", help="CSV com OHLC histórico")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--universe", default="", help="Lista de pares separados por vírgula para validação multi-pair")
    parser.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--output", default="best_genome.json")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido no CSV.")

    extra: dict[str, list] = {}
    if args.universe.strip():
        # No modo CLI, o usuário pode informar um universo extra separado por vírgula.
        for s in (x.strip().upper() for x in args.universe.split(",") if x.strip()):
            if s != args.symbol.upper():
                extra[s] = bars

    log(f"[GENETIC] {len(bars)} barras | {args.symbol} | {args.generations} gerações")
    results = run_evolution(bars if not extra else {args.symbol.upper(): bars, **extra}, args.symbol, args.balance, args.generations)

    overall_best = max(results, key=lambda r: r.best_fitness)
    save_best_genome(overall_best, args.output)

    # salva em strategy_settings.json também para virar default operacional
    saved_settings = {
        "profile": "hedge_fund",
        "min_confluence": int(overall_best.best_genome["MIN_CONFLUENCE"]),
        "adx_min": float(overall_best.best_genome["ADX_MIN"]),
        "atr_sl_mult": float(overall_best.best_genome["ATR_MULT_SL"]),
        "atr_tp_mult": float(overall_best.best_genome["ATR_MULT_TP"]),
        "pull_min": float(overall_best.best_genome["PULL_MIN"]),
        "pull_max": float(overall_best.best_genome["PULL_MAX"]),
        "risk_pct": float(overall_best.best_genome["RISK_PCT"]),
        "weekly_trade_target": float(overall_best.best_genome["WEEKLY_TARGET"]),
        "min_rr": float(overall_best.best_genome["MIN_RR"]),
        "warmup_bars": int(overall_best.best_genome["WARMUP_BARS"]),
        "max_bars_in_trade": int(overall_best.best_genome["MAX_BARS_IN_TRADE"]),
        "optimization_mode": "robust",
    }
    try:
        save_strategy_settings(saved_settings)
    except Exception as e:
        log(f"[GENETIC] Falha ao salvar strategy_settings.json: {e}")

    print()
    print("═" * 50)
    print("  MELHOR CONFIGURAÇÃO ENCONTRADA")
    print("═" * 50)
    for k, v in overall_best.best_genome.items():
        print(f"  {k:<22} = {v}")
    print("─" * 50)
    m = overall_best.best_test_metrics
    print(f"  Fitness:   {overall_best.best_fitness:.4f}")
    print(f"  Win Rate:  {m.get('winrate', 0)}%")
    print(f"  PF:        {m.get('profit_factor', 0)}")
    print(f"  Drawdown:  {m.get('max_drawdown_pct', 0)}%")
    print(f"  Trades:    {m.get('total_trades', 0)}")
    print(f"  Trades/wk: {m.get('trade_frequency_per_week', 0)}")
    print("═" * 50)



if __name__ == "__main__":
    main()
