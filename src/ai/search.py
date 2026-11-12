"""Dijkstra and A* written from scratch (networkx is used only in tests to check costs).

Both return a SearchResult with the path, its cost, the number of nodes expanded and the
expansion order (so the demo can animate the search frontier).

A* heuristic: h(n) = haversine(n, goal) / v_max, v_max = fastest speed of any mode.
Admissible because every edge costs at least (straight-line length / v_max): metro edges follow
track that is never shorter than the straight line, walk/bus edges are slower than v_max and add
detours and waits, entry edges have length 0. Summing along any path, the true remaining cost is
>= straight-line distance to the goal / v_max = h(n). (It is also consistent, by the same edge bound.)

Crowd-aware variant: boarding at a station whose load ratio exceeds `crowd_from` adds
crowd_penalty * (ratio - crowd_from) minutes. Penalties are >= 0, so the heuristic stays admissible.
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Callable

from src.core.graph import Edge, Graph, max_speed_kmh, station_of


@dataclass
class SearchResult:
    path: list[str]
    cost: float
    expanded: int
    runtime_ms: float
    order: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)   # per expansion: node, g, h, f, frontier size
    pushes: int = 0                                    # nodes added to the priority queue

    @property
    def found(self) -> bool:
        return math.isfinite(self.cost)


def zero_heuristic(_n: str, _goal: str) -> float:
    return 0.0


def _haversine_scalar(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Same formula as data.haversine_km, in plain math: ~10x faster than numpy on single numbers,
    which matters because A* evaluates h once per queue push."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def make_haversine_heuristic(g: Graph) -> Callable[[str, str], float]:
    """h(n) = straight-line minutes to goal at the fastest mode speed (cached per node and goal)."""
    to_min = 60.0 / max_speed_kmh()
    cache: dict[tuple[str, str], float] = {}

    def h(n: str, goal: str) -> float:
        key = (n, goal)
        v = cache.get(key)
        if v is None:
            (a, b), (c, d) = g.pos[n], g.pos[goal]
            v = cache[key] = _haversine_scalar(a, b, c, d) * to_min
        return v

    return h


def make_crowd_penalty(load_ratio: dict[str, float], penalty: float, start: float) -> Callable[[str, "Edge"], float]:
    """Penalty for BOARDING at a crowded station (street -> platform entry edge). Riding through a
    crowded station adds no load, so it is not penalised."""
    def p(u: str, e: "Edge") -> float:
        if e.mode != "entry" or not e.to.startswith("P:") or not u.startswith("S:"):
            return 0.0
        r = load_ratio.get(station_of(e.to), 0.0)
        return penalty * (r - start) if r > start else 0.0

    return p


def best_first(g: Graph, source: str, goal: str, h: Callable[[str, str], float],
               edge_penalty: Callable[[str, Edge], float] | None = None, record: bool = False) -> SearchResult:
    """Generic best-first search with f = g + h. h = 0 gives Dijkstra, admissible h gives A*."""
    t0 = time.perf_counter()
    if source not in g.adj or goal not in g.adj:
        return SearchResult([], math.inf, 0, 0.0)
    dist = {source: 0.0}
    parent: dict[str, tuple[str, str]] = {}
    closed: set[str] = set()
    counter = 0  # tie-breaker keeps heap comparisons on numbers only
    heap = [(h(source, goal), counter, source)]
    order: list[str] = []
    trace: list[dict] = []
    pushes = 1
    while heap:
        _, _, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        if record:
            order.append(u)
            hu = h(u, goal)
            trace.append({"node": u, "g": dist[u], "h": hu, "f": dist[u] + hu, "frontier": len(heap),
                          "parent": parent.get(u, (None, None))[0], "via": parent.get(u, (None, None))[1]})
        if u == goal:
            break
        du = dist[u]
        for e in g.adj[u]:
            if e.to in closed:
                continue
            nd = du + e.cost + (edge_penalty(u, e) if edge_penalty else 0.0)
            if nd < dist.get(e.to, math.inf):
                dist[e.to] = nd
                parent[e.to] = (u, e.mode)
                counter += 1
                pushes += 1
                heapq.heappush(heap, (nd + h(e.to, goal), counter, e.to))
    ms = (time.perf_counter() - t0) * 1000
    if goal not in closed:
        return SearchResult([], math.inf, len(closed), ms, order, trace=trace, pushes=pushes)
    path, modes, n = [goal], [], goal
    while n != source:
        n, m = parent[n]
        path.append(n)
        modes.append(m)
    return SearchResult(path[::-1], dist[goal], len(closed), ms, order, modes[::-1], trace, pushes)


def dijkstra(g: Graph, source: str, goal: str, **kw) -> SearchResult:
    return best_first(g, source, goal, zero_heuristic, **kw)


def astar(g: Graph, source: str, goal: str, h: Callable[[str, str], float] | None = None, **kw) -> SearchResult:
    return best_first(g, source, goal, h or make_haversine_heuristic(g), **kw)


def dijkstra_all(g: Graph, source: str) -> dict[str, float]:
    """Single-source shortest times to every reachable node (used for coverage matrices)."""
    dist = {source: 0.0}
    heap = [(0.0, source)]
    done: set[str] = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        for e in g.adj[u]:
            nd = d + e.cost
            if nd < dist.get(e.to, math.inf):
                dist[e.to] = nd
                heapq.heappush(heap, (nd, e.to))
    return dist
