"""Sensitivity of the April 2024 replay to two key assumptions (one at a time, others at default):

    crowd.abandon_per_step           0.2, 0.3 (default), 0.4   share of queued people who give up per 15 min
    capacity.station_capacity_factor 1.2, 1.3 (default), 1.5   capacity proxy = factor x busiest normal 15 min

For each value: N seeds, both policies. The table says, per metric, whether the AI still beats the
2024-style response on average, and on how many seeds.

Usage:  python scripts/run_sensitivity.py [--seeds 30]
Writes: results/sensitivity_runs.csv, results/sensitivity.csv
"""
from __future__ import annotations

import argparse
import os

from _common import RESULTS, compare, ensure_dirs, parallel

import pandas as pd  # noqa: E402

GRID = {"crowd.abandon_per_step": [0.2, 0.3, 0.4], "capacity.station_capacity_factor": [1.2, 1.3, 1.5]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    ensure_dirs()
    jobs = [{"scenario": "april_2024_replay", "seed": s, "overrides": {p: v}, "param": p, "value": v}
            for p, vals in GRID.items() for v in vals for s in range(args.seeds)]
    res = parallel(jobs, args.workers, "sensitivity")
    rows = []
    for r in res:
        j = r["job"]
        for pol, s in r["summary"].items():
            rows.append({"param": j["param"], "value": j["value"], "seed": j["seed"], "policy": pol,
                         **{k: v for k, v in s.items() if not isinstance(v, (list, dict))}})
    runs = pd.DataFrame(rows)
    runs.to_csv(os.path.join(RESULTS, "sensitivity_runs.csv"), index=False)
    cmp = compare(runs, ["param", "value"])
    cmp["ai_better_on_average"] = [
        (r.diff_mean < -1e-9) if r.better_if == "lower" else (r.diff_mean > 1e-9) for r in cmp.itertuples()]
    cmp.to_csv(os.path.join(RESULTS, "sensitivity.csv"), index=False)
    view = cmp[cmp.metric.isin(["gave_up", "waiting_person_hours", "worst_station_waiting", "avg_extra_min", "covered_pct", "unserved_pct"])]
    print(view[["param", "value", "metric", "baseline_mean", "ai_mean", "pct_change", "ai_better_seeds", "n", "ai_better_on_average"]].to_string(index=False))


if __name__ == "__main__":
    main()
