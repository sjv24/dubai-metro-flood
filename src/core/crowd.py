"""Demand, capacity, displaced passengers and station loads."""
from __future__ import annotations

import numpy as np

from src.config import CFG
from src.core.graph import Graph


def hour_share(hours: np.ndarray) -> np.ndarray:
    """Share of daily trips in each time step (profile per hour / steps per hour)."""
    prof = {int(k): v for k, v in CFG["time"]["hourly_profile"].items()}
    per_hour = 60 / CFG["time"]["step_min"]
    return np.array([prof.get(int(h), 0.0) for h in hours]) / per_hour


def base_load(daily: np.ndarray, hours: np.ndarray) -> np.ndarray:
    """(T, N) passengers entering each station per step without disruption."""
    return hour_share(hours)[:, None] * daily[None, :]


def capacity(base: np.ndarray) -> np.ndarray:
    """Per-station, per-step capacity proxy (ASSUMPTION, see config): factor x busiest baseline step."""
    return CFG["capacity"]["station_capacity_factor"] * base.max(axis=0)


def stranded_stations(g: Graph, names: list[str], closed: set[str]) -> set[str]:
    """Open stations with no rail connection to the main network (e.g. an open station between two
    closed ones). Found as platform components not equal to the largest one."""
    platforms = [n for n in g.adj if n.startswith("P:")]
    comp: dict[str, int] = {}
    sizes = []
    for p in platforms:
        if p in comp:
            continue
        cid, stack, size = len(sizes), [p], 0
        comp[p] = cid
        while stack:
            u = stack.pop()
            size += 1
            for e in g.adj[u]:
                if e.mode == "metro" and e.to not in comp:
                    comp[e.to] = cid
                    stack.append(e.to)
        sizes.append(size)
    if not sizes:
        return set(names) - closed
    main = int(np.argmax(sizes))
    ok = {p.split(":")[1] for p, c in comp.items() if sizes[c] >= 0.25 * max(sizes) or c == main}
    return {n for n in names if n not in closed and n not in ok}
