"""Genetic algorithm: chromosomes always valid, elitism, and comparison with the baselines."""
import numpy as np
import pytest

from src.ai.ga import HubProblem, crossover, greedy, mutate, random_placement, repair, run_ga


def small_problem(seed=0, n_t=30, n_c=40):
    rng = np.random.default_rng(seed)
    t = rng.random((n_t, n_c)) * 40
    return HubProblem(t, rng.random(n_t) * (rng.random(n_t) < 0.4), rng.random(n_t) * 50, rng.random(n_c) * 0.5, 5, 10)


@pytest.mark.parametrize("seed", range(5))
def test_ga_chromosomes_always_valid(seed):
    p = small_problem(seed)
    rng = np.random.default_rng(seed)
    for _ in range(200):
        a = repair(rng.integers(0, p.n_cand, 5), p.n_cand, 5, rng)
        b = repair(rng.integers(0, p.n_cand, 5), p.n_cand, 5, rng)
        for child in (repair(crossover(a, b, 5, rng), p.n_cand, 5, rng), mutate(a, p.n_cand, rng)):
            assert len(child) == 5 and len(set(child.tolist())) == 5
            assert child.min() >= 0 and child.max() < p.n_cand
    res = run_ga(p, rng, population=30, generations=30)
    assert len(set(res.best)) == 5
    assert all(b >= a - 1e-12 for a, b in zip(res.curve_best, res.curve_best[1:]))  # elitism: never worse


def test_ga_beats_random_and_is_close_to_greedy():
    p = small_problem(3)
    rng = np.random.default_rng(1)
    ga = run_ga(p, rng)
    assert ga.fitness >= random_placement(p, rng).fitness
    assert ga.fitness >= greedy(p).fitness - 0.02


def test_fitness_breakdown_adds_up():
    p = small_problem(2)
    genes = [0, 3, 7, 11, 20]
    b = p.breakdown(genes)
    parts = b["cover_displaced"] + b["cover_priority"] + b["overload_penalty"] + b["time_penalty"]
    assert b["total"] == pytest.approx(parts)
    assert b["total"] == pytest.approx(p.fitness(np.array(genes)))


def test_ga_is_reproducible_with_a_seed():
    p = small_problem(4)
    a = run_ga(p, np.random.default_rng(7), population=30, generations=20)
    b = run_ga(p, np.random.default_rng(7), population=30, generations=20)
    assert a.best == b.best and a.curve_best == b.curve_best
