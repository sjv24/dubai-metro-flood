"""Genetic algorithm for placing k relief / shuttle hubs, plus greedy and random baselines.

Decision: choose k distinct sites (open metro stations or real bus stops near a closure) to host
relief hubs (staff, water, information, taxi rank).

Fitness of a hub set H (all terms normalised to 0..1, higher is better):
    F(H) = cover_displaced(H) + w_p * cover_priority(H) - w_o * overload(H) - w_t * mean_time(H) / 60
  cover_displaced = sum_s d_s * c(min_h t[s,h]) / sum_s d_s        s = displaced (closed / stranded) stations
  cover_priority  = sum_i p_i * c(min_h t[i,h]) / sum_i p_i        i = open stations, p_i = fuzzy priority
  overload        = mean_h max(0, load_ratio_h - 1)                 (hubs at overloaded stations are bad)
  mean_time       = demand-weighted mean minutes from displaced stations to their nearest hub (capped 120);
                    breaks ties once coverage saturates
  c(t) = 1 if t <= T, else exp(-(t - T) / T)                        soft coverage within T minutes
t[s,h] = travel minutes from s to h on the disrupted graph (rail, walking, the bus bridges).

Why cover_priority AND overload are both kept (they look similar because fuzzy urgency is mostly
driven by crowding): they act on different things. cover_priority is about the TARGETS, i.e. crowded
or urgent stations should be within reach of some hub; it pulls hubs towards crowded areas.
overload is about the hub's own LOCATION: don't put the hub inside a station that is already over
capacity (it would add people there); it pushes hubs one step away from the crush. Ablation
(scripts/ablate_ga_overload.py): no effect in the April 2024 replay, but in the extreme storm removing
it puts more hubs at overcrowded stations, at a very small coverage cost.

Operators: tournament (or roulette) selection, set-preserving crossover (child drawn from the union
of the parents' genes, shared genes kept first), swap mutation (replace one gene by a non-member),
a repair step that guarantees k unique genes, and elitism.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class HubProblem:
    t: np.ndarray            # (n_targets, n_candidates) minutes
    demand: np.ndarray       # (n_targets,) displaced demand; 0 for non-displaced targets
    prio: np.ndarray         # (n_targets,) fuzzy priority 0..100 (0 for displaced targets)
    cand_overload: np.ndarray  # (n_candidates,) max(0, ratio - 1)
    k: int
    T: float
    w_p: float = 0.5
    w_o: float = 0.3
    w_t: float = 0.5

    def __post_init__(self) -> None:
        self.tc = np.minimum(np.where(np.isfinite(self.t), self.t, 120.0), 120.0)
        self.cov = np.where(self.t <= self.T, 1.0, np.exp(-(self.t - self.T) / self.T))
        self.cov[~np.isfinite(self.t)] = 0.0
        self.d_sum = max(self.demand.sum(), 1e-9)
        self.p_sum = max(self.prio.sum(), 1e-9)

    @property
    def n_cand(self) -> int:
        return self.t.shape[1]

    def fitness(self, genes: np.ndarray) -> float:
        best = self.cov[:, genes].max(axis=1)
        f = (self.demand @ best) / self.d_sum
        f += self.w_p * (self.prio @ best) / self.p_sum
        f -= self.w_o * float(self.cand_overload[genes].mean())
        f -= self.w_t * float(self.demand @ self.tc[:, genes].min(axis=1)) / self.d_sum / 60
        return float(f)

    def breakdown(self, genes) -> dict:
        """The four fitness terms separately (already weighted) and their total."""
        g = np.array(list(genes), dtype=int)
        best = self.cov[:, g].max(axis=1)
        terms = {
            "cover_displaced": float((self.demand @ best) / self.d_sum),
            "cover_priority": float(self.w_p * (self.prio @ best) / self.p_sum),
            "overload_penalty": float(-self.w_o * self.cand_overload[g].mean()),
            "time_penalty": float(-self.w_t * (self.demand @ self.tc[:, g].min(axis=1)) / self.d_sum / 60),
        }
        terms["total"] = sum(terms.values())
        terms["mean_minutes_to_hub"] = float((self.demand @ self.tc[:, g].min(axis=1)) / self.d_sum)
        return terms

    def covered_share(self, genes) -> float:
        """Share of displaced demand with a hub within T minutes (hard coverage)."""
        ok = (self.t[:, list(genes)] <= self.T).any(axis=1)
        return float(self.demand[ok].sum() / self.d_sum)


@dataclass
class GAResult:
    best: list[int]
    fitness: float
    curve_best: list[float] = field(default_factory=list)
    curve_mean: list[float] = field(default_factory=list)
    curve_worst: list[float] = field(default_factory=list)
    diversity: list[float] = field(default_factory=list)   # distinct genes in population / candidates
    evaluations: int = 0
    steps: list[dict] = field(default_factory=list)        # greedy: hub added + fitness after each step
    first_gen_best: list[int] = field(default_factory=list)
    best_per_gen: list[list[int]] = field(default_factory=list)


def repair(genes: np.ndarray, n_cand: int, k: int, rng: np.random.Generator) -> np.ndarray:
    """Drop duplicates (keeping order) and top up with random non-members until k unique genes."""
    seen, out = set(), []
    for g in genes.tolist():
        if g not in seen and 0 <= g < n_cand:
            seen.add(g)
            out.append(g)
    while len(out) < k:
        g = int(rng.integers(n_cand))
        if g not in seen:
            seen.add(g)
            out.append(g)
    return np.array(out[:k], dtype=int)


def crossover(a: np.ndarray, b: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """Set-preserving: keep genes both parents share, fill from the rest of the union at random."""
    shared = np.intersect1d(a, b)
    rest = np.setdiff1d(np.union1d(a, b), shared)
    rng.shuffle(rest)
    return np.concatenate([shared, rest])[:k].astype(int)


def mutate(genes: np.ndarray, n_cand: int, rng: np.random.Generator) -> np.ndarray:
    """Swap mutation: replace one gene with a candidate not already in the set."""
    out = genes.copy()
    pool = np.setdiff1d(np.arange(n_cand), out)
    if pool.size:
        out[rng.integers(len(out))] = rng.choice(pool)
    return out


def _select(pop, fit, rng, method: str, tsize: int):
    if method == "roulette":
        w = fit - fit.min() + 1e-9
        return pop[rng.choice(len(pop), p=w / w.sum())]
    idx = rng.choice(len(pop), size=tsize, replace=False)
    return pop[idx[np.argmax(fit[idx])]]


def run_ga(p: HubProblem, rng: np.random.Generator, population: int = 60, generations: int = 80,
           tournament_size: int = 3, crossover_rate: float = 0.9, mutation_rate: float = 0.2,
           elitism: int = 2, selection: str = "tournament") -> GAResult:
    k = min(p.k, p.n_cand)
    pop = [repair(rng.permutation(p.n_cand)[:k], p.n_cand, k, rng) for _ in range(population)]
    fit = np.array([p.fitness(g) for g in pop])
    res = GAResult([], -np.inf, evaluations=population)
    res.first_gen_best = sorted(pop[int(np.argmax(fit))].tolist())
    res.best_per_gen.append(res.first_gen_best)
    res.curve_best.append(float(fit.max()))
    res.curve_mean.append(float(fit.mean()))
    res.curve_worst.append(float(fit.min()))
    res.diversity.append(len(set(np.concatenate(pop).tolist())) / p.n_cand)
    for _ in range(generations):
        order = np.argsort(-fit)
        new = [pop[i] for i in order[:elitism]]
        while len(new) < population:
            a = _select(pop, fit, rng, selection, tournament_size)
            b = _select(pop, fit, rng, selection, tournament_size)
            child = crossover(a, b, k, rng) if rng.random() < crossover_rate else a.copy()
            if rng.random() < mutation_rate:
                child = mutate(child, p.n_cand, rng)
            new.append(repair(child, p.n_cand, k, rng))
        pop = new
        fit = np.array([p.fitness(g) for g in pop])
        res.evaluations += population
        res.curve_best.append(float(fit.max()))
        res.curve_mean.append(float(fit.mean()))
        res.curve_worst.append(float(fit.min()))
        res.diversity.append(len(set(np.concatenate(pop).tolist())) / p.n_cand)
        res.best_per_gen.append(sorted(pop[int(np.argmax(fit))].tolist()))
    i = int(np.argmax(fit))
    res.best, res.fitness = sorted(pop[i].tolist()), float(fit[i])
    return res


def greedy(p: HubProblem) -> GAResult:
    """Add the hub with the best marginal fitness gain, k times."""
    chosen: list[int] = []
    steps = []
    for _ in range(min(p.k, p.n_cand)):
        best_g, best_f = None, -np.inf
        for g in range(p.n_cand):
            if g in chosen:
                continue
            f = p.fitness(np.array(chosen + [g]))
            if f > best_f:
                best_g, best_f = g, f
        chosen.append(best_g)
        steps.append({"added": int(best_g), "fitness": float(best_f)})
    return GAResult(sorted(chosen), p.fitness(np.array(chosen)), evaluations=p.k * p.n_cand, steps=steps)


def random_placement(p: HubProblem, rng: np.random.Generator) -> GAResult:
    g = rng.choice(p.n_cand, size=min(p.k, p.n_cand), replace=False)
    return GAResult(sorted(g.tolist()), p.fitness(g), evaluations=1)
