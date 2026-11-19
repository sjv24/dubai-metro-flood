"""Reproduce every result in one command (about 10-15 minutes on 16 cores; scales with core count).

Usage (from the project root):
    python scripts/run_all.py            # 30 seeds everywhere
    python scripts/run_all.py --seeds 5  # quick check

Runs, in order: the multi-seed experiments, the calibration validation, the A* vs Dijkstra benchmark,
the GA tuning check, the GA overload-penalty ablation, the sensitivity analysis, then the figures.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    args = ap.parse_args()
    s = str(args.seeds)
    steps = [
        ["run_experiments.py", "--seeds", s],
        ["validate_calibration.py", "--seeds", s],
        ["benchmark_search.py", "--trips", "200"],
        ["tune_ga.py"],
        ["ablate_ga_overload.py", "--seeds", s],
        ["run_sensitivity.py", "--seeds", s],
        ["make_figures.py"],
    ]
    t0 = time.time()
    for cmd in steps:
        print(f"\n=== {' '.join(cmd)}", flush=True)
        subprocess.run([sys.executable, os.path.join(HERE, cmd[0]), *cmd[1:]], check=True)
    print(f"\nAll results regenerated in {(time.time() - t0) / 60:.1f} min -> results/")


if __name__ == "__main__":
    main()
