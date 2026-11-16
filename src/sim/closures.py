"""Which stations are closed at each step: forced closures on top of the flood model."""
from __future__ import annotations

import numpy as np

from src.config import CFG
from src.sim.network import Net

def apply_forced_closures(net: Net, scenario: str, closed: np.ndarray, water: np.ndarray, storm, hours: np.ndarray,
                          rng: np.random.Generator) -> np.ndarray:
    """Apply a preset's forced closures to the (T, N) closed matrix.

    force_mode "flood_timed" (April 2024 replay): exactly the listed stations close and no others.
    The storm model only decides WHEN: a station closes at the first step its water level crosses
    the threshold, or at its peak water level if it never crosses.
    Otherwise (default): the flood model stays fully active and listed / random stations are added,
    closing at force_hour (+30 min for each further station)."""
    preset = CFG["presets"].get(scenario, {})
    forced = list(preset.get("force_closed", []))
    if preset.get("force_mode") == "flood_timed":
        thr = CFG["flood"]["threshold_mm"]
        out = np.zeros_like(closed)
        for name in forced:
            i = net.idx[name]
            cross = np.flatnonzero(water[:, i] >= thr)
            if cross.size:
                t0 = int(cross[0])
            elif water[:, i].max() > 0:
                t0 = int(np.argmax(water[:, i]))
            else:  # never wet at all: close at the storm's peak intensity
                t0 = int(np.argmax([storm.intensity(h) for h in hours]))
            out[t0:, i] = True
        return out
    if preset.get("random_closures"):
        forced += rng.choice(net.names, size=preset["random_closures"], replace=False).tolist()
    for j, name in enumerate(forced):
        hr = preset.get("force_hour", 8.0) + 0.5 * j
        t0 = int(np.searchsorted(hours, hr))
        closed[t0:, net.idx[name]] = True
    return closed
