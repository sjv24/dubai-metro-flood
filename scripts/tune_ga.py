"""Small GA tuning check: is the GA's search budget enough to match the greedy baseline?

Runs the April 2024 replay for a few GA settings on tuning seeds 0-7, then on held-out seeds 100-107
(different from the evaluation seeds 0-29 used by run_experiments.py only in the tuning half), and
reports mean GA vs greedy fitness and how often GA >= greedy. The chosen setting is the one in
experiments/config.yaml.

Usage:  python scripts/tune_ga.py
Writes: results/ga_tuning.csv
"""
from __future__ import annotations

import os

from _common import RESULTS, ensure_dirs, parallel

import pandas as pd  # noqa: E402

SETTINGS = {
    "pop 60, gen 80, mutation 0.2 (original)": {"ga.population": 60, "ga.generations": 80, "ga.mutation_rate": 0.2},
    "pop 60, gen 80, mutation 0.4": {"ga.population": 60, "ga.generations": 80, "ga.mutation_rate": 0.4},
    "pop 100, gen 150, mutation 0.2 (chosen)": {"ga.population": 100, "ga.generations": 150, "ga.mutation_rate": 0.2},
    "pop 100, gen 150, mutation 0.4": {"ga.population": 100, "ga.generations": 150, "ga.mutation_rate": 0.4},
}
SEED_SETS = {"tuning seeds 0-7": range(0, 8), "held-out seeds 100-107": range(100, 108)}


def main() -> None:
    ensure_dirs()
    jobs = [{"scenario": "april_2024_replay", "seed": s, "overrides": o, "setting": name, "seed_set": ss}
            for ss, seeds in SEED_SETS.items() for name, o in SETTINGS.items() for s in seeds]
    res = parallel(jobs, label="tune")
    df = pd.DataFrame([{"seed_set": r["job"]["seed_set"], "setting": r["job"]["setting"], "seed": r["job"]["seed"],
                        "ga": r["ga"]["fitness"], "greedy": r["ga"]["greedy"]} for r in res])
    df["ga_minus_greedy"] = df.ga - df.greedy
    df["ga_ge_greedy"] = df.ga_minus_greedy >= -1e-9
    out = df.groupby(["seed_set", "setting"]).agg(ga_mean=("ga", "mean"), greedy_mean=("greedy", "mean"),
                                                  gap_mean=("ga_minus_greedy", "mean"), ga_ge_greedy=("ga_ge_greedy", "sum"),
                                                  n=("seed", "count")).round(4).reset_index()
    out.to_csv(os.path.join(RESULTS, "ga_tuning.csv"), index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
