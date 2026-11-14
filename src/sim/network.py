"""Network model shared by the simulation: stations, line order, base graph, time axis."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.config import CFG
from src.core.data import build as build_network
from src.core.graph import Graph, build_graph, rail_neighbours

@dataclass
class Net:
    raw: dict
    names: list[str]
    idx: dict[str, int]
    lat: np.ndarray
    lon: np.ndarray
    daily: np.ndarray
    vuln: np.ndarray
    hub: np.ndarray
    pos: dict[str, tuple[float, float]]
    order: list[str]          # network order for the baseline staff rule
    nb: dict[str, set[str]]
    g0: Graph


_NET: Net | None = None


def load_net() -> Net:
    global _NET
    if _NET is None:
        raw = build_network()
        st = raw["stations"]
        names = [s["name"] for s in st]
        order = []
        for line in ("Red", "Route 2020", "Green"):
            order += [n for n in raw["lines"][line] if n not in order]
        _NET = Net(raw, names, {n: i for i, n in enumerate(names)},
                   np.array([s["lat"] for s in st]), np.array([s["lon"] for s in st]),
                   np.array([s["daily_trips"] for s in st], float), np.array([s["vulnerability"] for s in st]),
                   np.array([1.0 if s["interchange"] else 0.0 for s in st]),
                   {s["name"]: (s["lat"], s["lon"]) for s in st}, order, rail_neighbours(raw), build_graph(raw))
    return _NET


def hours_axis() -> np.ndarray:
    t = CFG["time"]
    return np.arange(t["start_hour"], t["end_hour"], t["step_min"] / 60)


def stops_to_closure(net: Net, closed: set[str]) -> np.ndarray:
    """BFS distance (in stops) from every station to the nearest closed one; 10 if none."""
    dist = {n: 0 for n in closed}
    frontier = list(closed)
    while frontier:
        nxt = []
        for u in frontier:
            for v in net.nb[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    nxt.append(v)
        frontier = nxt
    return np.array([min(dist.get(n, 10), 10) for n in net.names], float)
