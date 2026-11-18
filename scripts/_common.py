"""Shared helpers for the experiment scripts: import path, metric definitions, parallel runner, CSV/summary."""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
FIGURES = os.path.join(RESULTS, "figures")

# Every per-run metric reported, and which direction is better ("lo" = lower is better).
METRICS = {
    "gave_up": ("People who gave up on the metro", "lo"),
    "waiting_person_hours": ("Hours spent queuing", "lo"),
    "peak_waiting": ("Peak people waiting (all stations)", "lo"),
    "worst_station_waiting": ("Peak queue at the worst station", "lo"),
    "peak_ratio": ("Peak crowding ratio", "lo"),
    "avg_extra_min": ("Average extra trip time (min)", "lo"),
    "p95_extra_min": ("95th percentile extra trip time (min)", "lo"),
    "unserved_pct": ("Unserved trips (%)", "lo"),
    "covered_pct": ("Stranded passengers within 10 min of relief (%)", "hi"),
    "staffed_critical_pct": ("Critical stations staffed (%)", "hi"),
    "max_overloaded_stations": ("Max stations over capacity at once", "lo"),
    "overloaded_station_steps": ("Station-steps over capacity", "lo"),
    "displaced_total": ("Stranded passengers (same for both)", None),
}


def ensure_dirs() -> None:
    os.makedirs(FIGURES, exist_ok=True)


_DEFAULT_CFG: dict | None = None


def apply_overrides(overrides: dict | None) -> None:
    """Reset the config to its file defaults, then set nested values, e.g. {"crowd.abandon_per_step": 0.2}.
    The reset matters: pool workers are reused, so one job's override must not leak into the next."""
    import copy

    from src.config import CFG
    global _DEFAULT_CFG
    if _DEFAULT_CFG is None:
        _DEFAULT_CFG = copy.deepcopy(CFG)
    CFG.clear()
    CFG.update(copy.deepcopy(_DEFAULT_CFG))  # in place: every module holds a reference to this dict
    for key, value in (overrides or {}).items():
        node = CFG
        *path, last = key.split(".")
        for p in path:
            node = node[p]
        node[last] = value


def run_one(job: dict) -> dict:
    """Worker: one scenario x seed (both policies are simulated inside every run)."""
    apply_overrides(job.get("overrides"))
    from src.sim.engine import run
    out = run(job["scenario"], job["seed"], detail=False)
    return {"job": job, "summary": out["summary"], "closed_final": out["closed_final"],
            "calibration": out.get("calibration"), "ga": out.get("ga")}


def parallel(jobs: list[dict], workers: int | None = None, label: str = "") -> list[dict]:
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(run_one, jobs), 1):
            out.append(res)
            if i % 10 == 0 or i == len(jobs):
                print(f"  {label} {i}/{len(jobs)} runs done", flush=True)
    return out


def summarise(runs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Mean, std and n of every metric, grouped by `by` (e.g. scenario + policy)."""
    rows = []
    for key, g in runs.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        for m in METRICS:
            if m not in g:
                continue
            v = pd.to_numeric(g[m], errors="coerce").dropna()
            rows.append({**dict(zip(by, key)), "metric": m, "label": METRICS[m][0],
                         "mean": round(float(v.mean()), 3) if len(v) else None,
                         "std": round(float(v.std(ddof=1)), 3) if len(v) > 1 else None, "n": int(len(v))})
    return pd.DataFrame(rows)


def compare(runs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Paired AI-vs-2024-style comparison per seed: mean/std of each policy, of the difference, and
    how many seeds the AI was better on."""
    rows = []
    for key, g in runs.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        b = g[g.policy == "baseline"].set_index("seed")
        a = g[g.policy == "ai"].set_index("seed")
        for m, (label, direction) in METRICS.items():
            if direction is None or m not in g:
                continue
            x = pd.to_numeric(b[m], errors="coerce")
            y = pd.to_numeric(a[m], errors="coerce").reindex(x.index)
            ok = x.notna() & y.notna()
            x, y = x[ok], y[ok]
            if not len(x):
                continue
            d = y - x
            better = (d < -1e-9) if direction == "lo" else (d > 1e-9)
            same = d.abs() <= 1e-9
            rows.append({
                **dict(zip(by, key)), "metric": m, "label": label, "better_if": "lower" if direction == "lo" else "higher",
                "baseline_mean": round(float(x.mean()), 3), "baseline_std": round(float(x.std(ddof=1)), 3) if len(x) > 1 else None,
                "ai_mean": round(float(y.mean()), 3), "ai_std": round(float(y.std(ddof=1)), 3) if len(y) > 1 else None,
                "diff_mean": round(float(d.mean()), 3), "diff_std": round(float(d.std(ddof=1)), 3) if len(d) > 1 else None,
                "pct_change": round(float(100 * d.mean() / x.mean()), 1) if abs(x.mean()) > 1e-9 else None,
                "ai_better_seeds": int(better.sum()), "tied_seeds": int(same.sum()), "n": int(len(d)),
            })
    return pd.DataFrame(rows)


def fmt_pm(mean, std, d: int = 1) -> str:
    if mean is None or (isinstance(mean, float) and np.isnan(mean)):
        return "–"
    s = f"{mean:,.{d}f}"
    if std is not None and not (isinstance(std, float) and np.isnan(std)):
        s += f" ± {std:,.{d}f}"
    return s
