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
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backtester import load_bars_from_csv, run_backtest, build_indicator_cache, prepare_bars_for_backtest, _build_h4_bias_map
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
    "MIN_CONFLUENCE": (4, 8),
    "ADX_MIN": (16, 34),
    "ATR_MULT_SL": (0.8, 1.8),
    "ATR_MULT_TP": (1.1, 2.8),
    "PULL_MIN": (-1.8, -0.2),
    "PULL_MAX": (0.3, 2.0),
    "RISK_PCT": (0.2, 1.2),
    "WEEKLY_TARGET": (1.0, 6.0),
    "MIN_RR": (0.8, 2.2),
    "WARMUP_BARS": (60, 240),
    "MAX_BARS_IN_TRADE": (8, 96),
}

def _get_tf() -> str:
    return str(getattr(Config, "TIMEFRAME", "M15")).strip().lower()

def _is_m15_mode() -> bool:
    return _get_tf() in {"m15", "15m", "15min", "15"}

def _is_h1_mode() -> bool:
    return _get_tf() in {"h1", "1h", "60m", "60"}


if _is_m15_mode():
    # M15: seletivo, buscando qualidade e evitando entradas frenéticas
    RANGES["MIN_CONFLUENCE"] = (5, 8)
    RANGES["ADX_MIN"]        = (18, 32)
    RANGES["ATR_MULT_SL"]    = (0.7, 1.4)
    RANGES["ATR_MULT_TP"]    = (1.1, 2.2)
    RANGES["PULL_MIN"]       = (-1.4, -0.15)
    RANGES["PULL_MAX"]       = (0.25, 1.6)
    RANGES["RISK_PCT"]       = (0.2, 0.9)
    RANGES["WEEKLY_TARGET"]  = (2.0, 10.0)
    RANGES["MIN_RR"]         = (0.8, 1.8)
    RANGES["WARMUP_BARS"]    = (100, 260)
    RANGES["MAX_BARS_IN_TRADE"] = (8, 36)
elif _is_h1_mode():
    RANGES["MIN_CONFLUENCE"] = (5, 8)
    RANGES["ADX_MIN"]        = (20, 36)
    RANGES["ATR_MULT_SL"]    = (0.9, 1.6)
    RANGES["ATR_MULT_TP"]    = (1.0, 2.1)
    RANGES["PULL_MIN"]       = (-1.3, -0.1)
    RANGES["PULL_MAX"]       = (0.25, 1.4)
    RANGES["RISK_PCT"]       = (0.2, 0.8)
    RANGES["WEEKLY_TARGET"]  = (0.8, 3.0)
    RANGES["MIN_RR"]         = (0.8, 1.6)
    RANGES["WARMUP_BARS"]    = (100, 260)
    RANGES["MAX_BARS_IN_TRADE"] = (12, 72)


# Pares correlacionados usados na validação multi-pair (quando disponíveis via API).
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

POPULATION_SIZE    = 16
ELITE_COUNT        = 4
MUTATION_RATE      = 0.22
TOURNAMENT_SIZE    = 4
# FIX #3: MIN_TRADES reduzido — 24 era muito agressivo para folds walk-forward menores
# M15 gera muito mais trades por janela — MIN_TRADES maior é razoável
MIN_TRADES         = 24 if _is_m15_mode() else (12 if _is_h1_mode() else 10)
TARGET_TRADES_WEEK = 8.0 if _is_m15_mode() else (2.5 if _is_h1_mode() else 3.0)
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


def _make_walk_forward_slices(
    total_len: int,
    train_ratio: float = 0.60,
    test_ratio: float = 0.20,
    max_folds: int = MAX_WALK_FORWARD_FOLDS,
) -> list[tuple[slice, slice]]:
    """Gera janelas cronológicas rolantes para walk-forward."""
    if total_len < 400:
        return []

    train_len = max(220, int(total_len * train_ratio))
    test_len  = max(100, int(total_len * test_ratio))
    if train_len + test_len > total_len:
        train_len = max(220, total_len - test_len)
    if train_len + test_len > total_len:
        return []

    step = max(60, test_len)
    folds: list[tuple[slice, slice]] = []
    start = 0
    while start + train_len + test_len <= total_len and len(folds) < max_folds:
        folds.append((
            slice(start, start + train_len),
            slice(start + train_len, start + train_len + test_len),
        ))
        start += step
    return folds


def _run_segment(
    bars,
    symbol: str,
    balance: float,
    genome: Genome,
    indicator_cache=None,
    h4_bias_map=None,
    prepared_bars: bool = False,
):
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
        prepared_bars=prepared_bars,
        h4_bias_map=h4_bias_map,
    )


def _metric_score(metrics: dict, target_trades_week: float) -> float:
    total = int(metrics.get("total_trades", 0) or 0)
    if total <= 0:
        return -1.0

    pf  = _safe_float(metrics.get("profit_factor", 0.0), 0.0)
    wr  = _safe_float(metrics.get("winrate", 0.0), 0.0) / 100.0
    dd  = _safe_float(metrics.get("max_drawdown_pct", 100.0), 100.0) / 100.0
    exp = _safe_float(metrics.get("expectancy", 0.0), 0.0)
    pnl = _safe_float(metrics.get("total_pnl", 0.0), 0.0)
    initial_balance = max(1.0, _safe_float(metrics.get("initial_balance", Config.INITIAL_BALANCE), Config.INITIAL_BALANCE))
    freq = _safe_float(metrics.get("trade_frequency_per_week", 0.0), 0.0)

    pf_score   = min(max(pf, 0.0), 3.0) / 3.0
    dd_score   = max(0.0, 1.0 - min(dd, 0.35) / 0.35)
    pnl_score  = max(-1.0, min(1.0, pnl / (initial_balance * 0.25)))
    exp_score  = max(-1.0, min(1.0, exp / max(1.0, initial_balance * 0.01)))
    freq_score = max(0.0, 1.0 - abs(freq - target_trades_week) / max(1.0, target_trades_week))

    # Calcula retorno mensal estimado (normalizado a 0-1)
    # Alvo: 20-30% ao mês com saldo de $1000 = $200-300
    monthly_return_target = 0.25  # 25% = ponto ideal
    monthly_days = 21.0           # dias úteis de trading
    freq_day = freq / 5.0 if freq > 0 else 0.0   # trades/dia
    exp_pct_per_trade = exp / max(1.0, initial_balance) if exp > 0 else 0.0
    est_monthly_return = freq_day * monthly_days * exp_pct_per_trade
    monthly_score = max(0.0, min(1.0, est_monthly_return / monthly_return_target))

    return (
        0.22 * pf_score +
        0.15 * wr +
        0.15 * dd_score +
        0.18 * freq_score +        # frequência tem peso maior agora
        0.15 * monthly_score +     # retorno mensal estimado
        0.08 * (exp_score + 1) / 2 +
        0.07 * (pnl_score + 1) / 2
    )


def fitness(genome: Genome, train_metrics: dict, test_metrics: dict) -> float:
    train_trades = int(train_metrics.get("total_trades", 0) or 0)
    test_trades  = int(test_metrics.get("total_trades", 0) or 0)
    min_test     = max(10, MIN_TRADES // 2)

    if train_trades < MIN_TRADES or test_trades < min_test:
        return -8.0

    target_week = float(genome.get("WEEKLY_TARGET", TARGET_TRADES_WEEK) or TARGET_TRADES_WEEK)
    train_score = _metric_score(train_metrics, target_week)
    test_score  = _metric_score(test_metrics,  target_week)

    train_pf = _safe_float(train_metrics.get("profit_factor", 0.0), 0.0)
    test_pf  = _safe_float(test_metrics.get("profit_factor", 0.0), 0.0)
    train_dd = _safe_float(train_metrics.get("max_drawdown_pct", 100.0), 100.0)
    test_dd  = _safe_float(test_metrics.get("max_drawdown_pct", 100.0), 100.0)
    train_wr = _safe_float(train_metrics.get("winrate", 0.0), 0.0)
    test_wr  = _safe_float(test_metrics.get("winrate", 0.0), 0.0)
    train_sh = _safe_float(train_metrics.get("sharpe_ratio", 0.0), 0.0)
    test_sh  = _safe_float(test_metrics.get("sharpe_ratio", 0.0), 0.0)
    train_exp = _safe_float(train_metrics.get("expectancy", 0.0), 0.0)
    test_exp  = _safe_float(test_metrics.get("expectancy", 0.0), 0.0)

    # Estratégia perdedora é descartada cedo.
    wr_floor = 40.0 if (_is_m15_mode() or _is_h1_mode()) else 35.0
    pf_floor = 1.03
    dd_limit = 12.0 if _is_m15_mode() else (15.0 if _is_h1_mode() else 22.0)

    if train_pf < pf_floor or test_pf < pf_floor:
        return -8.0 - abs(min(train_pf, test_pf) - pf_floor)
    if train_wr < wr_floor or test_wr < wr_floor:
        return -7.0 - (wr_floor - min(train_wr, test_wr)) / 10.0
    if train_exp <= 0 or test_exp <= 0:
        return -6.0

    dd_penalty = 0.0
    if max(train_dd, test_dd) > dd_limit:
        dd_penalty += min(1.5, (max(train_dd, test_dd) - dd_limit) / dd_limit)

    sh_penalty = 0.0
    if train_sh < 0 or test_sh < 0:
        sh_penalty += 0.5 + abs(min(train_sh, test_sh)) * 0.1

    robustness = 1.0 - min(1.0, abs(train_score - test_score))
    pf_gap = min(1.0, abs(train_pf - test_pf) / 2.0)
    wr_gap = min(1.0, abs(train_wr - test_wr) / 30.0)
    trade_balance = min(1.0, test_trades / max(1.0, train_trades))

    raw = (
        0.34 * test_score +
        0.18 * train_score +
        0.16 * robustness +
        0.12 * (1.0 - pf_gap) +
        0.08 * (1.0 - wr_gap) +
        0.08 * trade_balance +
        0.04 * max(0.0, min(1.0, test_sh / 3.0))
    )
    raw -= (0.14 * dd_penalty) + (0.10 * sh_penalty)

    # Bônus para tração com frequência adequada, mas sem overtrade.
    freq = _safe_float(test_metrics.get("trade_frequency_per_week", 0.0), 0.0)
    freq_target = max(1.0, target_week)
    freq_score = max(0.0, 1.0 - abs(freq - freq_target) / freq_target)
    raw += 0.04 * freq_score


def live_viability_reason(train_metrics: dict, test_metrics: dict) -> tuple[bool, str]:
    train_trades = int(train_metrics.get("total_trades", 0) or 0)
    test_trades = int(test_metrics.get("total_trades", 0) or 0)
    train_pf = _safe_float(train_metrics.get("profit_factor", 0.0), 0.0)
    test_pf = _safe_float(test_metrics.get("profit_factor", 0.0), 0.0)
    train_wr = _safe_float(train_metrics.get("winrate", 0.0), 0.0)
    test_wr = _safe_float(test_metrics.get("winrate", 0.0), 0.0)
    train_dd = _safe_float(train_metrics.get("max_drawdown_pct", 100.0), 100.0)
    test_dd = _safe_float(test_metrics.get("max_drawdown_pct", 100.0), 100.0)
    train_exp = _safe_float(train_metrics.get("expectancy", 0.0), 0.0)
    test_exp = _safe_float(test_metrics.get("expectancy", 0.0), 0.0)

    wr_floor = 40.0 if (_is_m15_mode() or _is_h1_mode()) else 35.0
    pf_floor = 1.05
    dd_limit = 12.0 if _is_m15_mode() else (15.0 if _is_h1_mode() else 22.0)
    min_trades = 25 if _is_m15_mode() else (18 if _is_h1_mode() else 10)

    if train_trades < max(MIN_TRADES, min_trades) or test_trades < min_trades:
        return False, "poucas operações"
    if train_pf < pf_floor or test_pf < pf_floor:
        return False, "profit factor insuficiente"
    if train_wr < wr_floor or test_wr < wr_floor:
        return False, "win rate abaixo do mínimo"
    if train_exp <= 0 or test_exp <= 0:
        return False, "expectancy negativa"
    if max(train_dd, test_dd) > dd_limit:
        return False, "drawdown acima do limite"

    return True, "ok"


def select_best_live_result(results: list[GenerationResult]) -> tuple[GenerationResult, bool, str]:
    if not results:
        raise ValueError("Nenhum resultado de otimização disponível.")
    viable = [r for r in results if live_viability_reason(r.best_train_metrics, r.best_test_metrics)[0]]
    if viable:
        best = max(viable, key=lambda r: r.best_fitness)
        return best, True, "ok"
    best = max(results, key=lambda r: r.best_fitness)
    _, reason = live_viability_reason(best.best_train_metrics, best.best_test_metrics)
    return best, False, reason

# ─── Avaliação de um genoma em walk-forward (serial, sem global state) ─────────
# FIX #1 + #2: Removido ProcessPoolExecutor e global _GENETIC_WORKER_CTX.
# Toda avaliação agora é serial e recebe o contexto diretamente como argumento.
# Isso corrige o bug onde o contexto ficava vazio no fallback serial,
# retornando fitness -5.0 para todos os genomas.

def _evaluate_genome(
    genome: Genome,
    prepared_map: dict[str, list],
    cache_map: dict[str, list],
    fold_map: dict[str, list],
    balance: float,
    primary: str,
) -> dict[str, Any]:
    """
    Avalia um genoma em todos os pares do universo e retorna fitness combinado.
    Contexto passado diretamente — sem global state, sem multiprocessing.
    """
    symbol_scores: list[float] = []
    primary_train: dict | None = None
    primary_test:  dict | None = None
    trade_penalty = 0.0

    for sym, prepared in prepared_map.items():
        ev = _evaluate_on_single_symbol(
            genome, sym, prepared, cache_map[sym], fold_map[sym], balance
        )
        symbol_scores.append(float(ev["fitness"]))
        trade_penalty += max(0.0, 1.0 - min(1.0, float(ev["avg_test_trades"]) / float(MIN_TRADES)))
        if sym == primary:
            primary_train = ev["primary_train"]
            primary_test  = ev["primary_test"]

    if not symbol_scores:
        empty = {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
        return {"fitness": -5.0, "train": empty, "test": empty}

    avg_fitness   = sum(symbol_scores) / len(symbol_scores)
    universe_pen  = min(0.40, trade_penalty / max(1, len(symbol_scores)))
    primary_f     = symbol_scores[list(prepared_map.keys()).index(primary)] if primary in prepared_map else avg_fitness

    combined = avg_fitness * 0.80 + primary_f * 0.20 - universe_pen

    train_m = primary_train or {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}
    test_m  = primary_test  or train_m.copy()
    return {"fitness": combined, "train": train_m, "test": test_m}


def _evaluate_on_single_symbol(
    genome: Genome,
    symbol: str,
    prepared: list,
    full_cache: list,
    folds: list[tuple[slice, slice]],
    balance: float,
) -> dict[str, Any]:
    """Avalia um genoma em walk-forward cronológico dentro de um único par."""
    empty = {"total_trades": 0, "winrate": 0, "profit_factor": 0, "max_drawdown_pct": 100, "trade_frequency_per_week": 0}

    if len(prepared) < 300 or not folds:
        return {"fitness": -5.0, "primary_train": empty, "primary_test": empty, "folds": 0, "avg_test_trades": 0.0, "avg_train_trades": 0.0}

    fold_scores: list[float] = []
    primary_train: dict | None = None
    primary_test:  dict | None = None
    train_trades_total = 0
    test_trades_total  = 0
    penalty_total      = 0.0

    for fold_idx, (train_slice, test_slice) in enumerate(folds):
        train_bars  = prepared[train_slice]
        test_bars   = prepared[test_slice]
        train_cache = full_cache[train_slice]
        test_cache  = full_cache[test_slice]

        h4_train = _build_h4_bias_map(train_bars) if len(train_bars) >= 200 else None
        h4_test  = _build_h4_bias_map(test_bars)  if len(test_bars)  >= 200 else None

        try:
            train_bt = _run_segment(train_bars, symbol, balance, genome, train_cache, h4_train, True)
            test_bt  = _run_segment(test_bars,  symbol, balance, genome, test_cache,  h4_test,  True)
            train_m  = train_bt.metrics
            test_m   = test_bt.metrics
        except Exception as e:
            log(f"[GENETIC] Erro no fold {fold_idx} de {symbol}: {e}")
            train_m = empty.copy()
            test_m  = empty.copy()

        train_trades = int(train_m.get("total_trades", 0) or 0)
        test_trades  = int(test_m.get("total_trades", 0) or 0)
        train_trades_total += train_trades
        test_trades_total  += test_trades

        if primary_train is None:
            primary_train = train_m
            primary_test  = test_m

        fold_f = fitness(genome, train_m, test_m)
        fold_scores.append(fold_f)

        # Penalidade suave por falta de trades — não agressiva
        min_test_trades = max(6, MIN_TRADES // 2)
        if train_trades < MIN_TRADES:
            penalty_total += 0.3
        if test_trades < min_test_trades:
            penalty_total += 0.2

        pf_gap = abs(
            _safe_float(train_m.get("profit_factor", 0.0), 0.0) -
            _safe_float(test_m.get("profit_factor", 0.0), 0.0)
        )
        if pf_gap > 1.5:
            penalty_total += min(0.2, (pf_gap - 1.5) / 10.0)

    avg_score       = sum(fold_scores) / max(1, len(fold_scores))
    avg_train       = train_trades_total / max(1, len(folds))
    avg_test        = test_trades_total  / max(1, len(folds))
    robustness_bonus = max(0.0, 1.0 - min(1.0, penalty_total / max(1, len(folds))))
    final_fitness   = avg_score * 0.85 + robustness_bonus * 0.15

    return {
        "fitness": final_fitness,
        "primary_train": primary_train or empty,
        "primary_test":  primary_test  or empty,
        "folds": len(folds),
        "avg_test_trades": avg_test,
        "avg_train_trades": avg_train,
    }


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

    paired  = sorted(zip(population, fitness_scores), key=lambda x: x[1], reverse=True)
    elites  = [copy.deepcopy(g) for g, _ in paired[:ELITE_COUNT]]
    new_pop = elites[:]
    while len(new_pop) < POPULATION_SIZE:
        p1    = _tournament(population, fitness_scores)
        p2    = _tournament(population, fitness_scores)
        child = crossover(p1, p2)
        new_pop.append(child)
    return new_pop[:POPULATION_SIZE]


def run_evolution(
    bars: list | dict[str, list],
    symbol: str,
    balance: float,
    generations: int = 20,
    extra_datasets: dict[str, list] | None = None,
) -> list[GenerationResult]:
    """
    Executa a evolução genética em modo serial walk-forward.

    FIX #1/#2: Removido ProcessPoolExecutor.
    Railway/containers não têm múltiplos CPUs livres e o multiprocessing
    causava falha silenciosa que deixava o contexto global vazio,
    fazendo todos os genomas retornarem fitness -5.0.
    """
    # ── Monta o universo de pares ─────────────────────────────────────────────
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

    # ── Pré-calcula indicadores e folds walk-forward ──────────────────────────
    log("[GENETIC] Pré-calculando indicadores e janelas walk-forward...")
    prepared_map: dict[str, list] = {}
    cache_map:    dict[str, list] = {}
    fold_map:     dict[str, list] = {}

    for sym, data in datasets.items():
        prepared = prepare_bars_for_backtest(data)
        if len(prepared) < 300:
            log(f"[GENETIC] {sym}: apenas {len(prepared)} barras — ignorado (mín. 300)")
            continue
        folds = _make_walk_forward_slices(len(prepared), max_folds=MAX_WALK_FORWARD_FOLDS)
        if not folds:
            # Fallback: split simples 70/30 quando dados insuficientes para walk-forward
            split = int(len(prepared) * 0.70)
            folds = [(slice(0, split), slice(split, len(prepared)))]
            log(f"[GENETIC] {sym}: dados insuficientes para walk-forward — usando split 70/30")
        prepared_map[sym] = prepared
        cache_map[sym]    = build_indicator_cache(prepared)
        fold_map[sym]     = folds

    if primary not in prepared_map:
        raise ValueError(f"Histórico insuficiente para {primary} (mín. 300 barras)")

    n_pairs = len(prepared_map)
    log(f"[GENETIC] Universo: {list(prepared_map.keys())} | {n_pairs} par(es) | serial mode")

    # ── Loop evolutivo ─────────────────────────────────────────────────────────
    population: list[Genome] = [random_genome() for _ in range(POPULATION_SIZE)]
    results: list[GenerationResult] = []

    for gen in range(1, generations + 1):
        log(f"[GENETIC] Geração {gen}/{generations} — avaliando {len(population)} genomas em {n_pairs} par(es)...")

        fitness_scores:     list[float] = []
        train_metrics_list: list[dict]  = []
        test_metrics_list:  list[dict]  = []

        for genome in population:
            # FIX #1: contexto passado diretamente — sem global dict
            ev = _evaluate_genome(genome, prepared_map, cache_map, fold_map, balance, primary)
            fitness_scores.append(float(ev["fitness"]))
            train_metrics_list.append(ev["train"])
            test_metrics_list.append(ev["test"])

        best_idx   = fitness_scores.index(max(fitness_scores))
        best_g     = population[best_idx]
        best_f     = fitness_scores[best_idx]
        best_train = train_metrics_list[best_idx]
        best_test  = test_metrics_list[best_idx]

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

        population = evolve(population, fitness_scores)

    return results


def save_best_genome(result: GenerationResult, path: str = "best_genome.json") -> bool:
    live_ok, reason = live_viability_reason(result.best_train_metrics, result.best_test_metrics)
    data = {
        "generation": result.generation,
        "fitness": round(result.best_fitness, 4),
        "genome": result.best_genome,
        "train_metrics": result.best_train_metrics,
        "test_metrics": result.best_test_metrics,
        "live_viable": live_ok,
        "live_viability_reason": reason,
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    if live_ok:
        saved_settings = {
            "profile": "hedge_fund",
            "min_confluence":       int(result.best_genome["MIN_CONFLUENCE"]),
            "adx_min":              float(result.best_genome["ADX_MIN"]),
            "atr_sl_mult":          float(result.best_genome["ATR_MULT_SL"]),
            "atr_tp_mult":          float(result.best_genome["ATR_MULT_TP"]),
            "pull_min":             float(result.best_genome["PULL_MIN"]),
            "pull_max":             float(result.best_genome["PULL_MAX"]),
            "risk_pct":             float(result.best_genome["RISK_PCT"]),
            "weekly_trade_target":  float(result.best_genome["WEEKLY_TARGET"]),
            "min_rr":               float(result.best_genome["MIN_RR"]),
            "warmup_bars":          int(result.best_genome["WARMUP_BARS"]),
            "max_bars_in_trade":    int(result.best_genome["MAX_BARS_IN_TRADE"]),
            "optimization_mode": "robust",
        }
        try:
            save_strategy_settings(saved_settings)
            log(f"[GENETIC] Melhor genoma salvo em {path} e aplicado ao strategy_settings.json")
        except Exception as e:
            log(f"[GENETIC] Falha ao salvar strategy_settings.json: {e}")
        return True

    log(f"[GENETIC] Melhor genoma salvo em {path}, mas NÃO aplicado: {reason}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Otimizador robusto do Sniper Bot")
    parser.add_argument("csv", help="CSV com OHLC histórico")
    parser.add_argument("--symbol",      default="EURUSD")
    parser.add_argument("--universe",    default="", help="Pares extra separados por vírgula")
    parser.add_argument("--balance",     type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--generations", type=int,   default=20)
    parser.add_argument("--output",      default="best_genome.json")
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
        args.symbol, args.balance, args.generations,
    )

    overall_best, live_ok, reason = select_best_live_result(results)
    save_best_genome(overall_best, args.output)
    if not live_ok:
        log(f"[GENETIC] Nenhum genoma atingiu os critérios mínimos de live: {reason}")

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
