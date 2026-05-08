from __future__ import annotations

import argparse
import copy
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from backtester import (
    load_bars_from_csv,
    run_backtest,
    build_indicator_cache,
    prepare_bars_for_backtest,
    _build_h4_bias_map,
)
from config import Config
from utils import log, save_strategy_settings


# ──────────────────────────────────────────────────────────────────────────────
# Genoma enxuto: poucos parâmetros, alto impacto.
# ──────────────────────────────────────────────────────────────────────────────

TF = str(getattr(Config, "TIMEFRAME", "M15")).strip().upper()
IS_M15 = TF in {"M15", "15M", "15", "15MIN"}
IS_H1 = TF in {"H1", "1H", "60M", "60"}

GENOME_KEYS_M15 = [
    "MIN_CONFLUENCE",
    "ADX_MIN",
    "ATR_MULT_SL",
    "ATR_MULT_TP",
    "RISK_PCT",
    "RSI_OB",
    "RSI_OS",
    "WARMUP_BARS",
    "MAX_BARS_IN_TRADE",
]

GENOME_KEYS_H1 = [
    "MIN_CONFLUENCE",
    "ADX_MIN",
    "ATR_MULT_SL",
    "ATR_MULT_TP",
    "RISK_PCT",
    "PULL_MIN",
    "PULL_MAX",
    "WARMUP_BARS",
    "MAX_BARS_IN_TRADE",
]

GENOME_KEYS = GENOME_KEYS_M15 if IS_M15 else GENOME_KEYS_H1

RANGES: dict[str, tuple[float, float]] = {
    "MIN_CONFLUENCE": (2, 5),
    "ADX_MIN": (12, 30),
    "ATR_MULT_SL": (0.8, 2.0),
    "ATR_MULT_TP": (1.4, 4.0),
    "RISK_PCT": (0.5, 2.0),
    "RSI_OB": (60, 75),
    "RSI_OS": (25, 40),
    "PULL_MIN": (-2.0, -0.2),
    "PULL_MAX": (0.3, 2.4),
    "WARMUP_BARS": (60, 240),
    "MAX_BARS_IN_TRADE": (6, 80),
}

if IS_M15:
    RANGES.update({
        "MIN_CONFLUENCE": (2, 4),
        "ADX_MIN": (12, 26),
        "ATR_MULT_SL": (0.8, 1.8),
        "ATR_MULT_TP": (1.4, 3.2),
        "RISK_PCT": (0.5, 1.8),
        "RSI_OB": (62, 74),
        "RSI_OS": (26, 40),
        "WARMUP_BARS": (80, 260),
        "MAX_BARS_IN_TRADE": (6, 32),
    })
elif IS_H1:
    RANGES.update({
        "MIN_CONFLUENCE": (2, 5),
        "ADX_MIN": (14, 32),
        "ATR_MULT_SL": (1.0, 2.2),
        "ATR_MULT_TP": (2.0, 4.2),
        "RISK_PCT": (0.5, 1.5),
        "PULL_MIN": (-1.8, -0.3),
        "PULL_MAX": (0.4, 2.2),
        "WARMUP_BARS": (80, 220),
        "MAX_BARS_IN_TRADE": (12, 72),
    })

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

POPULATION_SIZE = 24
ELITE_COUNT = 5
TOURNAMENT_SIZE = 4
MUTATION_RATE = 0.22
MAX_WALK_FORWARD_FOLDS = 4

MIN_TOTAL_TEST_TRADES = 24 if IS_M15 else 14
MIN_TEST_TRADES_PER_FOLD = 8 if IS_M15 else 5
MIN_TRAIN_TRADES = 24 if IS_M15 else 14
TARGET_TRADES_WEEK = 8.0 if IS_M15 else 3.5

Genome = dict[str, Any]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and value.lower() == "inf":
            return 999.0
        return float(value)
    except Exception:
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _rand_gene(key: str) -> float | int:
    lo, hi = RANGES[key]
    if float(lo).is_integer() and float(hi).is_integer():
        return random.randint(int(lo), int(hi))
    return round(random.uniform(lo, hi), 2)


def _normalize_genome(g: Genome) -> Genome:
    out = {k: g[k] for k in GENOME_KEYS if k in g}

    for key in list(out.keys()):
        if key not in RANGES:
            continue
        lo, hi = RANGES[key]
        out[key] = _clamp(_safe_float(out[key], lo), lo, hi)
        if float(lo).is_integer() and float(hi).is_integer():
            out[key] = int(round(out[key]))
        else:
            out[key] = round(float(out[key]), 2)

    if "PULL_MIN" in out and "PULL_MAX" in out:
        if out["PULL_MIN"] > out["PULL_MAX"]:
            out["PULL_MIN"], out["PULL_MAX"] = out["PULL_MAX"], out["PULL_MIN"]
        out["PULL_MIN"] = round(float(out["PULL_MIN"]), 2)
        out["PULL_MAX"] = round(float(out["PULL_MAX"]), 2)

    if "RSI_OB" in out and "RSI_OS" in out:
        # mantém um canal útil para pullbacks; evita thresholds cruzados
        if out["RSI_OB"] <= out["RSI_OS"] + 5:
            out["RSI_OB"] = min(RANGES["RSI_OB"][1], out["RSI_OS"] + 8)
        out["RSI_OB"] = round(float(out["RSI_OB"]), 2)
        out["RSI_OS"] = round(float(out["RSI_OS"]), 2)

    return out


def _base_genome() -> Genome:
    if IS_M15:
        return _normalize_genome({
            "MIN_CONFLUENCE": 3,
            "ADX_MIN": 18,
            "ATR_MULT_SL": 1.10,
            "ATR_MULT_TP": 2.20,
            "RISK_PCT": 1.00,
            "RSI_OB": 69,
            "RSI_OS": 33,
            "WARMUP_BARS": 140,
            "MAX_BARS_IN_TRADE": 18,
        })
    return _normalize_genome({
        "MIN_CONFLUENCE": 3,
        "ADX_MIN": 20,
        "ATR_MULT_SL": 1.20,
        "ATR_MULT_TP": 2.70,
        "RISK_PCT": 0.90,
        "PULL_MIN": -1.00,
        "PULL_MAX": 1.50,
        "WARMUP_BARS": 120,
        "MAX_BARS_IN_TRADE": 32,
    })


def random_genome() -> Genome:
    g = {k: _rand_gene(k) for k in GENOME_KEYS}
    return _normalize_genome(g)


def mutate(genome: Genome) -> Genome:
    child = copy.deepcopy(genome)
    for key in GENOME_KEYS:
        if random.random() < MUTATION_RATE:
            lo, hi = RANGES[key]
            cur = _safe_float(child.get(key), (lo + hi) / 2)
            if float(lo).is_integer() and float(hi).is_integer():
                span = max(1, int(round((hi - lo) * 0.25)))
                cur = int(round(cur)) + random.randint(-span, span)
                child[key] = int(_clamp(cur, lo, hi))
            else:
                span = (hi - lo) * 0.18
                cur = cur + random.uniform(-span, span)
                child[key] = round(_clamp(cur, lo, hi), 2)
    return _normalize_genome(child)


def crossover(g1: Genome, g2: Genome) -> Genome:
    child: Genome = {}
    for key in GENOME_KEYS:
        child[key] = g1[key] if random.random() < 0.5 else g2[key]
    if random.random() < 0.35:
        child = mutate(child)
    return _normalize_genome(child)


def _make_walk_forward_slices(total_len: int, train_ratio: float = 0.70, test_ratio: float = 0.30, max_folds: int = MAX_WALK_FORWARD_FOLDS) -> list[tuple[slice, slice]]:
    if total_len < 500:
        return []
    train_len = max(260, int(total_len * train_ratio))
    test_len = max(120, int(total_len * test_ratio))
    if train_len + test_len > total_len:
        train_len = max(260, total_len - test_len)
    if train_len + test_len > total_len:
        return []
    folds: list[tuple[slice, slice]] = []
    step = max(test_len, test_len // 2)
    start = 0
    while start + train_len + test_len <= total_len and len(folds) < max_folds:
        folds.append((slice(start, start + train_len), slice(start + train_len, start + train_len + test_len)))
        start += step
    return folds


def _metric_score(metrics: dict, *, target_week: float) -> float:
    total = int(metrics.get("total_trades", 0) or 0)
    if total <= 0:
        return -5.0

    pf = _safe_float(metrics.get("profit_factor", 0.0), 0.0)
    wr = _safe_float(metrics.get("winrate", 0.0), 0.0)
    dd = _safe_float(metrics.get("max_drawdown_pct", 100.0), 100.0)
    pnl = _safe_float(metrics.get("total_pnl", 0.0), 0.0)
    bal = max(1.0, _safe_float(metrics.get("initial_balance", Config.INITIAL_BALANCE), Config.INITIAL_BALANCE))
    freq = _safe_float(metrics.get("trade_frequency_per_week", 0.0), 0.0)
    exp = _safe_float(metrics.get("expectancy", 0.0), 0.0)

    # Hard gates: amostra e qualidade mínima.
    if total < MIN_TEST_TRADES_PER_FOLD:
        return -4.5 - (MIN_TEST_TRADES_PER_FOLD - total) * 0.15
    if pf < 1.05:
        return -3.5 - (1.05 - pf) * 1.5
    if wr < 45.0:
        return -3.0 - (45.0 - wr) * 0.08
    if dd > 18.0:
        return -3.0 - (dd - 18.0) * 0.08
    if pnl <= 0:
        return -2.5 - abs(pnl) / max(1.0, bal * 0.02)

    profit_pct = pnl / bal
    return_score = _clamp(profit_pct / 0.20, -1.0, 2.0)          # 20% alvo como referência
    pf_score = _clamp((pf - 1.0) / 1.2, -1.0, 1.5)               # PF 2.2 já é excelente
    wr_score = _clamp((wr - 45.0) / 20.0, -1.0, 1.5)
    dd_score = _clamp(1.0 - dd / 18.0, 0.0, 1.0)
    freq_score = _clamp(1.0 - abs(freq - target_week) / max(1.0, target_week), 0.0, 1.0)
    exp_score = _clamp(exp / max(1.0, bal * 0.002), -1.0, 1.0)

    return (
        0.29 * return_score +
        0.26 * pf_score +
        0.16 * wr_score +
        0.15 * freq_score +
        0.10 * dd_score +
        0.04 * exp_score
    )


# ──────────────────────────────────────────────────────────────────────────────
# Avaliação
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GenerationResult:
    generation: int
    best_genome: Genome
    best_fitness: float
    best_train_metrics: dict
    best_test_metrics: dict
    population: list[Genome] = field(default_factory=list)


def _run_segment(
    bars,
    symbol: str,
    balance: float,
    genome: Genome,
    indicator_cache=None,
    h4_bias_map=None,
    prepared_bars: bool = False,
):
    kwargs = dict(
        bars=bars,
        symbol=symbol,
        initial_balance=balance,
        min_confluence=int(genome["MIN_CONFLUENCE"]),
        adx_min=float(genome["ADX_MIN"]),
        atr_sl_mult=float(genome["ATR_MULT_SL"]),
        atr_tp_mult=float(genome["ATR_MULT_TP"]),
        risk_pct=float(genome["RISK_PCT"]),
        warmup_bars=int(genome["WARMUP_BARS"]),
        weekly_trade_target=TARGET_TRADES_WEEK,
        max_bars_in_trade=int(genome["MAX_BARS_IN_TRADE"]),
        indicator_cache=indicator_cache,
        prepared_bars=prepared_bars,
        h4_bias_map=h4_bias_map,
    )
    if IS_M15:
        kwargs.update({
            "rsi_ob": float(genome["RSI_OB"]),
            "rsi_os": float(genome["RSI_OS"]),
        })
    else:
        kwargs.update({
            "pull_range": (float(genome["PULL_MIN"]), float(genome["PULL_MAX"])),
        })
    return run_backtest(**kwargs)


def _evaluate_on_single_symbol(
    genome: Genome,
    symbol: str,
    prepared: list,
    full_cache: list,
    folds: list[tuple[slice, slice]],
    balance: float,
) -> dict[str, Any]:
    empty = {
        "total_trades": 0,
        "winrate": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 100.0,
        "trade_frequency_per_week": 0.0,
        "total_pnl": 0.0,
        "expectancy": 0.0,
        "initial_balance": balance,
    }
    if len(prepared) < 350 or not folds:
        return {
            "fitness": -5.0,
            "primary_train": empty,
            "primary_test": empty,
            "folds": 0,
            "avg_test_trades": 0.0,
            "avg_train_trades": 0.0,
        }

    fold_scores: list[float] = []
    primary_train = None
    primary_test = None
    train_trades_total = 0
    test_trades_total = 0
    penalties = 0.0

    for fold_idx, (train_slice, test_slice) in enumerate(folds):
        train_bars = prepared[train_slice]
        test_bars = prepared[test_slice]
        train_cache = full_cache[train_slice]
        test_cache = full_cache[test_slice]
        h4_train = _build_h4_bias_map(train_bars) if (not IS_M15 and len(train_bars) >= 200) else None
        h4_test = _build_h4_bias_map(test_bars) if (not IS_M15 and len(test_bars) >= 200) else None

        try:
            train_bt = _run_segment(train_bars, symbol, balance, genome, train_cache, h4_train, True)
            test_bt = _run_segment(test_bars, symbol, balance, genome, test_cache, h4_test, True)
            train_m = train_bt.metrics
            test_m = test_bt.metrics
        except Exception as exc:
            log(f"[GENETIC] Erro em {symbol} fold {fold_idx}: {exc}")
            train_m = empty.copy()
            test_m = empty.copy()

        if primary_train is None:
            primary_train = train_m
            primary_test = test_m

        train_trades = int(train_m.get("total_trades", 0) or 0)
        test_trades = int(test_m.get("total_trades", 0) or 0)
        train_trades_total += train_trades
        test_trades_total += test_trades

        train_score = _metric_score(train_m, target_week=TARGET_TRADES_WEEK)
        test_score = _metric_score(test_m, target_week=TARGET_TRADES_WEEK)
        fold_scores.append(0.35 * train_score + 0.65 * test_score)

        if test_trades < MIN_TEST_TRADES_PER_FOLD:
            penalties += 0.5
        if train_trades < MIN_TRAIN_TRADES:
            penalties += 0.35

        pf_gap = abs(_safe_float(train_m.get("profit_factor", 0.0)) - _safe_float(test_m.get("profit_factor", 0.0)))
        wr_gap = abs(_safe_float(train_m.get("winrate", 0.0)) - _safe_float(test_m.get("winrate", 0.0)))
        dd_gap = abs(_safe_float(train_m.get("max_drawdown_pct", 0.0)) - _safe_float(test_m.get("max_drawdown_pct", 0.0)))
        penalties += min(0.35, pf_gap * 0.08)
        penalties += min(0.20, wr_gap * 0.005)
        penalties += min(0.15, dd_gap * 0.01)

    avg_train = train_trades_total / max(1, len(folds))
    avg_test = test_trades_total / max(1, len(folds))
    avg_score = sum(fold_scores) / len(fold_scores)
    consistency = 1.0
    if len(fold_scores) > 1:
        std = pstdev(fold_scores)
        consistency = _clamp(1.0 - std / 1.25, 0.0, 1.0)

    final_fitness = avg_score + 0.18 * consistency - penalties
    return {
        "fitness": final_fitness,
        "primary_train": primary_train or empty,
        "primary_test": primary_test or empty,
        "folds": len(folds),
        "avg_test_trades": avg_test,
        "avg_train_trades": avg_train,
    }


def _evaluate_genome(
    genome: Genome,
    prepared_map: dict[str, list],
    cache_map: dict[str, list],
    fold_map: dict[str, list],
    balance: float,
    primary: str,
) -> dict[str, Any]:
    symbol_scores: list[float] = []
    primary_train: dict | None = None
    primary_test: dict | None = None
    trade_penalty = 0.0

    for sym, prepared in prepared_map.items():
        ev = _evaluate_on_single_symbol(genome, sym, prepared, cache_map[sym], fold_map[sym], balance)
        symbol_scores.append(float(ev["fitness"]))
        trade_penalty += max(0.0, 1.0 - min(1.0, float(ev["avg_test_trades"]) / max(1.0, float(MIN_TEST_TRADES_PER_FOLD) * max(1, len(fold_map[sym])))))
        if sym == primary:
            primary_train = ev["primary_train"]
            primary_test = ev["primary_test"]

    if not symbol_scores:
        return {
            "fitness": -5.0,
            "train": {"total_trades": 0, "winrate": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 100.0, "trade_frequency_per_week": 0.0},
            "test": {"total_trades": 0, "winrate": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 100.0, "trade_frequency_per_week": 0.0},
        }

    avg_fitness = sum(symbol_scores) / len(symbol_scores)
    primary_f = symbol_scores[list(prepared_map.keys()).index(primary)] if primary in prepared_map else avg_fitness
    universe_pen = min(0.75, trade_penalty / max(1, len(symbol_scores)))
    combined = avg_fitness * 0.78 + primary_f * 0.22 - universe_pen

    return {
        "fitness": combined,
        "train": primary_train or {"total_trades": 0, "winrate": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 100.0, "trade_frequency_per_week": 0.0},
        "test": primary_test or {"total_trades": 0, "winrate": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 100.0, "trade_frequency_per_week": 0.0},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Evolução
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EvolutionState:
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


def _evolve_population(population: list[Genome], fitness_scores: list[float]) -> list[Genome]:
    paired = sorted(zip(population, fitness_scores), key=lambda x: x[1], reverse=True)
    elites = [copy.deepcopy(g) for g, _ in paired[:ELITE_COUNT]]
    new_population = elites[:]

    # Mantém diversidade: parte elitista + mutações próximas + imigrantes aleatórios.
    while len(new_population) < POPULATION_SIZE:
        if len(new_population) < ELITE_COUNT + max(3, POPULATION_SIZE // 3):
            p1 = _tournament(population, fitness_scores)
            if random.random() < 0.5:
                child = mutate(p1)
            else:
                p2 = _tournament(population, fitness_scores)
                child = crossover(p1, p2)
        else:
            child = random_genome()
        new_population.append(child)

    return new_population[:POPULATION_SIZE]


def _seed_population() -> list[Genome]:
    seeds: list[Genome] = []
    base = _base_genome()
    seeds.append(base)

    if IS_M15:
        seeds.extend([
            _normalize_genome({**base, "MIN_CONFLUENCE": 2, "ADX_MIN": 16, "ATR_MULT_SL": 0.95, "ATR_MULT_TP": 2.35, "RSI_OB": 72, "RSI_OS": 30, "MAX_BARS_IN_TRADE": 14}),
            _normalize_genome({**base, "MIN_CONFLUENCE": 3, "ADX_MIN": 20, "ATR_MULT_SL": 1.15, "ATR_MULT_TP": 2.80, "RSI_OB": 68, "RSI_OS": 34, "MAX_BARS_IN_TRADE": 20}),
            _normalize_genome({**base, "MIN_CONFLUENCE": 4, "ADX_MIN": 22, "ATR_MULT_SL": 1.25, "ATR_MULT_TP": 3.00, "RSI_OB": 66, "RSI_OS": 36, "MAX_BARS_IN_TRADE": 24}),
        ])
    else:
        seeds.extend([
            _normalize_genome({**base, "MIN_CONFLUENCE": 2, "ADX_MIN": 16, "ATR_MULT_SL": 1.00, "ATR_MULT_TP": 2.40, "PULL_MIN": -1.30, "PULL_MAX": 1.20, "MAX_BARS_IN_TRADE": 24}),
            _normalize_genome({**base, "MIN_CONFLUENCE": 3, "ADX_MIN": 20, "ATR_MULT_SL": 1.15, "ATR_MULT_TP": 2.90, "PULL_MIN": -0.95, "PULL_MAX": 1.60, "MAX_BARS_IN_TRADE": 32}),
            _normalize_genome({**base, "MIN_CONFLUENCE": 4, "ADX_MIN": 24, "ATR_MULT_SL": 1.30, "ATR_MULT_TP": 3.30, "PULL_MIN": -0.75, "PULL_MAX": 1.85, "MAX_BARS_IN_TRADE": 40}),
        ])

    while len(seeds) < POPULATION_SIZE:
        if random.random() < 0.6:
            seeds.append(random_genome())
        else:
            seeds.append(mutate(random.choice(seeds)))
    return seeds[:POPULATION_SIZE]


def run_evolution(
    bars: list | dict[str, list],
    symbol: str,
    balance: float,
    generations: int = 80,
    extra_datasets: dict[str, list] | None = None,
) -> list[GenerationResult]:
    if isinstance(bars, dict):
        datasets: dict[str, list] = {str(k).upper(): list(v) for k, v in bars.items() if v}
    else:
        datasets = {symbol.upper(): list(bars)}

    if extra_datasets:
        for k, v in extra_datasets.items():
            if v:
                datasets[str(k).upper()] = list(v)

    primary = symbol.upper()
    universe = _unique_preserve_order([primary] + [s.upper() for s in SYMBOL_PEERS.get(primary, [])])
    datasets = {k: datasets[k] for k in universe if k in datasets}

    if primary not in datasets:
        if datasets:
            primary = next(iter(datasets.keys()))
        else:
            raise ValueError("Nenhum histórico válido para o símbolo principal")

    log("[GENETIC] Pré-calculando indicadores e janelas walk-forward...")
    prepared_map: dict[str, list] = {}
    cache_map: dict[str, list] = {}
    fold_map: dict[str, list] = {}

    for sym, data in datasets.items():
        prepared = prepare_bars_for_backtest(data)
        if len(prepared) < 350:
            log(f"[GENETIC] {sym}: apenas {len(prepared)} barras — ignorado (mín. 350)")
            continue
        folds = _make_walk_forward_slices(len(prepared), max_folds=MAX_WALK_FORWARD_FOLDS)
        if not folds:
            split = int(len(prepared) * 0.70)
            folds = [(slice(0, split), slice(split, len(prepared)))]
            log(f"[GENETIC] {sym}: usando split 70/30")
        prepared_map[sym] = prepared
        cache_map[sym] = build_indicator_cache(prepared)
        fold_map[sym] = folds

    if primary not in prepared_map:
        raise ValueError(f"Histórico insuficiente para {primary} (mín. 350 barras)")

    log(f"[GENETIC] Universo: {list(prepared_map.keys())} | {len(prepared_map)} par(es)")
    population = _seed_population()
    results: list[GenerationResult] = []

    for gen in range(1, generations + 1):
        log(f"[GENETIC] Geração {gen}/{generations} — avaliando {len(population)} genomas...")
        fitness_scores: list[float] = []
        train_metrics_list: list[dict] = []
        test_metrics_list: list[dict] = []

        for genome in population:
            ev = _evaluate_genome(genome, prepared_map, cache_map, fold_map, balance, primary)
            fitness_scores.append(float(ev["fitness"]))
            train_metrics_list.append(ev["train"])
            test_metrics_list.append(ev["test"])

        best_idx = max(range(len(population)), key=lambda i: fitness_scores[i])
        best_g = population[best_idx]
        best_f = fitness_scores[best_idx]
        best_train = train_metrics_list[best_idx]
        best_test = test_metrics_list[best_idx]

        log(
            f"[GENETIC] Gen {gen}: fitness={best_f:.3f} | "
            f"WR(t)={best_test.get('winrate', 0)}% | PF(t)={best_test.get('profit_factor', 0)} | "
            f"DD(t)={best_test.get('max_drawdown_pct', 0)}% | Trades(t)={best_test.get('total_trades', 0)}"
        )

        results.append(GenerationResult(
            generation=gen,
            best_genome=copy.deepcopy(best_g),
            best_fitness=best_f,
            best_train_metrics=best_train,
            best_test_metrics=best_test,
            population=list(population),
        ))

        population = _evolve_population(population, fitness_scores)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Persistência / CLI
# ──────────────────────────────────────────────────────────────────────────────

def save_best_genome(result: GenerationResult, path: str = "best_genome.json"):
    data = {
        "generation": result.generation,
        "fitness": round(result.best_fitness, 4),
        "genome": result.best_genome,
        "train_metrics": result.best_train_metrics,
        "test_metrics": result.best_test_metrics,
        "generated_at": datetime.now().isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    log(f"[GENETIC] Melhor genoma salvo em {path}")


def main():
    parser = argparse.ArgumentParser(description="Otimizador genético robusto")
    parser.add_argument("csv", help="CSV com OHLC histórico")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--universe", default="", help="Pares extra separados por vírgula")
    parser.add_argument("--balance", type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--generations", type=int, default=80)
    parser.add_argument("--output", default="best_genome.json")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido no CSV.")

    extra: dict[str, list] = {}
    if args.universe.strip():
        for s in (x.strip().upper() for x in args.universe.split(",") if x.strip()):
            if s != args.symbol.upper():
                extra[s] = bars

    log(f"[GENETIC] {len(bars)} barras | {args.symbol} | {args.generations} gerações")
    results = run_evolution(
        bars if not extra else {args.symbol.upper(): bars, **extra},
        args.symbol,
        args.balance,
        args.generations,
    )

    overall_best = max(results, key=lambda r: r.best_fitness)
    save_best_genome(overall_best, args.output)

    g = overall_best.best_genome
    test_m = overall_best.best_test_metrics
    train_m = overall_best.best_train_metrics

    # Settings compatíveis com o bot ao vivo.
    saved_settings = {
        "profile": "trend_pullback",
        "timeframe": TF if TF in {"M15", "H1"} else "M15",
        "min_confluence": int(g["MIN_CONFLUENCE"]),
        "adx_min": float(g["ADX_MIN"]),
        "atr_sl_mult": float(g["ATR_MULT_SL"]),
        "atr_tp_mult": float(g["ATR_MULT_TP"]),
        "risk_pct": float(g["RISK_PCT"]),
        "warmup_bars": int(g["WARMUP_BARS"]),
        "max_bars_in_trade": int(g["MAX_BARS_IN_TRADE"]),
        "optimization_mode": "robust_trend_pullback",
        "weekly_trade_target": round(_safe_float(test_m.get("trade_frequency_per_week", TARGET_TRADES_WEEK), TARGET_TRADES_WEEK), 2),
        "min_rr": round(float(g["ATR_MULT_TP"]) / max(1e-6, float(g["ATR_MULT_SL"])), 2),
    }
    if IS_M15:
        saved_settings.update({
            "rsi_ob": float(g["RSI_OB"]),
            "rsi_os": float(g["RSI_OS"]),
        })
    else:
        saved_settings.update({
            "pull_min": float(g["PULL_MIN"]),
            "pull_max": float(g["PULL_MAX"]),
        })

    try:
        save_strategy_settings(saved_settings)
    except Exception as e:
        log(f"[GENETIC] Falha ao salvar strategy_settings.json: {e}")

    print()
    print("═" * 54)
    print("  MELHOR CONFIGURAÇÃO ENCONTRADA")
    print("═" * 54)
    for k, v in overall_best.best_genome.items():
        print(f"  {k:<22} = {v}")
    print("─" * 54)
    print(f"  Fitness:   {overall_best.best_fitness:.4f}")
    print(f"  Train WR:  {train_m.get('winrate', 0)}%")
    print(f"  Test WR:   {test_m.get('winrate', 0)}%")
    print(f"  Test PF:   {test_m.get('profit_factor', 0)}")
    print(f"  Test DD:   {test_m.get('max_drawdown_pct', 0)}%")
    print(f"  Trades:    {test_m.get('total_trades', 0)}")
    print(f"  Trades/wk: {test_m.get('trade_frequency_per_week', 0)}")
    print("═" * 54)


if __name__ == "__main__":
    main()
