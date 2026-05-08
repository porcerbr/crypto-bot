"""
genetic_optimizer.py — otimizador walk-forward robusto.

M15: genoma evolui EMA50+MACD+RSI params + gestão de risco.
H1:  genoma evolui params do sinal original + pullback zone.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backtester import (
    load_bars_from_csv, run_backtest,
    build_indicator_cache, prepare_bars_for_backtest,
    _build_h4_bias_map, detect_timeframe,
)
from config import Config
from performance import calculate_metrics_from_history
from utils import log, save_strategy_settings


# ──────────────────────────────────────────────────────────────────────────────
# Timeframe detection
# ──────────────────────────────────────────────────────────────────────────────

def _get_tf() -> str:
    return str(getattr(Config, "TIMEFRAME", "M15")).strip().lower()

def _is_m15() -> bool:
    return _get_tf() in {"m15", "15m", "15min", "15"}

def _is_h1() -> bool:
    return _get_tf() in {"h1", "1h", "60m", "60"}


# ──────────────────────────────────────────────────────────────────────────────
# Genome definition
# ──────────────────────────────────────────────────────────────────────────────

# M15: evolui RSI_OB/OS e gestão; sem pullback zone (não usada no _signal_m15)
GENOME_KEYS_M15 = [
    "MIN_CONFLUENCE",    # soft conditions extra (0-2)
    "ADX_MIN",           # filtro ADX opcional (10-28)
    "ATR_MULT_SL",       # multiplicador SL
    "ATR_MULT_TP",       # multiplicador TP
    "RSI_OB",            # não compra acima deste RSI (62-75)
    "RSI_OS",            # não vende abaixo deste RSI (25-38)
    "RISK_PCT",          # risco por trade
    "WEEKLY_TARGET",     # meta de frequência (fitness)
    "MIN_RR",            # R:R mínimo
    "WARMUP_BARS",       # barras de aquecimento
    "MAX_BARS_IN_TRADE", # expiração em barras
]

# H1: mantém pullback zone
GENOME_KEYS_H1 = [
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

GENOME_KEYS: list[str] = GENOME_KEYS_M15  # padrão M15

# Ranges completos (ambos TFs)
RANGES: dict[str, tuple[float, float]] = {
    "MIN_CONFLUENCE": (0, 2),
    "ADX_MIN":        (10, 28),
    "ATR_MULT_SL":    (1.3, 2.5),   # mínimo 1.3 para sobreviver spread M15
    "ATR_MULT_TP":    (2.0, 4.0),
    "RSI_OB":         (62, 75),
    "RSI_OS":         (25, 38),
    "PULL_MIN":       (-2.2, -0.4),
    "PULL_MAX":       (0.8, 3.0),
    "RISK_PCT":       (0.8, 2.5),
    "WEEKLY_TARGET":  (5.0, 25.0),
    "MIN_RR":         (1.2, 2.5),
    "WARMUP_BARS":    (60, 200),
    "MAX_BARS_IN_TRADE": (12, 48),  # mínimo 12 barras M15 = 3h
}

if _is_h1():
    GENOME_KEYS = GENOME_KEYS_H1
    RANGES["ATR_MULT_SL"]    = (1.0, 2.2)
    RANGES["ATR_MULT_TP"]    = (2.0, 4.5)
    RANGES["MIN_CONFLUENCE"] = (4, 8)
    RANGES["ADX_MIN"]        = (18, 34)
    RANGES["WEEKLY_TARGET"]  = (1.5, 4.0)
    RANGES["MAX_BARS_IN_TRADE"] = (16, 72)
    RANGES["WARMUP_BARS"]    = (60, 180)

POPULATION_SIZE = 16
ELITE_COUNT     = 4
MUTATION_RATE   = 0.22
TOURNAMENT_SIZE = 4
MIN_TRADES      = 15 if _is_m15() else 12
TARGET_TRADES_WEEK = 10.0 if _is_m15() else 2.5
MAX_WALK_FOLDS  = 3

Genome = dict[str, Any]

# Pares correlatos por símbolo principal
SYMBOL_PEERS: dict[str, list[str]] = {
    "EURUSD": ["GBPUSD", "USDJPY"],
    "GBPUSD": ["EURUSD", "USDJPY"],
    "USDJPY": ["EURUSD", "GBPUSD"],
    "EURJPY": ["EURUSD", "GBPJPY"],
    "XAUUSD": ["EURUSD", "USDJPY"],
    "AUDUSD": ["NZDUSD"],
    "NZDUSD": ["AUDUSD"],
}


# ──────────────────────────────────────────────────────────────────────────────
# Genome helpers
# ──────────────────────────────────────────────────────────────────────────────

def _rand_gene(key: str) -> float | int:
    lo, hi = RANGES[key]
    if float(lo).is_integer() and float(hi).is_integer():
        return random.randint(int(lo), int(hi))
    return round(random.uniform(lo, hi), 2)


def random_genome() -> Genome:
    g = {k: _rand_gene(k) for k in GENOME_KEYS}
    if "PULL_MIN" in g and "PULL_MAX" in g and g["PULL_MIN"] > g["PULL_MAX"]:
        g["PULL_MIN"], g["PULL_MAX"] = g["PULL_MAX"], g["PULL_MIN"]
    return g


def crossover(g1: Genome, g2: Genome) -> Genome:
    child: Genome = {}
    for k in GENOME_KEYS:
        child[k] = g1[k] if random.random() < 0.5 else g2[k]
    # Mutação
    for k in GENOME_KEYS:
        if random.random() < MUTATION_RATE:
            child[k] = _rand_gene(k)
    # Clamp
    for k in GENOME_KEYS:
        if k not in RANGES:
            continue
        lo, hi = RANGES[k]
        child[k] = max(lo, min(hi, child[k]))
    if "PULL_MIN" in child and "PULL_MAX" in child and child["PULL_MIN"] > child["PULL_MAX"]:
        child["PULL_MIN"], child["PULL_MAX"] = child["PULL_MAX"], child["PULL_MIN"]
    return child


# ──────────────────────────────────────────────────────────────────────────────
# Fitness
# ──────────────────────────────────────────────────────────────────────────────

def _safe(v, default=0.0):
    try:
        if v is None: return default
        if isinstance(v, str) and v.lower() == "inf": return 999.0
        return float(v)
    except Exception:
        return default


def _metric_score(metrics: dict, target_week: float, balance: float) -> float:
    total = int(metrics.get("total_trades", 0) or 0)
    if total <= 0:
        return -1.0
    pf   = min(_safe(metrics.get("profit_factor"), 0.0), 4.0) / 4.0
    wr   = _safe(metrics.get("winrate"), 0.0) / 100.0
    dd   = min(_safe(metrics.get("max_drawdown_pct"), 100.0), 40.0) / 40.0
    freq = _safe(metrics.get("trade_frequency_per_week"), 0.0)
    exp  = _safe(metrics.get("expectancy"), 0.0)
    pnl  = _safe(metrics.get("total_pnl"), 0.0)

    freq_score = max(0.0, 1.0 - abs(freq - target_week) / max(1.0, target_week))
    pnl_score  = max(-1.0, min(1.0, pnl / max(1.0, balance * 0.20)))
    exp_score  = max(-1.0, min(1.0, exp / max(1.0, balance * 0.01)))

    # Retorno mensal estimado (alvo 20-25%)
    monthly_days   = 21.0
    est_monthly    = (freq / 5.0) * monthly_days * (exp / max(1.0, balance)) if exp > 0 else 0.0
    monthly_score  = max(0.0, min(1.0, est_monthly / 0.22))

    return (
        0.22 * pf +
        0.16 * wr +
        0.16 * (1.0 - dd) +
        0.16 * freq_score +
        0.15 * monthly_score +
        0.08 * (exp_score + 1) / 2 +
        0.07 * (pnl_score + 1) / 2
    )


def fitness(genome: Genome, train_m: dict, test_m: dict, balance: float) -> float:
    train_trades = int(train_m.get("total_trades", 0) or 0)
    test_trades  = int(test_m.get("total_trades", 0) or 0)
    min_test     = max(6, MIN_TRADES // 2)

    if train_trades < MIN_TRADES or test_trades < min_test:
        return -5.0

    target = float(genome.get("WEEKLY_TARGET", TARGET_TRADES_WEEK) or TARGET_TRADES_WEEK)
    train_score = _metric_score(train_m, target, balance)
    test_score  = _metric_score(test_m,  target, balance)

    train_pf = _safe(train_m.get("profit_factor"), 0.0)
    test_pf  = _safe(test_m.get("profit_factor"), 0.0)
    train_dd = _safe(train_m.get("max_drawdown_pct"), 100.0)
    test_dd  = _safe(test_m.get("max_drawdown_pct"), 100.0)

    # Penalidade proporcional por PF < 1 (não um hard cliff)
    pf_pen = 0.0
    if train_pf < 1.0:
        pf_pen += (1.0 - train_pf) * 0.5
    if test_pf < 0.95:
        pf_pen += (0.95 - test_pf) * 0.7
    dd_limit = 15.0 if _is_m15() else 20.0
    if max(train_dd, test_dd) > dd_limit:
        pf_pen += min(1.0, (max(train_dd, test_dd) - dd_limit) / dd_limit) * 0.4

    robustness  = 1.0 - min(1.0, abs(train_score - test_score))
    pf_gap_pen  = min(1.0, abs(train_pf - test_pf) / 2.0)
    dd_pen      = min(1.0, max(train_dd, test_dd) / 30.0)
    trade_bal   = min(1.0, test_trades / max(1.0, train_trades))

    raw = (
        0.52 * test_score +
        0.20 * train_score +
        0.12 * robustness +
        0.08 * (1.0 - pf_gap_pen) +
        0.04 * trade_bal -
        0.10 * dd_pen
    )
    return raw - pf_pen


# ──────────────────────────────────────────────────────────────────────────────
# Walk-forward slices
# ──────────────────────────────────────────────────────────────────────────────

def _make_folds(n: int, train_ratio=0.60, test_ratio=0.20, max_folds=MAX_WALK_FOLDS):
    if n < 300:
        return []
    train_len = max(200, int(n * train_ratio))
    test_len  = max(80,  int(n * test_ratio))
    if train_len + test_len > n:
        train_len = max(200, n - test_len)
    if train_len + test_len > n:
        return []
    step  = max(50, test_len)
    folds = []
    start = 0
    while start + train_len + test_len <= n and len(folds) < max_folds:
        folds.append((slice(start, start + train_len),
                      slice(start + train_len, start + train_len + test_len)))
        start += step
    return folds


# ──────────────────────────────────────────────────────────────────────────────
# Segment runner
# ──────────────────────────────────────────────────────────────────────────────

def _run_segment(bars, symbol, balance, genome, indicator_cache=None, h4_bias_map=None, prepared=False):
    if _is_m15():
        pull   = None
        rsi_ob = float(genome.get("RSI_OB", 68.0))
        rsi_os = float(genome.get("RSI_OS", 32.0))
    else:
        pull   = (float(genome.get("PULL_MIN", -1.0)), float(genome.get("PULL_MAX", 2.0)))
        rsi_ob = 68.0
        rsi_os = 32.0

    return run_backtest(
        bars, symbol=symbol, initial_balance=balance,
        min_confluence=int(genome["MIN_CONFLUENCE"]),
        adx_min=float(genome["ADX_MIN"]),
        atr_sl_mult=float(genome["ATR_MULT_SL"]),
        atr_tp_mult=float(genome["ATR_MULT_TP"]),
        pull_range=pull,
        risk_pct=float(genome["RISK_PCT"]),
        warmup_bars=int(genome["WARMUP_BARS"]),
        weekly_trade_target=float(genome["WEEKLY_TARGET"]),
        max_bars_in_trade=int(genome["MAX_BARS_IN_TRADE"]),
        indicator_cache=indicator_cache,
        prepared_bars=prepared,
        h4_bias_map=h4_bias_map,
        rsi_ob=rsi_ob,
        rsi_os=rsi_os,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Genome evaluation (serial, sem global state)
# ──────────────────────────────────────────────────────────────────────────────

def _eval_genome(genome, prepared_map, cache_map, fold_map, h4_map, balance, primary):
    empty = {"total_trades": 0, "winrate": 0, "profit_factor": 0,
             "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
    symbol_scores: list[float] = []
    primary_train = primary_test = None

    for sym, prepared in prepared_map.items():
        folds = fold_map[sym]
        cache = cache_map[sym]
        h4    = h4_map.get(sym, [None] * len(prepared))
        fold_scores: list[float] = []

        for train_sl, test_sl in folds:
            train_bars = prepared[train_sl]
            test_bars  = prepared[test_sl]
            try:
                r_train = _run_segment(train_bars, sym, balance, genome,
                                       cache[train_sl], h4[train_sl] if len(h4) > 0 else None, True)
                r_test  = _run_segment(test_bars,  sym, balance, genome,
                                       cache[test_sl],  h4[test_sl]  if len(h4) > 0 else None, True)
                train_m = r_train.metrics
                test_m  = r_test.metrics
            except Exception as e:
                log(f"[GENETIC] Erro no fold de {sym}: {e}")
                train_m = empty.copy()
                test_m  = empty.copy()

            f = fitness(genome, train_m, test_m, balance)
            fold_scores.append(f)
            if sym == primary and primary_train is None:
                primary_train = train_m
                primary_test  = test_m

        avg = sum(fold_scores) / max(1, len(fold_scores))
        symbol_scores.append(avg)

    if not symbol_scores:
        return {"fitness": -5.0, "train": empty, "test": empty}

    combined = sum(symbol_scores) / len(symbol_scores)
    return {
        "fitness": combined,
        "train":   primary_train or empty,
        "test":    primary_test  or empty,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Evolution
# ──────────────────────────────────────────────────────────────────────────────

def _tournament(population, scores):
    idxs = random.sample(range(len(population)), k=min(TOURNAMENT_SIZE, len(population)))
    return population[max(idxs, key=lambda i: scores[i])]


def evolve(population: list[Genome], scores: list[float]) -> list[Genome]:
    if not population:
        return [random_genome() for _ in range(POPULATION_SIZE)]
    paired = sorted(zip(population, scores), key=lambda x: x[1], reverse=True)
    new_pop = [copy.deepcopy(g) for g, _ in paired[:ELITE_COUNT]]
    while len(new_pop) < POPULATION_SIZE:
        new_pop.append(crossover(_tournament(population, scores), _tournament(population, scores)))
    return new_pop[:POPULATION_SIZE]


@dataclass
class GenerationResult:
    generation: int
    best_genome: Genome
    best_fitness: float
    best_train_metrics: dict
    best_test_metrics: dict
    population: list[Genome] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Main evolution loop
# ──────────────────────────────────────────────────────────────────────────────

def run_evolution(bars, symbol: str, balance: float, generations: int = 50,
                  extra_datasets=None) -> list[GenerationResult]:
    """Evolução genética serial walk-forward. Sem multiprocessing (Railway-safe)."""
    # Monta datasets
    if isinstance(bars, dict):
        datasets = {str(k).upper(): list(v) for k, v in bars.items() if v}
    else:
        datasets = {symbol.upper(): list(bars)}
    if extra_datasets:
        for k, v in extra_datasets.items():
            if v: datasets[str(k).upper()] = list(v)

    primary  = symbol.upper()
    universe = [primary] + [s for s in SYMBOL_PEERS.get(primary, []) if s != primary]
    datasets = {k: datasets[k] for k in universe if k in datasets}
    if primary not in datasets:
        if datasets: primary = next(iter(datasets))
        else: raise ValueError("Nenhum histórico válido")

    # Pré-calcula tudo
    log(f"[GENETIC] Pré-calculando indicadores para {list(datasets.keys())}...")
    prepared_map: dict[str, list] = {}
    cache_map:    dict[str, list] = {}
    fold_map:     dict[str, list] = {}
    h4_map:       dict[str, list] = {}

    for sym, data in datasets.items():
        prepared = prepare_bars_for_backtest(data)
        if len(prepared) < 200:
            log(f"[GENETIC] {sym}: apenas {len(prepared)} barras — ignorado")
            continue
        tf = detect_timeframe(prepared)
        folds = _make_folds(len(prepared))
        if not folds:
            split = int(len(prepared) * 0.70)
            folds = [(slice(0, split), slice(split, len(prepared)))]
            log(f"[GENETIC] {sym}: split simples 70/30 ({len(prepared)} barras)")
        prepared_map[sym] = prepared
        cache_map[sym]    = build_indicator_cache(prepared)
        fold_map[sym]     = folds
        h4_map[sym]       = _build_h4_bias_map(prepared) if tf == "H1" else [None] * len(prepared)

    if primary not in prepared_map:
        raise ValueError(f"Histórico insuficiente para {primary}")

    log(f"[GENETIC] Universo: {list(prepared_map.keys())} | {len(prepared_map)} par(es) | {generations} gerações")

    population = [random_genome() for _ in range(POPULATION_SIZE)]
    results: list[GenerationResult] = []

    for gen in range(1, generations + 1):
        log(f"[GENETIC] Geração {gen}/{generations}...")
        fit_scores, train_list, test_list = [], [], []

        for genome in population:
            ev = _eval_genome(genome, prepared_map, cache_map, fold_map, h4_map, balance, primary)
            fit_scores.append(float(ev["fitness"]))
            train_list.append(ev["train"])
            test_list.append(ev["test"])

        best_idx = fit_scores.index(max(fit_scores))
        results.append(GenerationResult(
            generation=gen,
            best_genome=copy.deepcopy(population[best_idx]),
            best_fitness=fit_scores[best_idx],
            best_train_metrics=train_list[best_idx],
            best_test_metrics=test_list[best_idx],
            population=list(population),
        ))
        best = results[-1]
        log(f"[GENETIC] Gen {gen}: fitness={best.best_fitness:.3f} | "
            f"WR(oos)={best.best_test_metrics.get('winrate',0)}% | "
            f"PF(oos)={best.best_test_metrics.get('profit_factor',0)} | "
            f"Trades(oos)={best.best_test_metrics.get('total_trades',0)}")
        population = evolve(population, fit_scores)

    return results


def save_best_genome(result: GenerationResult, path: str = "best_genome.json"):
    g = result.best_genome
    data = {
        "generation": result.generation,
        "fitness": round(result.best_fitness, 4),
        "genome": g,
        "train_metrics": result.best_train_metrics,
        "test_metrics": result.best_test_metrics,
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "timeframe": "M15" if _is_m15() else "H1",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    log(f"[GENETIC] Melhor genoma salvo em {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv"); parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--generations", type=int, default=50)
    parser.add_argument("--output", default="best_genome.json")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars: raise SystemExit("Nenhum candle válido.")
    log(f"[GENETIC] {len(bars)} barras | {args.symbol} | {args.generations} gerações")

    results = run_evolution(bars, args.symbol, args.balance, args.generations)
    best = max(results, key=lambda r: r.best_fitness)
    save_best_genome(best, args.output)

    g = best.best_genome
    settings = {
        "timeframe": "M15" if _is_m15() else "H1",
        "min_confluence": int(g["MIN_CONFLUENCE"]),
        "adx_min": float(g["ADX_MIN"]),
        "atr_sl_mult": float(g["ATR_MULT_SL"]),
        "atr_tp_mult": float(g["ATR_MULT_TP"]),
        "risk_pct": float(g["RISK_PCT"]),
        "weekly_trade_target": float(g["WEEKLY_TARGET"]),
        "max_bars_in_trade": int(g["MAX_BARS_IN_TRADE"]),
        "rsi_ob": float(g.get("RSI_OB", 68.0)),
        "rsi_os": float(g.get("RSI_OS", 32.0)),
        "pull_min": float(g.get("PULL_MIN", -1.0)),
        "pull_max": float(g.get("PULL_MAX", 2.0)),
    }
    try: save_strategy_settings(settings)
    except Exception as e: log(f"[GENETIC] Falha ao salvar strategy_settings.json: {e}")

    m = best.best_test_metrics
    print(f"\n{'═'*50}")
    print(f"  MELHOR GENOMA — Geração {best.generation} | Fitness {best.best_fitness:.4f}")
    print(f"{'═'*50}")
    for k, v in g.items(): print(f"  {k:<22} = {v}")
    print(f"{'─'*50}")
    print(f"  WR: {m.get('winrate',0)}%  PF: {m.get('profit_factor',0)}  "
          f"DD: {m.get('max_drawdown_pct',0)}%  Trades: {m.get('total_trades',0)}")
    print(f"{'═'*50}")


if __name__ == "__main__":
    main()
