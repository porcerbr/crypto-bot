"""
genetic_optimizer.py — Otimizador genético integrado com o backtester real.

Otimiza os parâmetros de confluência e risco rodando backtests reais
sobre dados históricos e evoluindo gerações via seleção + crossover.

Uso:
    python genetic_optimizer.py EURUSD.csv --symbol EURUSD --generations 20
"""

from __future__ import annotations

import argparse
import copy
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backtester import load_bars_from_csv, run_backtest
from config import Config
from utils import log


# ═══════════════════════════════════════════════════════════════════════════════
# ESPAÇO DE BUSCA
# ═══════════════════════════════════════════════════════════════════════════════

GENOME_KEYS = [
    "MIN_CONFLUENCE",
    "ADX_MIN",
    "ATR_MULT_SL",
    "ATR_MULT_TP",
    "MIN_RR",
    "RISK_PCT",
]

RANGES: dict[str, tuple] = {
    "MIN_CONFLUENCE": (4,   10),
    "ADX_MIN":        (15,  35),
    "ATR_MULT_SL":    (1.0, 3.0),
    "ATR_MULT_TP":    (2.0, 5.0),
    "MIN_RR":         (1.5, 3.5),
    "RISK_PCT":       (0.5, 3.0),
}

POPULATION_SIZE = 12
ELITE_COUNT     = 3
MUTATION_RATE   = 0.25


# ═══════════════════════════════════════════════════════════════════════════════
# GENOMA
# ═══════════════════════════════════════════════════════════════════════════════

Genome = dict[str, Any]


def _rand_gene(key: str) -> float | int:
    lo, hi = RANGES[key]
    if isinstance(lo, int) and isinstance(hi, int):
        return random.randint(lo, hi)
    return round(random.uniform(lo, hi), 2)


def random_genome() -> Genome:
    return {k: _rand_gene(k) for k in GENOME_KEYS}


def crossover(g1: Genome, g2: Genome) -> Genome:
    child: Genome = {}
    for k in GENOME_KEYS:
        child[k] = g1[k] if random.random() < 0.5 else g2[k]
    # Mutação
    for k in GENOME_KEYS:
        if random.random() < MUTATION_RATE:
            child[k] = _rand_gene(k)
    # Garante limites
    for k in GENOME_KEYS:
        lo, hi = RANGES[k]
        child[k] = max(lo, min(hi, child[k]))
    return child


# ═══════════════════════════════════════════════════════════════════════════════
# FITNESS
# ═══════════════════════════════════════════════════════════════════════════════

def fitness(genome: Genome, metrics: dict) -> float:
    """
    Função de fitness multi-objetivo:
      60% Profit Factor (qualidade das operações)
      20% Win Rate (consistência)
      20% Penalidade por drawdown (controle de risco)

    Requer mínimo de 10 trades para ser considerado válido.
    """
    total = metrics.get("total_trades", 0)
    if total < 10:
        return -1.0  # penaliza genomas que geram poucos trades

    pf  = float(metrics.get("profit_factor", 0) or 0)
    wr  = metrics.get("winrate", 0) / 100.0
    dd  = metrics.get("max_drawdown_pct", 100) / 100.0

    pf_capped = min(pf, 5.0) / 5.0   # normaliza entre 0 e 1
    dd_penalty = max(0.0, 1.0 - dd * 2)   # dd de 50% → penalty = 0

    return 0.60 * pf_capped + 0.20 * wr + 0.20 * dd_penalty


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR EVOLUTIVO
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GenerationResult:
    generation:   int
    best_genome:  Genome
    best_fitness: float
    best_metrics: dict
    population:   list[Genome] = field(default_factory=list)


def evolve(population: list[Genome], fitness_scores: list[float]) -> list[Genome]:
    """Seleciona elites, faz crossover e retorna nova população."""
    if not population:
        return [random_genome() for _ in range(POPULATION_SIZE)]

    paired = sorted(
        zip(population, fitness_scores),
        key=lambda x: x[1],
        reverse=True,
    )
    elites = [g for g, _ in paired[:ELITE_COUNT]]

    new_pop = copy.deepcopy(elites)
    while len(new_pop) < POPULATION_SIZE:
        p1, p2 = random.sample(elites, 2)
        new_pop.append(crossover(p1, p2))
    return new_pop


def run_evolution(
    bars:       list,
    symbol:     str,
    balance:    float,
    generations: int = 20,
) -> list[GenerationResult]:
    """
    Executa o loop evolutivo completo.

    Retorna uma lista de GenerationResult (um por geração),
    do qual você pode extrair o melhor genoma para aplicar ao Config.
    """
    population: list[Genome] = [random_genome() for _ in range(POPULATION_SIZE)]
    results: list[GenerationResult] = []

    for gen in range(1, generations + 1):
        log(f"[GENETIC] Geração {gen}/{generations} — avaliando {len(population)} genomas...")

        fitness_scores: list[float] = []
        metrics_list:   list[dict]  = []

        for i, genome in enumerate(population):
            # Aplica genoma temporariamente ao Config via monkey-patch
            _old_atr_sl = Config.ATR_SL_MULT
            _old_atr_tp = Config.ATR_TP_MULT
            _old_min_rr = Config.REGIME_MIN_RR.copy()
            _old_risk   = Config.RISK_PERCENT_PER_TRADE

            Config.ATR_SL_MULT = genome["ATR_MULT_SL"]
            Config.ATR_TP_MULT = genome["ATR_MULT_TP"]
            Config.REGIME_MIN_RR = {k: genome["MIN_RR"] for k in Config.REGIME_MIN_RR}
            Config.RISK_PERCENT_PER_TRADE = genome["RISK_PCT"]

            try:
                bt = run_backtest(
                    bars,
                    symbol=symbol,
                    initial_balance=balance,
                    min_confluence=int(genome["MIN_CONFLUENCE"]),
                )
                m = bt.metrics
            except Exception as e:
                log(f"[GENETIC] Erro no genoma {i}: {e}")
                m = {"total_trades": 0, "winrate": 0, "profit_factor": 0,
                     "max_drawdown_pct": 100}
            finally:
                # Restaura Config original
                Config.ATR_SL_MULT  = _old_atr_sl
                Config.ATR_TP_MULT  = _old_atr_tp
                Config.REGIME_MIN_RR = _old_min_rr
                Config.RISK_PERCENT_PER_TRADE = _old_risk

            f = fitness(genome, m)
            fitness_scores.append(f)
            metrics_list.append(m)

        # Melhor da geração
        best_idx  = fitness_scores.index(max(fitness_scores))
        best_g    = population[best_idx]
        best_f    = fitness_scores[best_idx]
        best_m    = metrics_list[best_idx]

        log(
            f"[GENETIC] Gen {gen}: fitness={best_f:.3f} | "
            f"WR={best_m.get('winrate', 0)}% | "
            f"PF={best_m.get('profit_factor', 0)} | "
            f"DD={best_m.get('max_drawdown_pct', 0)}% | "
            f"Trades={best_m.get('total_trades', 0)}"
        )

        results.append(GenerationResult(
            generation=gen,
            best_genome=best_g,
            best_fitness=best_f,
            best_metrics=best_m,
            population=list(population),
        ))

        population = evolve(population, fitness_scores)

    return results


def save_best_genome(result: GenerationResult, path: str = "best_genome.json"):
    """Salva o melhor genoma encontrado em JSON para referência."""
    data = {
        "generation":   result.generation,
        "fitness":      round(result.best_fitness, 4),
        "genome":       result.best_genome,
        "metrics":      result.best_metrics,
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    log(f"[GENETIC] Melhor genoma salvo em {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Otimizador genético do Sniper Bot")
    parser.add_argument("csv",          help="CSV com OHLC histórico")
    parser.add_argument("--symbol",     default="EURUSD")
    parser.add_argument("--balance",    type=float, default=Config.INITIAL_BALANCE)
    parser.add_argument("--generations", type=int,  default=20)
    parser.add_argument("--output",     default="best_genome.json")
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido no CSV.")

    log(f"[GENETIC] {len(bars)} barras | {args.symbol} | {args.generations} gerações")
    results = run_evolution(bars, args.symbol, args.balance, args.generations)

    # Melhor entre todas as gerações
    overall_best = max(results, key=lambda r: r.best_fitness)
    save_best_genome(overall_best, args.output)

    print("\n" + "═" * 50)
    print("  MELHOR CONFIGURAÇÃO ENCONTRADA")
    print("═" * 50)
    for k, v in overall_best.best_genome.items():
        print(f"  {k:<22} = {v}")
    print("─" * 50)
    m = overall_best.best_metrics
    print(f"  Fitness:   {overall_best.best_fitness:.4f}")
    print(f"  Win Rate:  {m.get('winrate', 0)}%")
    print(f"  PF:        {m.get('profit_factor', 0)}")
    print(f"  Drawdown:  {m.get('max_drawdown_pct', 0)}%")
    print(f"  Trades:    {m.get('total_trades', 0)}")
    print("═" * 50 + "\n")


if __name__ == "__main__":
    main()
