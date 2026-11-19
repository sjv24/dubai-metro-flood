"""Multi-seed experiments: every scenario preset x N seeds, both policies (2024-style and AI).

Usage (from the project root):
    python scripts/run_experiments.py                 # all presets, 30 seeds
    python scripts/run_experiments.py --seeds 5 --scenarios april_2024_replay

Writes to results/:
    runs.csv            one row per scenario x seed x policy, every metric
    summary.csv         mean, std and n of every metric per scenario x policy
    comparison.csv      paired AI vs 2024-style: means, stds, mean difference, seeds where AI is better
    ga_runs.csv         GA vs greedy vs random hub placement per run (final closure state)
    ga_curves.csv       GA best / mean / worst fitness per generation per run
Seeds are 0..N-1; every random draw in the simulation comes from that seed.
"""
from __future__ import annotations

import argparse
import os
import time

from _common import RESULTS, compare, ensure_dirs, parallel, summarise

import pandas as pd  # noqa: E402

from src.config import CFG  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--scenarios", nargs="*", default=list(CFG["presets"]))
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    ensure_dirs()

    jobs = [{"scenario": sc, "seed": s} for sc in args.scenarios for s in range(args.seeds)]
    print(f"Running {len(jobs)} runs ({len(args.scenarios)} scenarios x {args.seeds} seeds, both policies each)")
    t0 = time.time()
    results = parallel(jobs, args.workers, "experiments")
    print(f"done in {time.time() - t0:.0f} s")

    rows, ga_rows, curve_rows = [], [], []
    for r in results:
        sc, seed = r["job"]["scenario"], r["job"]["seed"]
        for pol, s in r["summary"].items():
            rows.append({"scenario": sc, "seed": seed, "policy": pol, "n_closed": len(r["closed_final"]),
                         "closed": ";".join(r["closed_final"]),
                         **{k: v for k, v in s.items() if not isinstance(v, (list, dict))}})
        g = r["ga"]
        if g:
            ga_rows.append({"scenario": sc, "seed": seed, "ga": g["fitness"], "greedy": g["greedy"], "random": g["random"],
                            "covered_ga": g["covered_ga"], "covered_greedy": g["covered_greedy"],
                            "covered_random": g["covered_random"], "n_candidates": g["n_candidates"],
                            "evaluations": g["evaluations"],
                            "ga_hubs": ";".join(h["name"] for h in g["hubs"]),
                            "mean_min_to_hub_ga": g["breakdown"]["ga"]["mean_minutes_to_hub"],
                            "mean_min_to_hub_greedy": g["breakdown"]["greedy"]["mean_minutes_to_hub"],
                            "mean_min_to_hub_random": g["breakdown"]["random"]["mean_minutes_to_hub"]})
            for gen, (b, m, w) in enumerate(zip(g["curve_best"], g["curve_mean"], g["curve_worst"])):
                curve_rows.append({"scenario": sc, "seed": seed, "generation": gen, "best": b, "mean": m, "worst": w})

    runs = pd.DataFrame(rows).sort_values(["scenario", "seed", "policy"])
    runs.to_csv(os.path.join(RESULTS, "runs.csv"), index=False)
    summarise(runs, ["scenario", "policy"]).to_csv(os.path.join(RESULTS, "summary.csv"), index=False)
    compare(runs, ["scenario"]).to_csv(os.path.join(RESULTS, "comparison.csv"), index=False)
    pd.DataFrame(ga_rows).sort_values(["scenario", "seed"]).to_csv(os.path.join(RESULTS, "ga_runs.csv"), index=False)
    pd.DataFrame(curve_rows).to_csv(os.path.join(RESULTS, "ga_curves.csv"), index=False)
    print("wrote results/runs.csv, summary.csv, comparison.csv, ga_runs.csv, ga_curves.csv")


if __name__ == "__main__":
    main()
