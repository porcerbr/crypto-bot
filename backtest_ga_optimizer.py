from __future__ import annotations

import random
from dataclasses import dataclass

from backtest_backtester import Backtester
from strategies_confluence_strategy import ConfluenceStrategy, StrategyConfig


@dataclass
class Individual:
    min_score: float
    atr_sl_mult: float
    atr_tp_mult: float
    min_adx: float
    fitness: float = -999999.0


def random_individual() -> Individual:
    return Individual(
        min_score=random.uniform(55, 85),
        atr_sl_mult=random.uniform(1.0, 2.0),
        atr_tp_mult=random.uniform(2.0, 4.0),
        min_adx=random.uniform(12, 28),
    )


def optimize(csv_path: str, generations: int = 10, population_size: int = 16) -> Individual:
    population = [random_individual() for _ in range(population_size)]
    best = population[0]

    for _ in range(generations):
        for individual in population:
            strategy = ConfluenceStrategy(
                StrategyConfig(
                    min_score=individual.min_score,
                    atr_sl_mult=individual.atr_sl_mult,
                    atr_tp_mult=individual.atr_tp_mult,
                    min_adx=individual.min_adx,
                )
            )
            result = Backtester(strategy).run(csv_path)
            metrics = result["metrics"]
            individual.fitness = (
                metrics["return_pct"]
                + metrics["win_rate"] * 100
                + metrics["profit_factor"] * 10
                - metrics["max_drawdown"] * 100
            )
        population.sort(key=lambda x: x.fitness, reverse=True)
        best = population[0]
        parents = population[: max(2, population_size // 4)]
        next_population = parents[:]
        while len(next_population) < population_size:
            a, b = random.sample(parents, 2)
            child = Individual(
                min_score=max(50, min(90, (a.min_score + b.min_score) / 2 + random.uniform(-2, 2))),
                atr_sl_mult=max(0.8, min(3.0, (a.atr_sl_mult + b.atr_sl_mult) / 2 + random.uniform(-0.1, 0.1))),
                atr_tp_mult=max(1.5, min(5.0, (a.atr_tp_mult + b.atr_tp_mult) / 2 + random.uniform(-0.2, 0.2))),
                min_adx=max(8, min(40, (a.min_adx + b.min_adx) / 2 + random.uniform(-1, 1))),
            )
            next_population.append(child)
        population = next_population

    return best
