"""Validation of the flood model against the real 2024 closures (separate from the replay, which forces them).

1. Re-runs the calibration grid search (src/core/flood.py::calibrate) and reports the chosen threshold
   and drainage with their precision / recall / F1.
2. For N seeds, runs the April 2024 storm with the flood model alone (no forced closures) and records
   which stations it closes, against Onpassive (Noor Bank), Equiti (First Abu Dhabi Bank), Mashreq, Energy.

Usage:  python scripts/validate_calibration.py [--seeds 30]
Writes: results/calibration.csv, results/calibration_seeds.csv
"""
from __future__ import annotations

import argparse
import os

from _common import RESULTS, ensure_dirs

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import CFG  # noqa: E402
from src.core import flood  # noqa: E402
from src.sim.engine import hours_axis, load_net  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    args = ap.parse_args()
    ensure_dirs()
    net, hours = load_net(), hours_axis()
    target = set(CFG["closures_2024"])

    best = flood.calibrate(net.lat, net.lon, net.vuln, net.names, hours, target)
    best["in_config_threshold_mm"] = CFG["flood"]["threshold_mm"]
    best["in_config_base_drainage_mmh"] = CFG["flood"]["base_drainage_mmh"]
    pd.DataFrame([best]).to_csv(os.path.join(RESULTS, "calibration.csv"), index=False)
    print("grid search:", best)

    storm = flood.Storm.preset("april_2024_replay")
    sus = flood.susceptibility(net.vuln)
    rows = []
    for seed in range(args.seeds):
        _, _, closed, _ = flood.simulate_water(storm, net.lat, net.lon, sus, hours, np.random.default_rng(seed))
        pred = set(np.array(net.names)[closed[-1]].tolist())
        tp = len(pred & target)
        rows.append({"seed": seed, "closed": ";".join(sorted(pred)), "n_closed": len(pred), "true_positive": tp,
                     "precision": tp / len(pred) if pred else 0.0, "recall": tp / len(target),
                     "missed": ";".join(sorted(target - pred)), "false_alarms": ";".join(sorted(pred - target))})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(RESULTS, "calibration_seeds.csv"), index=False)
    print(f"flood model alone over {args.seeds} seeds: precision {df.precision.mean():.3f} +/- {df.precision.std():.3f}, "
          f"recall {df.recall.mean():.3f} +/- {df.recall.std():.3f}")
    print("most common closure sets:", df.closed.value_counts().head(3).to_dict())


if __name__ == "__main__":
    main()
