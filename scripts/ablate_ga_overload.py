"""Ablation: does the GA's "hubs at overcrowded stations" penalty matter, or does it overlap with the
"urgent stations covered" term (fuzzy urgency is mostly driven by crowding)?

Runs the GA with the penalty weight at its default (ga.w_overload = 0.3) and at 0, for the April
2024 replay and the extreme storm, and counts how many chosen hubs sit AT an overcrowded station.

Usage:  python scripts/ablate_ga_overload.py [--seeds 30]
Writes: results/ga_overload_ablation_runs.csv, results/ga_overload_ablation.csv
"""
from __future__ import annotations

import argparse
import os

from _common import RESULTS, ensure_dirs, parallel

import pandas as pd  # noqa: E402

from src.config import CFG  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    args = ap.parse_args()
    ensure_dirs()
    default = CFG["ga"]["w_overload"]
    jobs = [{"scenario": sc, "seed": s, "overrides": {"ga.w_overload": w}, "w": w}
            for sc in ("april_2024_replay", "extreme_storm") for w in (default, 0.0) for s in range(args.seeds)]
    res = parallel(jobs, label="ablation")
    rows = [{"scenario": r["job"]["scenario"], "w_overload": r["job"]["w"], "seed": r["job"]["seed"],
             "hubs_at_overloaded": r["ga"]["hubs_at_overloaded"]["ga"], "overloaded_candidates": r["ga"]["n_overloaded_candidates"],
             "covered_within_T": r["ga"]["covered_ga"], "covered_pct_ai": r["summary"]["ai"]["covered_pct"],
             "hubs": ";".join(sorted(h["name"] for h in r["ga"]["hubs"]))} for r in res]
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(RESULTS, "ga_overload_ablation_runs.csv"), index=False)
    out = df.groupby(["scenario", "w_overload"]).agg(
        runs=("seed", "count"), hubs_at_overloaded_total=("hubs_at_overloaded", "sum"),
        hubs_total=("seed", lambda s: 5 * len(s)), runs_with_any_hub_at_overloaded=("hubs_at_overloaded", lambda s: int((s > 0).sum())),
        overloaded_candidates_mean=("overloaded_candidates", "mean"),
        covered_mean=("covered_within_T", "mean"), covered_std=("covered_within_T", "std")).round(4).reset_index()
    out.to_csv(os.path.join(RESULTS, "ga_overload_ablation.csv"), index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
