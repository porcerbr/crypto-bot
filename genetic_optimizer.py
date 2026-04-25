import random

GENOME_KEYS = [
    "MIN_CONFLUENCE", "ADX_MIN", "ATR_MULT_SL", "ATR_MULT_TP",
    "REVERSAL_MIN_SCORE", "RADAR_COOLDOWN", "GATILHO_COOLDOWN"
]

RANGES = {
    "MIN_CONFLUENCE": (3, 7),
    "ADX_MIN": (15, 35),
    "ATR_MULT_SL": (1.0, 2.5),
    "ATR_MULT_TP": (2.5, 5.0),
    "REVERSAL_MIN_SCORE": (4, 8),
    "RADAR_COOLDOWN": (600, 3600),
    "GATILHO_COOLDOWN": (120, 900),
}

def random_genome():
    return {
        k: (random.randint(*RANGES[k]) if isinstance(RANGES[k][0], int)
            else round(random.uniform(*RANGES[k]), 2))
        for k in GENOME_KEYS
    }

def crossover(g1, g2):
    child = {}
    for k in GENOME_KEYS:
        child[k] = g1[k] if random.random() < 0.5 else g2[k]
    if random.random() < 0.2:
        k = random.choice(GENOME_KEYS)
        child[k] = (random.randint(*RANGES[k]) if isinstance(RANGES[k][0], int)
                    else round(random.uniform(*RANGES[k]), 2))
    return child

def fitness(genome, history):
    if not history:
        return 0.0
    wins = sum(1 for h in history if h.get("result") == "WIN")
    total = len(history)
    wr = wins / total if total else 0.0
    avg_pnl = sum(h.get("pnl_money", 0.0) for h in history) / total
    return wr * 0.6 + avg_pnl / 100.0 * 0.4

def evolve(population, history):
    if not population:
        return [random_genome() for _ in range(10)]
    scored = sorted(
        [(g, fitness(g, history)) for g in population],
        key=lambda x: x[1], reverse=True
    )
    elites = [g for g, _ in scored[:3]]
    new_pop = elites.copy()
    while len(new_pop) < 10:
        p1, p2 = random.sample(elites, 2)
        new_pop.append(crossover(p1, p2))
    return new_pop
