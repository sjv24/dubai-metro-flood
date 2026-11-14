"""Routing stranded passengers (A* / crowd-aware A* with incremental assignment), queue waits,
and the resulting station loads and travel-time statistics for one closure state."""
from __future__ import annotations

import math

import numpy as np

from src.ai.search import astar, make_crowd_penalty
from src.config import CFG
from src.core.graph import Graph, street
from src.sim.network import Net

def path_time(g: Graph, path: list[str]) -> float:
    t = 0.0
    for a, b in zip(path, path[1:]):
        t += min(e.cost for e in g.adj[a] if e.to == b)
    return t


def first_board(path: list[str]) -> str | None:
    for n in path:
        if n.startswith("P:"):
            return n.split(":")[1]
    return None


def route_one(g: Graph, s: str, d: str, penalty=None):
    r = astar(g, street(s), street(d), edge_penalty=penalty)
    if not r.found:
        return math.inf, None
    return (path_time(g, r.path) if penalty else r.cost), first_board(r.path)


def assign(net: Net, g: Graph, trips, peak_dem: np.ndarray, cap: np.ndarray, displaced: set[str],
           crowd_aware: bool):
    """Route every sampled trip. Plain: independent shortest paths. Crowd-aware: incremental
    assignment, routing trips in `increments` rounds and updating station loads after each round so
    later passengers see the crowding caused by earlier ones (no stampede onto one quiet station)."""
    if not crowd_aware:
        return [route_one(g, s, d) for s, d, _ in trips]
    cc = CFG["crowd"]
    load = peak_dem.copy()
    for s in sorted(displaced):
        load[net.idx[s]] = 0.0
    out: list = [None] * len(trips)
    inc = cc.get("increments", 5)
    for k in range(inc):
        pen = make_crowd_penalty({n: float(load[i] / cap[i]) for i, n in enumerate(net.names)},
                                 cc["crowd_penalty_min"], cc["crowd_penalty_from"])
        for idx in range(k, len(trips), inc):
            s, d, w = trips[idx]
            tm, board = route_one(g, s, d, pen)
            out[idx] = (tm, board)
            if board is not None and math.isfinite(tm):
                load[net.idx[board]] += peak_dem[net.idx[s]] * w
    return out


def summarise_routes(net: Net, trips, routed, normal, displaced):
    """Spill shares, unserved share, extra-time stats per displaced station."""
    lim = CFG["crowd"]["unserved_max_min"]
    share = {s: np.zeros(len(net.names)) for s in sorted(displaced)}
    unserved = {s: 0.0 for s in sorted(displaced)}
    tot = {s: 0.0 for s in sorted(displaced)}
    extra, weights = [], []
    for (s, d, w), (tm, board) in zip(trips, routed):
        tot[s] += w
        if not math.isfinite(tm) or tm > lim:
            unserved[s] += w
            continue
        extra.append(max(0.0, tm - normal[(s, d)]))
        weights.append(w)
        if board is not None:
            share[s][net.idx[board]] += w
    for s in sorted(displaced):
        if tot[s]:
            share[s] /= tot[s]
            unserved[s] /= tot[s]
    extra, weights = np.array(extra), np.array(weights)
    if extra.size:
        avg = float(np.average(extra, weights=weights))
        order = np.argsort(extra)
        cw = np.cumsum(weights[order]) / weights.sum()
        p95 = float(extra[order][min(np.searchsorted(cw, 0.95), len(order) - 1)])
    else:
        avg = p95 = 0.0
    return share, unserved, avg, p95


def station_loads(net: Net, base_t: np.ndarray, displaced: set[str], share, unserved) -> np.ndarray:
    load = base_t.copy()
    for s in sorted(displaced):
        load[net.idx[s]] = 0.0
    for s in sorted(displaced):
        load += base_t[net.idx[s]] * (1 - unserved[s]) * share[s]
    return load


def queue_wait_min(ratio: float) -> float:
    """Expected extra wait (minutes) to board at a station loaded to `ratio` of capacity:
    each full capacity's worth of people ahead of you is one more 15-minute slot."""
    return CFG["time"]["step_min"] * max(0.0, ratio - 1.0)


def evaluate_policy(net, g, trips, normal, displaced, peak_dem, cap, crowd_aware):
    """Route trips, then charge every trip the queue wait at the station it boards (same rule for
    both policies). Crowd-aware routing anticipates that wait; plain routing ignores it but still pays."""
    routed = assign(net, g, trips, peak_dem, cap, displaced, crowd_aware)
    share, uns, _, _ = summarise_routes(net, trips, routed, normal, displaced)
    ratio = station_loads(net, peak_dem, displaced, share, uns) / cap
    with_wait = [(tm + (queue_wait_min(ratio[net.idx[b]]) if b is not None else 0.0), b) for tm, b in routed]
    _, _, avg, p95 = summarise_routes(net, trips, with_wait, normal, displaced)
    return {"share": share, "unserved": uns, "avg_extra": avg, "p95_extra": p95, "ratio": ratio}
